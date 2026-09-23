cmake_minimum_required(VERSION 3.30)

project(pk_test_package LANGUAGES CXX)

if(NOT PK_TESTED_PACKAGE)
  message(FATAL_ERROR
    "PK_TESTED_PACKAGE was not set; run this through 'conan create', not "
    "directly.")
endif()

find_package(${PK_TESTED_PACKAGE} REQUIRED)

if(NOT PK_TEST_SOURCE)
  set(PK_TEST_SOURCE "${CMAKE_CURRENT_LIST_DIR}/src/example.cpp")
endif()

if(NOT EXISTS "${PK_TEST_SOURCE}")
  message(FATAL_ERROR "PK_TEST_SOURCE does not exist: ${PK_TEST_SOURCE}")
endif()

add_executable(test_package "${PK_TEST_SOURCE}")

target_link_libraries(test_package PRIVATE
  ${PK_TESTED_PACKAGE}::${PK_TESTED_PACKAGE})
