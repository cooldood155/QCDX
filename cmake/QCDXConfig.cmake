# find_package(QCDX) puts ProjectKit on the module path:
#
#   find_package(QCDX 0.1 REQUIRED)
#   include(ProjectKit)
#
# The same file works installed (share/qcdx/cmake), inside the Python package
# ('pk cmake-dir') and in a source tree or FetchContent download (cmake/), since
# everything is found relative to this file.

get_filename_component(QCDX_MODULE_DIR "${CMAKE_CURRENT_LIST_DIR}/projectkit" ABSOLUTE)
file(STRINGS "${QCDX_MODULE_DIR}/VERSION" QCDX_VERSION LIMIT_COUNT 1)

if(NOT QCDX_MODULE_DIR IN_LIST CMAKE_MODULE_PATH)
  list(APPEND CMAKE_MODULE_PATH "${QCDX_MODULE_DIR}")
endif()

set(QCDX_FOUND TRUE)
