#!/usr/bin/env bash
# shellcheck shell=bash
#
# Registry of every target the ProjectKit verify script knows how to verify.
# A case statement and not an associative array because macOS still ships bash
# 3.2 and that is what I went with.
#
# Record fields: name|kind|os|arch|env|probe|description
#   os     host OS family required: linux, macos, windows, any
#   arch   host arch required: x86_64, armv8, any
#   env    MSYSTEM value required, or "-"
#   probe  executable that must be on PATH, or "-"
#
# A target is only reported as runnable when every field it names is satisfied,
# an environment you don't have installed shows up as such rather than being
# attempted and failing.
#
# - If you would like to stop this behaviour and get all targets that are
#   *possible* to run on the host machine and not what can, then pass the
#   '--possible' flag.

pk_target_records() {
  printf '%s\n' \
    "linux-x86_64|native|linux|x86_64|-|-|Linux x86_64, native toolchain" \
    "linux-armv8|native|linux|armv8|-|-|Linux armv8, native toolchain" \
    "macos-x86_64|native|macos|x86_64|-|-|macOS x86_64, Apple Clang" \
    "macos-armv8|native|macos|armv8|-|-|macOS armv8, Apple Clang" \
    "windows-ucrt64|native|windows|x86_64|UCRT64|gcc|Windows x86_64, MSYS2 UCRT64 (GCC, UCRT)" \
    "windows-clang64|native|windows|x86_64|CLANG64|clang|Windows x86_64, MSYS2 CLANG64 (Clang, libc++)" \
    "windows-clangarm64|native|windows|armv8|CLANGARM64|clang|Windows armv8, MSYS2 CLANGARM64 (Clang, libc++)" \
    "cross-x86_64-linux-gnu|cross|any|any|-|x86_64-linux-gnu-gcc|Cross to Linux x86_64 via x86_64-linux-gnu" \
    "cross-aarch64-linux-gnu|cross|any|any|-|aarch64-linux-gnu-gcc|Cross to Linux armv8 via aarch64-linux-gnu" \
    "cross-x86_64-mingw-w64|cross|any|any|-|x86_64-w64-mingw32-gcc|Cross to Windows x86_64 via MinGW-w64 GCC" \
    "cross-aarch64-mingw-llvm-w64|cross|any|any|-|aarch64-w64-mingw32-clang|Cross to Windows armv8 via llvm-mingw"
}

pk_host_platform() {
  case "$(uname -s 2>/dev/null || echo unknown)" in
    Linux)                printf 'linux\n' ;;
    Darwin)               printf 'macos\n' ;;
    MINGW*|MSYS*|CYGWIN*) printf 'windows\n' ;;
    *) printf 'unknown\n' ;;
  esac
}

pk_host_arch() {
  case "$(uname -m 2>/dev/null || echo unknown)" in
    x86_64|amd64)         printf 'x86_64\n' ;;
    aarch64|arm64|armv8*) printf 'armv8\n' ;;
    *) printf 'unknown\n' ;;
  esac
}

pk_target_field() {
  local name="$1" index="$2" record
  while IFS= read -r record; do
    case "$record" in
      "${name}|"*)
        printf '%s' "$record" | cut -d'|' -f"$index"
        return 0
        ;;
    esac
  done < <(pk_target_records)
  return 1
}

pk_target_exists() { pk_target_field "$1" 1 >/dev/null 2>&1; }
pk_target_kind()   { pk_target_field "$1" 2; }
pk_target_desc()   { pk_target_field "$1" 7; }

# Prints "yes" when the target can run here, otherwise "no" and a reason on the
# second line. Never runs anything.
#
# Mode comes from PK_SELECT_MODE, or the second argument:
#   strict    (default) every field must be satisfied
#   possible  only os and arch are checked, so a target whose environment is
#             not active or whose toolchain is not installed still counts
pk_target_availability() {
  local name="$1"
  local mode="${2:-${PK_SELECT_MODE:-strict}}"
  local want_os want_arch want_env probe
  want_os="$(pk_target_field "$name" 3)"
  want_arch="$(pk_target_field "$name" 4)"
  want_env="$(pk_target_field "$name" 5)"
  probe="$(pk_target_field "$name" 6)"

  if [[ "$want_os" != "any" && "$want_os" != "$(pk_host_platform)" ]]; then
    printf 'no\nneeds %s host, this is %s\n' "$want_os" "$(pk_host_platform)"
    return 1
  fi

  if [[ "$want_arch" != "any" && "$want_arch" != "$(pk_host_arch)" ]]; then
    printf 'no\nneeds %s host, this is %s\n' "$want_arch" "$(pk_host_arch)"
    return 1
  fi

  # os and arch are the only properties of the machine itself: everything below
  # is something you could install or a terminal you could open.
  #
  # !! "Possible" stops here !!
  if [[ "$mode" == "possible" ]]; then
    printf 'yes\n\n'
    return 0
  fi

  # MSYSTEM is fixed by which MSYS2 launcher started the shell: it sets PATH to
  # that environment's /bin. Reassigning the variable would not move PATH, so
  # a different environment requires an entire seperate terminal.
  if [[ "$want_env" != "-" && "${MSYSTEM:-}" != "$want_env" ]]; then
    printf 'no\nneeds MSYSTEM=%s, this shell is %s\n' \
      "$want_env" "${MSYSTEM:-unset}"
    return 1
  fi

  if [[ "$probe" != "-" ]] && ! command -v "$probe" >/dev/null 2>&1; then
    printf 'no\n%s not on PATH\n' "$probe"
    return 1
  fi

  if [[ "$(pk_target_kind "$name")" == "cross" ]]; then
    local triple="${name#cross-}"
    if [[ ! -f "${PK_REPO_ROOT}/profiles/${triple}" ]]; then
      printf 'no\nno profiles/%s\n' "$triple"
      return 1
    fi
  fi

  printf 'yes\n\n'
  return 0
}

pk_target_runnable_here() {
  local result
  result="$(pk_target_availability "$1" | head -n 1)"
  [[ "$result" == "yes" ]]
}

# Applies one target's configuration to the current shell. Callers run this in
# a subshell so settings DON'T overwrite eachother / leak.
pk_target_configure() {
  local name="$1"

  # A function body is not a closure: $name has to outlive this function.
  PK_TARGET_NAME="$name"

  PK_PLATFORM_LABEL="$(pk_target_desc "$name")"
  PK_BUILD_PROFILE="${PK_REPO_ROOT}/profiles/native"
  PK_HOST_PROFILE=""
  PK_PRESET_PREFIX="native"

  PK_LIBRARY_TYPES="STATIC SHARED STATIC+SHARED"
  PK_REQUIRED_TOOLS="conan cmake ctest ninja git"

  # Setup and final stages run once. Type stages run once per build type.
  PK_SETUP_STAGES="
    environment
    clean_slate"
  PK_TYPE_STAGES="
    workflow
    library_matrix
    auto_discovery
    install
    consumer
    cpack
    host_tools"
  PK_FINAL_STAGES="
    reset"

  case "$name" in
    linux-x86_64|linux-armv8|macos-x86_64|macos-armv8)
      ;;

    windows-ucrt64|windows-clang64|windows-clangarm64)
      ;;

    cross-*)
      local triple="${name#cross-}"
      PK_HOST_PROFILE="${PK_REPO_ROOT}/profiles/${triple}"
      PK_PRESET_PREFIX="$triple"
      PK_LIBRARY_TYPES="STATIC SHARED"
      PK_REQUIRED_TOOLS="conan cmake ninja git"

      PK_TYPE_STAGES="
        host_tools_for_cross
        cross_build
        library_matrix"
      ;;

    *)
      printf 'unknown target: %s\n' "$name" >&2
      return 1
      ;;
  esac

  # !! Always strict !!
  pk_platform_check() {
    local verdict reason
    verdict="$(pk_target_availability "$PK_TARGET_NAME" strict | sed -n '1p')"
    reason="$(pk_target_availability "$PK_TARGET_NAME" strict | sed -n '2p')"

    if [[ "$verdict" == "yes" ]]; then
      pk_pass "target ${PK_TARGET_NAME} is available here"
      return 0
    fi

    pk_fail "target ${PK_TARGET_NAME} not available: ${reason}"
    return 1
  }
}
