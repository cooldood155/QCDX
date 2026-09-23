include_guard(GLOBAL)

macro(pk_setup_tooling)
  pk_project_prefix(PK_PREFIX)

  option(${PK_PREFIX}_VALGRIND
    "Register a Valgrind run of every test executable" OFF)

  set(${PK_PREFIX}_VALGRIND_TOOL "memcheck" CACHE STRING
    "The Valgrind tool valgrind-labelled tests use")
  set_property(CACHE ${PK_PREFIX}_VALGRIND_TOOL
    PROPERTY STRINGS memcheck helgrind drd)

  set(${PK_PREFIX}_FUZZER "off" CACHE STRING
    "Fuzzing engine for fuzz/ targets: off, libfuzzer or afl")
  set_property(CACHE ${PK_PREFIX}_FUZZER PROPERTY STRINGS off libfuzzer afl)

  set(${PK_PREFIX}_FUZZ_SECONDS "45" CACHE STRING
    "How long each fuzz target runs when driven by ctest")

  if(NOT ${PK_PREFIX}_VALGRIND_TOOL MATCHES "^(memcheck|helgrind|drd)$")
    message(FATAL_ERROR
      "${PK_PREFIX}_VALGRIND_TOOL must be memcheck, helgrind or drd, NOT "
      "'${${PK_PREFIX}_VALGRIND_TOOL}'")
  endif()

  if(NOT ${PK_PREFIX}_FUZZER MATCHES "^(off|libfuzzer|afl)$")
    message(FATAL_ERROR
      "${PK_PREFIX}_FUZZER must be off, libfuzzer or afl, NOT "
      "'${${PK_PREFIX}_FUZZER}'")
  endif()

  set(_pk_tooling_labels "")
  set(_pk_valgrind_command "")

  if(${PK_PREFIX}_VALGRIND)
    if(CMAKE_CROSSCOMPILING)
      message(FATAL_ERROR
        "${PK_PREFIX}_VALGRIND cannot run target binaries from a cross build")
    endif()

    if(${PK_PREFIX}_COMPILER_IS_MSVC OR WIN32)
      message(FATAL_ERROR
        "Valgrind is not supported on Windows/MSVC environments")
    endif()

    find_program(${PK_PREFIX}_VALGRIND_PATH NAMES valgrind REQUIRED)

    list(APPEND _pk_valgrind_command
      "${${PK_PREFIX}_VALGRIND_PATH}"
      "--tool=${${PK_PREFIX}_VALGRIND_TOOL}"
      "--error-exitcode=1")

    if(${PK_PREFIX}_VALGRIND_TOOL STREQUAL "memcheck")
      list(APPEND _pk_valgrind_command
        "--leak-check=full"
        "--errors-for-leak-kinds=definite,possible"
        "--track-origins=yes")
    endif()

    if(EXISTS "${PROJECT_SOURCE_DIR}/tests/valgrind.supp")
      list(APPEND _pk_valgrind_command
        "--suppressions=${PROJECT_SOURCE_DIR}/tests/valgrind.supp")
    endif()

    list(APPEND _pk_tooling_labels valgrind)
    message(STATUS
      "${PROJECT_NAME}: Valgrind ${${PK_PREFIX}_VALGRIND_TOOL} tests enabled "
      "(${${PK_PREFIX}_VALGRIND_PATH})")
  endif()

  if(NOT ${PK_PREFIX}_FUZZER STREQUAL "off")
    if(CMAKE_CROSSCOMPILING)
      message(FATAL_ERROR
        "${PK_PREFIX}_FUZZER cannot run target binaries from a cross build")
    endif()

    add_library(${PROJECT_NAME}_fuzzing INTERFACE)
    add_library(${PROJECT_NAME}::fuzzing ALIAS ${PROJECT_NAME}_fuzzing)

    if(${PK_PREFIX}_FUZZER STREQUAL "libfuzzer")
      include(CheckCXXSourceCompiles)

      if(${PK_PREFIX}_COMPILER_IS_MSVC)
        set(_pk_fuzz_flag "/fsanitize=fuzzer")
        set(_pk_fuzz_no_link_flag "/fsanitize=fuzzer-no-link")
      else()
        set(_pk_fuzz_flag "-fsanitize=fuzzer")
        set(_pk_fuzz_no_link_flag "-fsanitize=fuzzer-no-link")
      endif()

      set(CMAKE_REQUIRED_FLAGS "${_pk_fuzz_flag}")
      set(CMAKE_REQUIRED_LINK_OPTIONS "${_pk_fuzz_flag}")
      check_cxx_source_compiles(
        "#include <cstddef>\n#include <cstdint>\nextern \"C\" int LLVMFuzzerTestOneInput(const uint8_t*, size_t) { return 0; }\n"
        ${PK_PREFIX}_HAS_LIBFUZZER)
      unset(CMAKE_REQUIRED_FLAGS)
      unset(CMAKE_REQUIRED_LINK_OPTIONS)

      if(NOT ${PK_PREFIX}_HAS_LIBFUZZER)
        message(FATAL_ERROR
          "The current compiler (${CMAKE_CXX_COMPILER_ID}) cannot link "
          "libFuzzer. Runtime libraries might be missing")
      endif()

      target_compile_options(${PROJECT_NAME}_fuzzing INTERFACE
        "$<IF:$<BOOL:${${PK_PREFIX}_COMPILER_IS_MSVC}>,${_pk_fuzz_flag},${_pk_fuzz_no_link_flag}>")
      target_link_options(${PROJECT_NAME}_fuzzing INTERFACE "${_pk_fuzz_flag}")
    else()
      if(${PK_PREFIX}_COMPILER_IS_MSVC)
        message(FATAL_ERROR "AFL++ is unsupported natively on Windows/MSVC")
      endif()

      get_filename_component(_pk_compiler_name "${CMAKE_CXX_COMPILER}" NAME)
      if(NOT _pk_compiler_name MATCHES "^afl-")
        message(FATAL_ERROR
          "${PK_PREFIX}_FUZZER=afl needs an AFL++ compiler wrapper. Configure "
          "with CXX=afl-clang-fast++ or CXX=afl-g++-fast")
      endif()
    endif()

    list(APPEND _pk_tooling_labels fuzz)
    message(STATUS
      "${PROJECT_NAME}: fuzzing enabled (${${PK_PREFIX}_FUZZER})")
  endif()

  pk_set_state(VALGRIND_COMMAND "${_pk_valgrind_command}")
  pk_set_state(TOOLING_LABELS "${_pk_tooling_labels}")

  if(_pk_tooling_labels)
    list(JOIN _pk_tooling_labels ", " _pk_tooling_summary)
    message(STATUS
      "${PROJECT_NAME}: extra ctest labels: ${_pk_tooling_summary}")
  endif()
endmacro()

function(pk_add_valgrind_test target)
  pk_get_state(VALGRIND_COMMAND valgrind_command)

  if(NOT valgrind_command)
    return()
  endif()

  add_test(NAME "${target}: valgrind"
    COMMAND ${valgrind_command} "$<TARGET_FILE:${target}>")

  set_tests_properties("${target}: valgrind" PROPERTIES
    LABELS "valgrind"
    TIMEOUT 900)
endfunction()
