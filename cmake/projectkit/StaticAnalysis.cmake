include_guard(GLOBAL)

function(pk_analyser_version OUT_VAR program)
  execute_process(
    COMMAND "${program}" --version
    OUTPUT_VARIABLE version_banner
    ERROR_VARIABLE version_banner
    OUTPUT_STRIP_TRAILING_WHITESPACE)

  if(version_banner MATCHES "(([0-9]+\\.){2,3}[0-9]+)")
    set(${OUT_VAR} "${CMAKE_MATCH_1}" PARENT_SCOPE)
  else()
    set(${OUT_VAR} "unknown" PARENT_SCOPE)
  endif()
endfunction()

function(pk_setup_static_analysis)
  pk_project_prefix(prefix)

  option(${prefix}_SA_ALL "Toggle static analysis tools" OFF)
  option(${prefix}_SA_CPPCHECK "Toggle Cppcheck static analysis" OFF)
  option(${prefix}_SA_CLANG_TIDY "Toggle Clang-Tidy static analysis" OFF)

  set(${prefix}_SA_OUTPUT "console" CACHE STRING
    "Where analyser findings go: console, or files to also write per-source reports")
  set_property(CACHE ${prefix}_SA_OUTPUT PROPERTY STRINGS console files)

  set(${prefix}_SA_OUTPUT_DIR "${PROJECT_BINARY_DIR}/analysis" CACHE PATH
    "Directory for per-source analyser reports when ${prefix}_SA_OUTPUT is files")

  set(${prefix}_SA_MESSAGE_FORMAT "default" CACHE STRING
    "cppcheck message format: default, gcc or vs")
  set_property(CACHE ${prefix}_SA_MESSAGE_FORMAT
    PROPERTY STRINGS default gcc vs)

  set(${prefix}_SA_LAUNCHER "${PK_MODULE_DIR}/scripts/analyser-launcher.sh"
    CACHE FILEPATH
    "Wrapper script used when ${prefix}_SA_OUTPUT is files")

  if(NOT ${prefix}_SA_OUTPUT MATCHES "^(console|files)$")
    message(FATAL_ERROR
      "${prefix}_SA_OUTPUT must be console or files, not "
      "'${${prefix}_SA_OUTPUT}'")
  endif()

  if(NOT ${prefix}_SA_MESSAGE_FORMAT MATCHES "^(default|gcc|vs)$")
    message(FATAL_ERROR
      "${prefix}_SA_MESSAGE_FORMAT must be default, gcc or vs, not "
      "'${${prefix}_SA_MESSAGE_FORMAT}'")
  endif()

  set(clang_tidy_command "")
  set(cppcheck_command "")

  if(${prefix}_SA_ALL OR ${prefix}_SA_CLANG_TIDY)
    find_program(${prefix}_CLANG_TIDY_PATH
      NAMES
        clang-tidy
        clang-tidy-22
        clang-tidy-21
        clang-tidy-20
        clang-tidy-19
        clang-tidy-18
      REQUIRED)

    set(clang_tidy_command
      "${${prefix}_CLANG_TIDY_PATH}"
      "--extra-arg=-Wno-unknown-warning-option"
      "--extra-arg=-Wno-unused-command-line-argument")

    if(${prefix}_SA_OUTPUT STREQUAL "files")
      find_program(${prefix}_SH_PATH NAMES sh REQUIRED)

      if(NOT EXISTS "${${prefix}_SA_LAUNCHER}")
        message(FATAL_ERROR
          "${prefix}_SA_OUTPUT is files but the launcher script is missing: "
          "'${${prefix}_SA_LAUNCHER}'")
      endif()

      file(MAKE_DIRECTORY "${${prefix}_SA_OUTPUT_DIR}/clang-tidy")

      list(PREPEND clang_tidy_command
        "${${prefix}_SH_PATH}"
        "${${prefix}_SA_LAUNCHER}"
        "${${prefix}_SA_OUTPUT_DIR}/clang-tidy")
    endif()

    if(${prefix}_WERROR)
      list(APPEND clang_tidy_command "--warnings-as-errors=*")
    endif()

    pk_analyser_version(tidy_version "${${prefix}_CLANG_TIDY_PATH}")
    message(STATUS
      "${PROJECT_NAME}: clang-tidy ${tidy_version} enabled "
      "(${${prefix}_CLANG_TIDY_PATH})")
  endif()

  if(${prefix}_SA_ALL OR ${prefix}_SA_CPPCHECK)
    find_program(${prefix}_CPPCHECK_PATH NAMES cppcheck REQUIRED)

    set(cppcheck_command
      "${${prefix}_CPPCHECK_PATH}"
      "--enable=warning,style,performance,portability"
      "--inline-suppr"
      "--suppress=missingInclude"
      "--suppress=missingIncludeSystem"
      "--suppress=unusedFunction"
      "--suppress=unmatchedSuppression"
      "--suppress=checkersReport"
      "--suppress=normalCheckLevelMaxBranches")

    if(NOT ${prefix}_SA_MESSAGE_FORMAT STREQUAL "default")
      list(APPEND cppcheck_command "--template=${${prefix}_SA_MESSAGE_FORMAT}")
    endif()

    if(${prefix}_SA_OUTPUT STREQUAL "files")
      file(MAKE_DIRECTORY "${${prefix}_SA_OUTPUT_DIR}/cppcheck")
      list(APPEND cppcheck_command
        "--plist-output=${${prefix}_SA_OUTPUT_DIR}/cppcheck")
    endif()

    if(${prefix}_WERROR)
      list(APPEND cppcheck_command "--error-exitcode=1")
    endif()

    pk_analyser_version(cppcheck_version "${${prefix}_CPPCHECK_PATH}")
    message(STATUS
      "${PROJECT_NAME}: cppcheck ${cppcheck_version} enabled "
      "(${${prefix}_CPPCHECK_PATH})")
  endif()

  pk_set_state(CLANG_TIDY_COMMAND "${clang_tidy_command}")
  pk_set_state(CPPCHECK_COMMAND "${cppcheck_command}")

  if(${prefix}_SA_OUTPUT STREQUAL "files"
      AND (clang_tidy_command OR cppcheck_command))
    message(STATUS
      "${PROJECT_NAME}: analyser reports under ${${prefix}_SA_OUTPUT_DIR}")
  endif()
endfunction()

function(pk_enable_static_analysis target)
  pk_get_state(CLANG_TIDY_COMMAND clang_tidy_command)
  pk_get_state(CPPCHECK_COMMAND cppcheck_command)

  if(clang_tidy_command)
    set_target_properties(${target} PROPERTIES
      CXX_CLANG_TIDY "${clang_tidy_command}")
  endif()

  if(cppcheck_command)
    set_target_properties(${target} PROPERTIES
      CXX_CPPCHECK "${cppcheck_command}")
  endif()
endfunction()
