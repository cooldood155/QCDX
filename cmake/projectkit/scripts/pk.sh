#!/usr/bin/env bash
#
# pk: one CLI for every day-to-day projectkit workflow.
#
#   ./scripts/pk.sh build                 deps + configure + build (Debug by default)
#   ./scripts/pk.sh run qcdx -- --flag    build one specific app and run it
#   ./scripts/pk.sh test release          build with tests and run them (Release mode)
#   ./scripts/pk.sh stage                 install into stage/ and check it
#   ./scripts/pk.sh full-clean --yes      remove everything the project made
#   ./scripts/pk.sh sync                  sync the kit from the QCDX template repo
#   ./scripts/pk.sh help build            everything 'build' accepts
#
# Conan and CMake are still what does the work: every command pk runs is
# printed before it runs, nothing is hidden; every command invocation and
# output can be easily seen, copied, and parsed.
#
# pk only decides *which* commands are needed:
#
#   deps       re-run only when conanfile.py or a profile changed, or when the
#              tests now need Catch2 and the last install skipped it
#   configure  re-run only when the tree is new, the deps changed, or a flag
#              asks for a value the tree does not yet have defined
#   options    are remembered per build tree, like the CMake cache they live
#              in, until changed again or reset with the --reset flag
#
# Kept compatible with bash 3.2 (macOS /bin/bash), like the rest of the kit.

set -u -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PK_ORIG_PWD="$PWD"

pk_find_repo_root() {
  local dir="$PWD"
  while [[ "$dir" != "/" ]]; do
    if [[ -f "${dir}/CMakeLists.txt" && -f "${dir}/CMakePresets.json" ]]; then
      printf '%s\n' "$dir"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

if [[ -z "${PK_REPO_ROOT:-}" ]]; then
  PK_REPO_ROOT="$(pk_find_repo_root)" || {
    printf 'pk: no CMakeLists.txt + CMakePresets.json above %s: set PK_REPO_ROOT\n' \
      "$PWD" >&2
    exit 2
  }
fi
export PK_REPO_ROOT

# shellcheck source=helpers/verify/verify_base.sh
source "${SCRIPT_DIR}/helpers/verify/verify_base.sh"
# shellcheck source=helpers/verify/targets.sh
source "${SCRIPT_DIR}/helpers/verify/targets.sh"

if [[ -n "${NO_COLOR:-}" ]]; then
  PK_BOLD=""; PK_RED=""; PK_GREEN=""; PK_YELLOW=""; PK_RESET=""
fi
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  PK_DIM=$'\033[2m'
else
  PK_DIM=""
fi

if [[ -f "${PK_REPO_ROOT}/scripts/helpers/pk/pk.conf" ]]; then
  # shellcheck source=/dev/null
  source "${PK_REPO_ROOT}/scripts/helpers/pk/pk.conf"
fi

: "${PK_DEFAULT_TYPE:=Debug}"
: "${PK_DEFAULT_JOBS:=}"
: "${PK_STAGE_DIR:=stage}"
: "${PK_NATIVE_PROFILE:=native}"
: "${PK_FORMAT_EXCLUDE:=cmake/projectkit/ build/ stage/ _install/}"

# Where 'pk sync' takes the kit from and the paths it uses. A fork of the
# template needs to set PK_UPSTREAM_URL in scripts/helpers/pk/pk.conf.
: "${PK_UPSTREAM_URL:=https://github.com/cooldood155/QCDX.git}"
: "${PK_UPSTREAM_BRANCH:=main}"
: "${PK_SYNC_PATHS:=cmake/projectkit scripts/pk.sh scripts/verify.sh scripts/package.sh}"
PK_SYNC_STATE="scripts/helpers/pk/upstream.conf"
PK_UPSTREAM_REF="refs/projectkit/upstream"

PK_PRESETS_SCRIPT="${SCRIPT_DIR}/helpers/pk/presets.cmake"
PK_STAMP_NAME="pk-deps.stamp"

cd "$PK_REPO_ROOT" || exit 2

# -----------------------------------------------------------------------------
# Output
# -----------------------------------------------------------------------------

pk_step() { printf '\n%s==>%s %s%s%s\n' "$PK_GREEN" "$PK_RESET" "$PK_BOLD" "$1" "$PK_RESET"; }
pk_info() { printf '%s  %s%s\n' "$PK_DIM" "$1" "$PK_RESET"; }
pk_warn() { printf '%swarning:%s %s\n' "$PK_YELLOW" "$PK_RESET" "$1" >&2; }
pk_die() { printf '%serror:%s %s\n' "$PK_RED" "$PK_RESET" "$1" >&2; exit 1; }

pk_usage_die() {
  printf '%serror:%s %s\n' "$PK_RED" "$PK_RESET" "$1" >&2
  if [[ -n "${CMD:-}" ]]; then
    printf "run '%s help %s' for what it accepts\n" "$(pk_self)" "$CMD" >&2
  else
    printf "run '%s help' for the command list\n" "$(pk_self)" >&2
  fi
  exit 2
}

pk_self() {
  if [[ -n "${PK_SELF_NAME:-}" ]]; then
    printf '%s\n' "$PK_SELF_NAME"
  else
    printf './scripts/pk.sh\n'
  fi
}

pk_show_command() {
  local arg
  printf '%s+%s' "$PK_YELLOW" "$PK_RESET"

  for arg in "$@"; do
    case "$arg" in
      "") printf " ''" ;;
      *[!A-Za-z0-9_./:=,+@%\ -]*) printf ' %q' "$arg" ;;
      *" "*) printf ' "%s"' "$arg" ;;
      *) printf ' %s' "$arg" ;;
    esac
  done
  printf '\n'
}

# Always prints the command, invokes it (unless this is a dry run).
pk_run() {
  pk_show_command "$@"
  [[ "$DRY_RUN" -eq 1 ]] && return 0
  "$@"
}

pk_install_hint() {
  local tool="$1" prefix="${MINGW_PACKAGE_PREFIX:-}"
  case "$(pk_host_platform)" in
    windows)
      case "$tool" in
        clang-tidy|clang-format) echo "pacman -S ${prefix:-mingw-w64-ucrt-x86_64}-clang-tools-extra" ;;
        *) echo "pacman -S ${prefix:-mingw-w64-ucrt-x86_64}-${tool}" ;;
      esac ;;

    macos)
      case "$tool" in
        clang-tidy|clang-format) echo "brew install llvm" ;;
        *) echo "brew install ${tool}" ;;
      esac ;;

    *) echo "sudo apt install ${tool}   (or your distribution's package)" ;;
  esac
}

pk_require_tools() {
  local tool missing=""
  for tool in "$@"; do
    command -v "$tool" >/dev/null 2>&1 || missing="${missing} ${tool}"
  done
  [[ -z "$missing" ]] && return 0

  printf '%serror:%s %s needs:%s\n' "$PK_RED" "$PK_RESET" "$CMD" "$missing" >&2
  for tool in $missing; do
    printf '  install %s: %s\n' "$tool" "$(pk_install_hint "$tool")" >&2
  done
  exit 1
}

pk_lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }
pk_upper() { printf '%s' "$1" | tr '[:lower:]' '[:upper:]'; }

# Conan and MinGW CMake are native Windows programs under MSYS2.
pk_native_path() {
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -m "$1"
  else
    printf '%s\n' "$1"
  fi
}

# 'pk dep' is written as a Python script
pk_python() {
  local candidate
  for candidate in "${PK_PYTHON:-}" python3 python; do
    [[ -n "$candidate" ]] || continue

    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 8))' 2>/dev/null; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

pk_dep_exec() {
  local python
  python="$(pk_python)" || pk_die "pk dep needs Python 3.8+ (the one Conan uses works; set PK_PYTHON)"
  PK_CONAN="${PK_CONAN:-conan}" PK_NATIVE_PROFILE="$PK_NATIVE_PROFILE" \
    exec "$python" "${SCRIPT_DIR}/helpers/pk/deps.py" "$@"
}

pk_repo_script() {
  if [[ -x "${PK_REPO_ROOT}/scripts/$1.sh" ]]; then
    printf '%s\n' "${PK_REPO_ROOT}/scripts/$1.sh"
  else
    printf '%s\n' "${SCRIPT_DIR}/$1.sh"
  fi
}

# -----------------------------------------------------------------------------
# Commands and flags
# -----------------------------------------------------------------------------

PK_COMMANDS="build run test configure deps dep install stage rebuild clean
  full-clean analyze memcheck sanitize format status list doctor sync verify
  package rename help shell-init"

pk_command_summary() {
  case "$1" in
    build)      echo "install deps, configure and build what is needed (default: Debug)" ;;
    run)        echo "build one application and run it, forwarding args after --" ;;
    test)       echo "build with tests turned on, then run them with ctest" ;;
    configure)  echo "install deps and (re)configure the build tree, no build" ;;
    deps)       echo "install Conan dependencies for a build type (profiles/native)" ;;
    dep)        echo "add, set, rm, update, lock, check, why, tree: deps.json + conan.lock" ;;
    install)    echo "build, then install into stage/ (or --prefix), no checks" ;;
    stage)      echo "fresh install into stage/, checked like verify.sh, with a report" ;;
    rebuild)    echo "delete the build tree, then build from scratch" ;;
    clean)      echo "delete one build tree, and its Conan output with --deps" ;;
    full-clean) echo "delete everything the project generates, stage/ included" ;;
    analyze)    echo "build with clang-tidy and cppcheck in their own tree" ;;
    memcheck)   echo "run the tests under Valgrind in their own tree" ;;
    sanitize)   echo "build and test with sanitizers in their own tree" ;;
    format)     echo "clang-format every C and C++ file (or --check)" ;;
    status)     echo "show build trees, their options and dependency state" ;;
    list)       echo "list build types, apps, cross targets and presets" ;;
    doctor)     echo "check tools and environment, --fix what can be fixed" ;;
    sync)       echo "update the kit (cmake/projectkit) from the QCDX template" ;;
    verify)     echo "full verification matrix (runs scripts/verify.sh)" ;;
    package)    echo "Conan packaging: create, upload... (runs scripts/package.sh)" ;;
    rename)     echo "rename a project made from the template (scripts/bootstrap.sh)" ;;
    help)       echo "show help, for one command with 'help <command>'" ;;
    shell-init) echo "print a 'pk' shell function + completion for ~/.bashrc" ;;
  esac
}

pk_command_alias() {
  case "$1" in
    b) echo build ;;
    r) echo run ;;
    t) echo test ;;
    c|cfg|conf) echo configure ;;
    i) echo install ;;
    st) echo status ;;
    ls) echo list ;;
    fmt) echo format ;;
    check) echo verify ;;
    bootstrap) echo rename ;;
    purge|distclean) echo full-clean ;;
    upgrade) echo sync ;;
    *) return 1 ;;
  esac
}

# Exact name, alias, or unambiguous prefix.
pk_resolve_command() {
  local word="$1" name matches="" count=0
  for name in $PK_COMMANDS; do
    [[ "$name" == "$word" ]] && { printf '%s\n' "$name"; return 0; }
  done
  pk_command_alias "$word" && return 0

  for name in $PK_COMMANDS; do
    case "$name" in
      "$word"*) matches="${matches} ${name}"; count=$((count + 1)) ;;
    esac
  done

  if [[ "$count" -eq 1 ]]; then
    printf '%s\n' "${matches# }"
    return 0
  fi

  if [[ "$count" -gt 1 ]]; then
    printf 'ambiguous:%s\n' "$matches"
  else
    printf 'unknown\n'
  fi
  return 1
}

pk_suggest_commands() {
  local word="$1" name out=""
  local first="${word:0:1}"
  for name in $PK_COMMANDS; do
    case "$name" in
      *"$word"*|"$first"*) out="${out} ${name}" ;;
    esac
  done
  printf '%s\n' "${out# }"
}

PK_CONFIG_FLAGS="tests apps lib werror lto sanitize coverage analyze option define reset"
PK_TREE_FLAGS="type cross variant update dry verbose"

pk_command_flags() {
  case "$1" in
    deps)      echo "type cross update dry verbose" ;;
    configure) echo "$PK_TREE_FLAGS $PK_CONFIG_FLAGS" ;;
    build|rebuild|analyze)
               echo "$PK_TREE_FLAGS $PK_CONFIG_FLAGS jobs target" ;;
    run)       echo "$PK_TREE_FLAGS $PK_CONFIG_FLAGS jobs" ;;
    test|memcheck|sanitize)
               echo "$PK_TREE_FLAGS $PK_CONFIG_FLAGS jobs filter label" ;;
    install)   echo "$PK_TREE_FLAGS $PK_CONFIG_FLAGS jobs prefix" ;;
    stage)     echo "$PK_TREE_FLAGS $PK_CONFIG_FLAGS jobs consumer" ;;
    clean)     echo "type cross variant all deps yes dry" ;;
    full-clean) echo "cache yes dry" ;;
    format)    echo "check dry" ;;
    doctor)    echo "fix" ;;
    sync)      echo "from branch base nocommit dry" ;;
    *)         echo "" ;;
  esac
}

pk_flag_spelling() {
  case "$1" in
    type)     echo "-t, --type=TYPE" ;;
    cross)    echo "-x, --cross=NAME" ;;
    variant)  echo "--variant=NAME" ;;
    update)   echo "--update" ;;
    dry)      echo "-n, --dry-run" ;;
    verbose)  echo "-v, --verbose" ;;
    tests)    echo "--tests, --no-tests" ;;
    apps)     echo "--apps, --no-apps" ;;
    lib)      echo "--lib=KIND" ;;
    werror)   echo "--werror, --no-werror" ;;
    lto)      echo "--lto, --no-lto" ;;
    sanitize) echo "--sanitize=LIST, --no-sanitize" ;;
    coverage) echo "--coverage, --no-coverage" ;;
    analyze)  echo "--analyze, --no-analyze" ;;
    option)   echo "-O, --option NAME=VALUE" ;;
    define)   echo "-D NAME=VALUE" ;;
    reset)    echo "--reset" ;;
    jobs)     echo "-j, --jobs=N" ;;
    target)   echo "--target=NAME" ;;
    filter)   echo "-R, --filter=REGEX" ;;
    label)    echo "-L, --label=REGEX" ;;
    prefix)   echo "--prefix=DIR" ;;
    all)      echo "--all" ;;
    deps)     echo "--deps" ;;
    check)    echo "--check" ;;
    fix)      echo "--fix" ;;
    consumer) echo "--no-consumer" ;;
    cache)    echo "--cache" ;;
    yes)      echo "-y, --yes" ;;
    from)     echo "--from=URL|PATH" ;;
    branch)   echo "--branch=NAME" ;;
    base)     echo "--base=COMMIT" ;;
    nocommit) echo "--no-commit" ;;
  esac
}

pk_flag_meaning() {
  case "$1" in
    type)     echo "Debug (default), Release, RelWithDebInfo or MinSizeRel; a bare word works too: 'build release', 'test rwd'" ;;
    cross)    echo "cross-compile with profiles/NAME and its presets, see '$(pk_self) list'" ;;
    variant)  echo "use a separate tree build/<preset>-NAME that remembers its own options" ;;
    update)   echo "re-run Conan even when the dependencies look current" ;;
    dry)      echo "print every command without running anything" ;;
    verbose)  echo "show full compiler and linker command lines" ;;
    tests)    echo "build the test suite; off by default, 'test' turns it on" ;;
    apps)     echo "build the applications under apps/" ;;
    lib)      echo "library artifacts: static, shared, both or none" ;;
    werror)   echo "treat compiler warnings as errors" ;;
    lto)      echo "link-time optimization" ;;
    sanitize) echo "sanitizers, comma separated: address,undefined,thread,leak" ;;
    coverage) echo "instrument for coverage" ;;
    analyze)  echo "run clang-tidy and cppcheck while compiling" ;;
    option)   echo "set project option ${PK_PREFIX}_NAME, e.g. -O VALGRIND=ON" ;;
    define)   echo "pass any CMake cache variable through unchanged" ;;
    reset)    echo "forget remembered options and reconfigure from scratch" ;;
    jobs)     echo "parallel compile jobs (default: the build tool's own choice)" ;;
    target)   echo "build only this CMake target; repeatable" ;;
    filter)   echo "run only tests whose name matches REGEX" ;;
    label)    echo "run only tests whose label matches REGEX" ;;
    prefix)   echo "install location, default ${PK_STAGE_DIR}/" ;;
    all)      echo "same as '$(pk_self) full-clean'" ;;
    deps)     echo "also delete the Conan output for this build type" ;;
    check)    echo "list files that need formatting, change nothing (exit 1 if any)" ;;
    fix)      echo "create Conan's default profile when it is missing" ;;
    consumer) echo "skip building a consumer project against stage/" ;;
    cache)    echo "also remove this package from the local Conan cache" ;;
    yes)      echo "do not ask before deleting" ;;
    from)     echo "template to sync from: a URL (remembered) or a local clone (this sync only)" ;;
    branch)   echo "template branch, default ${PK_UPSTREAM_BRANCH} (remembered)" ;;
    base)     echo "template commit the kit currently matches, if pk guesses wrong" ;;
    nocommit) echo "stage the update for review instead of committing it" ;;
  esac
}

pk_command_usage_line() {
  case "$1" in
    build|rebuild|install|analyze)
      echo "$1 [TYPE] [flag...] [-- build-tool args]" ;;
    configure) echo "configure [TYPE] [flag...] [-- cmake args]" ;;
    deps)      echo "deps [TYPE] [flag...] [-- conan args]" ;;
    run)       echo "run [APP] [TYPE] [flag...] [-- app args]" ;;
    test|memcheck|sanitize)
               echo "$1 [TYPE] [flag...] [-- ctest args]" ;;
    clean)     echo "clean [TYPE] [flag...]" ;;
    stage)     echo "stage [TYPE] [flag...]" ;;
    full-clean) echo "full-clean [--cache] [-y] [-n]" ;;
    sync)      echo "sync [--from URL|PATH] [--branch NAME] [--base COMMIT] [--no-commit] [-n]" ;;
    format)    echo "format [--check] [path...]" ;;
    help)      echo "help [command]" ;;
    verify|package|rename)
               echo "$1 [args...]   (everything is passed to the script)" ;;
    *)         echo "$1" ;;
  esac
}

pk_command_examples() {
  local self
  self="$(pk_self)"
  case "$1" in
    build)
      printf '  %s build\n  %s build release --werror\n  %s build --lib=shared --target=%s\n  %s build -x x86_64-mingw-w64\n' \
        "$self" "$self" "$self" "$PK_PROJECT" "$self" ;;
    run)
      printf '  %s run\n  %s run %s release -- --help\n' "$self" "$self" "$PK_PROJECT" ;;
    test)
      printf '  %s test\n  %s test release -R core\n  %s test -- --repeat until-fail:5\n' \
        "$self" "$self" "$self" ;;
    configure)
      printf '  %s configure --tests --werror\n  %s configure -O LTO=ON -D CMAKE_VERBOSE_MAKEFILE=ON\n  %s configure --reset\n' \
        "$self" "$self" "$self" ;;
    deps)
      printf '  %s deps\n  %s deps release --update\n' "$self" "$self" ;;
    install)
      printf '  %s install release\n  %s install --prefix=/tmp/%s\n' "$self" "$self" "$PK_PROJECT" ;;
    clean)
      printf '  %s clean\n  %s clean release --deps\n' "$self" "$self" ;;
    sync)
      printf '  %s sync -n\n  %s sync\n  %s sync --from /path/to/QCDX\n' "$self" "$self" "$self" ;;
    full-clean)
      printf '  %s full-clean -n\n  %s full-clean\n  %s full-clean --cache --yes\n' \
        "$self" "$self" "$self" ;;
    stage)
      printf '  %s stage\n  %s stage release --lib=shared\n  grep "^check|" %s/pk-stage.txt\n' \
        "$self" "$self" "$PK_STAGE_DIR" ;;
    analyze)   printf '  %s analyze\n' "$self" ;;
    memcheck)  printf '  %s memcheck\n' "$self" ;;
    sanitize)
      printf '  %s sanitize\n  %s sanitize --sanitize=thread\n' "$self" "$self" ;;
    format)    printf '  %s format\n  %s format --check\n' "$self" "$self" ;;
    doctor)    printf '  %s doctor\n  %s doctor --fix\n' "$self" "$self" ;;
    verify)    printf '  %s verify list\n  %s verify run --native --build_type=Debug\n' "$self" "$self" ;;
    package)   printf '  %s package create\n  %s package help\n' "$self" "$self" ;;
    rename)    printf '  %s rename myproject --dry-run\n' "$self" ;;
    shell-init)
      # shellcheck disable=SC2016
      printf '  eval "$(%s/scripts/pk.sh shell-init)"    # once, in ~/.bashrc\n' "$PK_REPO_ROOT" ;;
  esac
}

pk_command_notes() {
  case "$1" in
    run)
      echo "APP defaults to the only app when there is one. Runs from the directory you"
      echo "called pk from. Not available for cross builds." ;;
    test)
      echo "Turns tests on in the tree (remembered) and installs Catch2 if the last"
      echo "dependency install skipped it. Not available for cross builds." ;;
    analyze)
      echo "Uses tree build/<preset>-analyze so your normal tree keeps compiling fast." ;;
    memcheck)
      echo "Uses tree build/<preset>-memcheck with ${PK_PREFIX}_VALGRIND=ON and runs the"
      echo "'valgrind' labelled tests. Linux only." ;;
    sanitize)
      echo "Uses tree build/<preset>-sanitize; default sanitizers: address,undefined." ;;
    format)
      echo "Formats tracked and new (not ignored) files; skips ${PK_FORMAT_EXCLUDE}" ;;
    clean)
      echo "Without flags only the selected build tree goes; Conan output is kept so the"
      echo "next build does not reinstall anything. For everything, use full-clean." ;;
    sync)
      echo "Brings the template's kit changes into this project: ${PK_SYNC_PATHS}."
      echo "Only the template's changes since the last sync are applied, as a 3-way"
      echo "merge, so changes you made to the kit here are kept; where both sides"
      echo "changed the same lines you get conflict markers to resolve. The result is"
      echo "one commit that touches only those paths plus ${PK_SYNC_STATE}, which"
      echo "records the template URL, branch and commit for the next sync. The first"
      echo "sync finds the template commit this kit matches by itself."
      echo "Needs: no staged changes, no uncommitted changes in those paths. Your"
      echo "other uncommitted work is left alone." ;;
    full-clean)
      echo "Removes every build tree and Conan output (build/), ${PK_STAGE_DIR}/, _install/,"
      echo "compile_commands.json, verify's scratch and consumer directories, the Conan"
      echo "test_package build, clangd's index, other CMake build dirs (build-*,"
      echo "cmake-build-*), Conan-written presets and sanitizer logs. Lists what exists"
      echo "and asks first. Ignored files it does not own (.vscode/, docs/notes...) are"
      echo "listed afterwards but never touched." ;;
    stage)
      echo "Like verify.sh's install and consumer stages, for the tree you build with:"
      echo "${PK_STAGE_DIR}/ is emptied, the tree is installed into it, the package files"
      echo "are checked, pkg-config reads the .pc, and a consumer project is built"
      echo "against ${PK_STAGE_DIR}/ and run. Every result is written to"
      echo "${PK_STAGE_DIR}/pk-stage.txt, one 'kind|field|value' record per line:"
      echo "  meta|type|Debug   file|lib/libx.a   check|<label>|pass   result|passed"
      echo "Your build tree and its options are not touched." ;;
  esac
}

pk_help_overview() {
  local self name
  self="$(pk_self)"
  cat <<EOF
${PK_BOLD}pk${PK_RESET} - ${PK_PROJECT} project workflows without typing Conan or CMake

usage: ${self} <command> [TYPE] [flag...] [-- passthrough]

EOF
  printf '%scommands%s\n' "$PK_BOLD" "$PK_RESET"
  for name in $PK_COMMANDS; do
    printf '  %-11s %s\n' "$name" "$(pk_command_summary "$name")"
  done
  cat <<EOF

${PK_BOLD}build types${PK_RESET} (a bare word anywhere, or -t TYPE)
  debug (d)  release (r)  relwithdebinfo (rwd)  minsizerel (msr)
  default: ${PK_DEFAULT_TYPE}

${PK_BOLD}shortcuts${PK_RESET}
  b=build r=run t=test c=configure i=install st=status ls=list fmt=format,
  and any unambiguous prefix: '${self} conf' is configure

${PK_BOLD}examples${PK_RESET}
EOF
  printf '  %-44s %s\n' \
    "${self} build" "first run installs deps and configures" \
    "${self} run" "build and start the app" \
    "${self} test release" "Release build with tests, then ctest" \
    "${self} build --werror --lib=both" "options are remembered per build tree" \
    "${self} status" "what is configured and how" \
    "${self} help build" "every flag 'build' accepts"
  printf '\nEvery command prints the Conan/CMake commands it runs; add -n to only print.\n'
  return 0
}

pk_help_command() {
  local command="$1" flag
  printf 'usage: %s %s\n\n' "$(pk_self)" "$(pk_command_usage_line "$command")"
  printf '%s\n' "$(pk_command_summary "$command")"

  local notes
  notes="$(pk_command_notes "$command")"
  [[ -n "$notes" ]] && printf '\n%s\n' "$notes"

  local flags
  flags="$(pk_command_flags "$command")"
  if [[ -n "$flags" ]]; then
    printf '\n%sflags%s\n' "$PK_BOLD" "$PK_RESET"
    for flag in $flags; do
      printf '  %-32s %s\n' "$(pk_flag_spelling "$flag")" "$(pk_flag_meaning "$flag")"
    done
    printf '  %-32s %s\n' "-h, --help" "this help"
  fi

  local examples
  examples="$(pk_command_examples "$command")"
  [[ -n "$examples" ]] && printf '\n%sexamples%s\n%s\n' "$PK_BOLD" "$PK_RESET" "$examples"
  return 0
}

# -----------------------------------------------------------------------------
# Build types & presets & trees
# -----------------------------------------------------------------------------

pk_parse_type() {
  case "$(pk_lower "$1")" in
    d|debug) echo Debug ;;
    r|rel|release) echo Release ;;
    rwd|relwithdebinfo) echo RelWithDebInfo ;;
    msr|minsizerel) echo MinSizeRel ;;
    *) return 1 ;;
  esac
}

pk_preset_query() {
  cmake -DPK_QUERY="$1" -DPK_PRESET="${2:-}" -DPK_PRESETS_FILE=CMakePresets.json \
    -P "$PK_PRESETS_SCRIPT" 2>/dev/null | sed -n 's/^-- pk|//p'
}

# Sets PRESET_BIN and PRESET_TOOLCHAIN for a configure preset.
pk_preset_dirs() {
  local answer
  answer="$(pk_preset_query dirs "$1")"
  [[ -z "$answer" || "$answer" == "missing" ]] && return 1

  PRESET_BIN="$(printf '%s\n' "$answer" | sed -n 's/^binary|//p')"
  PRESET_TOOLCHAIN="$(printf '%s\n' "$answer" | sed -n 's/^toolchain|//p')"
  return 0
}

# Cross names are presets "<name>-debug" that have a matching profiles/<name>.
pk_cross_names() {
  local preset name
  pk_preset_query configure-presets | while IFS= read -r preset; do
    case "$preset" in
      native-debug|*-release|*-relwithdebinfo|*-minsizerel|host-tools) continue ;;
      *-debug)
        name="${preset%-debug}"
        [[ -f "profiles/${name}" ]] && printf '%s\n' "$name"
        ;;
    esac
  done
}

pk_app_names() {
  local dir
  if [[ -d apps ]]; then
    for dir in apps/*/; do
      [[ -d "$dir" ]] || continue

      dir="${dir%/}"
      printf '%s\n' "${dir#apps/}"
    done
  fi
}

pk_cache_get() {
  local cache="$1/CMakeCache.txt" key="$2"
  [[ -f "$cache" ]] || return 1
  sed -n "s/^${key}:[A-Z_]*=//p" "$cache" | head -n 1
}

pk_normalize_value() {
  case "$(pk_upper "$1")" in
    ON|TRUE|YES|Y|1) echo ON ;;
    OFF|FALSE|NO|N|0|"") echo OFF ;;
    *) printf '%s\n' "$1" ;;
  esac
}

# -----------------------------------------------------------------------------
# Argument parsing
# -----------------------------------------------------------------------------

CMD=""
TYPE=""
CROSS=""
VARIANT=""
DRY_RUN=0
VERBOSE=0
UPDATE=0
RESET=0
JOBS="${PK_DEFAULT_JOBS}"
FILTER=""
LABEL=""
PREFIX_DIR=""
CLEAN_ALL=0
CLEAN_DEPS=0
CHECK=0
FIX=0
ASSUME_YES=0
CLEAN_CACHE=0
NO_CONSUMER=0
SYNC_FROM=""
SYNC_BRANCH=""
SYNC_BASE=""
NO_COMMIT=0
TESTS=""
CONFIG_DEFS=()
TARGETS=()
POSITIONAL=()
EXTRA=()

pk_flag_ok() {
  local flag
  for flag in $(pk_command_flags "$CMD"); do
    [[ "$flag" == "$1" ]] && return 0
  done
  return 1
}

pk_flag_allowed() {
  local flag
  for flag in $(pk_command_flags "$CMD"); do
    [[ "$flag" == "$1" ]] && return 0
  done
  pk_usage_die "'$CMD' does not take $(pk_flag_spelling "$1")"
}

pk_add_option() {
  local name="$1" value="$2"
  case "$name" in
    "${PK_PREFIX}"_*) ;;
    *) name="${PK_PREFIX}_$(pk_upper "$name")" ;;
  esac
  CONFIG_DEFS+=("${name}=${value}")
}

# Value of --flag=value or --flag value; sets FLAG_VALUE and FLAG_SHIFT.
pk_flag_value() {
  local arg="$1" next="${2-}" has_next="$3"
  if [[ "$arg" == --*=* ]]; then
    FLAG_VALUE="${arg#*=}"
    FLAG_SHIFT=1
    return 0
  fi
  [[ "$has_next" -eq 1 ]] || pk_usage_die "$arg needs a value"

  FLAG_VALUE="$next"
  FLAG_SHIFT=2
}

pk_parse_args() {
  local arg has_next value
  while [[ $# -gt 0 ]]; do
    arg="$1"
    has_next=0
    [[ $# -gt 1 ]] && has_next=1
    FLAG_SHIFT=1

    case "$arg" in
      --) shift; EXTRA=("$@"); return 0 ;;
      -h|--help) pk_help_command "$CMD"; exit 0 ;;

      -t|--type|--type=*)
        pk_flag_allowed type; pk_flag_value "$arg" "${2-}" "$has_next"
        TYPE="$(pk_parse_type "$FLAG_VALUE")" \
          || pk_usage_die "unknown build type '$FLAG_VALUE'" ;;
      -x|--cross|--cross=*)
        pk_flag_allowed cross; pk_flag_value "$arg" "${2-}" "$has_next"
        CROSS="$FLAG_VALUE" ;;
      --variant|--variant=*)
        pk_flag_allowed variant; pk_flag_value "$arg" "${2-}" "$has_next"
        VARIANT="$FLAG_VALUE"
        case "$VARIANT" in
          ""|*/*|*" "*) pk_usage_die "variant names are one word without '/'" ;;
        esac ;;
      --update) pk_flag_allowed update; UPDATE=1 ;;
      -n|--dry-run) pk_flag_allowed dry; DRY_RUN=1 ;;
      -v|--verbose) pk_flag_allowed verbose; VERBOSE=1 ;;

      --tests)    pk_flag_allowed tests; TESTS=ON ;;
      --no-tests) pk_flag_allowed tests; TESTS=OFF ;;
      --apps)     pk_flag_allowed apps; pk_add_option BUILD_APPS ON ;;
      --no-apps)  pk_flag_allowed apps; pk_add_option BUILD_APPS OFF ;;
      --werror)   pk_flag_allowed werror; pk_add_option WERROR ON ;;
      --no-werror) pk_flag_allowed werror; pk_add_option WERROR OFF ;;
      --lto)      pk_flag_allowed lto; pk_add_option LTO ON ;;
      --no-lto)   pk_flag_allowed lto; pk_add_option LTO OFF ;;
      --coverage) pk_flag_allowed coverage; pk_add_option COVERAGE ON ;;
      --no-coverage) pk_flag_allowed coverage; pk_add_option COVERAGE OFF ;;
      --analyze)  pk_flag_allowed analyze; pk_add_option SA_ALL ON ;;
      --no-analyze) pk_flag_allowed analyze; pk_add_option SA_ALL OFF ;;
      --no-sanitize) pk_flag_allowed sanitize; pk_add_option SANITIZE "" ;;
      --sanitize|--sanitize=*)
        pk_flag_allowed sanitize; pk_flag_value "$arg" "${2-}" "$has_next"
        pk_add_option SANITIZE "$FLAG_VALUE" ;;
      --lib|--lib=*)
        pk_flag_allowed lib; pk_flag_value "$arg" "${2-}" "$has_next"
        case "$(pk_lower "$FLAG_VALUE")" in
          static) value=STATIC ;;
          shared) value=SHARED ;;
          both|static+shared) value=STATIC+SHARED ;;
          none) value=NONE ;;
          *) pk_usage_die "--lib takes static, shared, both or none, not '$FLAG_VALUE'" ;;
        esac
        pk_add_option LIBRARY_TYPE "$value" ;;
      -O|--option|--option=*|-O*)
        pk_flag_allowed option
        if [[ "$arg" == -O?* ]]; then
          FLAG_VALUE="${arg#-O}"; FLAG_SHIFT=1
        else
          pk_flag_value "$arg" "${2-}" "$has_next"
        fi
        [[ "$FLAG_VALUE" == *=* ]] || pk_usage_die "-O takes NAME=VALUE, got '$FLAG_VALUE'"
        pk_add_option "${FLAG_VALUE%%=*}" "${FLAG_VALUE#*=}" ;;
      -D|-D*)
        pk_flag_allowed define
        if [[ "$arg" == -D?* ]]; then
          FLAG_VALUE="${arg#-D}"; FLAG_SHIFT=1
        else
          pk_flag_value "$arg" "${2-}" "$has_next"
        fi
        [[ "$FLAG_VALUE" == *=* ]] || pk_usage_die "-D takes NAME=VALUE, got '$FLAG_VALUE'"
        CONFIG_DEFS+=("$FLAG_VALUE") ;;
      --reset) pk_flag_allowed reset; RESET=1 ;;

      -j|--jobs|--jobs=*|-j*)
        pk_flag_allowed jobs
        if [[ "$arg" == -j?* ]]; then
          FLAG_VALUE="${arg#-j}"; FLAG_SHIFT=1
        else
          pk_flag_value "$arg" "${2-}" "$has_next"
        fi
        case "$FLAG_VALUE" in
          ''|*[!0-9]*) pk_usage_die "--jobs takes a number, not '$FLAG_VALUE'" ;;
        esac
        JOBS="$FLAG_VALUE" ;;
      --target|--target=*)
        pk_flag_allowed target; pk_flag_value "$arg" "${2-}" "$has_next"
        TARGETS+=("$FLAG_VALUE") ;;
      -R|--filter|--filter=*)
        pk_flag_allowed filter; pk_flag_value "$arg" "${2-}" "$has_next"
        FILTER="$FLAG_VALUE" ;;
      -L|--label|--label=*)
        pk_flag_allowed label; pk_flag_value "$arg" "${2-}" "$has_next"
        LABEL="$FLAG_VALUE" ;;
      --prefix|--prefix=*)
        pk_flag_allowed prefix; pk_flag_value "$arg" "${2-}" "$has_next"
        PREFIX_DIR="$FLAG_VALUE" ;;
      --all)   pk_flag_allowed all; CLEAN_ALL=1 ;;
      --deps)  pk_flag_allowed deps; CLEAN_DEPS=1 ;;
      --check) pk_flag_allowed check; CHECK=1 ;;
      -y|--yes) pk_flag_allowed yes; ASSUME_YES=1 ;;
      --cache) pk_flag_allowed cache; CLEAN_CACHE=1 ;;
      --no-consumer) pk_flag_allowed consumer; NO_CONSUMER=1 ;;
      --from|--from=*)
        pk_flag_allowed from; pk_flag_value "$arg" "${2-}" "$has_next"
        SYNC_FROM="$FLAG_VALUE" ;;
      --branch|--branch=*)
        pk_flag_allowed branch; pk_flag_value "$arg" "${2-}" "$has_next"
        SYNC_BRANCH="$FLAG_VALUE" ;;
      --base|--base=*)
        pk_flag_allowed base; pk_flag_value "$arg" "${2-}" "$has_next"
        SYNC_BASE="$FLAG_VALUE" ;;
      --no-commit) pk_flag_allowed nocommit; NO_COMMIT=1 ;;
      --fix)   pk_flag_allowed fix; FIX=1 ;;

      -*) pk_usage_die "unknown flag '$arg'" ;;

      *)
        if [[ -z "$TYPE" ]] && pk_flag_ok type \
            && value="$(pk_parse_type "$arg")"; then
          TYPE="$value"
        else
          POSITIONAL+=("$arg")
        fi ;;
    esac
    shift "$FLAG_SHIFT"
  done
}

# -----------------------------------------------------------------------------
# Selection: what preset, tree and Conan output this run works on
# -----------------------------------------------------------------------------

pk_select() {
  if [[ -z "$TYPE" ]]; then
    TYPE="$(pk_parse_type "$PK_DEFAULT_TYPE")" \
      || pk_die "PK_DEFAULT_TYPE='${PK_DEFAULT_TYPE}' is not a build type"
  fi
  TYPE_LOWER="$(pk_lower "$TYPE")"

  if [[ -n "$CROSS" ]]; then
    CROSS="${CROSS#cross-}"
    [[ -f "profiles/${CROSS}" ]] || pk_usage_die \
      "no profiles/${CROSS}; cross targets here: $(pk_cross_names | tr '\n' ' ')"
    PRESET="${CROSS}-${TYPE_LOWER}"
  else
    PRESET="native-${TYPE_LOWER}"
  fi

  pk_preset_dirs "$PRESET" || pk_die "CMakePresets.json has no configure preset '${PRESET}'"
  TREE="$PRESET_BIN"
  [[ -n "$VARIANT" ]] && TREE="${TREE}-${VARIANT}"
  TOOLCHAIN="$PRESET_TOOLCHAIN"
  [[ -n "$TOOLCHAIN" ]] || pk_die "preset '${PRESET}' has no toolchainFile, pk needs Conan's"
  CONAN_DIR="$(dirname "$(dirname "$TOOLCHAIN")")"

  PLATFORM_LABEL="native"
  [[ -n "$CROSS" ]] && PLATFORM_LABEL="cross ${CROSS}"
}

pk_banner() {
  local tests_now
  tests_now="$(pk_cache_get "$TREE" "${PK_PREFIX}_BUILD_TESTS" || true)"
  printf '%s%s%s  %s  %s%s%s  %s  tree %s' \
    "$PK_BOLD" "$PK_PROJECT" "$PK_RESET" "$CMD" "$PK_BOLD" "$TYPE" "$PK_RESET" \
    "$PLATFORM_LABEL" "$TREE"
  [[ -n "$tests_now" ]] && printf '  (tests %s)' "$(pk_normalize_value "$tests_now")"
  printf '\n'
}

# -----------------------------------------------------------------------------
# Dependencies
# -----------------------------------------------------------------------------

# Changes to anything that effects 'conan install' requries this key to be changed.
pk_deps_key() {
  local host_profile="$1" file files=""
  for file in conanfile.py conanfile.txt deps.json conan.lock \
      "profiles/${PK_NATIVE_PROFILE}" "$host_profile"; do
    [[ -n "$file" && -f "$file" ]] && files="${files} ${file}"
  done
  # shellcheck disable=SC2086
  cat $files 2>/dev/null | cksum | cut -d' ' -f1
}

pk_stamp_get() {
  local stamp="$1/${PK_STAMP_NAME}" key="$2"
  [[ -f "$stamp" ]] || return 1
  sed -n "s/^${key}=//p" "$stamp" | head -n 1
}

pk_deps_current() {
  local conan_dir="$1" toolchain="$2" host_profile="$3" want_tests="$4"
  if [[ ! -f "$toolchain" ]]; then
    echo "not installed yet"; return 1
  fi

  local key tests
  key="$(pk_stamp_get "$conan_dir" key)" || { echo "installed outside pk, reinstalling once"; return 1; }
  if [[ "$key" != "$(pk_deps_key "$host_profile")" ]]; then
    echo "conanfile.py, deps.json, conan.lock or a profile changed"; return 1
  fi
  tests="$(pk_stamp_get "$conan_dir" tests || echo 0)"
  if [[ "$want_tests" -eq 1 && "$tests" != "1" ]]; then
    echo "tests need Catch2, the last install skipped it"; return 1
  fi
  echo "up to date"
  return 0
}

pk_ensure_deps() {
  local build_type="$1" cross="$2" conan_dir="$3" toolchain="$4" want_tests="$5"
  local host_profile="" label="native" why
  if [[ -n "$cross" ]]; then
    host_profile="profiles/${cross}"
    label="cross ${cross}"
    want_tests=0
  fi

  why="$(pk_deps_current "$conan_dir" "$toolchain" "$host_profile" "$want_tests")"
  if [[ $? -eq 0 && "$UPDATE" -eq 0 ]]; then
    pk_info "deps ${build_type} (${label}): up to date"
    return 0
  fi
  [[ "$UPDATE" -eq 1 ]] && why="--update given"

  pk_step "deps ${build_type} (${label}): ${why}"

  local args
  args=(install "--build_type=${build_type}")
  [[ -f "profiles/${PK_NATIVE_PROFILE}" ]] && args+=("--profile=${PK_NATIVE_PROFILE}")
  [[ -n "$cross" ]] && args+=("--host-profile=${cross}")
  args+=(--)
  if [[ "$want_tests" -eq 1 ]]; then
    args+=(-c tools.build:skip_test=False -c tools.graph:skip_test=False)
  else
    args+=(-c tools.build:skip_test=True -c tools.graph:skip_test=True)
  fi
  if [[ "$CMD" == "deps" && ${#EXTRA[@]} -gt 0 ]]; then
    args+=("${EXTRA[@]}")
  fi

  if [[ "$DRY_RUN" -eq 1 ]]; then
    "$(pk_repo_script package)" "${args[0]}" --dry-run "${args[@]:1}"
    DEPS_CHANGED=1
    return 0
  fi

  "$(pk_repo_script package)" "${args[@]}" || pk_die "conan install failed for ${build_type} (${label})"

  printf 'key=%s\ntests=%s\n' "$(pk_deps_key "$host_profile")" "$want_tests" \
    > "${conan_dir}/${PK_STAMP_NAME}"
  DEPS_CHANGED=1
}

pk_ensure_host_tools() {
  pk_preset_dirs host-tools || { pk_info "no host-tools preset, skipping host tools"; return 0; }
  local tools_tree="$PRESET_BIN"

  pk_preset_dirs "native-${TYPE_LOWER}" || pk_die "no native-${TYPE_LOWER} preset for host tools"
  local native_toolchain="$PRESET_TOOLCHAIN"
  local native_conan
  native_conan="$(dirname "$(dirname "$native_toolchain")")"

  local saved_changed="$DEPS_CHANGED"
  DEPS_CHANGED=0
  pk_ensure_deps "$TYPE" "" "$native_conan" "$native_toolchain" 0
  local native_changed="$DEPS_CHANGED"
  DEPS_CHANGED="$saved_changed"

  local cached_type
  cached_type="$(pk_cache_get "$tools_tree" CMAKE_BUILD_TYPE || true)"
  if [[ "$cached_type" != "$TYPE" || "$native_changed" -eq 1 ]]; then
    pk_step "host tools ${TYPE}"
    pk_run rm -rf "$tools_tree"
    pk_run cmake --preset host-tools -DCMAKE_BUILD_TYPE="$TYPE" \
      -DCMAKE_TOOLCHAIN_FILE="$(pk_native_path "${PK_REPO_ROOT}/${native_toolchain}")" \
      || pk_die "host-tools configure failed"
  fi
  pk_run cmake --build "$tools_tree" || pk_die "host-tools build failed"
}

# -----------------------------------------------------------------------------
# Configure and build
# -----------------------------------------------------------------------------

# Checks for flag first, then what the command needs, then what the tree
# has, then off.
pk_decide_tests() {
  local needs="$1" cached
  if [[ -n "$TESTS" ]]; then
    WANT_TESTS="$TESTS"
  elif [[ "$needs" == "on" ]]; then
    WANT_TESTS=ON
  elif cached="$(pk_cache_get "$TREE" "${PK_PREFIX}_BUILD_TESTS")" && [[ -n "$cached" ]]; then
    WANT_TESTS="$(pk_normalize_value "$cached")"
  else
    WANT_TESTS=OFF
  fi

  if [[ -n "$CROSS" && "$WANT_TESTS" == "ON" ]]; then
    [[ "$needs" == "on" ]] && pk_die "'${CMD}' runs binaries, a cross build cannot"
    pk_warn "tests are built but not run for cross targets"
  fi
}

pk_configure() {
  local force="$1"
  local fresh=0 reason="" def key value cached
  local defs
  defs=("${PK_PREFIX}_BUILD_TESTS=${WANT_TESTS}")
  [[ ${#CONFIG_DEFS[@]} -gt 0 ]] && defs+=("${CONFIG_DEFS[@]}")

  if [[ ! -f "${TREE}/CMakeCache.txt" ]]; then
    reason="new tree"
  elif [[ ! -f "${TREE}/build.ninja" && ! -f "${TREE}/Makefile" ]]; then
    reason="last configure did not finish"
  elif [[ "$CMD" == "rebuild" ]]; then
    reason="rebuild"
  elif [[ "$RESET" -eq 1 ]]; then
    reason="--reset"; fresh=1
  elif [[ "$DEPS_CHANGED" -eq 1 ]]; then
    reason="dependencies changed"
  elif [[ "$force" -eq 1 ]]; then
    reason="requested"
  else
    for def in "${defs[@]}"; do
      key="${def%%=*}"; key="${key%%:*}"; value="${def#*=}"
      cached="$(pk_cache_get "$TREE" "$key" || true)"
      if [[ "$(pk_normalize_value "$cached")" != "$(pk_normalize_value "$value")" ]]; then
        reason="${key}: ${cached:-unset} -> ${value:-empty}"
        break
      fi
    done
  fi

  if [[ -z "$reason" ]]; then
    pk_info "configure ${TREE}: up to date"
    return 0
  fi

  pk_step "configure ${PRESET}${VARIANT:+ (${VARIANT})}: ${reason}"
  local args
  args=(--preset "$PRESET")
  [[ -n "$VARIANT" ]] && args+=(-B "$TREE")
  [[ "$fresh" -eq 1 ]] && args+=(--fresh)
  for def in "${defs[@]}"; do
    args+=("-D${def}")
  done
  if [[ "$CMD" == "configure" && ${#EXTRA[@]} -gt 0 ]]; then
    args+=("${EXTRA[@]}")
  fi

  pk_run cmake "${args[@]}" || pk_die "configure failed"
}

# deps, host tools and configuration, only when needed.
pk_prepare() {
  local needs_tests="$1" force_configure="$2"
  pk_select
  pk_decide_tests "$needs_tests"
  pk_banner

  DEPS_CHANGED=0
  local want=0
  [[ "$WANT_TESTS" == "ON" ]] && want=1
  [[ -n "$CROSS" ]] && pk_ensure_host_tools
  pk_ensure_deps "$TYPE" "$CROSS" "$CONAN_DIR" "$TOOLCHAIN" "$want"
  pk_configure "$force_configure"
}

pk_build() {
  local args
  args=(--build "$TREE")
  [[ -n "$JOBS" ]] && args+=(-j "$JOBS")
  [[ "$VERBOSE" -eq 1 ]] && args+=(-v)
  if [[ $# -gt 0 ]]; then
    args+=(--target "$@")
  elif [[ ${#TARGETS[@]} -gt 0 ]]; then
    args+=(--target "${TARGETS[@]}")
  fi

  case "$CMD" in
    build|rebuild|install|analyze)
      [[ ${#EXTRA[@]} -gt 0 ]] && args+=(-- "${EXTRA[@]}") ;;
  esac

  pk_step "build ${TREE}"
  pk_run cmake "${args[@]}" || pk_die "build failed"
}

pk_ctest() {
  local args
  args=(--test-dir "$TREE" --output-on-failure)
  [[ -n "$JOBS" ]] && args+=(-j "$JOBS")
  [[ -n "$FILTER" ]] && args+=(-R "$FILTER")
  [[ -n "$LABEL" ]] && args+=(-L "$LABEL")
  [[ ${#EXTRA[@]} -gt 0 ]] && args+=("${EXTRA[@]}")

  pk_step "test ${TREE}"
  pk_run ctest "${args[@]}"
}

# -----------------------------------------------------------------------------
# Commands
# -----------------------------------------------------------------------------

pk_no_positionals() {
  [[ ${#POSITIONAL[@]} -eq 0 ]] || pk_usage_die "unexpected argument '${POSITIONAL[0]}'"
}

cmd_deps() {
  pk_no_positionals
  pk_select
  pk_banner

  DEPS_CHANGED=0
  local want=0 cached
  cached="$(pk_cache_get "$TREE" "${PK_PREFIX}_BUILD_TESTS" || true)"
  [[ "$(pk_normalize_value "$cached")" == "ON" ]] && want=1

  if [[ -n "$CROSS" ]]; then
    pk_ensure_host_tools
  fi
  pk_ensure_deps "$TYPE" "$CROSS" "$CONAN_DIR" "$TOOLCHAIN" "$want"
}

cmd_configure() { pk_no_positionals; pk_prepare off 1; }
cmd_build()     { pk_no_positionals; pk_prepare off 0; pk_build; }

cmd_rebuild() {
  pk_no_positionals
  pk_select
  pk_step "remove ${TREE}"
  pk_run rm -rf "$TREE"
  pk_prepare off 0
  pk_build
}

cmd_test() {
  pk_no_positionals
  pk_prepare on 0
  pk_build
  pk_ctest
}

cmd_install() {
  pk_no_positionals
  pk_prepare off 0
  pk_build
  local prefix="${PREFIX_DIR:-${PK_STAGE_DIR}}"
  pk_step "install into ${prefix}"
  pk_run cmake --install "$TREE" --prefix "$(pk_native_path "$prefix")" || pk_die "install failed"
}

cmd_run() {
  local app="" apps count
  if [[ ${#POSITIONAL[@]} -gt 1 ]]; then
    pk_usage_die "run takes one APP, got: ${POSITIONAL[*]} (app args go after --)"
  fi
  [[ ${#POSITIONAL[@]} -eq 1 ]] && app="${POSITIONAL[0]}"

  if [[ -z "$app" ]]; then
    apps="$(pk_app_names)"
    count="$(printf '%s\n' "$apps" | grep -c . || true)"
    if [[ "$count" -eq 1 ]]; then
      app="$apps"
    elif [[ "$count" -eq 0 ]]; then
      pk_die "no apps/ directories found, name the executable: run NAME"
    else
      pk_usage_die "several apps, pick one: $(printf '%s' "$apps" | tr '\n' ' ')"
    fi
  fi

  [[ -n "$CROSS" ]] && pk_die "cannot run a cross-compiled binary on this machine"
  pk_prepare off 0

  local target="${app}_app"
  if [[ "$DRY_RUN" -eq 0 ]] && ! ninja -C "$TREE" -t query "$target" >/dev/null 2>&1; then
    target="$app"
    ninja -C "$TREE" -t query "$target" >/dev/null 2>&1 || target=""
  fi
  if [[ -n "$target" ]]; then
    pk_build "$target"
  else
    pk_build
  fi

  local exe="${TREE}/bin/${app}${PK_EXE_SUFFIX}"
  if [[ "$DRY_RUN" -eq 0 && ! -f "$exe" ]]; then
    local found
    found="$(find "${TREE}/bin" -maxdepth 1 -type f 2>/dev/null | sed 's|.*/||' | tr '\n' ' ')"
    pk_die "no ${exe}; executables in ${TREE}/bin: ${found:-none}"
  fi

  local run_env="${CONAN_DIR}/generators/conanrun.sh"
  pk_step "run ${app}"
  cd "$PK_ORIG_PWD" || exit 1
  exe="${PK_REPO_ROOT}/${exe}"
  if [[ -f "${PK_REPO_ROOT}/${run_env}" ]]; then
    pk_info "with the Conan run environment ${run_env}"
    pk_show_command "$exe" ${EXTRA[@]+"${EXTRA[@]}"}
    [[ "$DRY_RUN" -eq 1 ]] && return 0
    # shellcheck source=/dev/null
    ( . "${PK_REPO_ROOT}/${run_env}" && exec "$exe" ${EXTRA[@]+"${EXTRA[@]}"} )
  else
    pk_run "$exe" ${EXTRA[@]+"${EXTRA[@]}"}
  fi
}

pk_variant_command() {
  local default_variant="$1" needs_tests="$2"
  [[ -z "$VARIANT" ]] && VARIANT="$default_variant"
  pk_no_positionals
  pk_prepare "$needs_tests" 0
}

cmd_analyze() {
  pk_require_tools clang-tidy cppcheck
  pk_add_option SA_ALL ON
  pk_variant_command analyze off
  pk_build
}

cmd_memcheck() {
  [[ "$(pk_host_platform)" == "linux" ]] || pk_die "memcheck needs Valgrind, which pk only supports on Linux"
  pk_require_tools valgrind
  pk_add_option VALGRIND ON
  [[ -z "$LABEL" ]] && LABEL="valgrind"
  pk_variant_command memcheck on
  pk_build
  pk_ctest
}

cmd_sanitize() {
  local def has_sanitize=0
  for def in ${CONFIG_DEFS[@]+"${CONFIG_DEFS[@]}"}; do
    [[ "${def%%=*}" == "${PK_PREFIX}_SANITIZE" ]] && has_sanitize=1
  done
  [[ "$has_sanitize" -eq 0 ]] && pk_add_option SANITIZE "address,undefined"

  pk_variant_command sanitize on
  pk_build
  pk_ctest
}

cmd_clean() {
  pk_no_positionals
  if [[ "$CLEAN_ALL" -eq 1 ]]; then
    cmd_full_clean
    return $?
  fi

  pk_select
  pk_step "remove ${TREE}"
  pk_run rm -rf "$TREE"
  if [[ "$CLEAN_DEPS" -eq 1 ]]; then
    pk_step "remove Conan output ${CONAN_DIR}"
    pk_run rm -rf "$CONAN_DIR"
  fi
}

# -----------------------------------------------------------------------------
# full-clean
# -----------------------------------------------------------------------------

pk_relative() {
  case "$1" in
    "${PK_REPO_ROOT}"/*) printf '%s\n' "${1#"${PK_REPO_ROOT}"/}" ;;
    *) printf '%s\n' "$1" ;;
  esac
}

# Everything the project's scripts, CMake, Conan and clangd can generate.
pk_full_clean_paths() {
  local path
  {
    pk_clean_paths
    printf '%s\n' \
      "${PK_REPO_ROOT}/${PK_STAGE_DIR}" \
      "${PK_REPO_ROOT}/cmake/projectkit/test_package/build" \
      "${PK_REPO_ROOT}/.cache/clangd" \
      "${PK_REPO_ROOT}/CMakeUserPresets.json" \
      "${PK_REPO_ROOT}/ConanPresets.json" \
      "${PK_REPO_ROOT}/.ninja_deps" \
      "${PK_REPO_ROOT}/.ninja_log"
    for path in "${PK_REPO_ROOT}"/build-* "${PK_REPO_ROOT}"/cmake-build-* \
                "${PK_REPO_ROOT}"/asan.log.* "${PK_REPO_ROOT}"/ubsan.log.*; do
      printf '%s\n' "$path"
    done
  } | while IFS= read -r path; do
    [[ -e "$path" || -L "$path" ]] && printf '%s\n' "$path"
  done | awk '!seen[$0]++'
}

pk_confirm() {
  [[ "$ASSUME_YES" -eq 1 ]] && return 0
  if [[ ! -t 0 ]]; then
    pk_die "not asking on a non-interactive input: pass --yes to delete"
  fi

  local answer
  printf '%s [y/N] ' "$1"
  read -r answer
  local low_answer=$(printf '%s' "$answer" | tr '[:upper:]' '[:lower:]')
  [[ "$low_answer" == "y" || "$low_answer" == "yes" ]]
}

cmd_full_clean() {
  pk_no_positionals
  local paths path size
  paths="$(pk_full_clean_paths)"

  pk_step "full clean of ${PK_PROJECT}"
  if [[ -z "$paths" && "$CLEAN_CACHE" -eq 0 ]]; then
    pk_info "nothing generated is present"
  else
    while IFS= read -r path; do
      [[ -z "$path" ]] && continue

      size="$(du -sh "$path" 2>/dev/null | cut -f1)"
      printf '  %-8s %s\n' "${size:--}" "$(pk_relative "$path")"
    done <<< "$paths"

    if [[ "$CLEAN_CACHE" -eq 1 ]]; then
      printf '  %-8s %s\n' "cache" "this package in the local Conan cache"
    fi

    if [[ "$DRY_RUN" -eq 1 ]]; then
      pk_info "dry run: nothing deleted"
    elif pk_confirm "delete the above?"; then
      while IFS= read -r path; do
        [[ -z "$path" ]] && continue
        pk_run rm -rf "$path"
      done <<< "$paths"

      rmdir "${PK_REPO_ROOT}/.cache" 2>/dev/null || true
      if [[ "$CLEAN_CACHE" -eq 1 ]]; then
        pk_run "$(pk_repo_script package)" remove --yes || pk_warn "removing the Conan cache entry failed"
      fi
      pk_info "removed"
    else
      pk_info "nothing deleted"
      return 1
    fi
  fi

  # What git ignores minus what full-clean owns: things like .vscode/ or
  # personal notes, reported so nothing surprising is hiding, never deleted.
  local leftovers="" entry owned covered
  while IFS= read -r entry; do
    [[ -z "$entry" ]] && continue
    covered=0
    while IFS= read -r owned; do
      [[ -z "$owned" ]] && continue
      owned="$(pk_relative "$owned")"
      case "${entry%/}" in
        "$owned"|"$owned"/*) covered=1; break ;;
      esac
      case "$owned" in
        "${entry%/}"/*) covered=1; break ;;
      esac
    done <<< "$paths"
    [[ "$covered" -eq 0 ]] && leftovers="${leftovers}  ${entry}"$'\n'
  done < <(git clean -ndX 2>/dev/null | sed 's/^Would remove //')
  if [[ -n "$leftovers" ]]; then
    printf '\n%signored by git but not generated by the build, left alone:%s\n' \
      "$PK_BOLD" "$PK_RESET"
    printf '%s' "$leftovers"
  fi
  return 0
}

# -----------------------------------------------------------------------------
# stage
# -----------------------------------------------------------------------------

PK_REPORT=""

pk_report() {
  local line="" field
  for field in "$@"; do
    field="$(printf '%s' "$field" | tr '|\n' '/ ')"
    line="${line}|${field}"
  done
  PK_REPORT="${PK_REPORT}${line#|}"$'\n'
}

pk_report_checks() {
  eval "$(declare -f pk_pass | sed '1s/^pk_pass/pk_verify_pass/')"
  eval "$(declare -f pk_fail | sed '1s/^pk_fail/pk_verify_fail/')"
  eval "$(declare -f pk_skip | sed '1s/^pk_skip/pk_verify_skip/')"
  pk_pass() { pk_verify_pass "$1"; pk_report check "$1" pass; }
  pk_fail() { pk_verify_fail "$1"; pk_report check "$1" fail; return 1; }
  pk_skip() { pk_verify_skip "$1"; pk_report check "$1" skip; }
}

pk_stage_dir_is_safe() {
  case "$PK_STAGE_DIR" in
    ""|"."|"./"|/*|..*|*/..*) return 1 ;;
  esac
  return 0
}

cmd_stage() {
  pk_no_positionals
  pk_stage_dir_is_safe || pk_die "PK_STAGE_DIR='${PK_STAGE_DIR}' must be a directory inside the project"
  pk_prepare off 0
  pk_build

  local stage="$PK_STAGE_DIR"
  local stage_abs="${PK_REPO_ROOT}/${stage}"

  if [[ "$DRY_RUN" -eq 1 ]]; then
    pk_step "stage into ${stage}"
    pk_run rm -rf "$stage"
    pk_run cmake --install "$TREE" --prefix "$(pk_native_path "$stage_abs")"
    pk_info "then: package file checks, pkg-config, consumer project, ${stage}/pk-stage.txt"
    return 0
  fi

  pk_report_checks
  PK_BUILD_TYPE="$TYPE"
  PK_PASS_COUNT=0
  PK_SKIP_COUNT=0
  PK_FAILURES=""

  pk_report meta project "$PK_PROJECT"
  pk_report meta version "$(pk_cache_get "$TREE" CMAKE_PROJECT_VERSION || true)"
  pk_report meta type "$TYPE"
  pk_report meta platform "$PLATFORM_LABEL"
  pk_report meta preset "$PRESET"
  pk_report meta tree "$TREE"
  pk_report meta git "$(git describe --always --dirty 2>/dev/null || echo -)"
  pk_report meta date "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  pk_stage "Install into ${stage}"
  rm -rf "$stage_abs"
  local installed=0
  pk_show_command cmake --install "$TREE" --prefix "$(pk_native_path "$stage_abs")"
  if pk_try "install ${TREE}" cmake --install "$TREE" --prefix "$(pk_native_path "$stage_abs")"; then
    installed=1
    local file
    while IFS= read -r file; do
      [[ -z "$file" ]] && continue
      printf '  %s\n' "$file"
      pk_report file "$file"
    done < <(cd "$stage_abs" && find . -type f | sed 's|^\./||' | sort)
  fi

  pk_stage "Package files"
  local library_type install_rules
  library_type="$(pk_cache_get "$TREE" "${PK_PREFIX}_LIBRARY_TYPE" || true)"
  install_rules="$(pk_cache_get "$TREE" "${PK_PREFIX}_INSTALL" || true)"
  if [[ "$installed" -eq 0 ]]; then
    pk_skip "package files (install failed)"
  elif [[ "$library_type" == "NONE" || "$(pk_normalize_value "$install_rules")" == "OFF" ]]; then
    pk_skip "package files (${PK_PREFIX}_LIBRARY_TYPE=NONE or ${PK_PREFIX}_INSTALL=OFF)"
  else
    local expected
    while IFS= read -r expected; do
      [[ -z "$expected" ]] && continue
      if [[ -f "${stage_abs}/${expected}" ]]; then
        pk_pass "installed ${expected}"
      else
        pk_fail "missing ${expected}"
      fi
    done < <(pk_expected_install_files)

    local pc="${stage_abs}/lib/pkgconfig/${PK_PACKAGE}.pc"
    if [[ ! -f "$pc" ]]; then
      pk_skip "pkg-config (no ${PK_PACKAGE}.pc)"
    elif pk_have pkg-config; then
      pk_try "pkg-config reads ${PK_PACKAGE}.pc" env \
        PKG_CONFIG_PATH="${stage_abs}/lib/pkgconfig" \
        pkg-config --cflags --libs "$PK_PACKAGE"
    else
      pk_skip "pkg-config not installed"
    fi
  fi

  if [[ "$NO_CONSUMER" -eq 1 ]]; then
    pk_stage "Consumer project"
    pk_skip "consumer (--no-consumer)"
  elif [[ -n "$CROSS" ]]; then
    pk_stage "Consumer project"
    pk_skip "consumer (a cross build cannot run here)"
  elif [[ "$stage" != "stage" ]]; then
    pk_stage "Consumer project"
    pk_skip "consumer (verify's consumer reads stage/, PK_STAGE_DIR is ${stage})"
  elif [[ "$installed" -eq 1 ]]; then
    pk_stage_consumer
  fi

  local failed
  failed="$(printf '%s' "$PK_REPORT" | grep -c '^check|.*|fail$' || true)"
  if [[ "$failed" -eq 0 ]]; then
    pk_report result passed
  else
    pk_report result failed
  fi

  if [[ -d "$stage_abs" ]]; then
    {
      printf '# pk stage report: one "kind|field|value" record per line\n'
      printf '# kinds: meta (about the build), file (installed, relative to this\n'
      printf '# directory), check (label|pass, fail or skip), result (passed/failed)\n'
      printf '%s' "$PK_REPORT"
    } > "${stage_abs}/pk-stage.txt"
  fi

  printf '\n%s---- stage %s ----%s\n' "$PK_BOLD" "$TYPE" "$PK_RESET"
  printf 'passed: %d  skipped: %d  failed: %d\n' "$PK_PASS_COUNT" "$PK_SKIP_COUNT" "$failed"
  [[ -f "${stage_abs}/pk-stage.txt" ]] && printf 'report: %s/pk-stage.txt\n' "$stage"
  [[ "$failed" -eq 0 ]]
}

# -----------------------------------------------------------------------------
# sync
# -----------------------------------------------------------------------------

pk_state_get() {
  [[ -f "$PK_SYNC_STATE" ]] || return 1
  sed -n "s/^$1=//p" "$PK_SYNC_STATE" | head -n 1
}

pk_state_write() {
  mkdir -p "$(dirname "$PK_SYNC_STATE")"
  {
    printf '# Written by "pk sync": the template cmake/projectkit comes from and\n'
    printf '# the template commit it was last synced to. Keep it committed.\n'
    printf 'url=%s\n' "$1"
    printf 'branch=%s\n' "$2"
    printf 'commit=%s\n' "$3"
  } > "$PK_SYNC_STATE"
}

# github.com/owner/repo for any https, ssh or scp-style spelling of a URL.
pk_normalize_url() {
  printf '%s\n' "$1" | sed -e 's|^[a-z+]*://||' -e 's|^[^@/]*@||' -e 's|:|/|' \
    -e 's|\.git$||' -e 's|/*$||' | tr '[:upper:]' '[:lower:]'
}

pk_sync_remembered_url() {
  case "$1" in
    *://*|*@*:*) printf '%s\n' "$1" ;;
    *) printf '%s\n' "${2:-$PK_UPSTREAM_URL}" ;;
  esac
}

pk_sync_detect_base() {
  local tip="$1" commit lines best="" best_lines=""
  # shellcheck disable=SC2086
  for commit in $(git rev-list --max-count=500 "$tip" -- $PK_SYNC_PATHS); do
    # shellcheck disable=SC2086
    lines="$(git diff --numstat "$commit" HEAD -- $PK_SYNC_PATHS \
      | awk '{ if ($1 != "-") n += $1 + $2 } END { print n + 0 }')"

    if [[ -z "$best_lines" || "$lines" -lt "$best_lines" ]]; then
      best="$commit"
      best_lines="$lines"
    fi
    [[ "$lines" -eq 0 ]] && break
  done
  [[ -n "$best" ]] || return 1
  printf '%s %s\n' "$best" "$best_lines"
}

pk_sync_run() {
  local patch="$1" url branch state_url name
  git rev-parse --verify -q HEAD >/dev/null || pk_die "sync needs at least one commit in this repository"
  git rev-parse --verify -q MERGE_HEAD >/dev/null && pk_die "finish the merge in progress first"
  git diff --cached --quiet || pk_die "you have staged changes: commit or unstage them first, so the sync commit holds only the kit"

  local dirty
  # shellcheck disable=SC2086
  dirty="$(git status --porcelain -- $PK_SYNC_PATHS "$PK_SYNC_STATE")"
  if [[ -n "$dirty" ]]; then
    printf '%s\n' "$dirty" | sed 's/^/  /' >&2
    pk_die "uncommitted changes in synced paths (above): commit or stash them first"
  fi

  state_url="$(pk_state_get url || true)"
  url="${SYNC_FROM:-${state_url:-$PK_UPSTREAM_URL}}"
  branch="${SYNC_BRANCH:-$(pk_state_get branch || true)}"
  branch="${branch:-$PK_UPSTREAM_BRANCH}"
  name="$(basename "$(printf '%s' "$url" | sed -e 's|\.git$||' -e 's|/*$||')")"
  [[ -n "$name" ]] || name="template"

  local origin
  origin="$(git remote get-url origin 2>/dev/null || true)"
  if [[ -n "$origin" && "$(pk_normalize_url "$origin")" == "$(pk_normalize_url "$url")" ]]; then
    pk_info "this repository is the template (${url}); there is nothing to sync from"
    return 0
  fi

  pk_step "fetch ${url} (${branch})"
  pk_show_command git fetch --no-tags --quiet "$url" "+refs/heads/${branch}:${PK_UPSTREAM_REF}"
  git fetch --no-tags --quiet "$url" "+refs/heads/${branch}:${PK_UPSTREAM_REF}" \
    || pk_die "could not fetch branch '${branch}' of ${url}"

  local tip
  tip="$(git rev-parse "${PK_UPSTREAM_REF}^{commit}")"
  if git merge-base --is-ancestor HEAD "$tip" 2>/dev/null; then
    pk_info "HEAD is already part of ${name}'s history: this is the template or an unchanged copy of it"
    return 0
  fi

  local base="" state_commit found lines
  state_commit="$(pk_state_get commit || true)"
  if [[ -n "$SYNC_BASE" ]]; then
    base="$(git rev-parse --verify -q "${SYNC_BASE}^{commit}")" \
      || pk_die "--base ${SYNC_BASE} is not a commit in ${name}"
    pk_info "base: ${SYNC_BASE} (--base)"
  elif [[ -n "$state_commit" ]] && git merge-base --is-ancestor "$state_commit" "$tip" 2>/dev/null; then
    base="$state_commit"
    pk_info "base: $(git log -1 --format='%h %s' "$base") (last sync)"
  else
    [[ -n "$state_commit" ]] && pk_warn "last synced commit $(printf '%s' "$state_commit" | cut -c1-7) is not in ${url} ${branch} (not pushed yet, or history rewritten); searching instead"
    pk_step "find the ${name} commit this kit matches"
    found="$(pk_sync_detect_base "$tip")" || pk_die "no commit in ${name} touches: ${PK_SYNC_PATHS}"
    base="${found%% *}"
    lines="${found##* }"
    pk_info "base: $(git log -1 --format='%h %s' "$base")"
    if [[ "$lines" -gt 0 ]]; then
      pk_info "${lines} lines of the kit here differ from it and are kept, in:"
      # shellcheck disable=SC2086
      git diff --name-only "$base" HEAD -- $PK_SYNC_PATHS | sed 's/^/    /'
      pk_info "if that base is wrong, pass --base with the right ${name} commit"
    fi
  fi

  local short
  short="$(git rev-parse --short "$tip")"

  # shellcheck disable=SC2086
  if git diff --quiet "$base" "$tip" -- $PK_SYNC_PATHS; then
    pk_info "kit is up to date with ${name} ${short}"
    if [[ -n "$state_commit" ]] && ! git merge-base --is-ancestor "$state_commit" "$tip" 2>/dev/null; then
      pk_info "${PK_SYNC_STATE} keeps $(printf '%s' "$state_commit" | cut -c1-7), which is newer than ${url} ${branch}"
      return 0
    fi
    if [[ "$state_commit" != "$tip" || "$state_url" != "$(pk_sync_remembered_url "$url" "$state_url")" ]]; then
      if [[ "$DRY_RUN" -eq 1 ]]; then
        pk_info "dry run: would record ${name} ${short} in ${PK_SYNC_STATE}"
        return 0
      fi
      pk_state_write "$(pk_sync_remembered_url "$url" "$state_url")" "$branch" "$tip"
      git add "$PK_SYNC_STATE"
      if [[ "$NO_COMMIT" -eq 0 ]]; then
        pk_run git commit -q -m "Record projectkit upstream ${name} ${short}" \
          || pk_die "commit failed; the change is staged, commit it yourself"
        pk_info "recorded ${name} ${short} in ${PK_SYNC_STATE}"
      else
        pk_info "staged ${PK_SYNC_STATE}; commit it when ready"
      fi
    fi
    return 0
  fi

  pk_step "${name} changes since $(git rev-parse --short "$base")"
  # shellcheck disable=SC2086
  git log --format='  %h %s' "${base}..${tip}" -- $PK_SYNC_PATHS
  # shellcheck disable=SC2086
  git diff --full-index --binary "$base" "$tip" -- $PK_SYNC_PATHS > "$patch"
  git apply --stat "$patch" | sed 's/^/ /'

  if [[ "$DRY_RUN" -eq 1 ]]; then
    pk_info "dry run: nothing changed"
    return 0
  fi

  pk_step "apply as a 3-way merge"
  pk_info "git apply --3way with the changes listed above"
  local applied=0
  git apply --3way --whitespace=nowarn "$patch" || applied=1

  pk_state_write "$(pk_sync_remembered_url "$url" "$state_url")" "$branch" "$tip"
  git add "$PK_SYNC_STATE"

  local message
  message="Sync projectkit from ${name} ${short}"

  local conflicts
  conflicts="$(git diff --name-only --diff-filter=U)"
  if [[ "$applied" -ne 0 || -n "$conflicts" ]]; then
    printf '\n%sconflicts%s: both sides changed the same lines in:\n' "$PK_RED" "$PK_RESET"
    printf '%s\n' "$conflicts" | sed 's/^/  /'
    printf '\nfix the <<<<<<< ======= >>>>>>> blocks in those files, then:\n'
    printf '  git add %s\n' "$(printf '%s' "$conflicts" | tr '\n' ' ')"
    printf '  git commit -m "%s"\n' "$message"
    printf 'or undo the whole sync (your other uncommitted work is kept): git reset --merge\n'
    return 1
  fi

  if [[ "$NO_COMMIT" -eq 1 ]]; then
    pk_info "staged: review with 'git diff --cached', then: git commit -m \"${message}\""
    return 0
  fi

  pk_step "commit"
  pk_run git commit -q -m "$message" -m "Upstream: ${url} ${branch} $(git rev-parse "$tip")" \
    || pk_die "commit failed; the sync is staged, commit it yourself: git commit -m \"${message}\""
  git show --stat --format='  %h %s' HEAD | sed 's/^/ /'
}

cmd_sync() {
  pk_no_positionals
  local patch status
  patch="$(mktemp "${TMPDIR:-/tmp}/pk-sync.XXXXXX")" || pk_die "cannot create a temporary file"
  pk_sync_run "$patch"
  status=$?
  rm -f "$patch"
  return "$status"
}

cmd_format() {
  pk_require_tools clang-format
  local files
  if [[ ${#POSITIONAL[@]} -gt 0 ]]; then
    files="$(printf '%s\n' "${POSITIONAL[@]}")"
  else
    local exclude pattern_args=()
    for exclude in $PK_FORMAT_EXCLUDE; do
      pattern_args+=(-e "^${exclude}")
    done
    files="$(git ls-files -co --exclude-standard -- \
      '*.c' '*.h' '*.cc' '*.cpp' '*.cxx' '*.hh' '*.hpp' '*.hxx' \
      | grep -v "${pattern_args[@]}" || true)"
  fi
  [[ -n "$files" ]] || { pk_info "no C or C++ files to format"; return 0; }

  local count
  count="$(printf '%s\n' "$files" | grep -c .)"
  if [[ "$CHECK" -eq 1 ]]; then
    pk_step "check formatting of ${count} files"
    local bad="" file
    while IFS= read -r file; do
      [[ -z "$file" ]] && continue
      clang-format --dry-run --Werror "$file" >/dev/null 2>&1 || bad="${bad}${file}"$'\n'
    done <<< "$files"
    if [[ -n "$bad" ]]; then
      printf '%s' "$bad" | sed 's/^/  needs formatting: /'
      printf "fix with: %s format\n" "$(pk_self)"
      return 1
    fi
    pk_info "all ${count} files are formatted"
    return 0
  fi

  pk_step "format ${count} files"
  local file
  while IFS= read -r file; do
    [[ -z "$file" ]] && continue
    pk_run clang-format -i "$file" || return 1
  done <<< "$files"
}

cmd_status() {
  pk_no_positionals
  printf '%s%s%s %s  (%s, prefix %s)\n' "$PK_BOLD" "$PK_PROJECT" "$PK_RESET" \
    "$(git describe --always --dirty 2>/dev/null || echo "-")" "$PK_REPO_ROOT" "$PK_PREFIX"

  printf '\n%sbuild trees%s\n' "$PK_BOLD" "$PK_RESET"
  local cache tree any=0 option value line
  for cache in build/*/CMakeCache.txt; do
    [[ -f "$cache" ]] || continue
    any=1
    tree="$(dirname "$cache")"
    line="$(pk_cache_get "$tree" CMAKE_BUILD_TYPE || true)"
    printf '  %-34s %-15s' "$tree" "${line:--}"
    for option in BUILD_TESTS BUILD_APPS LIBRARY_TYPE WERROR SANITIZE SA_ALL LTO COVERAGE VALGRIND; do
      value="$(pk_cache_get "$tree" "${PK_PREFIX}_${option}" || true)"
      case "$option:$(pk_normalize_value "$value")" in
        BUILD_TESTS:ON)  printf ' tests' ;;
        BUILD_APPS:OFF)  printf ' no-apps' ;;
        LIBRARY_TYPE:OFF) ;;
        LIBRARY_TYPE:*)  printf ' lib=%s' "$(pk_lower "$value")" ;;
        SANITIZE:OFF) ;;
        SANITIZE:*)      printf ' sanitize=%s' "$value" ;;
        WERROR:ON)       printf ' werror' ;;
        SA_ALL:ON)       printf ' analyze' ;;
        LTO:ON)          printf ' lto' ;;
        COVERAGE:ON)     printf ' coverage' ;;
        VALGRIND:ON)     printf ' valgrind' ;;
      esac
    done
    printf '\n'
  done
  [[ "$any" -eq 0 ]] && printf "  none yet, '%s build' creates one\n" "$(pk_self)"

  printf '\n%sConan output%s\n' "$PK_BOLD" "$PK_RESET"
  any=0
  local toolchain dir tests key state
  for toolchain in build/*/generators/conan_toolchain.cmake; do
    [[ -f "$toolchain" ]] || continue
    any=1
    dir="$(dirname "$(dirname "$toolchain")")"
    if key="$(pk_stamp_get "$dir" key)"; then
      tests="$(pk_stamp_get "$dir" tests || echo 0)"
      state="installed by pk"
      [[ "$tests" == "1" ]] && state="${state}, with Catch2" || state="${state}, without Catch2"
    else
      state="installed outside pk (next pk use reinstalls once)"
    fi
    printf '  %-34s %s\n' "$dir" "$state"
  done
  [[ "$any" -eq 0 ]] && printf '  none\n'

  printf '\n%s%s/%s\n' "$PK_BOLD" "$PK_STAGE_DIR" "$PK_RESET"
  local report="${PK_STAGE_DIR}/pk-stage.txt"
  if [[ -f "$report" ]]; then
    printf '  %s from %s, %s, %s checks, %s\n' \
      "$(sed -n 's/^meta|type|//p' "$report")" \
      "$(sed -n 's/^meta|preset|//p' "$report")" \
      "$(sed -n 's/^meta|date|//p' "$report")" \
      "$(grep -c '^check|' "$report")" \
      "$(sed -n 's/^result|//p' "$report")"
  elif [[ -d "$PK_STAGE_DIR" ]]; then
    printf '  present, not made by stage (no pk-stage.txt)\n'
  else
    printf '  none\n'
  fi

  printf '\n%scompile_commands.json%s\n' "$PK_BOLD" "$PK_RESET"
  if [[ -L compile_commands.json ]]; then
    printf '  -> %s\n' "$(readlink compile_commands.json)"
  elif [[ -f compile_commands.json ]]; then
    printf '  copy (not a link)\n'
  else
    printf '  none\n'
  fi
}

cmd_list() {
  pk_no_positionals
  printf '%sbuild types%s  Debug Release RelWithDebInfo MinSizeRel (default %s)\n' \
    "$PK_BOLD" "$PK_RESET" "$PK_DEFAULT_TYPE"

  printf '\n%sapps%s (pk run NAME)\n' "$PK_BOLD" "$PK_RESET"
  local apps
  apps="$(pk_app_names)"
  if [[ -n "$apps" ]]; then printf '%s\n' "$apps" | sed 's/^/  /'; else printf '  none\n'; fi

  printf '\n%scross targets%s (pk build -x NAME)\n' "$PK_BOLD" "$PK_RESET"
  local name verdict reason any=0
  while IFS= read -r name; do
    [[ -z "$name" ]] && continue
    any=1
    verdict="$(pk_target_availability "cross-${name}" strict 2>/dev/null | sed -n '1p')"
    reason="$(pk_target_availability "cross-${name}" strict 2>/dev/null | sed -n '2p')"
    if [[ "$verdict" == "yes" ]]; then
      printf '  %-28s %sready%s\n' "$name" "$PK_GREEN" "$PK_RESET"
    elif [[ -n "$verdict" ]]; then
      printf '  %-28s %s\n' "$name" "${reason:-not available}"
    else
      printf '  %s\n' "$name"
    fi
  done < <(pk_cross_names)
  [[ "$any" -eq 0 ]] && printf '  none\n'

  printf '\n%snative presets%s\n' "$PK_BOLD" "$PK_RESET"
  pk_preset_query configure-presets | grep -e '^native-' -e '^host-tools$' | sed 's/^/  /'
}

pk_tool_line() {
  local tool="$1" need="$2" version
  if command -v "$tool" >/dev/null 2>&1; then
    version="$("$tool" --version 2>/dev/null | head -n 1)"
    printf '  %sOK%s    %-13s %s\n' "$PK_GREEN" "$PK_RESET" "$tool" "$version"
    return 0
  fi

  if [[ "$need" == "required" ]]; then
    printf '  %sMISS%s  %-13s required\n' "$PK_RED" "$PK_RESET" "$tool"
    return 1
  fi

  printf '  %s--%s    %-13s optional: %s\n' "$PK_YELLOW" "$PK_RESET" "$tool" "$need"
  return 0
}

cmd_doctor() {
  pk_no_positionals
  local failed=0
  printf '%shost%s     %s %s' "$PK_BOLD" "$PK_RESET" "$(pk_host_platform)" "$(pk_host_arch)"
  [[ -n "${MSYSTEM:-}" ]] && printf ' (MSYSTEM=%s)' "$MSYSTEM"
  printf ', bash %s\n' "${BASH_VERSION%%(*}"
  printf '%sproject%s  %s at %s\n\n' "$PK_BOLD" "$PK_RESET" "$PK_PROJECT" "$PK_REPO_ROOT"

  printf '%srequired%s\n' "$PK_BOLD" "$PK_RESET"
  local tool
  for tool in conan cmake ctest ninja git; do
    pk_tool_line "$tool" required || failed=1
  done

  local compiler=""
  for tool in gcc clang cc; do
    command -v "$tool" >/dev/null 2>&1 && { compiler="$tool"; break; }
  done
  if [[ -n "$compiler" ]]; then
    pk_tool_line "$compiler" required
  else
    printf '  %sMISS%s  %-13s required: gcc, clang or cc\n' "$PK_RED" "$PK_RESET" "compiler"
    failed=1
  fi

  printf '\n%soptional%s\n' "$PK_BOLD" "$PK_RESET"
  pk_tool_line clang-format "pk format"
  pk_tool_line clang-tidy "pk analyze"
  pk_tool_line cppcheck "pk analyze"
  pk_tool_line ccache "faster rebuilds (sccache works too)"
  pk_tool_line pkg-config "verify's pkg-config check"
  [[ "$(pk_host_platform)" == "linux" ]] && pk_tool_line valgrind "pk memcheck"

  if command -v cmake >/dev/null 2>&1; then
    local cmake_version major minor
    cmake_version="$(cmake --version | head -n 1 | sed 's/[^0-9.]//g')"
    major="${cmake_version%%.*}"; minor="${cmake_version#*.}"; minor="${minor%%.*}"
    if [[ "$major" -lt 3 || ( "$major" -eq 3 && "$minor" -lt 30 ) ]]; then
      printf '\n%sproblem%s CMake %s is older than 3.30, which the project requires\n' \
        "$PK_RED" "$PK_RESET" "$cmake_version"
      failed=1
    fi
  fi

  printf '\n%sConan%s\n' "$PK_BOLD" "$PK_RESET"
  if command -v conan >/dev/null 2>&1; then
    if conan profile path default >/dev/null 2>&1; then
      printf '  %sOK%s    default profile %s\n' "$PK_GREEN" "$PK_RESET" "$(conan profile path default 2>/dev/null)"
    elif [[ "$FIX" -eq 1 ]]; then
      pk_run conan profile detect --exist-ok || failed=1
    else
      printf "  %sMISS%s  no default profile: run '%s doctor --fix'\n" "$PK_RED" "$PK_RESET" "$(pk_self)"
      failed=1
    fi
    [[ -f "profiles/${PK_NATIVE_PROFILE}" ]] \
      && printf '  %sOK%s    profiles/%s\n' "$PK_GREEN" "$PK_RESET" "$PK_NATIVE_PROFILE" \
      || printf '  %s--%s    no profiles/%s, the default profile is used\n' "$PK_YELLOW" "$PK_RESET" "$PK_NATIVE_PROFILE"
  fi

  printf '\n%snative verify targets here%s\n' "$PK_BOLD" "$PK_RESET"
  local record name kind
  while IFS= read -r record; do
    name="${record%%|*}"; kind="$(printf '%s' "$record" | cut -d'|' -f2)"
    [[ "$kind" == "native" ]] || continue
    pk_target_runnable_here "$name" && printf '  %s\n' "$name"
  done < <(pk_target_records)

  printf '\n'
  if [[ "$failed" -eq 1 ]]; then
    printf '%snot ready%s: fix the MISS lines above\n' "$PK_RED" "$PK_RESET"
    return 1
  fi
  printf "%sready%s: try '%s build'\n" "$PK_GREEN" "$PK_RESET" "$(pk_self)"
}

cmd_shell_init() {
  cat <<'EOF'
# projectkit 'pk': runs the nearest scripts/pk.sh from anywhere in a project.
pk() {
  local dir="$PWD"
  while [ "$dir" != "/" ]; do
    if [ -x "$dir/scripts/pk.sh" ]; then
      PK_SELF_NAME=pk "$dir/scripts/pk.sh" "$@"
      return $?
    fi
    dir="$(dirname "$dir")"
  done
  echo "pk: no scripts/pk.sh in $PWD or above" >&2
  return 2
}

_pk_complete() {
  local dir="$PWD" script=""
  while [ "$dir" != "/" ]; do
    [ -x "$dir/scripts/pk.sh" ] && { script="$dir/scripts/pk.sh"; break; }
    dir="$(dirname "$dir")"
  done
  [ -n "$script" ] || return 0
  local cur="${COMP_WORDS[COMP_CWORD]}" command=""
  [ "$COMP_CWORD" -gt 1 ] && command="${COMP_WORDS[1]}"
  local IFS=$'\n'
  COMPREPLY=($(compgen -W "$("$script" __words "$command" "$cur" 2>/dev/null)" -- "$cur"))
}
complete -o default -F _pk_complete pk
EOF
}

cmd_words() {
  local command="${1:-}" cur="${2:-}" resolved flag spelling part
  if [[ -z "$command" ]]; then
    # shellcheck disable=SC2086
    printf '%s\n' $PK_COMMANDS
    return 0
  fi
  resolved="$(pk_resolve_command "$command")" || return 0

  case "$cur" in
    -*)
      for flag in $(pk_command_flags "$resolved"); do
        spelling="$(pk_flag_spelling "$flag")"
        for part in $(printf '%s' "$spelling" | tr ',' ' '); do
          case "$part" in
            -*) printf '%s\n' "${part%%=*}" ;;
          esac
        done
      done
      printf '%s\n' --help
      ;;

    *)
      case "$resolved" in
        help)
          # shellcheck disable=SC2086
          printf '%s\n' $PK_COMMANDS ;;
        verify) printf '%s\n' list list-possible run run-possible clean help ;;
        package) printf '%s\n' reference install create build export export-pkg list info path editable remove upload cache-clean help ;;
        dep)
          printf '%s\n' ls add set rm update lock check why tree help
          [[ -f deps.json ]] && sed -n 's/^    "\([a-z0-9_.+-]*\)": {$/\1/p' deps.json ;;
        format|status|doctor|list|shell-init|rename|full-clean|sync) ;;
        *)
          printf '%s\n' debug release relwithdebinfo minsizerel
          [[ "$resolved" == "run" ]] && pk_app_names
          ;;
      esac
      ;;
  esac
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

main() {
  if [[ $# -eq 0 ]]; then
    pk_help_overview
    exit 0
  fi

  local word="$1" resolved
  shift

  case "$word" in
    -h|--help) pk_help_overview; exit 0 ;;
    __words) cmd_words "$@"; exit 0 ;;
  esac

  if ! resolved="$(pk_resolve_command "$word")"; then
    case "$resolved" in
      ambiguous:*)
        pk_usage_die "'${word}' could be:${resolved#ambiguous:}" ;;
      *)
        local suggestions
        suggestions="$(pk_suggest_commands "$word")"
        if [[ -n "$suggestions" ]]; then
          pk_usage_die "unknown command '${word}', did you mean: ${suggestions}?"
        fi
        pk_usage_die "unknown command '${word}'" ;;
    esac
  fi
  CMD="$resolved"

  case "$CMD" in
    verify)  exec "$(pk_repo_script verify)" "$@" ;;
    dep)     pk_dep_exec "$@" ;;
    package) exec "$(pk_repo_script package)" "$@" ;;
    rename)  exec "$(pk_repo_script bootstrap)" "$@" ;;
    help)
      if [[ $# -eq 0 ]]; then
        pk_help_overview
      else
        local topic
        topic="$(pk_resolve_command "$1")" || pk_usage_die "no command '$1'"
        [[ "$topic" == "dep" ]] && pk_dep_exec help "${@:2}"
        CMD="$topic"
        pk_help_command "$topic"
      fi
      exit 0 ;;
    shell-init) cmd_shell_init; exit 0 ;;
  esac

  pk_parse_args "$@"

  local started="$SECONDS" status=0
  case "$CMD" in
    build)     cmd_build ;;
    run)       cmd_run ;;
    test)      cmd_test ;;
    configure) cmd_configure ;;
    deps)      cmd_deps ;;
    install)   cmd_install ;;
    rebuild)   cmd_rebuild ;;
    clean)     cmd_clean ;;
    full-clean) cmd_full_clean ;;
    stage)     cmd_stage ;;
    sync)      cmd_sync ;;
    analyze)   cmd_analyze ;;
    memcheck)  cmd_memcheck ;;
    sanitize)  cmd_sanitize ;;
    format)    cmd_format ;;
    status)    cmd_status ;;
    list)      cmd_list ;;
    doctor)    cmd_doctor ;;
  esac
  status=$?

  case "$CMD" in
    build|test|configure|deps|install|stage|rebuild|analyze|memcheck|sanitize)
      if [[ "$status" -eq 0 ]]; then
        printf '\n%sdone%s in %ss\n' "$PK_GREEN" "$PK_RESET" "$((SECONDS - started))"
      else
        printf '\n%sfailed%s after %ss\n' "$PK_RED" "$PK_RESET" "$((SECONDS - started))"
      fi ;;
  esac
  exit "$status"
}

main "$@"
