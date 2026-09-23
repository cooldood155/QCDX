include_guard(GLOBAL)

function(pk_collect_components NAME)
  set(options
    REQUIRE_SOURCES
    REQUIRE_PUBLIC_HEADERS
    REQUIRE_PRIVATE_HEADERS)
  set(one_value_args
    SOURCE_DIR
    INCLUDE_DIR
    OUT_SOURCES
    OUT_PUBLIC_HEADERS
    OUT_PRIVATE_HEADERS)

  cmake_parse_arguments(ARG
    "${options}" "${one_value_args}" "" ${ARGN})

  set(sources "")
  set(private_headers "")
  set(public_headers "")

  if(ARG_SOURCE_DIR)
    file(GLOB_RECURSE sources CONFIGURE_DEPENDS
      "${ARG_SOURCE_DIR}/*.cpp" "${ARG_SOURCE_DIR}/*.cxx"
      "${ARG_SOURCE_DIR}/*.cc" "${ARG_SOURCE_DIR}/*.c")
    file(GLOB_RECURSE private_headers CONFIGURE_DEPENDS
      "${ARG_SOURCE_DIR}/*.hpp" "${ARG_SOURCE_DIR}/*.hxx"
      "${ARG_SOURCE_DIR}/*.hh" "${ARG_SOURCE_DIR}/*.h")
  endif()

  if(ARG_INCLUDE_DIR)
    file(GLOB_RECURSE public_headers CONFIGURE_DEPENDS
      "${ARG_INCLUDE_DIR}/*.hpp" "${ARG_INCLUDE_DIR}/*.hxx"
      "${ARG_INCLUDE_DIR}/*.hh" "${ARG_INCLUDE_DIR}/*.h")
  endif()

  if(NOT sources AND ARG_REQUIRE_SOURCES)
    message(FATAL_ERROR
      "pk_collect_components (func): no sources found for '${NAME}' in "
      "'${ARG_SOURCE_DIR}'. Expected files following the format "
      "'*.<cpp|cxx|cc|c>'.")
  endif()
  if(NOT public_headers AND ARG_REQUIRE_PUBLIC_HEADERS)
    message(FATAL_ERROR
      "pk_collect_components (func): no public headers found for '${NAME}' "
      "in '${ARG_INCLUDE_DIR}'. Expected files following the format "
      "'*.<hpp|hxx|hh|h>'.")
  endif()
  if(NOT private_headers AND ARG_REQUIRE_PRIVATE_HEADERS)
    message(FATAL_ERROR
      "pk_collect_components (func): no private headers found for "
      "'${NAME}' in '${ARG_SOURCE_DIR}'. Expected files following the format "
      "'*.<hpp|hxx|hh|h>'.")
  endif()

  if(ARG_OUT_SOURCES)
    set(${ARG_OUT_SOURCES} "${sources}" PARENT_SCOPE)
  endif()
  if(ARG_OUT_PUBLIC_HEADERS)
    set(${ARG_OUT_PUBLIC_HEADERS} "${public_headers}" PARENT_SCOPE)
  endif()
  if(ARG_OUT_PRIVATE_HEADERS)
    set(${ARG_OUT_PRIVATE_HEADERS} "${private_headers}" PARENT_SCOPE)
  endif()
endfunction()

function(pk_resolve_files OUT_VAR LABEL PATTERN)
  set(resolved "")
  foreach(path IN LISTS ARGN)
    cmake_path(ABSOLUTE_PATH path
      BASE_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}" NORMALIZE)
    string(TOLOWER "${path}" path_lower)
    if(NOT EXISTS "${path}" OR IS_DIRECTORY "${path}")
      message(FATAL_ERROR
        "pk_resolve_files (func): ${LABEL} file does not exist: '${path}'.")
    elseif(NOT path_lower MATCHES "${PATTERN}")
      message(FATAL_ERROR
        "pk_resolve_files (func): ${LABEL} file has the wrong extension: "
        "'${path}'.")
    endif()
    list(APPEND resolved "${path}")
  endforeach()
  list(REMOVE_DUPLICATES resolved)
  set(${OUT_VAR} "${resolved}" PARENT_SCOPE)
endfunction()
