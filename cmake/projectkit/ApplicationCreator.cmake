include_guard(GLOBAL)

function(pk_create_app)
  set(options
    DEFAULT_DIRS
    REQUIRE_SOURCES
    REQUIRE_PUBLIC_HEADERS
    REQUIRE_PRIVATE_HEADERS
    NO_DEFAULT_LINKS
    NO_INSTALL
    NO_APP_PATHS
    GUI
    OWN_MANIFEST
    STATIC_RUNTIME)

  set(one_value_args
    NAME
    LANGUAGE
    SOURCE_DIR
    INCLUDE_DIR
    RC_FILE)

  set(multi_value_args
    TARGET_NAME
    OUTPUT_NAME
    SOURCES
    PUBLIC_HEADERS
    PRIVATE_HEADERS
    LINK_PRIVATE
    LINK_INTERFACE
    DEPS)

  cmake_parse_arguments(ARG
    "${options}" "${one_value_args}" "${multi_value_args}" ${ARGN})

  pk_project_prefix(prefix)

  if(NOT ARG_NAME)
    message(FATAL_ERROR "pk_create_app requires a 'NAME' argument.")
  endif()
  if(ARG_UNPARSED_ARGUMENTS)
    message(FATAL_ERROR
      "pk_create_app (func): unrecognized arguments for '${ARG_NAME}': "
      "${ARG_UNPARSED_ARGUMENTS}")
  endif()

  if(NOT ARG_TARGET_NAME)
    set(ARG_TARGET_NAME "${ARG_NAME}_app")
  endif()
  list(LENGTH ARG_TARGET_NAME target_count)

  if(NOT ARG_OUTPUT_NAME)
    if(target_count EQUAL 1)
      set(ARG_OUTPUT_NAME "${ARG_NAME}")
    else()
      set(ARG_OUTPUT_NAME ${ARG_TARGET_NAME})
    endif()
  endif()
  list(LENGTH ARG_OUTPUT_NAME output_count)

  if(NOT output_count EQUAL target_count)
    message(FATAL_ERROR
      "pk_create_app (func): '${ARG_NAME}' has ${target_count} "
      "'TARGET_NAME' values but ${output_count} 'OUTPUT_NAME' values, one "
      "'OUTPUT_NAME' is required per target.")
  endif()

  set(unique_targets ${ARG_TARGET_NAME})
  set(unique_outputs ${ARG_OUTPUT_NAME})
  list(REMOVE_DUPLICATES unique_targets)
  list(REMOVE_DUPLICATES unique_outputs)
  list(LENGTH unique_targets unique_target_count)
  list(LENGTH unique_outputs unique_output_count)

  if(NOT unique_target_count EQUAL target_count)
    message(FATAL_ERROR
      "pk_create_app (func): '${ARG_NAME}' has duplicate 'TARGET_NAME' "
      "values: ${ARG_TARGET_NAME}")
  endif()
  if(NOT unique_output_count EQUAL output_count)
    message(FATAL_ERROR
      "pk_create_app (func): '${ARG_NAME}' has duplicate 'OUTPUT_NAME' "
      "values: ${ARG_OUTPUT_NAME}")
  endif()

  if(ARG_RC_FILE)
    cmake_path(ABSOLUTE_PATH ARG_RC_FILE
      BASE_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}" NORMALIZE)
    if(NOT EXISTS "${ARG_RC_FILE}")
      message(FATAL_ERROR
        "pk_create_app (func): 'RC_FILE' for '${ARG_NAME}' does not exist: "
        "'${ARG_RC_FILE}'.")
    endif()
    get_property(enabled_languages GLOBAL PROPERTY ENABLED_LANGUAGES)
    if(WIN32 AND NOT "RC" IN_LIST enabled_languages)
      message(FATAL_ERROR
        "pk_create_app (func): 'RC_FILE' for '${ARG_NAME}' needs the RC "
        "language; call enable_language(RC) before pk_create_app.")
    endif()
  endif()

  if(MINGW AND ARG_OWN_MANIFEST)
    if(CMAKE_C_COMPILER)
      set(stub_compiler "${CMAKE_C_COMPILER}")
    else()
      set(stub_compiler "${CMAKE_CXX_COMPILER}")
    endif()
    set(no_manifest_dir "${CMAKE_CURRENT_BINARY_DIR}/${ARG_NAME}_no_default_manifest")
    if(NOT EXISTS "${no_manifest_dir}/default-manifest.o")
      file(WRITE "${no_manifest_dir}/empty.c" "")
      execute_process(
        COMMAND "${stub_compiler}" -c empty.c -o default-manifest.o
        WORKING_DIRECTORY "${no_manifest_dir}"
        COMMAND_ERROR_IS_FATAL ANY)
    endif()
  endif()

  pk_resolve_files(ARG_SOURCES "'${ARG_NAME}' SOURCES"
    "\\.(c|cc|cpp|cxx)$" ${ARG_SOURCES})
  pk_resolve_files(ARG_PUBLIC_HEADERS "'${ARG_NAME}' PUBLIC_HEADERS"
    "\\.(h|hh|hpp|hxx)$" ${ARG_PUBLIC_HEADERS})
  pk_resolve_files(ARG_PRIVATE_HEADERS "'${ARG_NAME}' PRIVATE_HEADERS"
    "\\.(h|hh|hpp|hxx)$" ${ARG_PRIVATE_HEADERS})

  foreach(header IN LISTS ARG_PUBLIC_HEADERS)
    if(header IN_LIST ARG_PRIVATE_HEADERS)
      message(FATAL_ERROR
        "pk_create_app (func): '${ARG_NAME}' header passed as both "
        "'PUBLIC_HEADERS' and 'PRIVATE_HEADERS': '${header}'.")
    endif()
  endforeach()

  set(source_dir_given FALSE)
  set(include_dir_given FALSE)

  if(ARG_SOURCE_DIR)
    cmake_path(ABSOLUTE_PATH ARG_SOURCE_DIR
      BASE_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}" NORMALIZE)
    string(REGEX REPLACE "(.)/+$" "\\1" ARG_SOURCE_DIR "${ARG_SOURCE_DIR}")
    if(NOT IS_DIRECTORY "${ARG_SOURCE_DIR}")
      message(FATAL_ERROR
        "pk_create_app (func): 'SOURCE_DIR' for '${ARG_NAME}' is not a "
        "directory: '${ARG_SOURCE_DIR}'.")
    endif()
    set(source_dir_given TRUE)
  elseif(ARG_DEFAULT_DIRS)
    pk_tree_dir(apps_dir apps)
    set(ARG_SOURCE_DIR "${apps_dir}/${ARG_NAME}")
  else()
    set(ARG_SOURCE_DIR "")
  endif()

  if(ARG_INCLUDE_DIR)
    cmake_path(ABSOLUTE_PATH ARG_INCLUDE_DIR
      BASE_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}" NORMALIZE)
    string(REGEX REPLACE "(.)/+$" "\\1" ARG_INCLUDE_DIR "${ARG_INCLUDE_DIR}")
    if(NOT IS_DIRECTORY "${ARG_INCLUDE_DIR}")
      message(FATAL_ERROR
        "pk_create_app (func): 'INCLUDE_DIR' for '${ARG_NAME}' is not a "
        "directory: '${ARG_INCLUDE_DIR}'.")
    endif()
    set(include_dir_given TRUE)
  else()
    set(ARG_INCLUDE_DIR "")
  endif()

  if(ARG_SOURCE_DIR)
    set(source_where "'${ARG_SOURCE_DIR}'")
  else()
    set(source_where "no 'SOURCE_DIR'")
  endif()
  if(ARG_INCLUDE_DIR)
    set(include_where "'${ARG_INCLUDE_DIR}'")
  else()
    set(include_where "no 'INCLUDE_DIR'")
  endif()

  pk_collect_components(${ARG_NAME}
    SOURCE_DIR "${ARG_SOURCE_DIR}"
    INCLUDE_DIR "${ARG_INCLUDE_DIR}"
    OUT_SOURCES globbed_sources
    OUT_PUBLIC_HEADERS globbed_public_headers
    OUT_PRIVATE_HEADERS globbed_private_headers)

  if(source_dir_given AND NOT globbed_sources AND NOT globbed_private_headers)
    message(FATAL_ERROR
      "pk_create_app (func): 'SOURCE_DIR' for '${ARG_NAME}' contains no "
      "sources or headers: '${ARG_SOURCE_DIR}'.")
  endif()
  if(include_dir_given AND NOT globbed_public_headers)
    message(FATAL_ERROR
      "pk_create_app (func): 'INCLUDE_DIR' for '${ARG_NAME}' contains no "
      "headers: '${ARG_INCLUDE_DIR}'.")
  endif()

  set(explicit_files ${ARG_SOURCES} ${ARG_PUBLIC_HEADERS} ${ARG_PRIVATE_HEADERS})
  if(explicit_files)
    foreach(globbed IN ITEMS
        globbed_sources globbed_public_headers globbed_private_headers)
      if(${globbed})
        list(REMOVE_ITEM ${globbed} ${explicit_files})
      endif()
    endforeach()
  endif()

  list(APPEND ARG_SOURCES ${globbed_sources})
  list(APPEND ARG_PUBLIC_HEADERS ${globbed_public_headers})
  list(APPEND ARG_PRIVATE_HEADERS ${globbed_private_headers})

  if(NOT ARG_SOURCES)
    message(FATAL_ERROR
      "pk_create_app (func): No sources found for '${ARG_NAME}' in "
      "${source_where} and none were given via 'SOURCES'.")
  endif()
  if(ARG_REQUIRE_PUBLIC_HEADERS AND NOT ARG_PUBLIC_HEADERS)
    message(FATAL_ERROR
      "pk_create_app (func): Public headers are required for "
      "'${ARG_NAME}', yet none were found in ${include_where} and none were "
      "given via 'PUBLIC_HEADERS'.")
  endif()
  if(ARG_REQUIRE_PRIVATE_HEADERS AND NOT ARG_PRIVATE_HEADERS)
    message(FATAL_ERROR
      "pk_create_app (func): Private headers are required for "
      "'${ARG_NAME}', yet none were found in ${source_where} and none were "
      "given via 'PRIVATE_HEADERS'.")
  endif()

  pk_resolve_language(language source_languages "application '${ARG_NAME}'"
    "${ARG_LANGUAGE}" ${ARG_SOURCES})

  set(app_languages ${language} ${source_languages})
  list(REMOVE_DUPLICATES app_languages)

  set(std_C "c_std_${${prefix}_C_STANDARD}")
  set(std_CXX "cxx_std_${${prefix}_CXX_STANDARD}")

  if(ARG_INCLUDE_DIR)
    pk_tree_base_dir(public_base_dir headers "${ARG_INCLUDE_DIR}")
  else()
    pk_tree_dir(public_base_dir headers)
  endif()
  if(ARG_SOURCE_DIR)
    pk_tree_base_dir(private_base_dir apps "${ARG_SOURCE_DIR}")
  else()
    pk_tree_dir(private_base_dir apps)
  endif()

  foreach(target output IN ZIP_LISTS ARG_TARGET_NAME ARG_OUTPUT_NAME)
    add_executable(${target} ${ARG_SOURCES})

    set_target_properties(${target} PROPERTIES
      OUTPUT_NAME "${output}")

    if(ARG_PUBLIC_HEADERS)
      target_sources(${target}
        PRIVATE
          FILE_SET    ${ARG_NAME}_app_public_headers
          TYPE        HEADERS
          BASE_DIRS   "${public_base_dir}"
          FILES       ${ARG_PUBLIC_HEADERS})
    endif()

    if(ARG_PRIVATE_HEADERS)
      target_sources(${target}
        PRIVATE
          FILE_SET    ${ARG_NAME}_app_private_headers
          TYPE        HEADERS
          BASE_DIRS   "${private_base_dir}"
          FILES       ${ARG_PRIVATE_HEADERS})
    endif()

    foreach(app_language IN LISTS app_languages)
      target_compile_features(${target} PRIVATE ${std_${app_language}})
    endforeach()

    target_compile_definitions(${target} PRIVATE
      ${prefix}_VERSION_STRING="${PROJECT_VERSION}")

    if(ARG_GUI)
      set_target_properties(${target} PROPERTIES WIN32_EXECUTABLE TRUE)
    endif()
    if(WIN32 AND ARG_RC_FILE)
      target_sources(${target} PRIVATE "${ARG_RC_FILE}")
    endif()
    if(MINGW AND ARG_OWN_MANIFEST)
      target_link_options(${target} PRIVATE "-B${no_manifest_dir}/")
    endif()
    if(MINGW AND ARG_STATIC_RUNTIME)
      target_link_options(${target} PRIVATE -static)
    endif()
  endforeach()

  # Generated <name>/app_paths.hpp for apps with C++, or <name>/app_paths.h
  # for C-only apps (AppPaths.cmake).
  if(NOT ARG_NO_APP_PATHS)
    if("CXX" IN_LIST app_languages)
      pk_add_app_paths(NAME ${ARG_NAME} TARGETS ${ARG_TARGET_NAME} LANGUAGE CXX)
    elseif("C" IN_LIST app_languages)
      pk_add_app_paths(NAME ${ARG_NAME} TARGETS ${ARG_TARGET_NAME} LANGUAGE C)
    endif()
  endif()

  if(ARG_NO_DEFAULT_LINKS)
    set(default_links NO_DEFAULT_LINKS)
  else()
    set(default_links "")
  endif()

  pk_link_targets(
    ${default_links}
    TARGETS ${ARG_TARGET_NAME}
    LINK_PRIVATE ${ARG_LINK_PRIVATE}
    LINK_INTERFACE ${ARG_LINK_INTERFACE})

  pk_deps_link(
    ROLE APPLICATION
    TARGETS ${ARG_TARGET_NAME}
    PRIVATE ${ARG_DEPS})

  foreach(target IN LISTS ARG_TARGET_NAME)
    pk_enable_static_analysis(${target})
  endforeach()

  if(${prefix}_INSTALL AND NOT ARG_NO_INSTALL)
    install(TARGETS ${ARG_TARGET_NAME}
      RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")
  endif()

  pk_register_targets(APPLICATION TARGETS ${ARG_TARGET_NAME})

  string(JOIN "', '" target_list ${ARG_TARGET_NAME})
  message(STATUS "${PROJECT_NAME}: Application built for '${ARG_NAME}' "
    "with executable target(s) named '${target_list}'.")
endfunction()
