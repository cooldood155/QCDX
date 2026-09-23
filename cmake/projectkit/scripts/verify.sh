#!/usr/bin/env bash
#
# Master verification entry point.
#
#   ./scripts/verify.sh list                    what can run in this shell now
#   ./scripts/verify.sh list-possible           what this machine could host
#   ./scripts/verify.sh run                     verify the runnable targets
#   ./scripts/verify.sh run-possible            queue everything possible
#   ./scripts/verify.sh run windows-ucrt64      dverify one named target
#   ./scripts/verify.sh run --cross             verify every runnable cross target
#   ./scripts/verify.sh clean                   remove generated output only
#
# The -possible commands widen what is listed and queued, never what is built:
# every target still re-checks its environment strictly **before** compiling,
# so a CLANG64 target queued from a UCRT64 shell stops at the environment stage
# and won't attempt to build against the wrong toolchain.
#
# Each target runs in a subshell, so its configuration and its pass/fail
# counters cannot overwrite eachother.

set -u -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The script lives in the kit, which may sit anywhere inside the project;
# the repository root is whatever the caller gives, else the nearest parent
# of the working directory holding a CMakeLists.txt is used.
pk_find_repo_root() {
  local dir="$PWD"
  while [[ "$dir" != "/" ]]; do
    if [[ -f "${dir}/CMakeLists.txt" ]]; then
      printf '%s\n' "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

if [[ -z "${PK_REPO_ROOT:-}" ]]; then
  PK_REPO_ROOT="$(pk_find_repo_root)" || {
    printf 'no CMakeLists.txt found above %s: set PK_REPO_ROOT\n' "$PWD" >&2
    exit 2
  }
fi

REPO_ROOT="$PK_REPO_ROOT"
export PK_REPO_ROOT

# 'verify_base.sh' MUST be sourced BEFORE 'targets.sh'
# shellcheck source=helpers/verify_base.sh
source "${SCRIPT_DIR}/helpers/verify/verify_base.sh"
# shellcheck source=helpers/targets.sh
source "${SCRIPT_DIR}/helpers/verify/targets.sh"

usage() {
  cat <<USAGE
usage: $(basename "$0") [command] [flag...] [target...]

commands:
  list              list targets that can run in this shell right now
  list-possible     list targets this machine could host, ignoring which MSYS2
                    environment is active and which toolchains are installed
  run               verify targets that can run right now (default)
  run-possible      queue every target this machine could host; each still
                    refuses to build unless its environment is actually active
  clean             remove generated output only, verify nothing
  help              show this message

flags for commands 'run' and 'run-possible':
  --native          only native targets
  --cross           only cross targets
  --all             both (the default)
  --keep            leave generated output in place
  --build_type=T    build type(s) to verify, separated by ',' or ';'
                    (default: Debug,Release). Every build stage runs once per
                    type and nothing is built in a type not listed. Quote a
                    ';' list, the shell treats a bare ';' as a command end.
                    Valid: Debug, Release, RelWithDebInfo, MinSizeRel

  Naming one or more targets selects exactly those, ignoring the filters
  above and running them even when unavailable.

examples:
  $(basename "$0") list
  $(basename "$0") run
  $(basename "$0") run --cross
  $(basename "$0") run --build_type=Debug
  $(basename "$0") run --build_type='Debug;RelWithDebInfo'
  $(basename "$0") run-possible
  $(basename "$0") run windows-ucrt64 cross-x86_64-mingw-w64
USAGE
}

list_targets() {
  local record name kind verdict reason note
  printf 'host: %s %s' "$(pk_host_platform)" "$(pk_host_arch)"
  [[ -n "${MSYSTEM:-}" ]] && printf ' (MSYSTEM=%s)' "$MSYSTEM"
  printf '\nmode: %s\n\n' "$PK_SELECT_MODE"
  printf '%-30s %-7s %-4s %s\n' "TARGET" "KIND" "RUN" "NOTE"

  while IFS= read -r record; do
    name="$(printf '%s' "$record" | cut -d'|' -f1)"
    kind="$(printf '%s' "$record" | cut -d'|' -f2)"
    verdict="$(pk_target_availability "$name" | sed -n '1p')"
    reason="$(pk_target_availability "$name" | sed -n '2p')"

    if [[ "$verdict" == "yes" ]]; then
      note="$(pk_target_desc "$name")"
    else
      note="$reason"
    fi

    printf '%-30s %-7s %-4s %s\n' "$name" "$kind" "$verdict" "$note"
  done < <(pk_target_records)
}

# Only ever returns targets whose availability *probe* passes.
targets_by_kind() {
  local want="$1" record name kind
  while IFS= read -r record; do
    name="$(printf '%s' "$record" | cut -d'|' -f1)"
    kind="$(printf '%s' "$record" | cut -d'|' -f2)"
    [[ "$want" != "any" && "$kind" != "$want" ]] && continue
    pk_target_runnable_here "$name" && printf '%s\n' "$name"
  done < <(pk_target_records)
}

COMMAND="${1:-run}"
[[ $# -gt 0 ]] && shift

case "$COMMAND" in
  list)          PK_SELECT_MODE="strict";   list_targets; exit 0 ;;
  list-possible) PK_SELECT_MODE="possible"; list_targets; exit 0 ;;
  run)           PK_SELECT_MODE="strict" ;;
  run-possible)  PK_SELECT_MODE="possible" ;;
  clean)         pk_cleanup; echo "cleaned."; exit 0 ;;
  help|--help|-h) usage; exit 0 ;;
  *)
    printf 'unknown command: %s\n\n' "$COMMAND" >&2
    usage >&2
    exit 2
    ;;
esac

KIND_FILTER=""
KEEP=0
NAMED=""
PK_BUILD_TYPES="Debug Release"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --native|--cross|--all)
      if [[ -n "$KIND_FILTER" ]]; then
        printf 'only one of --native, --cross, --all may be given\n' >&2
        exit 2
      fi
      [[ "$1" == "--all" ]] && KIND_FILTER="any" || KIND_FILTER="${1#--}"
      shift ;;
    --keep) KEEP=1; shift ;;
    --help|-h) usage; exit 0 ;;
    --build_type|--build_type=*)
      if [[ "$1" == "--build_type" ]]; then
        if [[ $# -lt 2 ]]; then
          printf 'missing value for --build_type\n\n' >&2
          usage >&2
          exit 2
        fi
        build_type_arg="$2"
        shift 2
      else
        build_type_arg="${1#--build_type=}"
        shift
      fi

      PK_BUILD_TYPES=""
      for build_type in $(printf '%s' "$build_type_arg" | tr ';,' '  '); do
        case "$build_type" in
          Debug|Release|RelWithDebInfo|MinSizeRel) ;;
          *)
            printf "invalid build type: '%s'\n" "$build_type" >&2
            printf 'expected Debug, Release, RelWithDebInfo or MinSizeRel\n' >&2
            exit 2
            ;;
        esac
        PK_BUILD_TYPES="${PK_BUILD_TYPES} ${build_type}"
      done
      PK_BUILD_TYPES="${PK_BUILD_TYPES# }"

      if [[ -z "$PK_BUILD_TYPES" ]]; then
        printf 'empty value for --build_type\n' >&2
        exit 2
      fi
      ;;
    -*)
      printf 'unknown option: %s\n\n' "$1" >&2
      usage >&2
      exit 2
      ;;
    *)
      if ! pk_target_exists "$1"; then
        printf 'unknown target: %s\n\n' "$1" >&2
        PK_SELECT_MODE="possible" list_targets >&2
        exit 2
      fi
      if ! pk_target_runnable_here "$1"; then
        printf 'warning: %s is not available here: %s -- ' \
          "$1" "$(pk_target_availability "$1" | sed -n '2p')" >&2
        printf "only use if absolutely necessary\n" >&2
        printf 'running it anyway because it was named explicitly.\n\n' >&2
      fi
      NAMED="${NAMED}${1}"$'\n'
      shift
      ;;
  esac
done

# Empty until here so the check above can tell whether a flag was given.
[[ -z "$KIND_FILTER" ]] && KIND_FILTER="any"

if [[ -n "$NAMED" ]]; then
  SELECTED="$NAMED"
else
  SELECTED="$(targets_by_kind "$KIND_FILTER")"
fi

SELECTED="$(printf '%s' "$SELECTED" | grep -v '^$')"

if [[ -z "$SELECTED" ]]; then
  printf 'no targets selected (host %s %s, mode %s, filter %s).\n\n' \
    "$(pk_host_platform)" "$(pk_host_arch)" \
    "$PK_SELECT_MODE" "$KIND_FILTER" >&2
  list_targets >&2
  printf '\nTry: %s run-possible\n' "$(basename "$0")" >&2
  exit 2
fi

printf '%s======== %s verification ========%s\n' "${PK_BOLD}" "$PK_PROJECT" "${PK_RESET}"
printf 'host:    %s %s\n' "$(pk_host_platform)" "$(pk_host_arch)"
printf 'command: %s\n' "$COMMAND"
printf 'types:   %s\n' "$PK_BUILD_TYPES"
printf 'targets:\n'
printf '%s\n' "$SELECTED" | sed 's/^/  - /'

PK_RESULTS_FILE="$(mktemp "${TMPDIR:-/tmp}/${PK_PROJECT}-results.XXXXXX")" || exit 1
trap 'rm -f "$PK_RESULTS_FILE"' EXIT

ANY_FAILED=0

while IFS= read -r target; do
  [[ -z "$target" ]] && continue

  printf '\n%s================ %s [%s] ================%s\n' \
    "${PK_BOLD}" "$target" "$PK_BUILD_TYPES" "${PK_RESET}"

  # Subshell: per-target configuration and counters must not leak.
  if ! ( PK_KEEP="$KEEP"
         pk_target_configure "$target" || exit 1
         pk_run_stages ); then
    ANY_FAILED=1
    if ! grep -q "^${target}|" "$PK_RESULTS_FILE"; then
      printf '%s|-|failed before any stage ran\n' "$target" >> "$PK_RESULTS_FILE"
    fi
  fi
done <<< "$SELECTED"

printf '\n%s======== Overall ========%s\n' "${PK_BOLD}" "${PK_RESET}"
printf '%-30s %-16s %s\n' "TARGET" "BUILD TYPE" "RESULT"

while IFS='|' read -r r_target r_type r_result; do
  case "$r_result" in
    passed)    r_color="$PK_GREEN" ;;
    "not run") r_color="$PK_YELLOW" ;;
    *)         r_color="$PK_RED" ;;
  esac
  printf '%-30s %-16s %s%s%s\n' \
    "$r_target" "$r_type" "$r_color" "$r_result" "$PK_RESET"
done < "$PK_RESULTS_FILE"

echo
echo "Tracked-file changes still present (should be only your own edits):"
git -C "$REPO_ROOT" status --short

echo
echo "Untracked files git clean -fd WOULD remove (nothing deleted yet):"
git -C "$REPO_ROOT" clean -nd

[[ "$ANY_FAILED" -eq 1 ]] && exit 1
exit 0
