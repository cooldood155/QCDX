include_guard(GLOBAL)

function(pk_create_test)
  set(options
    NO_DEFAULT_LINKS
    NO_VALGRIND)

  set(one_value_args
    NAME
    SOURCE_DIR
    LABEL
    BASE_DIR)

  set(multi_value_args
    SOURCES
    LINK_PRIVATE)

  cmake_parse_arguments(ARG
    "${options}" "${one_value_args}" "${multi_value_args}" ${ARGN})

  pk_project_prefix(prefix)

  if(NOT ARG_NAME)
    message(FATAL_ERROR "pk_create_test requires a 'NAME' argument.")
  endif()
  if(ARG_UNPARSED_ARGUMENTS)
    message(FATAL_ERROR
      "pk_create_test (func): unrecognized arguments for '${ARG_NAME}': "
      "${ARG_UNPARSED_ARGUMENTS}")
  endif()
  if(NOT COMMAND catch_discover_tests)
    message(FATAL_ERROR
      "pk_create_test (func): 'catch_discover_tests' is not defined; call "
      "find_package(Catch2 3 REQUIRED) and include(Catch) first.")
  endif()

  if(NOT ARG_LABEL)
    set(ARG_LABEL "unit")
  endif()
  if(NOT ARG_SOURCE_DIR)
    set(ARG_SOURCE_DIR "${PROJECT_SOURCE_DIR}/tests/${ARG_NAME}")
  endif()
  if(NOT ARG_BASE_DIR)
    set(ARG_BASE_DIR "${PROJECT_SOURCE_DIR}/tests")
  endif()

  pk_resolve_files(ARG_SOURCES "'${ARG_NAME}' SOURCES"
    "\\.(c|cc|cpp|cxx)$" ${ARG_SOURCES})

  pk_collect_components(${ARG_NAME}
    SOURCE_DIR "${ARG_SOURCE_DIR}"
    OUT_SOURCES globbed_sources
    OUT_PRIVATE_HEADERS globbed_private_headers)

  if(ARG_SOURCES AND globbed_sources)
    list(REMOVE_ITEM globbed_sources ${ARG_SOURCES})
  endif()
  list(APPEND ARG_SOURCES ${globbed_sources})

  if(NOT ARG_SOURCES)
    message(FATAL_ERROR
      "pk_create_test (func): no test sources found for '${ARG_NAME}' in "
      "'${ARG_SOURCE_DIR}' and none were given via 'SOURCES'.")
  endif()

  pk_get_targets(LIBRARY libraries)

  set(library_variants "")
  foreach(library IN LISTS libraries)
    if(library MATCHES "^${ARG_NAME}(_static|_shared)?$")
      list(APPEND library_variants ${library})
    endif()
  endforeach()

  if(NOT library_variants)
    message(FATAL_ERROR
      "pk_create_test (func): no library targets found for '${ARG_NAME}'. "
      "Was pk_create_library(NAME ${ARG_NAME} ...) called first?")
  endif()

  if(ARG_NO_DEFAULT_LINKS)
    set(default_links NO_DEFAULT_LINKS)
  else()
    set(default_links "")
  endif()

  foreach(library IN LISTS library_variants)
    if(library MATCHES "_static$")
      set(test_target "${ARG_NAME}_tests_static")
    elseif(library MATCHES "_shared$")
      set(test_target "${ARG_NAME}_tests_shared")
    else()
      set(test_target "${ARG_NAME}_tests")
    endif()

    add_executable(${test_target} ${ARG_SOURCES})

    if(globbed_private_headers)
      target_sources(${test_target}
        PRIVATE
          FILE_SET    ${test_target}_headers
          TYPE        HEADERS
          BASE_DIRS   "${ARG_BASE_DIR}"
          FILES       ${globbed_private_headers})
    endif()

    target_compile_features(${test_target} PRIVATE
      cxx_std_${${prefix}_CXX_STANDARD})

    pk_link_targets(
      ${default_links}
      TARGETS ${test_target}
      LINK_PRIVATE
        ${library}
        ${ARG_LINK_PRIVATE}
        Catch2::Catch2WithMain)

    pk_enable_static_analysis(${test_target})

    if(CMAKE_CROSSCOMPILING AND NOT CMAKE_CROSSCOMPILING_EMULATOR)
      add_test(NAME ${test_target} COMMAND ${test_target})
      set_tests_properties(${test_target} PROPERTIES DISABLED TRUE)
    else()
      catch_discover_tests(${test_target}
        TEST_PREFIX "${test_target}: "
        PROPERTIES LABELS "${ARG_LABEL}"
        DISCOVERY_MODE PRE_TEST)

      if(NOT ARG_NO_VALGRIND)
        pk_add_valgrind_test(${test_target})
      endif()
    endif()

    pk_register_targets(TEST TARGETS ${test_target})

    message(STATUS
      "${PROJECT_NAME}: library tests built for '${library}' with target name "
      "of '${test_target}'.")
  endforeach()
endfunction()
