include_guard(GLOBAL)

# pk_add_app_paths(NAME <app> TARGETS <executable>... [LANGUAGE C|CXX])
#
# Generates <build>/generated/<app>/app_paths.{hpp,cpp} (CXX) or
# app_paths.{h,c} (C) from the templates in templates/app_paths/ and compiles
# them into each target. C++ code includes <<app>/app_paths.hpp> and calls
# '<app>::app_paths()'; C code includes <<app>/app_paths.h> and calls
# '<app>_app_paths()'. LANGUAGE defaults to CXX when C++ is enabled, else C.
#
# pk_create_app calls this for every application (opt out with
# NO_APP_PATHS); call it yourself for executables made with add_executable.
function(pk_add_app_paths)
  set(one_value_args NAME LANGUAGE)
  set(multi_value_args TARGETS)
  cmake_parse_arguments(ARG "" "${one_value_args}" "${multi_value_args}" ${ARGN})

  if(NOT ARG_NAME)
    message(FATAL_ERROR "pk_add_app_paths (func): No 'NAME' was provided?")
  endif()
  if(NOT ARG_TARGETS)
    message(FATAL_ERROR
      "pk_add_app_paths (func): No 'TARGETS' were provided for '${ARG_NAME}'?")
  endif()
  if(ARG_UNPARSED_ARGUMENTS)
    message(FATAL_ERROR
      "pk_add_app_paths (func): unrecognized arguments for '${ARG_NAME}': "
      "${ARG_UNPARSED_ARGUMENTS}")
  endif()

  if(NOT ARG_LANGUAGE)
    if(CMAKE_CXX_COMPILER_LOADED)
      set(ARG_LANGUAGE CXX)
    else()
      set(ARG_LANGUAGE C)
    endif()
  endif()
  if(ARG_LANGUAGE STREQUAL "CXX")
    set(header_ext hpp)
    set(source_ext cpp)
  elseif(ARG_LANGUAGE STREQUAL "C")
    set(header_ext h)
    set(source_ext c)
  else()
    message(FATAL_ERROR
      "pk_add_app_paths (func): 'LANGUAGE' must be C or CXX, not "
      "'${ARG_LANGUAGE}'.")
  endif()
  if(NOT CMAKE_${ARG_LANGUAGE}_COMPILER_LOADED)
    message(FATAL_ERROR
      "pk_add_app_paths (func): the generated code is ${ARG_LANGUAGE}, but "
      "${ARG_LANGUAGE} is not enabled in project(${PROJECT_NAME}).")
  endif()

  # Templates values ----------------------------------------------------------
  # configure_file replaces @NAME@ with the value of the CMake variable NAME;
  # each value is just a variable set in this function's scope.

  string(MAKE_C_IDENTIFIER "${ARG_NAME}" PK_APP_NAMESPACE)
  set(PK_APP_NAME "${ARG_NAME}")
  set(PK_APP_VERSION "${PROJECT_VERSION}")
  set(PK_APP_C_PREFIX "${PK_APP_NAMESPACE}")
  string(TOUPPER "${PK_APP_NAMESPACE}" PK_APP_C_MACRO_PREFIX)

  # CMAKE_INSTALL_PREFIX should NOT reach generated code.
  if(IS_ABSOLUTE "${CMAKE_INSTALL_BINDIR}")
    message(WARNING
      "pk_add_app_paths (func): CMAKE_INSTALL_BINDIR is absolute "
      "('${CMAKE_INSTALL_BINDIR}'), so the root can't be derived from the "
      "executable's location; assuming '..'.")
    set(PK_APP_BIN_TO_ROOT "..")

  else()
    file(RELATIVE_PATH PK_APP_BIN_TO_ROOT
      "${CMAKE_INSTALL_PREFIX}/${CMAKE_INSTALL_BINDIR}"
      "${CMAKE_INSTALL_PREFIX}")
    if(PK_APP_BIN_TO_ROOT STREQUAL "")
      set(PK_APP_BIN_TO_ROOT ".")
    endif()
  endif()

  get_property(multi_config GLOBAL PROPERTY GENERATOR_IS_MULTI_CONFIG)
  if(multi_config)
    message(WARNING
      "pk_add_app_paths (func): '${CMAKE_GENERATOR}' builds into "
      "bin/<config>/, one level deeper than the install tree; app_paths().root"
      "for '${ARG_NAME}' is only correct once installed. The kit's presets"
      "use the single-config 'Ninja' generator.")

  elseif(CMAKE_RUNTIME_OUTPUT_DIRECTORY)
    file(RELATIVE_PATH build_bin_to_root
      "${CMAKE_RUNTIME_OUTPUT_DIRECTORY}" "${PROJECT_BINARY_DIR}")
    if(NOT build_bin_to_root STREQUAL PK_APP_BIN_TO_ROOT)
      message(WARNING
        "pk_add_app_paths (func): '${ARG_NAME}' is built in "
        "'${CMAKE_RUNTIME_OUTPUT_DIRECTORY}' but installed in "
        "'${CMAKE_INSTALL_BINDIR}'; app_paths().root will only be correct once"
        "installed.")
    endif()
  endif()

  if(IS_ABSOLUTE "${CMAKE_INSTALL_DATADIR}")
    set(PK_APP_DATADIR "share")
  else()
    set(PK_APP_DATADIR "${CMAKE_INSTALL_DATADIR}")
  endif()

  # Write files ---------------------------------------------------------------
  # configure_file only rewrites an output if its content has changed,
  # reconfiguring doesn't force a rebuild, and it registers the template as a
  # configuration dependency, so editing the .in file re-runs CMake on the next
  # build. @ONLY will only expand '@...@' and not '${...}'. Generated files go
  # to the build tree, not source tree.

  set(template_dir "${PK_MODULE_DIR}/templates/app_paths")
  set(generated_root "${PROJECT_BINARY_DIR}/generated")
  set(out_dir "${generated_root}/${ARG_NAME}")

  set(header "${out_dir}/app_paths.${header_ext}")
  set(source "${out_dir}/app_paths.${source_ext}")
  configure_file("${template_dir}/app_paths.${header_ext}.in" "${header}" @ONLY)
  configure_file("${template_dir}/app_paths.${source_ext}.in" "${source}" @ONLY)

  set_source_files_properties("${header}" "${source}"
    PROPERTIES SKIP_LINTING ON)

  if(ARG_LANGUAGE STREQUAL "C" AND NOT WIN32)
    find_package(Threads REQUIRED)
  endif()

  # Files to targets ----------------------------------------------------------
  # The .cpp is compiled into each executable. The header goes in a FILE_SET
  # with the base <build>/generated which puts the folder on the include path,
  # so the code includes it as <app>/app_paths.hpp.

  foreach(target IN LISTS ARG_TARGETS)
    if(NOT TARGET ${target})
      message(FATAL_ERROR
        "pk_add_app_paths (func): '${target}' is not a target.")
    endif()
    get_target_property(target_type ${target} TYPE)
    if(NOT target_type STREQUAL "EXECUTABLE")
      message(FATAL_ERROR
        "pk_add_app_paths (func): '${target}' is a ${target_type}; app paths "
        "are found from the running executable.")
    endif()

    target_sources(${target}
      PRIVATE
        "${source}")
    target_sources(${target}
      PRIVATE
        FILE_SET    pk_app_paths_${PK_APP_NAMESPACE}_${source_ext}
        TYPE        HEADERS
        BASE_DIRS   "${generated_root}"
        FILES       "${header}")

    if(WIN32)
      # SHGetKnownFolderPath (shell32) & CoTaskMemFree (ole32).
      target_link_libraries(${target} PRIVATE shell32 ole32)
    elseif(ARG_LANGUAGE STREQUAL "C")
      target_link_libraries(${target} PRIVATE Threads::Threads)
    endif()
  endforeach()
endfunction()
