include_guard(GLOBAL)

function(pk_require_host_tools)
  set(one_value_args PACKAGE)
  cmake_parse_arguments(ARG "" "${one_value_args}" "" ${ARGN})

  if(NOT ARG_PACKAGE)
    set(ARG_PACKAGE "${PROJECT_NAME}HostTools")
  endif()

  if(CMAKE_CROSSCOMPILING)
    find_package(${ARG_PACKAGE} REQUIRED)
  endif()
endfunction()

function(pk_add_generated_source)
  set(one_value_args NAME SPEC OUTPUT TOOL)
  set(multi_value_args TARGETS)
  cmake_parse_arguments(ARG "" "${one_value_args}" "${multi_value_args}" ${ARGN})

  if(NOT ARG_NAME)
    message(FATAL_ERROR
      "pk_add_generated_source (func): No 'NAME' was provided?")
  endif()
  if(NOT ARG_SPEC)
    message(FATAL_ERROR
      "pk_add_generated_source (func): No 'SPEC' was provided?")
  endif()
  if(NOT ARG_OUTPUT)
    message(FATAL_ERROR
      "pk_add_generated_source (func): No 'OUTPUT' was provided?")
  endif()
  if(NOT ARG_TARGETS)
    message(FATAL_ERROR
      "pk_add_generated_source (func): No 'TARGETS' were provided?")
  endif()
  if(NOT ARG_TOOL)
    set(ARG_TOOL "${PROJECT_NAME}::codegen")
  endif()
  if(NOT EXISTS "${ARG_SPEC}")
    message(FATAL_ERROR
      "pk_add_generated_source (func): spec '${ARG_SPEC}' does not exist.")
  endif()
  if(NOT TARGET ${ARG_TOOL})
    message(FATAL_ERROR
      "pk_add_generated_source (func): '${ARG_TOOL}' is not defined. When "
      "cross compiling, configure a native build first and point "
      "${PROJECT_NAME}HostTools_DIR at its binary directory.")
  endif()

  set(out "${PROJECT_BINARY_DIR}/generated/${ARG_NAME}/${ARG_OUTPUT}")

  add_custom_command(
    OUTPUT "${out}"
    COMMAND ${ARG_TOOL} --input "${ARG_SPEC}" --output "${out}"
    DEPENDS "${ARG_SPEC}" ${ARG_TOOL}
    COMMENT "Generating ${ARG_NAME}/${ARG_OUTPUT}"
    VERBATIM)

  set_source_files_properties("${out}" PROPERTIES
    SKIP_LINTING ON
    GENERATED ON)

  foreach(target IN LISTS ARG_TARGETS)
    get_target_property(target_type ${target} TYPE)
    if(target_type STREQUAL "INTERFACE_LIBRARY")
      message(FATAL_ERROR
        "pk_add_generated_source (func): '${target}' is an interface library "
        "and cannot compile a generated source.")
    endif()

    target_sources(${target} PRIVATE "${out}")
  endforeach()
endfunction()
