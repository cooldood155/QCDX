include_guard(GLOBAL)

function(pk_require_conan_build_dir)
  set(one_value_args OUT_BUILD_TYPE OUT_DIR OUT_TOOLCHAIN)
  cmake_parse_arguments(ARG "" "${one_value_args}" "" ${ARGN})

  if(NOT CMAKE_BUILD_TYPE)
    message(FATAL_ERROR "A build type must be specified, not set by default.")
  endif()

  string(STRIP "${CMAKE_BUILD_TYPE}" given_type)
  string(TOLOWER "${given_type}" given_type_lower)

  set(known_types Debug Release RelWithDebInfo MinSizeRel)
  set(build_type "")
  foreach(candidate IN LISTS known_types)
    string(TOLOWER "${candidate}" candidate_lower)
    if(given_type_lower STREQUAL candidate_lower)
      set(build_type "${candidate}")
      break()
    endif()
  endforeach()

  if(NOT build_type)
    message(FATAL_ERROR
      "'CMAKE_BUILD_TYPE' is not a known build type: '${CMAKE_BUILD_TYPE}'. "
      "Expected one of: ${known_types}.")
  endif()

  string(TOLOWER "${build_type}" build_type_lower)

  if(CMAKE_TOOLCHAIN_FILE)
    cmake_path(ABSOLUTE_PATH CMAKE_TOOLCHAIN_FILE
      BASE_DIRECTORY "${CMAKE_BINARY_DIR}" NORMALIZE
      OUTPUT_VARIABLE toolchain)
    cmake_path(GET toolchain PARENT_PATH generators_dir)
    cmake_path(GET generators_dir PARENT_PATH conan_dir)
  else()
    cmake_path(GET CMAKE_BINARY_DIR PARENT_PATH build_root)
    set(conan_dir "${build_root}/${build_type}")
    set(generators_dir "${conan_dir}/generators")
    set(toolchain "${generators_dir}/conan_toolchain.cmake")
  endif()

  if(NOT EXISTS "${toolchain}")
    message(FATAL_ERROR
      "\nConan has not generated dependencies for '${build_type}' yet, "
      "missing: ${toolchain}"
      "\nRun conan install with '-s build_type=${build_type}' first.")
  endif()

  file(GLOB dependency_data "${generators_dir}/*-data.cmake")
  if(dependency_data)
    set(matching "")
    foreach(data_file IN LISTS dependency_data)
      cmake_path(GET data_file FILENAME data_name)
      if(data_name MATCHES "-${build_type_lower}-")
        list(APPEND matching "${data_name}")
      endif()
    endforeach()

    if(NOT matching)
      message(FATAL_ERROR
        "\nThe Conan output in '${generators_dir}' was not generated for "
        "'${build_type}'."
        "\nCMAKE_TOOLCHAIN_FILE: ${toolchain}"
        "\nRun conan install with '-s build_type=${build_type}', or configure "
        "with the preset that matches this build type.")
    endif()
  endif()

  message(STATUS
    "ProjectKit: using Conan output for '${build_type}': '${conan_dir}'")

  if(ARG_OUT_BUILD_TYPE)
    set(${ARG_OUT_BUILD_TYPE} "${build_type}" PARENT_SCOPE)
  endif()
  if(ARG_OUT_DIR)
    set(${ARG_OUT_DIR} "${conan_dir}" PARENT_SCOPE)
  endif()
  if(ARG_OUT_TOOLCHAIN)
    set(${ARG_OUT_TOOLCHAIN} "${toolchain}" PARENT_SCOPE)
  endif()
endfunction()
