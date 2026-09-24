#!/usr/bin/env bash
# shellcheck shell=bash
#
# Platform-neutral base for the ProjectKit verification script. Nothing here
# knows the project's name: it comes from PK_PROJECT from the top-level
# project() call, or from scripts/helpers/verify/verify.conf in the project.
# Kept compatible with bash 3.2 because that is what macOS still ships as
# /bin/bash:
#   - no associative arrays
#   - no readarray/mapfile
#   - no [[ -v ]]
#   - no ${var,,} lowercase expansion
#
# A caller sets only what its target needs, then calls 'pk_run_stages'. The
# stage lists **are data**, so a cross target that cannot execute what it builds
# names fewer stages rather than setting skip flags everywhere.
#
# Stages come in three lists:
#   PK_SETUP_STAGES   once, before anything is built
#   PK_TYPE_STAGES    once per entry in PK_BUILD_TYPES, as a pipeline
#   PK_FINAL_STAGES   once, after every build type
#
# Nothing is ever built in a build type that was not asked for.

[[ -n "${PK_VERIFY_BASE_SOURCED:-}" ]] && return 0
PK_VERIFY_BASE_SOURCED=1

set -u -o pipefail

: "${PK_REPO_ROOT:=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

pk_detect_project() {
  local file="${PK_REPO_ROOT}/CMakeLists.txt"
  [[ -f "$file" ]] || return 0
  sed -n 's/^[[:space:]]*project[[:space:]]*([[:space:]]*\([A-Za-z0-9_.+-]\{1,\}\).*/\1/p' \
    "$file" | head -n 1
}

if [[ -f "${PK_REPO_ROOT}/scripts/helpers/verify/verify.conf" ]]; then
  # shellcheck source=/dev/null
  source "${PK_REPO_ROOT}/scripts/helpers/verify/verify.conf"
fi

: "${PK_PROJECT:=$(pk_detect_project)}"

if [[ -z "${PK_PROJECT}" ]]; then
  printf 'cannot determine the project name: set PK_PROJECT or add a\n' >&2
  printf 'project() call to %s/CMakeLists.txt\n' "$PK_REPO_ROOT" >&2
  exit 2
fi

: "${PK_PACKAGE:=${PK_PROJECT}}"
: "${PK_LINK_TARGET:=${PK_PACKAGE}::${PK_PACKAGE}}"
: "${PK_CONSUMER_SOURCE:=}"
: "${PK_SCRATCH_DIR:=${PK_REPO_ROOT}/src/${PK_PROJECT}/scratch}"
PK_PREFIX="$(printf '%s' "$PK_PROJECT" | tr '[:lower:]' '[:upper:]' | tr -c 'A-Z0-9' '_')"
PK_PREFIX="${PK_PREFIX%_}"

: "${PK_CONSUMER_DIR:=${TMPDIR:-/tmp}/${PK_PROJECT}-consumer}"
: "${PK_PLATFORM_LABEL:=$(uname -s 2>/dev/null || echo unknown) $(uname -m 2>/dev/null || echo unknown)}"

: "${PK_BUILD_PROFILE:=${PK_REPO_ROOT}/profiles/native}"
: "${PK_HOST_PROFILE:=}"

# Space separated CMake build types. Each one uses the preset
# "<PK_PRESET_PREFIX>-<lowercase type>", e.g. native-minsizerel.
: "${PK_BUILD_TYPES:=Debug Release}"
: "${PK_PRESET_PREFIX:=native}"
: "${PK_HOST_TOOLS_PRESET:=host-tools}"

# Optional file that receives one "target|type|result" line per build type.
: "${PK_RESULTS_FILE:=}"

: "${PK_LIBRARY_TYPES:=
    STATIC
    SHARED
    STATIC+SHARED}"

: "${PK_REQUIRED_TOOLS:=
    conan
    cmake
    ctest
    ninja
    git}"

: "${PK_SETUP_STAGES:=
    environment
    clean_slate}"

# Each stage may rely on the build tree or stage/ left by the one before it,
# for the same build type.
: "${PK_TYPE_STAGES:=
    workflow
    library_matrix
    auto_discovery
    install
    consumer
    cpack
    host_tools}"

: "${PK_FINAL_STAGES:=
    reset}"

# Set by pk_run_stages for each pass, empty when outside per-type loop.
PK_BUILD_TYPE=""
PK_PRESET=""
PK_SETUP_FAILED=0

if [[ -z "${PK_EXE_SUFFIX+x}" ]]; then
  case "$(uname -s 2>/dev/null || echo unknown)" in
    MINGW*|MSYS*|CYGWIN*) PK_EXE_SUFFIX=".exe" ;;
    *) PK_EXE_SUFFIX="" ;;
  esac
fi

pk_have_function() { declare -f "$1" >/dev/null 2>&1; }
pk_have() { command -v "$1" >/dev/null 2>&1; }

pk_preset_for() {
  printf '%s-%s\n' "$PK_PRESET_PREFIX" \
    "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
}

pk_clean_paths() {
  printf '%s\n' \
    "${PK_REPO_ROOT}/build" \
    "${PK_REPO_ROOT}/stage" \
    "${PK_REPO_ROOT}/_install" \
    "${PK_REPO_ROOT}/compile_commands.json" \
    "${PK_SCRATCH_DIR}" \
    "${PK_CONSUMER_DIR}"
}

# -----------------------------------------------------------------------------
# Hooks
# -----------------------------------------------------------------------------
# Override any of these in the platform script.
# Each default is a no-op or a generic implementation, everything is optional.

# Extra environment assertions. Return non-zero to abort the whole run: use
# this only for conditions that make every later stage meaningless/impossible.
pk_platform_check() { return 0; }

# Runs after the environment stage, before anything is built.
pk_platform_setup() { return 0; }

# Runs at the very end, before the summary.
pk_platform_teardown() { return 0; }

# Files that must exist under stage/ after installing.
# Override when a platform installs a different set.
pk_expected_install_files() {
  printf '%s\n' \
    "lib/cmake/${PK_PACKAGE}/${PK_PACKAGE}Config.cmake" \
    "lib/cmake/${PK_PACKAGE}/${PK_PACKAGE}ConfigVersion.cmake" \
    "lib/cmake/${PK_PACKAGE}/${PK_PACKAGE}Targets.cmake" \
    "lib/pkgconfig/${PK_PACKAGE}.pc"
}

if [[ -t 1 ]]; then
  PK_BOLD=$'\033[1m'
  PK_RED=$'\033[31m'
  PK_GREEN=$'\033[32m'
  PK_YELLOW=$'\033[33m'
  PK_RESET=$'\033[0m'
else
  PK_BOLD=""; PK_RED=""; PK_GREEN=""; PK_YELLOW=""; PK_RESET=""
fi

PK_STAGE_NUMBER=0
PK_PASS_COUNT=0
PK_SKIP_COUNT=0
PK_FAILURES=""

# Inside the per-type loop every header carries the build type:
pk_stage() {
  local tag=""
  [[ -n "$PK_BUILD_TYPE" ]] && tag="[${PK_BUILD_TYPE}] "
  PK_STAGE_NUMBER=$((PK_STAGE_NUMBER + 1))
  printf '\n%s---- %d. %s%s ----%s\n' \
    "$PK_BOLD" "$PK_STAGE_NUMBER" "$tag" "$1" "$PK_RESET"
}

pk_pass() {
  printf '%sOK%s    %s\n' "$PK_GREEN" "$PK_RESET" "$1"
  PK_PASS_COUNT=$((PK_PASS_COUNT + 1))
}

pk_fail() {
  local entry="$1"
  [[ -n "$PK_BUILD_TYPE" ]] && entry="[${PK_BUILD_TYPE}] $1"
  printf '%sFAIL%s  %s\n' "$PK_RED" "$PK_RESET" "$1"
  PK_FAILURES="${PK_FAILURES}${entry}"$'\n'
  return 1
}

pk_skip() {
  printf '%sSKIP%s  %s\n' "$PK_YELLOW" "$PK_RESET" "$1"
  PK_SKIP_COUNT=$((PK_SKIP_COUNT + 1))
}

# Records a failure but will never abort:
pk_try() {
  local label="$1"; shift
  if "$@"; then
    pk_pass "$label"
    return 0
  fi
  pk_fail "$label"
  return 1
}

# Conan owns build/<BuildType>/ and CMake owns build/<presetName>/. Deleting
# the build/ directory therefore invalidates every preset's toolchainFile. Any
# stage that does so must call this again before configuring.
pk_conan_install() {
  if [[ -n "$PK_HOST_PROFILE" ]]; then
    conan install "$PK_REPO_ROOT" \
      -pr:b "$PK_BUILD_PROFILE" -pr:h "$PK_HOST_PROFILE" \
      -s build_type="$1" --build=missing
  else
    conan install "$PK_REPO_ROOT" -pr:a "$PK_BUILD_PROFILE" \
      -s build_type="$1" --build=missing
  fi
}

# The host-tools preset fixes toolchainFile at build/Release/...; presets
# have no macro for the build type, so both are overridden here. A -D on the
# command line wins over the preset's value, so it can be easily overrided.
pk_configure_host_tools() {
  cmake --preset "$PK_HOST_TOOLS_PRESET" \
    -DCMAKE_BUILD_TYPE="$PK_BUILD_TYPE" \
    -DCMAKE_TOOLCHAIN_FILE="${PK_REPO_ROOT}/build/${PK_BUILD_TYPE}/generators/conan_toolchain.cmake"
}

# Streams conan's output and keeps a copy in $1, so it can be searched after a
# single run. pipefail makes the pipeline report conan's exit status.
pk_conan_install_logged() {
  local log="$1" build_type="$2"
  pk_conan_install "$build_type" 2>&1 | tee "$log"
}

pk_cleanup() {
  local path
  while IFS= read -r path; do
    rm -rf "$path"
  done < <(pk_clean_paths)
}

# -----------------------------------------------------------------------------
# Setup stages
# -----------------------------------------------------------------------------

pk_stage_environment() {
  pk_stage "Environment"
  printf 'target:   %s\n' "$PK_PLATFORM_LABEL"
  printf 'build:    %s\n' "$(basename "$PK_BUILD_PROFILE")"
  if [[ -n "$PK_HOST_PROFILE" ]]; then
    printf 'host:     %s\n' "$(basename "$PK_HOST_PROFILE")"
  fi
  printf 'types:    %s\n' "$PK_BUILD_TYPES"

  local tool
  for tool in $PK_REQUIRED_TOOLS; do
    if pk_have "$tool"; then
      pk_pass "found $tool"
    else
      pk_fail "missing $tool"
      return 1
    fi
  done

  pk_platform_check || return 1
  pk_platform_setup
}

pk_stage_clean_slate() {
  pk_stage "Clean slate"
  pk_cleanup
  pk_pass "removed generated output"
}

# -----------------------------------------------------------------------------
# Per-type stages: read PK_BUILD_TYPE and PK_PRESET, never hardcode one
# -----------------------------------------------------------------------------

pk_stage_workflow() {
  pk_stage "Workflow"

  local conan_log
  conan_log="$(mktemp "${TMPDIR:-/tmp}/${PK_PROJECT}-conan.XXXXXX")" || return 1

  if ! pk_try "conan install (${PK_BUILD_TYPE})" \
      pk_conan_install_logged "$conan_log" "$PK_BUILD_TYPE"; then
    rm -f "$conan_log"
    return 1
  fi

  # if 'tools.build:skip_test=True' is given to Conan in anyway then it sets
  # PK_BUILD_TESTS=OFF skipping add_subdirectory(tests) and responds with
  # "No tests were found" instead of an error.
  if grep -q "${PK_PREFIX}_BUILD_TESTS=OFF" "$conan_log"; then
    pk_fail "${PK_PREFIX}_BUILD_TESTS=OFF -- check tools.build:skip_test in your default profile"
  else
    pk_pass "${PK_PREFIX}_BUILD_TESTS is ON"
  fi
  rm -f "$conan_log"

  pk_try "workflow ${PK_PRESET}" cmake --workflow --preset "$PK_PRESET"
}

# Host tools run on the build machine, so they always use the native profile,
# built in the same type as the pass they belong to.
pk_stage_host_tools_for_cross() {
  pk_stage "Host tools for cross"

  pk_try "conan install (${PK_BUILD_TYPE}, native)" \
    conan install "$PK_REPO_ROOT" -pr:a "${PK_REPO_ROOT}/profiles/native" \
      -s build_type="$PK_BUILD_TYPE" --build=missing || return 1

  rm -rf "${PK_REPO_ROOT}/build/${PK_HOST_TOOLS_PRESET}"
  pk_try "configure ${PK_HOST_TOOLS_PRESET} (${PK_BUILD_TYPE})" \
    pk_configure_host_tools || return 1
  pk_try "build ${PK_HOST_TOOLS_PRESET} (${PK_BUILD_TYPE})" \
    cmake --build "build/${PK_HOST_TOOLS_PRESET}"
}

# Cross targets have no test preset and cannot run what they produce, all they
# do is configure and build rather than running a workflow and testing etc.
pk_stage_cross_build() {
  pk_stage "Cross configure and build"

  pk_try "conan install (${PK_BUILD_TYPE})" \
    pk_conan_install "$PK_BUILD_TYPE" || return 1
  pk_try "configure ${PK_PRESET}" cmake --preset "$PK_PRESET" || return 1
  pk_try "build ${PK_PRESET}" cmake --build "build/${PK_PRESET}"
}

# Relies on 'workflow' (native) or 'cross_build' (cross) having already run
# conan install for this build type.
pk_stage_library_matrix() {
  pk_stage "Library type matrix"

  local library_type
  for library_type in $PK_LIBRARY_TYPES; do
    printf -- '  -- %s --\n' "$library_type"
    rm -rf "${PK_REPO_ROOT}/build/${PK_PRESET}"

    pk_try "configure $library_type" cmake --preset "$PK_PRESET" \
      -D${PK_PREFIX}_LIBRARY_TYPE="$library_type" || continue
    pk_try "build $library_type" \
      cmake --build "build/${PK_PRESET}" || continue

    if [[ -n "$PK_HOST_PROFILE" ]]; then
      pk_skip "ctest $library_type (cross target, binaries not runnable here)"
      continue
    fi

    pk_try "ctest $library_type" \
      ctest --test-dir "build/${PK_PRESET}" --output-on-failure
  done
}

pk_stage_auto_discovery() {
  pk_stage "Auto-discovery"

  local scratch="${PK_SCRATCH_DIR}"
  mkdir -p "$scratch"
  printf 'int pk_scratch_probe() { return 1; }\n' > "$scratch/probe.cpp"

  local log
  log="$(cmake --build "build/${PK_PRESET}" 2>&1)"
  printf '%s\n' "$log"

  if printf '%s' "$log" | grep -q 'probe\.cpp'; then
    pk_pass "new source compiled without editing CMake"
  else
    pk_fail "probe.cpp was not picked up -- CONFIGURE_DEPENDS is not working"
  fi

  rm -rf "$scratch"
  pk_try "rebuild after removing the probe" \
    cmake --build "build/${PK_PRESET}"
}

# Reconfigured from scratch because library_matrix left this tree set to
# its last library type. Nothing done here since 'workflow' has already
# touched build/<Type>/.
pk_stage_install() {
  pk_stage "Install and package metadata"

  rm -rf "${PK_REPO_ROOT}/build/${PK_PRESET}" "${PK_REPO_ROOT}/stage"

  pk_try "configure ${PK_PRESET}" cmake --preset "$PK_PRESET" || return 1
  pk_try "build ${PK_PRESET}" cmake --build "build/${PK_PRESET}" || return 1
  pk_try "install ${PK_PRESET}" cmake --install "build/${PK_PRESET}" \
    --prefix "${PK_REPO_ROOT}/stage" || return 1

  find "${PK_REPO_ROOT}/stage" -type f | sort

  local expected
  while IFS= read -r expected; do
    if [[ -f "${PK_REPO_ROOT}/stage/${expected}" ]]; then
      pk_pass "installed ${expected}"
    else
      pk_fail "missing ${expected}"
    fi
  done < <(pk_expected_install_files)

  local pc="${PK_REPO_ROOT}/stage/lib/pkgconfig/${PK_PACKAGE}.pc"
  if [[ -f "$pc" ]]; then
    cat "$pc"
    if pk_have pkg-config; then
      pk_try "pkg-config reads ${PK_PACKAGE}.pc" env \
        PKG_CONFIG_PATH="${PK_REPO_ROOT}/stage/lib/pkgconfig" \
        pkg-config --cflags --libs ${PK_PACKAGE}
    else
      pk_skip "pkg-config not installed"
    fi
  fi
}

# This consumer project will only ever see installed files. Tests can be
# supplied for the consumed project to run.
pk_stage_consumer() {
  pk_stage "Consumer project"

  if [[ ! -f "${PK_REPO_ROOT}/stage/lib/cmake/${PK_PACKAGE}/${PK_PACKAGE}Config.cmake" ]]; then
    pk_skip "no ${PK_PACKAGE}Config.cmake was installed"
    return 0
  fi

  rm -rf "$PK_CONSUMER_DIR"
  mkdir -p "$PK_CONSUMER_DIR"

  {
    printf 'cmake_minimum_required(VERSION 3.30)\n'
    printf 'project(consumer LANGUAGES CXX)\n'
    printf 'find_package(%s REQUIRED)\n' "$PK_PACKAGE"
    printf 'add_executable(consumer main.cpp)\n'
    printf 'target_link_libraries(consumer PRIVATE %s)\n' "$PK_LINK_TARGET"
  } > "$PK_CONSUMER_DIR/CMakeLists.txt"

  if [[ -n "$PK_CONSUMER_SOURCE" ]]; then
    if [[ ! -f "$PK_CONSUMER_SOURCE" ]]; then
      pk_fail "PK_CONSUMER_SOURCE does not exist: ${PK_CONSUMER_SOURCE}"
      return 1
    fi
    cp "$PK_CONSUMER_SOURCE" "$PK_CONSUMER_DIR/main.cpp"
  else
    printf 'int main() { return 0; }\n' > "$PK_CONSUMER_DIR/main.cpp"
  fi

  pk_try "configure consumer (${PK_BUILD_TYPE})" cmake -S "$PK_CONSUMER_DIR" \
    -B "$PK_CONSUMER_DIR/b" -G Ninja \
    -DCMAKE_BUILD_TYPE="$PK_BUILD_TYPE" \
    -DCMAKE_PREFIX_PATH="${PK_REPO_ROOT}/stage" || return 1
  pk_try "build consumer (${PK_BUILD_TYPE})" \
    cmake --build "$PK_CONSUMER_DIR/b" || return 1
  pk_try "run consumer (${PK_BUILD_TYPE})" \
    "${PK_CONSUMER_DIR}/b/consumer${PK_EXE_SUFFIX}"
}

pk_stage_cpack() {
  pk_stage "CPack"

  local build_dir="${PK_REPO_ROOT}/build/${PK_PRESET}"
  if [[ ! -d "$build_dir" ]]; then
    pk_skip "no build tree for ${PK_PRESET}"
    return 0
  fi

  if ( cd "$build_dir" && cpack && cpack --config CPackSourceConfig.cmake ); then
    pk_pass "cpack binary and source packages (${PK_PRESET})"
    ls -1 "$build_dir"/*.tar.gz "$build_dir"/*.zip 2>/dev/null
  else
    pk_fail "cpack (${PK_PRESET})"
  fi
}

pk_stage_host_tools() {
  pk_stage "Host tools only"

  # Ensures PK_LIBRARY_TYPE=NONE is properly guarded within the project.
  rm -rf "${PK_REPO_ROOT}/build/${PK_HOST_TOOLS_PRESET}"
  pk_try "configure ${PK_HOST_TOOLS_PRESET} (${PK_BUILD_TYPE})" \
    pk_configure_host_tools || return 1
  pk_try "build ${PK_HOST_TOOLS_PRESET} (${PK_BUILD_TYPE})" \
    cmake --build "build/${PK_HOST_TOOLS_PRESET}"
}

# -----------------------------------------------------------------------------
# Final stages
# -----------------------------------------------------------------------------

pk_stage_reset() {
  pk_stage "Reset"

  if [[ "${PK_KEEP:-0}" -eq 1 ]]; then
    echo "--keep given: leaving generated output in place."
  else
    pk_cleanup
    pk_pass "removed generated output"
  fi
}

# -----------------------------------------------------------------------------
# Driver
# -----------------------------------------------------------------------------

# One line per build type, both printed and appended to PK_RESULTS_FILE.
pk_target_summary() {
  printf '\n%s---- %s ----%s\n' "$PK_BOLD" "$PK_PLATFORM_LABEL" "$PK_RESET"
  printf 'passed: %d  skipped: %d\n' "$PK_PASS_COUNT" "$PK_SKIP_COUNT"

  local build_type count result
  for build_type in $PK_BUILD_TYPES; do
    if [[ "$PK_SETUP_FAILED" -eq 1 ]]; then
      result="not run"
    else
      count="$(printf '%s' "$PK_FAILURES" | grep -c "^\[${build_type}\] ")"
      if [[ "$count" -eq 0 ]]; then
        result="passed"
      else
        result="failed (${count})"
      fi
    fi

    printf '  %-16s %s\n' "$build_type" "$result"
    if [[ -n "$PK_RESULTS_FILE" ]]; then
      printf '%s|%s|%s\n' "${PK_TARGET_NAME:-unknown}" "$build_type" "$result" \
        >> "$PK_RESULTS_FILE"
    fi
  done

  if [[ -n "$PK_FAILURES" ]]; then
    printf '%sfailures:%s\n' "$PK_RED" "$PK_RESET"
    printf '%s' "$PK_FAILURES" | while IFS= read -r failure; do
      [[ -n "$failure" ]] && printf '  - %s\n' "$failure"
    done
    return 1
  fi

  printf '%sall stages passed%s\n' "$PK_GREEN" "$PK_RESET"
  return 0
}

# Runs one whitespace separated stage list. Returns non-zero when a stage
# that later stages depend on fails (environment, or a stage that produces
# the build tree), skipping the rest of the list.
pk_run_stage_list() {
  local stage_name
  for stage_name in $1; do
    if ! pk_have_function "pk_stage_${stage_name}"; then
      pk_fail "unknown stage '${stage_name}'"
      continue
    fi

    if ! "pk_stage_${stage_name}"; then
      case "$stage_name" in
        environment|workflow|host_tools_for_cross|cross_build)
          pk_skip "remaining ${PK_BUILD_TYPE:-setup} stages: ${stage_name} failed"
          return 1
          ;;
      esac
    fi
  done
  return 0
}

pk_run_stages() {
  cd "$PK_REPO_ROOT" || return 1

  if pk_run_stage_list "$PK_SETUP_STAGES"; then
    local build_type
    for build_type in $PK_BUILD_TYPES; do
      PK_BUILD_TYPE="$build_type"
      PK_PRESET="$(pk_preset_for "$build_type")"
      pk_run_stage_list "$PK_TYPE_STAGES"
    done

    PK_BUILD_TYPE=""
    PK_PRESET=""
    pk_run_stage_list "$PK_FINAL_STAGES"
  else
    PK_SETUP_FAILED=1
  fi

  pk_platform_teardown
  pk_target_summary
}
