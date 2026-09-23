set(CMAKE_SYSTEM_NAME      Windows)
set(CMAKE_SYSTEM_PROCESSOR aarch64)

set(QCDX_TARGET_TRIPLE aarch64-w64-mingw32)

# llvm-mingw, not MinGW-w64 GCC: there is no aarch64-w64-mingw32 GCC. The
# -gcc/-g++ names do exist in llvm-mingw as wrappers around clang, but naming
# clang directly keeps this file honest about what it is invoking.
find_program(CMAKE_C_COMPILER   ${QCDX_TARGET_TRIPLE}-clang   REQUIRED)
find_program(CMAKE_CXX_COMPILER ${QCDX_TARGET_TRIPLE}-clang++ REQUIRED)
find_program(CMAKE_RC_COMPILER  ${QCDX_TARGET_TRIPLE}-windres)

# llvm-mingw ships llvm-ar/llvm-ranlib/llvm-strip under the plain triple
# names. It does NOT ship -gcc-ar or -gcc-ranlib, so asking for those yields
# CMAKE_AR-NOTFOUND and static archives fail at link time with an error that
# points nowhere near this file.
find_program(CMAKE_AR           ${QCDX_TARGET_TRIPLE}-ar      REQUIRED)
find_program(CMAKE_RANLIB       ${QCDX_TARGET_TRIPLE}-ranlib  REQUIRED)
find_program(CMAKE_STRIP        ${QCDX_TARGET_TRIPLE}-strip)

if(EXISTS "/usr/${QCDX_TARGET_TRIPLE}")
  list(APPEND CMAKE_FIND_ROOT_PATH "/usr/${QCDX_TARGET_TRIPLE}")
endif()

set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY BOTH)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE BOTH)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE BOTH)
