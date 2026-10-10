cmake_minimum_required(VERSION 3.30)

list(APPEND CMAKE_MODULE_PATH
  "${CMAKE_CURRENT_LIST_DIR}/cmake/projectkit"
  "${CMAKE_CURRENT_LIST_DIR}/cmake")

include(ConanBuildDir)

pk_require_conan_build_dir(
  OUT_BUILD_TYPE QCDX_BUILD_TYPE
  OUT_DIR        qcdx_conan_dir)

set(CONAN_BUILD_DIR "${qcdx_conan_dir}" CACHE INTERNAL
  "Conan's binary output path for the current configuration / build type.")

project(qcdx
  VERSION     0.1.0
  DESCRIPTION "Template project built on ProjectKit"
  LANGUAGES   C CXX)

include(ProjectKit)

pk_project_setup(CXX_STANDARD 23 C_STANDARD 23)
pk_check_shared_intent()
pk_require_host_tools()

if(NOT CMAKE_CROSSCOMPILING)
  add_subdirectory(tools)
endif()

if(NOT QCDX_LIBRARY_TYPE STREQUAL "NONE")
  add_subdirectory(src)
endif()

if(QCDX_BUILD_APPS)
  add_subdirectory(apps)
endif()

if(QCDX_BUILD_TESTS OR NOT QCDX_FUZZER STREQUAL "off")
  enable_testing()
endif()

if(QCDX_BUILD_TESTS)
  add_subdirectory(tests)
endif()

if(QCDX_INSTALL AND NOT QCDX_LIBRARY_TYPE STREQUAL "NONE")
  pk_install_package(INTERFACE_TARGETS qcdx_warnings qcdx_options)
endif()

pk_link_compile_commands()

pk_enable_cpack()
