set(CMAKE_SYSTEM_NAME      Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)

set(QCDX_TARGET_TRIPLE aarch64-linux-gnu)

find_program(CMAKE_C_COMPILER   ${QCDX_TARGET_TRIPLE}-gcc)
find_program(CMAKE_CXX_COMPILER ${QCDX_TARGET_TRIPLE}-g++)

if(NOT CMAKE_C_COMPILER OR NOT CMAKE_CXX_COMPILER)
  set(helpful_hint "install a cross toolchain providing ${QCDX_TARGET_TRIPLE}-gcc and -g++")

  if(CMAKE_HOST_WIN32)
    set(helpful_hint
      "no ${QCDX_TARGET_TRIPLE} toolchain is packaged for MSYS2. Use ARM's or "
      "Linaro's Windows-host GNU toolchain and put its bin/ on PATH, or cross-compile "
      "in a container or WSL")
  elseif(CMAKE_HOST_APPLE)
    set(helpful_hint "on macOS use a container; Homebrew has no ${QCDX_TARGET_TRIPLE} GCC")
  elseif(CMAKE_HOST_UNIX)
    set(helpful_hint "on Debian/Ubuntu: sudo apt install gcc-aarch64-linux-gnu g++-aarch64-linux-gnu")
  endif()

  message(FATAL_ERROR
    "Cannot cross-compile for ${QCDX_TARGET_TRIPLE}: compiler not found on PATH.\n"
    "${helpful_hint}")
endif()

find_program(CMAKE_AR           ${QCDX_TARGET_TRIPLE}-gcc-ar)
find_program(CMAKE_RANLIB       ${QCDX_TARGET_TRIPLE}-gcc-ranlib)
find_program(CMAKE_STRIP        ${QCDX_TARGET_TRIPLE}-strip)
find_program(CMAKE_OBJCOPY      ${QCDX_TARGET_TRIPLE}-objcopy)

if(CMAKE_SYSROOT)
  list(APPEND CMAKE_FIND_ROOT_PATH "${CMAKE_SYSROOT}")
endif()

set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY BOTH)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE BOTH)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE BOTH)
