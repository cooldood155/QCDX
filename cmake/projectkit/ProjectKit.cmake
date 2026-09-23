include_guard(GLOBAL)

set(PK_MODULE_DIR "${CMAKE_CURRENT_LIST_DIR}" CACHE INTERNAL
  "Directory holding the ProjectKit modules and templates.")

include(GNUInstallDirs)
include(CMakePackageConfigHelpers)

include("${CMAKE_CURRENT_LIST_DIR}/ProjectSetup.cmake")
include("${CMAKE_CURRENT_LIST_DIR}/CompilerWarnings.cmake")
include("${CMAKE_CURRENT_LIST_DIR}/ProjectOptions.cmake")
include("${CMAKE_CURRENT_LIST_DIR}/StaticAnalysis.cmake")
include("${CMAKE_CURRENT_LIST_DIR}/Tooling.cmake")
include("${CMAKE_CURRENT_LIST_DIR}/HostTools.cmake")
include("${CMAKE_CURRENT_LIST_DIR}/FileCollection.cmake")
include("${CMAKE_CURRENT_LIST_DIR}/LibraryCreator.cmake")
include("${CMAKE_CURRENT_LIST_DIR}/ApplicationCreator.cmake")
include("${CMAKE_CURRENT_LIST_DIR}/TestCreator.cmake")
include("${CMAKE_CURRENT_LIST_DIR}/ToolCreator.cmake")
include("${CMAKE_CURRENT_LIST_DIR}/Packaging.cmake")
