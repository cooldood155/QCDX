include_guard(GLOBAL)

function(pk_project_prefix OUT_VAR)
  string(TOUPPER "${PROJECT_NAME}" prefix)
  string(MAKE_C_IDENTIFIER "${prefix}" prefix)
  set(${OUT_VAR} "${prefix}" PARENT_SCOPE)
endfunction()

function(pk_register_targets KIND)
  cmake_parse_arguments(ARG "" "" "TARGETS" ${ARGN})

  if(NOT ARG_TARGETS)
    message(FATAL_ERROR "pk_register_targets (func): no 'TARGETS' given.")
  endif()

  set_property(GLOBAL APPEND
    PROPERTY PK_${PROJECT_NAME}_${KIND}_TARGETS ${ARG_TARGETS})
endfunction()

function(pk_get_targets KIND OUT_VAR)
  get_property(found GLOBAL PROPERTY PK_${PROJECT_NAME}_${KIND}_TARGETS)
  set(${OUT_VAR} "${found}" PARENT_SCOPE)
endfunction()

function(pk_set_state KEY)
  set_property(GLOBAL PROPERTY PK_${PROJECT_NAME}_${KEY} "${ARGN}")
endfunction()

function(pk_get_state KEY OUT_VAR)
  get_property(found GLOBAL PROPERTY PK_${PROJECT_NAME}_${KEY})
  set(${OUT_VAR} "${found}" PARENT_SCOPE)
endfunction()

function(pk_link_targets)
  set(options NO_DEFAULT_LINKS)
  set(multi_value_args
    LINK_PUBLIC
    LINK_PRIVATE
    LINK_INTERFACE
    TARGETS)
  cmake_parse_arguments(ARG "${options}" "" "${multi_value_args}" ${ARGN})

  pk_get_state(DEFAULT_LINKS default_links)

  foreach(t IN LISTS ARG_TARGETS)
    get_target_property(target_type ${t} TYPE)

    if(target_type STREQUAL "INTERFACE_LIBRARY")
      set(pub INTERFACE)
      set(priv INTERFACE)
    else()
      set(pub PUBLIC)
      set(priv PRIVATE)
    endif()

    if(NOT ARG_NO_DEFAULT_LINKS AND default_links)
      target_link_libraries(${t} ${priv} ${default_links})
    endif()

    if(ARG_LINK_PUBLIC)
      target_link_libraries(${t} ${pub} ${ARG_LINK_PUBLIC})
    endif()
    if(ARG_LINK_PRIVATE)
      target_link_libraries(${t} ${priv} ${ARG_LINK_PRIVATE})
    endif()
    if(ARG_LINK_INTERFACE)
      target_link_libraries(${t} INTERFACE ${ARG_LINK_INTERFACE})
    endif()
  endforeach()
endfunction()

macro(pk_project_setup)
  set(_pk_one_value_args CXX_STANDARD C_STANDARD LIBRARY_TYPE)
  cmake_parse_arguments(_PK "" "${_pk_one_value_args}" "" ${ARGN})

  pk_project_prefix(PK_PREFIX)

  if(PROJECT_SOURCE_DIR STREQUAL PROJECT_BINARY_DIR)
    message(FATAL_ERROR
      "In-source builds are not supported, please use a build directory")
  endif()

  if(NOT CMAKE_CXX_COMPILER_ID MATCHES "^(GNU|Clang|AppleClang|IntelLLVM|MSVC)$")
    message(FATAL_ERROR
      "This project requires a mainstream compiler; found: "
      "${CMAKE_CXX_COMPILER_ID}")
  endif()

  option(${PK_PREFIX}_BUILD_APPS "Build ${PROJECT_NAME} applications"
    ${PROJECT_IS_TOP_LEVEL})
  option(${PK_PREFIX}_BUILD_TESTS "Build ${PROJECT_NAME} tests"
    ${PROJECT_IS_TOP_LEVEL})
  option(${PK_PREFIX}_INSTALL "Generate ${PROJECT_NAME} install rules"
    ${PROJECT_IS_TOP_LEVEL})
  option(${PK_PREFIX}_WERROR "Treat warnings as errors" OFF)

  set(${PK_PREFIX}_LIBRARY_TYPE "${_PK_LIBRARY_TYPE}" CACHE STRING
    "Library artifacts to build: STATIC, SHARED, STATIC+SHARED, NONE, or empty to follow BUILD_SHARED_LIBS")
  set_property(CACHE ${PK_PREFIX}_LIBRARY_TYPE
    PROPERTY STRINGS "" STATIC SHARED "STATIC+SHARED" NONE)

  if(NOT ${PK_PREFIX}_LIBRARY_TYPE)
    if(BUILD_SHARED_LIBS)
      set(${PK_PREFIX}_LIBRARY_TYPE SHARED)
    else()
      set(${PK_PREFIX}_LIBRARY_TYPE STATIC)
    endif()
    set(${PK_PREFIX}_LIBRARY_TYPE_FOLLOWS_BUILD_SHARED_LIBS TRUE)
  endif()

  if(NOT ${PK_PREFIX}_LIBRARY_TYPE MATCHES "^(STATIC|SHARED|STATIC\\+SHARED|NONE)$")
    message(FATAL_ERROR
      "${PK_PREFIX}_LIBRARY_TYPE must be STATIC, SHARED, STATIC+SHARED or "
      "NONE, not '${${PK_PREFIX}_LIBRARY_TYPE}'")
  endif()

  if(NOT _PK_CXX_STANDARD)
    set(_PK_CXX_STANDARD 23)
  endif()
  if(NOT _PK_C_STANDARD)
    set(_PK_C_STANDARD 23)
  endif()

  set(${PK_PREFIX}_CXX_STANDARD "${_PK_CXX_STANDARD}" CACHE STRING
    "C++ standard the project requires")
  set_property(CACHE ${PK_PREFIX}_CXX_STANDARD PROPERTY STRINGS 17 20 23 26)
  set(${PK_PREFIX}_C_STANDARD "${_PK_C_STANDARD}" CACHE STRING
    "C standard the project requires")
  set_property(CACHE ${PK_PREFIX}_C_STANDARD PROPERTY STRINGS 17 20 23 26)

  if(CMAKE_CXX_STANDARD)
    set(${PK_PREFIX}_CXX_STANDARD ${CMAKE_CXX_STANDARD})
  else()
    set(CMAKE_CXX_STANDARD ${${PK_PREFIX}_CXX_STANDARD})
  endif()
  if(CMAKE_C_STANDARD)
    set(${PK_PREFIX}_C_STANDARD ${CMAKE_C_STANDARD})
  else()
    set(CMAKE_C_STANDARD ${${PK_PREFIX}_C_STANDARD})
  endif()

  if(NOT ${PK_PREFIX}_CXX_STANDARD MATCHES "^(17|20|23|26)$")
    message(FATAL_ERROR
      "${PK_PREFIX}_CXX_STANDARD must be 17, 20, 23 or 26, not "
      "'${${PK_PREFIX}_CXX_STANDARD}'")
  endif()
  if(NOT ${PK_PREFIX}_C_STANDARD MATCHES "^(17|20|23|26)$")
    message(FATAL_ERROR
      "${PK_PREFIX}_C_STANDARD must be 17, 20, 23 or 26, not "
      "'${${PK_PREFIX}_C_STANDARD}'")
  endif()

  set(CMAKE_CXX_STANDARD_REQUIRED ON)
  set(CMAKE_CXX_EXTENSIONS OFF)
  set(CMAKE_CXX_SCAN_FOR_MODULES OFF)
  set(CMAKE_C_STANDARD_REQUIRED ON)
  set(CMAKE_C_EXTENSIONS OFF)

  set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${PROJECT_BINARY_DIR}/bin")
  set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${PROJECT_BINARY_DIR}/lib")
  set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY "${PROJECT_BINARY_DIR}/lib")

  if(CMAKE_CROSSCOMPILING)
    set(CMAKE_INSTALL_RPATH_USE_LINK_PATH FALSE)
    set(CMAKE_BUILD_WITH_INSTALL_RPATH TRUE)
    set(CMAKE_INSTALL_RPATH "$ORIGIN/../${CMAKE_INSTALL_LIBDIR}")
  else()
    set(CMAKE_INSTALL_RPATH_USE_LINK_PATH TRUE)
    if(APPLE)
      set(CMAKE_INSTALL_RPATH "@loader_path/../${CMAKE_INSTALL_LIBDIR}")
    else()
      set(CMAKE_INSTALL_RPATH "$ORIGIN/../${CMAKE_INSTALL_LIBDIR}")
    endif()
  endif()

  pk_add_warnings_target()
  pk_add_options_target()
  pk_setup_static_analysis()
  pk_setup_tooling()

  pk_set_state(DEFAULT_LINKS
    "${PROJECT_NAME}::warnings" "${PROJECT_NAME}::options")
endmacro()

function(pk_check_shared_intent)
  pk_project_prefix(prefix)

  if(NOT CMAKE_TOOLCHAIN_FILE
      OR NOT ${prefix}_LIBRARY_TYPE_FOLLOWS_BUILD_SHARED_LIBS)
    return()
  endif()

  cmake_path(GET CMAKE_TOOLCHAIN_FILE PARENT_PATH generators_dir)
  set(intent "${generators_dir}/${PROJECT_NAME}_intent.cmake")

  if(NOT EXISTS "${intent}")
    return()
  endif()

  include("${intent}")

  if(BUILD_SHARED_LIBS)
    set(cached_shared ON)
  else()
    set(cached_shared OFF)
  endif()

  if(NOT cached_shared STREQUAL ${prefix}_TOOLCHAIN_SHARED)
    message(FATAL_ERROR
      "Conan was last run with shared=${${prefix}_TOOLCHAIN_SHARED}, but this "
      "build tree is already configured with BUILD_SHARED_LIBS="
      "${cached_shared}. CMake never overwrites a cached BUILD_SHARED_LIBS "
      "causing wrong library binaries. Delete ${PROJECT_BINARY_DIR} and "
      "configure again.")
  endif()
endfunction()
