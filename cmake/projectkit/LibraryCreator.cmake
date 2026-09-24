include_guard(GLOBAL)

include(GenerateExportHeader)

function(pk_add_library_targets NAME)
  if(NOT NAME)
    message(FATAL_ERROR
      "pk_add_library_targets (func): No NAME was provided?")
  endif()

  set(one_value_args KIND LINKAGE)
  set(multi_value_args SOURCES)
  cmake_parse_arguments(ARG
    "" "${one_value_args}" "${multi_value_args}" ${ARGN})

  string(TOUPPER "${NAME}" NAME_UPPER)

  set(local_library_targets "")
  set(local_export_target "")

  if(ARG_KIND STREQUAL "COMPILED")
    if(NOT ARG_SOURCES)
      message(FATAL_ERROR
        "pk_add_library_targets (func): No SOURCES were provided?")
    endif()

    if(ARG_LINKAGE STREQUAL "STATIC+SHARED")
      add_library("${NAME}_static" STATIC ${ARG_SOURCES})
      add_library("${NAME}_shared" SHARED ${ARG_SOURCES})

      set_target_properties("${NAME}_static" PROPERTIES EXPORT_NAME static)
      set_target_properties("${NAME}_shared" PROPERTIES EXPORT_NAME shared
                                             DEFINE_SYMBOL "${NAME}_EXPORTS")

      add_library("${NAME}::static" ALIAS "${NAME}_static")
      add_library("${NAME}::shared" ALIAS "${NAME}_shared")
      add_library("${NAME}::${NAME}" ALIAS "${NAME}_shared")

      list(APPEND local_library_targets "${NAME}_static" "${NAME}_shared")
      set(local_export_target "${NAME}_shared")

    elseif(ARG_LINKAGE STREQUAL "SHARED" OR ARG_LINKAGE STREQUAL "STATIC")
      add_library("${NAME}" ${ARG_LINKAGE} ${ARG_SOURCES})
      add_library("${NAME}::${NAME}" ALIAS "${NAME}")

      list(APPEND local_library_targets "${NAME}")
      set(local_export_target "${NAME}")

    else()
      message(FATAL_ERROR
        "pk_add_library_targets (func): 'LINKAGE' is unrecognized for '${NAME}': "
        "${ARG_LINKAGE}")
    endif()

  elseif(ARG_KIND STREQUAL "HEADER_ONLY" OR ARG_KIND STREQUAL "INTERFACE")
    add_library("${NAME}" INTERFACE)
    add_library("${NAME}::${NAME}" ALIAS "${NAME}")

    list(APPEND local_library_targets "${NAME}")

  else()
    message(FATAL_ERROR
      "pk_add_library_targets (func): 'KIND' is unrecognized for '${NAME}': "
      "${ARG_KIND}")
  endif()

  set(${NAME_UPPER}_LIBRARY_TARGETS "${local_library_targets}" PARENT_SCOPE)
  set(${NAME_UPPER}_EXPORT_HEADER_TARGET "${local_export_target}" PARENT_SCOPE)
endfunction()

function(pk_configure_libraries)
  set(one_value_args BASE_NAME)
  set(multi_value_args
    PUBLIC_HEADERS
    PRIVATE_HEADERS
    TARGETS)
  cmake_parse_arguments(ARG
    "" "${one_value_args}" "${multi_value_args}" ${ARGN})

  pk_project_prefix(prefix)

  if(NOT ARG_BASE_NAME)
    message(FATAL_ERROR
      "pk_configure_libraries (func): no 'BASE_NAME' given.")
  endif()
  if(NOT ARG_TARGETS)
    message(FATAL_ERROR
      "pk_configure_libraries (func): no 'TARGETS' given.")
  endif()

  set(BASE_NAME "${ARG_BASE_NAME}")
  string(TOUPPER "${BASE_NAME}" BASE_NAME_UPPER)

  foreach(target IN LISTS ARG_TARGETS)
    if(NOT TARGET ${target})
      message(FATAL_ERROR
        "pk_configure_libraries (func): '${target}' is not a target.")
    endif()

    get_target_property(target_type ${target} TYPE)

    if(target_type STREQUAL "INTERFACE_LIBRARY")
      set(pub INTERFACE)
    else()
      set(pub PUBLIC)
    endif()

    if(target MATCHES "_static$")
      set_target_properties(${target} PROPERTIES
        OUTPUT_NAME "${BASE_NAME}-static")
    elseif(target MATCHES "_shared$")
      set_target_properties(${target} PROPERTIES
        OUTPUT_NAME "${BASE_NAME}-shared")
    endif()

    if(ARG_PUBLIC_HEADERS)
      target_sources(${target}
        ${pub}
          FILE_SET    ${BASE_NAME}_headers
          TYPE        HEADERS
          BASE_DIRS   "${PROJECT_SOURCE_DIR}/include"
          FILES       ${ARG_PUBLIC_HEADERS})
    endif()

    if(ARG_PRIVATE_HEADERS)
      if(target_type STREQUAL "INTERFACE_LIBRARY")
        message(FATAL_ERROR
          "'pk_configure_libraries' (func): Private headers are NOT "
          "allowed to be linked to Interface libraries.")
      endif()

      target_sources(${target}
        PRIVATE
          FILE_SET    ${BASE_NAME}_private_headers
          TYPE        HEADERS
          BASE_DIRS   "${PROJECT_SOURCE_DIR}/src"
          FILES       ${ARG_PRIVATE_HEADERS})
    endif()

    if(EXISTS "${PROJECT_BINARY_DIR}/generated/${BASE_NAME}/export.hpp")
      target_sources(${target}
        ${pub}
          FILE_SET    ${BASE_NAME}_generated_headers
          TYPE        HEADERS
          BASE_DIRS   "${PROJECT_BINARY_DIR}/generated"
          FILES       "${PROJECT_BINARY_DIR}/generated/${BASE_NAME}/export.hpp")
    endif()

    target_compile_features(${target} ${pub}
      cxx_std_${${prefix}_CXX_STANDARD})

    if(NOT target_type STREQUAL "INTERFACE_LIBRARY")
      target_compile_definitions(${target} PRIVATE
        ${prefix}_VERSION_STRING="${PROJECT_VERSION}")

      pk_enable_static_analysis(${target})

      set_target_properties(${target} PROPERTIES
        VERSION "${PROJECT_VERSION}"
        SOVERSION "${PROJECT_VERSION_MAJOR}"
        CXX_VISIBILITY_PRESET hidden
        VISIBILITY_INLINES_HIDDEN ON)

      if(NOT target_type STREQUAL "SHARED_LIBRARY")
        target_compile_definitions(${target} PUBLIC
          ${BASE_NAME_UPPER}_STATIC_DEFINE)
      else()
        target_compile_definitions(${target} PUBLIC
          ${BASE_NAME_UPPER}_SHARED_DEFINE)
      endif()
    endif()
  endforeach()
endfunction()

function(pk_create_library)
  set(options
    LOCKED_STATIC
    LOCKED_SHARED
    LOCKED_STATIC_SHARED

    REQUIRE_SOURCES
    REQUIRE_PUBLIC_HEADERS
    REQUIRE_PRIVATE_HEADERS

    NO_DEFAULT_LINKS
    NO_INSTALL
    VERBATIM)

  set(one_value_args
    NAME
    KIND
    SOURCE_DIR
    INCLUDE_DIR
    EXPORT_SET)

  set(multi_value_args
    SOURCES
    PUBLIC_HEADERS
    PRIVATE_HEADERS
    LINK_PUBLIC
    LINK_PRIVATE
    LINK_INTERFACE)

  cmake_parse_arguments(ARG
    "${options}" "${one_value_args}" "${multi_value_args}" ${ARGN})

  pk_project_prefix(prefix)

  if(NOT ARG_NAME)
    message(FATAL_ERROR "pk_create_library requires a 'NAME' argument.")
  endif()
  if(ARG_UNPARSED_ARGUMENTS)
    message(FATAL_ERROR
      "pk_create_library (func): unrecognized arguments for "
      "'${ARG_NAME}': ${ARG_UNPARSED_ARGUMENTS}")
  endif()

  if(NOT ARG_EXPORT_SET)
    set(ARG_EXPORT_SET "${PROJECT_NAME}Targets")
  endif()

  if(NOT ARG_KIND AND NOT ARG_VERBATIM)
    set(ARG_KIND "AUTO")
  elseif(NOT ARG_KIND)
    message(FATAL_ERROR
      "'pk_create_library' (func): Requires a 'KIND' be set for the "
      "libraries with the 'VERBATIM' option enabled. 'KIND' can be set to: "
      "\"COMPILED\", \"HEADER_ONLY\", or \"INTERFACE\".")
  endif()

  set(flags_selected 0)
  set(linkage "")
  if(ARG_LOCKED_STATIC)
    math(EXPR flags_selected "${flags_selected} + 1")
    set(linkage "STATIC")
  endif()
  if(ARG_LOCKED_SHARED)
    math(EXPR flags_selected "${flags_selected} + 1")
    set(linkage "SHARED")
  endif()
  if(ARG_LOCKED_STATIC_SHARED)
    math(EXPR flags_selected "${flags_selected} + 1")
    set(linkage "STATIC+SHARED")
  endif()

  if(flags_selected GREATER 1)
    message(FATAL_ERROR
      "pk_create_library (func): Only one option flag allowed at once.")
  elseif(flags_selected EQUAL 1)
    message(STATUS
      "${PROJECT_NAME}: library '${ARG_NAME}' linkage locked to ${linkage}")
  endif()

  set(require_sources ${ARG_REQUIRE_SOURCES})
  set(require_public_headers ${ARG_REQUIRE_PUBLIC_HEADERS})
  set(require_private_headers ${ARG_REQUIRE_PRIVATE_HEADERS})

  if(NOT require_sources AND ARG_SOURCES)
    set(require_sources ON)
  endif()
  if(NOT require_public_headers AND ARG_PUBLIC_HEADERS OR ARG_INCLUDE_DIR)
    set(require_public_headers ON)
  endif()
  if(NOT require_private_headers AND ARG_PRIVATE_HEADERS)
    set(require_private_headers ON)
  endif()

  if(NOT require_sources)
    message(STATUS
      "${PROJECT_NAME}: Sources are not required for library target '${ARG_NAME}'.")
  else()
    message(STATUS
      "${PROJECT_NAME}: Sources are required for library target '${ARG_NAME}'.")
  endif()

  if(NOT require_public_headers)
    message(STATUS
      "${PROJECT_NAME}: Public headers are not required for library target '${ARG_NAME}'.")
  else()
    message(STATUS
      "${PROJECT_NAME}: Public headers are required for library target '${ARG_NAME}'.")
  endif()

  if(NOT require_private_headers)
    message(STATUS
      "${PROJECT_NAME}: Private headers are not required for library target '${ARG_NAME}'.")
  else()
    message(STATUS
      "${PROJECT_NAME}: Private headers are required for library target '${ARG_NAME}'.")
  endif()

  if(NOT ARG_KIND MATCHES "^(AUTO|COMPILED|HEADER_ONLY|INTERFACE)$")
    message(FATAL_ERROR
      "pk_create_library (func): 'KIND' is unrecognized for '${ARG_NAME}': "
      "${ARG_KIND}")
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
        "pk_create_library (func): '${ARG_NAME}' header passed as both "
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
        "pk_create_library (func): 'SOURCE_DIR' for '${ARG_NAME}' is not a "
        "directory: '${ARG_SOURCE_DIR}'.")
    endif()
    set(source_dir_given TRUE)
  elseif(NOT ARG_VERBATIM AND ARG_KIND MATCHES "^(AUTO|COMPILED)$")
    set(ARG_SOURCE_DIR "${PROJECT_SOURCE_DIR}/src/${ARG_NAME}")
  else()
    message(STATUS
      "${PROJECT_NAME}: No source directory provided for library target '${ARG_NAME}'.")
    set(ARG_SOURCE_DIR "")
  endif()

  if(ARG_INCLUDE_DIR)
    cmake_path(ABSOLUTE_PATH ARG_INCLUDE_DIR
      BASE_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}" NORMALIZE)
    string(REGEX REPLACE "(.)/+$" "\\1" ARG_INCLUDE_DIR "${ARG_INCLUDE_DIR}")
    if(NOT IS_DIRECTORY "${ARG_INCLUDE_DIR}")
      message(FATAL_ERROR
        "pk_create_library (func): 'INCLUDE_DIR' for '${ARG_NAME}' is not "
        "a directory: '${ARG_INCLUDE_DIR}'.")
    endif()
    set(include_dir_given TRUE)
  elseif(NOT ARG_VERBATIM AND NOT ARG_KIND STREQUAL "INTERFACE")
    set(ARG_INCLUDE_DIR "${PROJECT_SOURCE_DIR}/include/${ARG_NAME}")
  else()
    message(STATUS
      "${PROJECT_NAME}: No include directory provided for library target '${ARG_NAME}'.")
    set(ARG_INCLUDE_DIR "")
  endif()

  pk_collect_components(${ARG_NAME}
    SOURCE_DIR "${ARG_SOURCE_DIR}"
    INCLUDE_DIR "${ARG_INCLUDE_DIR}"
    OUT_SOURCES globbed_sources
    OUT_PUBLIC_HEADERS globbed_public_headers
    OUT_PRIVATE_HEADERS globbed_private_headers)

  if(source_dir_given AND NOT globbed_sources AND NOT globbed_private_headers)
    message(FATAL_ERROR
      "pk_create_library (func): 'SOURCE_DIR' for '${ARG_NAME}' contains "
      "no sources or headers: '${ARG_SOURCE_DIR}'.")
  endif()
  if(include_dir_given AND NOT globbed_public_headers)
    message(FATAL_ERROR
      "pk_create_library (func): 'INCLUDE_DIR' for '${ARG_NAME}' contains "
      "no headers: '${ARG_INCLUDE_DIR}'.")
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

  if(NOT ARG_SOURCES AND require_sources)
    message(FATAL_ERROR
      "'pk_create_library' (func): Sources are required when the "
      "'REQUIRE_SOURCES' option is provided, yet no 'SOURCES' were provided.")
  elseif(NOT ARG_PUBLIC_HEADERS AND require_public_headers)
    message(FATAL_ERROR
      "'pk_create_library' (func): Public headers are required when the "
      "'REQUIRE_PUBLIC_HEADERS' option is provided, yet no 'PUBLIC_HEADERS' "
      "were provided.")
  elseif(NOT ARG_PRIVATE_HEADERS AND require_private_headers)
    message(FATAL_ERROR
      "'pk_create_library' (func): Private headers are required when the "
      "'REQUIRE_PRIVATE_HEADERS' option is provided, yet no 'PRIVATE_HEADERS' "
      "were provided.")
  endif()

  if(ARG_KIND STREQUAL "AUTO")
    if(ARG_SOURCES)
      set(ARG_KIND "COMPILED")
    elseif(flags_selected OR ARG_PRIVATE_HEADERS)
      message(FATAL_ERROR
        "pk_create_library (func): '${ARG_NAME}' has a 'LOCKED_*' linkage "
        "or private headers, which require a COMPILED library, but no sources "
        "were found in '${ARG_SOURCE_DIR}' and none were given via 'SOURCES'.")
    elseif(ARG_PUBLIC_HEADERS)
      set(ARG_KIND "HEADER_ONLY")
    else()
      set(ARG_KIND "INTERFACE")
    endif()
    message(STATUS "${PROJECT_NAME}: library '${ARG_NAME}' detected as ${ARG_KIND}")
  endif()

  if(ARG_KIND STREQUAL "COMPILED" AND NOT ARG_SOURCES)
    message(FATAL_ERROR
      "pk_create_library (func): '${ARG_NAME}' is 'KIND' COMPILED but no "
      "sources were found in '${ARG_SOURCE_DIR}' and none were given via "
      "'SOURCES'.")
  elseif(NOT ARG_KIND STREQUAL "COMPILED"
      AND (ARG_SOURCES OR ARG_PRIVATE_HEADERS OR flags_selected))
    message(FATAL_ERROR
      "pk_create_library (func): '${ARG_NAME}' is 'KIND' ${ARG_KIND} but "
      "has sources, private headers or a 'LOCKED_*' linkage, which only apply "
      "to COMPILED libraries.")
  elseif(ARG_KIND STREQUAL "HEADER_ONLY" AND NOT ARG_PUBLIC_HEADERS)
    message(FATAL_ERROR
      "pk_create_library (func): '${ARG_NAME}' is 'KIND' HEADER_ONLY but "
      "no public headers were found in '${ARG_INCLUDE_DIR}'.")
  endif()

  if(ARG_KIND STREQUAL "COMPILED" AND flags_selected EQUAL 0)
    if(ARG_VERBATIM)
      message(FATAL_ERROR
        "'pk_create_library' (func): A linkage for the library must be "
        "provided when the 'VERBATIM' option is enabled. The available "
        "linkage options, only one can be set at a time, are: "
        "'LOCKED_STATIC', 'LOCKED_SHARED', or 'LOCKED_STATIC_SHARED'.")
    endif()
    set(linkage "${${prefix}_LIBRARY_TYPE}")
  endif()

  pk_add_library_targets(${ARG_NAME}
    KIND "${ARG_KIND}"
    LINKAGE "${linkage}"
    SOURCES ${ARG_SOURCES})

  string(TOUPPER "${ARG_NAME}" ARG_NAME_UPPER)
  set(target_list_var "${ARG_NAME_UPPER}_LIBRARY_TARGETS")
  set(export_target_var "${ARG_NAME_UPPER}_EXPORT_HEADER_TARGET")

  if(NOT ${target_list_var})
    message(FATAL_ERROR
      "'${target_list_var}' was not set (internal logic issue).")
  endif()

  if(${export_target_var})
    generate_export_header(${${export_target_var}}
      BASE_NAME        "${ARG_NAME}"
      EXPORT_FILE_NAME "${PROJECT_BINARY_DIR}/generated/${ARG_NAME}/export.hpp")
  endif()

  if(ARG_NO_DEFAULT_LINKS)
    set(default_links NO_DEFAULT_LINKS)
  else()
    set(default_links "")
  endif()

  pk_configure_libraries(
    TARGETS ${${target_list_var}}
    BASE_NAME "${ARG_NAME}"
    PUBLIC_HEADERS ${ARG_PUBLIC_HEADERS}
    PRIVATE_HEADERS ${ARG_PRIVATE_HEADERS})

  pk_link_targets(
    ${default_links}
    TARGETS ${${target_list_var}}
    LINK_PUBLIC ${ARG_LINK_PUBLIC}
    LINK_PRIVATE ${ARG_LINK_PRIVATE}
    LINK_INTERFACE ${ARG_LINK_INTERFACE})

  pk_register_targets(LIBRARY TARGETS ${${target_list_var}})

  if(${prefix}_INSTALL AND NOT ARG_NO_INSTALL)
    set(install_file_sets "")
    if(ARG_PUBLIC_HEADERS)
      list(APPEND install_file_sets
        FILE_SET ${ARG_NAME}_headers
          DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
    endif()
    if(${export_target_var})
      list(APPEND install_file_sets
        FILE_SET ${ARG_NAME}_generated_headers
          DESTINATION "${CMAKE_INSTALL_INCLUDEDIR}")
    endif()

    install(TARGETS ${${target_list_var}}
      EXPORT ${ARG_EXPORT_SET}
      RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}"
      LIBRARY DESTINATION "${CMAKE_INSTALL_LIBDIR}"
      ARCHIVE DESTINATION "${CMAKE_INSTALL_LIBDIR}"
      ${install_file_sets})
  endif()
endfunction()
