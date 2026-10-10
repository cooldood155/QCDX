# The QCDX kit (ProjectKit) as a CMake package. Projects made with 'pk new'
# vendor the kit and never need this; it is for using ProjectKit modules in an
# existing CMake project:
#
#   cmake -S . -B build && cmake --install build --prefix /usr/local
#   find_package(QCDX 0.1 REQUIRED)        # in the consuming project
#   include(ProjectKit)
#
# or without installing anything (CMake 3.24+):
#
#   include(FetchContent)
#   FetchContent_Declare(qcdx URL <release qcdx-X.Y.Z.tar.gz> URL_HASH SHA256=...)
#   FetchContent_MakeAvailable(qcdx)
#   find_package(QCDX 0.1 REQUIRED)
#   include(ProjectKit)

cmake_minimum_required(VERSION 3.25)

file(STRINGS "${CMAKE_CURRENT_LIST_DIR}/cmake/projectkit/VERSION" _qcdx_version LIMIT_COUNT 1)

project(QCDX
  VERSION       ${_qcdx_version}
  DESCRIPTION   "ProjectKit: CMake modules and scripts for C and C++ projects"
  HOMEPAGE_URL  "https://github.com/cooldood155/QCDX"
  LANGUAGES     NONE)

# Added by FetchContent or add_subdirectory: point find_package(QCDX) at this
# tree. QCDX_DIR is what find_package checks first; the redirect file serves
# FetchContent_Declare(... FIND_PACKAGE_ARGS) and OVERRIDE_FIND_PACKAGE.
if(NOT PROJECT_IS_TOP_LEVEL)
  set(QCDX_DIR "${CMAKE_CURRENT_SOURCE_DIR}/cmake" CACHE PATH "QCDX package configuration" FORCE)
  if(CMAKE_FIND_PACKAGE_REDIRECTS_DIR)
    file(WRITE "${CMAKE_FIND_PACKAGE_REDIRECTS_DIR}/qcdx-extra.cmake"
      "include(\"${CMAKE_CURRENT_SOURCE_DIR}/cmake/QCDXConfig.cmake\")\n")
    file(WRITE "${CMAKE_FIND_PACKAGE_REDIRECTS_DIR}/qcdx-extra-version.cmake"
      "include(\"${CMAKE_CURRENT_SOURCE_DIR}/cmake/QCDXConfigVersion.cmake\")\n")
  endif()
  return()
endif()

# <prefix>/share/qcdx/cmake/ is on find_package's default search path.
# GNUInstallDirs is not used: it needs a language enabled, only share/ matters.
set(QCDX_INSTALL_CMAKEDIR "share/qcdx/cmake" CACHE STRING
  "Where QCDXConfig.cmake and projectkit/ are installed, relative to the prefix")

install(DIRECTORY cmake/projectkit
  DESTINATION "${QCDX_INSTALL_CMAKEDIR}"
  USE_SOURCE_PERMISSIONS
  PATTERN "__pycache__" EXCLUDE
  PATTERN "*.pyc" EXCLUDE)

install(FILES cmake/QCDXConfig.cmake cmake/QCDXConfigVersion.cmake
  DESTINATION "${QCDX_INSTALL_CMAKEDIR}")
