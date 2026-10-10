cmake_minimum_required(VERSION 3.25)
project(qcdx_test_package LANGUAGES NONE)

find_package(QCDX REQUIRED CONFIG)
include(ProjectKit)

if(NOT COMMAND pk_create_library)
  message(FATAL_ERROR "include(ProjectKit) did not define pk_create_library")
endif()
message(STATUS "qcdx test_package: QCDX ${QCDX_VERSION} from ${QCDX_MODULE_DIR}")
