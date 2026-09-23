include_guard(GLOBAL)

function(pk_create_tool)
  set(options VERBATIM)
  set(one_value_args
    NAME
    ALIAS
    ROUT_DIR
    EXPORT_NAME
    EXPORT_NAMESPACE
    EXPORT_FILE
    SOURCE_DIR)
  set(multi_value_args SOURCES NAME_SEPARATORS)

  cmake_parse_arguments(ARG
    "${options}" "${one_value_args}" "${multi_value_args}" ${ARGN})

  if(NOT ARG_NAME)
    message(FATAL_ERROR
      "'pk_create_tool' (func): Expects a single-valued NAME argument to "
      "represent the executable target.")
  endif()

  if(NOT ARG_NAME_SEPARATORS)
    set(ARG_NAME_SEPARATORS "_" "-")
  endif()

  set(escaped_separators "")
  foreach(separator IN LISTS ARG_NAME_SEPARATORS)
    string(REGEX REPLACE "([][+*?^$().|\\\\-])" "\\\\1" escaped "${separator}")
    list(APPEND escaped_separators "${escaped}")
  endforeach()

  string(JOIN "|" separator_regex ${escaped_separators})
  string(REGEX REPLACE "${separator_regex}" ";" name_pieces "${ARG_NAME}")

  if(NOT ARG_SOURCE_DIR AND NOT ARG_SOURCES)
    message(FATAL_ERROR
      "'pk_create_tool' (func): No sources were recieved; 'SOURCE_DIR' and "
      "'SOURCES' are empty?")
  endif()

  pk_resolve_files(ARG_SOURCES "'${ARG_NAME}' SOURCES"
    "\\.(c|cc|cpp|cxx|h|hh|hpp|hxx)$" ${ARG_SOURCES})

  set(source_files ${ARG_SOURCES})

  if(ARG_SOURCE_DIR)
    pk_collect_components(${ARG_NAME}
      SOURCE_DIR "${ARG_SOURCE_DIR}"
      OUT_SOURCES globbed_sources
      OUT_PRIVATE_HEADERS globbed_private_headers)

    set(globbed ${globbed_sources} ${globbed_private_headers})
    if(source_files AND globbed)
      list(REMOVE_ITEM globbed ${source_files})
    endif()
    list(APPEND source_files ${globbed})
  endif()

  if(NOT source_files)
    message(FATAL_ERROR
      "'pk_create_tool' (func): No valid source files were able to be "
      "resolved for target '${ARG_NAME}'.")
  endif()

  list(GET name_pieces -1 export_name_piece)
  list(LENGTH name_pieces pieces_length)
  math(EXPR namespace_length "${pieces_length} - 1")
  list(SUBLIST name_pieces 0 ${namespace_length} namespace_pieces)

  if(NOT ARG_ALIAS AND NOT ARG_VERBATIM)
    if(pieces_length GREATER 1)
      string(JOIN "::" ARG_ALIAS ${name_pieces})
    else()
      set(ARG_ALIAS "")
    endif()
  endif()

  if(NOT ARG_ROUT_DIR)
    set(ARG_ROUT_DIR "${PROJECT_BINARY_DIR}/bin")
  endif()

  if(NOT ARG_EXPORT_NAME)
    if(NOT ARG_VERBATIM)
      set(ARG_EXPORT_NAME "${export_name_piece}")
    else()
      message(FATAL_ERROR
        "'pk_create_tool' (func): 'EXPORT_NAME' argument is not auto-set and "
        "expected when option 'VERBATIM' is enabled.")
    endif()
  endif()

  if(NOT ARG_EXPORT_NAMESPACE AND NOT ARG_VERBATIM)
    if(namespace_pieces)
      string(JOIN "::" namespace_string ${namespace_pieces})
      set(ARG_EXPORT_NAMESPACE "${namespace_string}::")
    else()
      set(ARG_EXPORT_NAMESPACE "")
    endif()
  endif()

  if(NOT ARG_EXPORT_FILE)
    if(NOT ARG_VERBATIM AND namespace_pieces)
      string(JOIN "_" file_prefix ${namespace_pieces})
      set(ARG_EXPORT_FILE "${PROJECT_BINARY_DIR}/${file_prefix}Targets.cmake")
    elseif(NOT ARG_VERBATIM)
      set(ARG_EXPORT_FILE "${PROJECT_BINARY_DIR}/${ARG_NAME}Targets.cmake")
    else()
      message(FATAL_ERROR
        "'pk_create_tool' (func): Expects 'EXPORT_FILE' when 'VERBATIM' is "
        "enabled.")
    endif()
  endif()

  add_executable(${ARG_NAME} ${source_files})
  if(ARG_ALIAS)
    add_executable(${ARG_ALIAS} ALIAS ${ARG_NAME})
  endif()

  pk_enable_static_analysis(${ARG_NAME})

  set_target_properties(${ARG_NAME} PROPERTIES
    EXPORT_NAME ${ARG_EXPORT_NAME}
    RUNTIME_OUTPUT_DIRECTORY ${ARG_ROUT_DIR})

  if(NOT ARG_EXPORT_NAMESPACE)
    export(TARGETS ${ARG_NAME}
      APPEND
      FILE "${ARG_EXPORT_FILE}")
  else()
    export(TARGETS ${ARG_NAME}
      APPEND
      NAMESPACE ${ARG_EXPORT_NAMESPACE}
      FILE "${ARG_EXPORT_FILE}")
  endif()

  pk_register_targets(TOOL TARGETS ${ARG_NAME})
endfunction()
