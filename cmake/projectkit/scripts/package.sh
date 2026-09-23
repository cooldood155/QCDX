#!/usr/bin/env bash
#
# ProjectKit package lifecycle: one entry point for Conan 2 operations needed,
# with the recipe as the source for name and version.
#
#   ./scripts/package.sh create                    build, package and test it
#   ./scripts/package.sh install --build_type=Debug   deps for the CMake presets
#   ./scripts/package.sh list                      what is in the cache
#   ./scripts/package.sh editable add              develop against it in place
#   ./scripts/package.sh remove --yes              drop it from the cache
#   ./scripts/package.sh upload --remote=myremote
#
# Anything after '--' is handed to conan unchanged.

set -u -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

pk_find_repo_root() {
  local dir="$PWD"
  while [[ "$dir" != "/" ]]; do
    if [[ -f "${dir}/conanfile.py" || -f "${dir}/conanfile.txt" ]]; then
      printf '%s\n' "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

if [[ -z "${PK_REPO_ROOT:-}" ]]; then
  PK_REPO_ROOT="$(pk_find_repo_root)" || {
    printf 'no conanfile.py found above %s: set PK_REPO_ROOT\n' "$PWD" >&2
    exit 2
  }
fi

if [[ -f "${PK_REPO_ROOT}/scripts/helpers/package/package.conf" ]]; then
  # shellcheck source=/dev/null
  source "${PK_REPO_ROOT}/scripts/helpers/package/package.conf"
fi

: "${PK_PROFILE:=}"
: "${PK_HOST_PROFILE:=}"
: "${PK_REMOTE:=}"
: "${PK_BUILD_TYPES:=Release}"
: "${PK_TEST_FOLDER:=}"
: "${PK_TEST_SOURCE:=}"
: "${PK_CONAN:=conan}"

if [[ -t 1 ]]; then
  PK_BOLD=$'\033[1m'; PK_RED=$'\033[31m'; PK_GREEN=$'\033[32m'
  PK_YELLOW=$'\033[33m'; PK_RESET=$'\033[0m'
else
  PK_BOLD=""; PK_RED=""; PK_GREEN=""; PK_YELLOW=""; PK_RESET=""
fi

pk_die() { printf '%serror%s  %s\n' "$PK_RED" "$PK_RESET" "$1" >&2; exit 1; }
pk_note() { printf '%s--%s %s\n' "$PK_BOLD" "$PK_RESET" "$1"; }

pk_run() {
  printf '%s+%s %s\n' "$PK_YELLOW" "$PK_RESET" "$*"
  [[ "$DRY_RUN" -eq 1 ]] && return 0
  "$@"
}

usage() {
  cat <<USAGE
usage: $(basename "$0") <command> [flag...] [-- conan args...]

commands:
  reference       print the name/version the recipe reports
  install         conan install, what the CMake presets consume
  create          conan create: build, package and run the test package
  build           conan build in the local folder
  export          export the recipe only, no build
  export-pkg      package an already built local tree
  list            list this package in the cache, or in --remote
  info            dependency graph for this recipe
  path            cache folder of the packaged binary
  editable        add | remove | list
  remove          delete this package from the cache, or from --remote
  upload          upload this package to --remote
  cache-clean     drop build and source folders of this package
  help            show this message

flags:
  --build_type=T[,T]  build type(s), default ${PK_BUILD_TYPES}
  --profile=NAME      build profile, a file under profiles/ or a named profile
  --host-profile=NAME host profile for cross packaging
  --remote=NAME       remote for list, remove and upload
  --version=X         override the version the recipe reports
  --test-folder=DIR   test package folder, "" disables the test stage
  --yes               do not ask before deleting
  --dry-run           print the conan commands without running them
USAGE
}

pk_profile_path() {
  local name="$1"
  if [[ -z "$name" ]]; then
    if [[ -f "${PK_REPO_ROOT}/profiles/native" ]]; then
      printf '%s\n' "${PK_REPO_ROOT}/profiles/native"
    else
      printf 'default\n'
    fi
    return 0
  fi
  if [[ -f "$name" ]]; then
    printf '%s\n' "$name"
  elif [[ -f "${PK_REPO_ROOT}/profiles/${name}" ]]; then
    printf '%s\n' "${PK_REPO_ROOT}/profiles/${name}"
  else
    printf '%s\n' "$name"
  fi
}

pk_recipe_field() {
  "$PK_CONAN" inspect "$PK_REPO_ROOT" --format=json 2>/dev/null \
    | sed -n "s/^[[:space:]]*\"$1\": \"\([^\"]*\)\".*/\1/p" | head -n 1
}

pk_reference() {
  local name version
  name="$(pk_recipe_field name)"
  [[ -n "$name" ]] || pk_die "the recipe in ${PK_REPO_ROOT} reports no name"

  if [[ -n "$VERSION_OVERRIDE" ]]; then
    version="$VERSION_OVERRIDE"
  else
    version="$(pk_recipe_field version)"
  fi
  [[ -n "$version" ]] || pk_die "the recipe in ${PK_REPO_ROOT} reports no version"

  printf '%s/%s\n' "$name" "$version"
}

pk_test_folder_args() {
  if [[ -n "${TEST_FOLDER+x}" ]]; then
    printf '%s\n' "-tf=${TEST_FOLDER}"
    return 0
  fi
  if [[ -n "$PK_TEST_FOLDER" ]]; then
    printf '%s\n' "-tf=${PK_TEST_FOLDER}"
  elif [[ -d "${PK_REPO_ROOT}/test_package" ]]; then
    return 0
  elif [[ -d "${SCRIPT_DIR}/../test_package" ]]; then
    printf '%s\n' "-tf=$(cd "${SCRIPT_DIR}/../test_package" && pwd)"
  fi
}

pk_confirm() {
  [[ "$ASSUME_YES" -eq 1 ]] && return 0
  local answer
  printf '%s [y/N] ' "$1"
  read -r answer
  [[ "$answer" == "y" || "$answer" == "Y" ]]
}

COMMAND="${1:-help}"
[[ $# -gt 0 ]] && shift

BUILD_TYPES_ARG=""
PROFILE_ARG=""
HOST_PROFILE_ARG=""
REMOTE_ARG=""
VERSION_OVERRIDE=""
ASSUME_YES=0
DRY_RUN=0
SUBCOMMAND=""
EXTRA=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build_type=*)   BUILD_TYPES_ARG="${1#--build_type=}"; shift ;;
    --profile=*)      PROFILE_ARG="${1#--profile=}"; shift ;;
    --host-profile=*) HOST_PROFILE_ARG="${1#--host-profile=}"; shift ;;
    --remote=*)       REMOTE_ARG="${1#--remote=}"; shift ;;
    --version=*)      VERSION_OVERRIDE="${1#--version=}"; shift ;;
    --test-folder=*)  TEST_FOLDER="${1#--test-folder=}"; shift ;;
    --yes|-y)         ASSUME_YES=1; shift ;;
    --dry-run)        DRY_RUN=1; shift ;;
    --help|-h)        usage; exit 0 ;;
    --)               shift; EXTRA=("$@"); break ;;
    -*)               printf 'unknown option: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
    *)
      if [[ -z "$SUBCOMMAND" ]]; then
        SUBCOMMAND="$1"; shift
      else
        printf 'unexpected argument: %s\n\n' "$1" >&2; usage >&2; exit 2
      fi
      ;;
  esac
done

[[ -n "$BUILD_TYPES_ARG" ]] && PK_BUILD_TYPES="$(printf '%s' "$BUILD_TYPES_ARG" | tr ';,' '  ')"
[[ -n "$REMOTE_ARG" ]] && PK_REMOTE="$REMOTE_ARG"

for build_type in $PK_BUILD_TYPES; do
  case "$build_type" in
    Debug|Release|RelWithDebInfo|MinSizeRel) ;;
    *) pk_die "invalid build type: '${build_type}'" ;;
  esac
done

command -v "$PK_CONAN" >/dev/null 2>&1 || pk_die "conan is not on PATH"

BUILD_PROFILE="$(pk_profile_path "${PROFILE_ARG:-$PK_PROFILE}")"
HOST_PROFILE="$(pk_profile_path "${HOST_PROFILE_ARG:-$PK_HOST_PROFILE}")"

PROFILE_ARGS=(-pr:b "$BUILD_PROFILE")
if [[ -n "${HOST_PROFILE_ARG:-}${PK_HOST_PROFILE}" ]]; then
  PROFILE_ARGS+=(-pr:h "$HOST_PROFILE")
else
  PROFILE_ARGS=(-pr:a "$BUILD_PROFILE")
fi

REMOTE_ARGS=()
[[ -n "$PK_REMOTE" ]] && REMOTE_ARGS=(-r "$PK_REMOTE")

VERSION_ARGS=()
[[ -n "$VERSION_OVERRIDE" ]] && VERSION_ARGS=(--version "$VERSION_OVERRIDE")

[[ -n "$PK_TEST_SOURCE" ]] && export PK_TEST_SOURCE

status=0

case "$COMMAND" in
  help|--help|-h) usage; exit 0 ;;

  reference)
    pk_reference
    ;;

  install)
    for build_type in $PK_BUILD_TYPES; do
      pk_note "install ${build_type}"
      pk_run "$PK_CONAN" install "$PK_REPO_ROOT" "${PROFILE_ARGS[@]}" \
        -s build_type="$build_type" --build=missing "${EXTRA[@]}" || status=1
    done
    ;;

  create)
    mapfile -t test_args < <(pk_test_folder_args)
    for build_type in $PK_BUILD_TYPES; do
      pk_note "create $(pk_reference) ${build_type}"
      pk_run "$PK_CONAN" create "$PK_REPO_ROOT" "${PROFILE_ARGS[@]}" \
        -s build_type="$build_type" --build=missing \
        "${VERSION_ARGS[@]}" "${test_args[@]}" "${EXTRA[@]}" || status=1
    done
    ;;

  build)
    for build_type in $PK_BUILD_TYPES; do
      pk_note "build ${build_type}"
      pk_run "$PK_CONAN" build "$PK_REPO_ROOT" "${PROFILE_ARGS[@]}" \
        -s build_type="$build_type" --build=missing "${EXTRA[@]}" || status=1
    done
    ;;

  export)
    pk_run "$PK_CONAN" export "$PK_REPO_ROOT" "${VERSION_ARGS[@]}" "${EXTRA[@]}" || status=1
    ;;

  export-pkg)
    for build_type in $PK_BUILD_TYPES; do
      pk_note "export-pkg ${build_type}"
      pk_run "$PK_CONAN" export-pkg "$PK_REPO_ROOT" "${PROFILE_ARGS[@]}" \
        -s build_type="$build_type" "${VERSION_ARGS[@]}" "${EXTRA[@]}" || status=1
    done
    ;;

  list)
    pk_run "$PK_CONAN" list "$(pk_reference):*" "${REMOTE_ARGS[@]}" "${EXTRA[@]}" || status=1
    ;;

  info)
    pk_run "$PK_CONAN" graph info "$PK_REPO_ROOT" "${PROFILE_ARGS[@]}" \
      -s build_type="${PK_BUILD_TYPES%% *}" "${EXTRA[@]}" || status=1
    ;;

  path)
    pk_run "$PK_CONAN" cache path "$(pk_reference)" "${EXTRA[@]}" || status=1
    ;;

  editable)
    case "${SUBCOMMAND:-list}" in
      add)
        pk_run "$PK_CONAN" editable add "$PK_REPO_ROOT" "${VERSION_ARGS[@]}" "${EXTRA[@]}" || status=1
        ;;
      remove)
        pk_run "$PK_CONAN" editable remove "$PK_REPO_ROOT" "${EXTRA[@]}" || status=1
        ;;
      list)
        pk_run "$PK_CONAN" editable list "${EXTRA[@]}" || status=1
        ;;
      *) pk_die "editable takes add, remove or list, not '${SUBCOMMAND}'" ;;
    esac
    ;;

  remove)
    reference="$(pk_reference)"
    target="$reference"
    [[ -n "$PK_REMOTE" ]] && target="${reference} (remote ${PK_REMOTE})"
    if pk_confirm "remove ${target} from the cache?"; then
      pk_run "$PK_CONAN" remove "$reference" -c "${REMOTE_ARGS[@]}" "${EXTRA[@]}" || status=1
    else
      pk_note "nothing removed"
    fi
    ;;

  upload)
    [[ -n "$PK_REMOTE" ]] || pk_die "upload needs --remote=NAME or PK_REMOTE"
    pk_run "$PK_CONAN" upload "$(pk_reference)" -r "$PK_REMOTE" --confirm "${EXTRA[@]}" || status=1
    ;;

  cache-clean)
    pk_run "$PK_CONAN" cache clean "$(pk_reference)" "${EXTRA[@]}" || status=1
    ;;

  *)
    printf 'unknown command: %s\n\n' "$COMMAND" >&2
    usage >&2
    exit 2
    ;;
esac

if [[ "$status" -eq 0 ]]; then
  printf '%sok%s\n' "$PK_GREEN" "$PK_RESET"
else
  printf '%sfailed%s\n' "$PK_RED" "$PK_RESET"
fi

exit "$status"
