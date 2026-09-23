include_guard(GLOBAL)

include(CheckCXXCompilerFlag)
include(CheckLinkerFlag)
include(CheckIPOSupported)

function(pk_try_compile_option target condition flag)
  string(MAKE_C_IDENTIFIER "${PROJECT_NAME}_has_c_${flag}" probe)
  check_cxx_compiler_flag("${flag}" ${probe})

  if(${probe})
    target_compile_options(${target} INTERFACE "$<${condition}:${flag}>")
  endif()
endfunction()

function(pk_try_link_option target condition flag)
  string(MAKE_C_IDENTIFIER "${PROJECT_NAME}_has_l_${flag}" probe)
  check_linker_flag(CXX "${flag}" ${probe})

  if(${probe})
    target_link_options(${target} INTERFACE "$<${condition}:${flag}>")
  endif()
endfunction()

macro(pk_add_options_target)
  pk_project_prefix(PK_PREFIX)
  set(_pk_target "${PROJECT_NAME}_options")

  set(${PK_PREFIX}_SANITIZE "" CACHE STRING
    "Comma-separated sanitizers to build with, e.g. address, undefined, or thread; address, thread, leak, memory, and undefined are the sanitizers")

  option(${PK_PREFIX}_HARDENING    "Compile and link with hardening flags"       ON)
  option(${PK_PREFIX}_COVERAGE     "Instrument for coverage"                     OFF)
  option(${PK_PREFIX}_REPRODUCIBLE "Strip build paths out of binaries"           OFF)
  option(${PK_PREFIX}_LTO          "Enable interprocedural optimization"         OFF)
  option(${PK_PREFIX}_CCACHE       "Use ccache or sccache when one is installed" ON)
  option(${PK_PREFIX}_REDUCE_SIZE  "Strip unecessary/dead code and unroll loops" ON)

  add_library(${_pk_target} INTERFACE)
  add_library(${PROJECT_NAME}::options ALIAS ${_pk_target})
  set_target_properties(${_pk_target} PROPERTIES EXPORT_NAME options)

  set(_pk_gnu_like "$<COMPILE_LANG_AND_ID:CXX,GNU,Clang,AppleClang,IntelLLVM>")
  set(_pk_msvc "$<COMPILE_LANG_AND_ID:CXX,MSVC>")

  if(CMAKE_CXX_COMPILER_FRONTEND_VARIANT STREQUAL "GNU")
    set(${PK_PREFIX}_COMPILER_LIKE_GNU ON CACHE INTERNAL "")
    set(${PK_PREFIX}_COMPILER_IS_MSVC OFF CACHE INTERNAL "")
    set(_pk_compiler "${_pk_gnu_like}")
  elseif(CMAKE_CXX_COMPILER_FRONTEND_VARIANT STREQUAL "MSVC")
    set(${PK_PREFIX}_COMPILER_LIKE_GNU OFF CACHE INTERNAL "")
    set(${PK_PREFIX}_COMPILER_IS_MSVC ON CACHE INTERNAL "")
    set(_pk_compiler "${_pk_msvc}")
  else()
    message(FATAL_ERROR
      "Unsupported compiler front-end: ${CMAKE_CXX_COMPILER_FRONTEND_VARIANT}")
  endif()

  if(${PK_PREFIX}_SANITIZE)
    string(REPLACE "," ";" _pk_sanitizer_list "${${PK_PREFIX}_SANITIZE}")

    foreach(_pk_sanitizer IN LISTS _pk_sanitizer_list)
      if(NOT _pk_sanitizer MATCHES "^(address|thread|leak|memory|undefined)$")
        message(FATAL_ERROR
          "${PK_PREFIX}_SANITIZE entries must be address, thread, leak, memory "
          "or undefined, NOT '${_pk_sanitizer}'")
      endif()

      if(${PK_PREFIX}_COMPILER_IS_MSVC AND NOT _pk_sanitizer STREQUAL "address")
        message(FATAL_ERROR
          "MSVC only natively supports the 'address' sanitizer. "
          "'${_pk_sanitizer}' is not supported")
      endif()
    endforeach()

    if("thread" IN_LIST _pk_sanitizer_list)
      foreach(_pk_conflict address leak memory)
        if("${_pk_conflict}" IN_LIST _pk_sanitizer_list)
          message(FATAL_ERROR
            "The thread sanitizer cannot be combined with ${_pk_conflict}")
        endif()
      endforeach()
    endif()

    if(${PK_PREFIX}_COMPILER_LIKE_GNU)
      set(_pk_sanitize_flag "-fsanitize=${${PK_PREFIX}_SANITIZE}")

      target_compile_options(${_pk_target} INTERFACE
        "$<${_pk_gnu_like}:${_pk_sanitize_flag}>"
        "$<${_pk_gnu_like}:-fno-omit-frame-pointer>"
        "$<${_pk_gnu_like}:-g>")
      target_link_options(${_pk_target} INTERFACE
        "$<${_pk_gnu_like}:${_pk_sanitize_flag}>")
    else()
      set(_pk_sanitize_flag "/fsanitize=address")

      target_compile_options(${_pk_target} INTERFACE
        "$<${_pk_msvc}:${_pk_sanitize_flag}>"
        "$<${_pk_msvc}:/Zi>"
        "$<${_pk_msvc}:/Oy->")
      target_link_options(${_pk_target} INTERFACE
        "$<${_pk_msvc}:${_pk_sanitize_flag}>"
        "$<${_pk_msvc}:/INCREMENTAL:NO>")
    endif()

    string(MAKE_C_IDENTIFIER
      "${PK_PREFIX}_HAS_SANITIZE_${${PK_PREFIX}_SANITIZE}" _pk_sanitize_probe)

    set(CMAKE_REQUIRED_LINK_OPTIONS "${_pk_sanitize_flag}")
    check_cxx_compiler_flag("${_pk_sanitize_flag}" ${_pk_sanitize_probe})
    unset(CMAKE_REQUIRED_LINK_OPTIONS)

    if(NOT ${_pk_sanitize_probe})
      if(MINGW AND CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
        message(FATAL_ERROR
          "Windows/MinGW has no sanitizer runtimes for Windows targets. "
          "Use Clang (pacman -S mingw-w64-ucrt-x86_64-clang) or build under WSL.")
      else()
        message(FATAL_ERROR
          "This toolchain cannot build with ${_pk_sanitize_flag}; the runtime "
          "library is probably not installed")
      endif()
    endif()

    if(${PK_PREFIX}_COMPILER_IS_MSVC)
      foreach(_pk_config RELEASE RELWITHDEBINFO MINSIZEREL)
        string(REPLACE "/O2" "/O2 /Oy-"
          CMAKE_CXX_FLAGS_${_pk_config} "${CMAKE_CXX_FLAGS_${_pk_config}}")
        string(REPLACE "/O1" "/O1 /Oy-"
          CMAKE_CXX_FLAGS_${_pk_config} "${CMAKE_CXX_FLAGS_${_pk_config}}")
        string(REPLACE "/Oy- /Oy-" "/Oy-"
          CMAKE_CXX_FLAGS_${_pk_config} "${CMAKE_CXX_FLAGS_${_pk_config}}")
      endforeach()
    endif()

    message(STATUS "${PROJECT_NAME}: sanitizers ${${PK_PREFIX}_SANITIZE}")
  endif()

  if(${PK_PREFIX}_HARDENING)
    if(${PK_PREFIX}_COMPILER_LIKE_GNU)
      pk_try_compile_option(${_pk_target} "${_pk_compiler}" -fstack-protector-strong)
      pk_try_compile_option(${_pk_target} "${_pk_compiler}" -fstack-clash-protection)
      pk_try_compile_option(${_pk_target} "${_pk_compiler}" -fcf-protection=full)
      pk_try_compile_option(${_pk_target} "${_pk_compiler}" -ftrivial-auto-var-init=zero)

      target_compile_definitions(${_pk_target} INTERFACE
        "$<${_pk_gnu_like}:_GLIBCXX_ASSERTIONS>")

      pk_try_link_option(${_pk_target} "${_pk_compiler}" LINKER:-z,relro)
      pk_try_link_option(${_pk_target} "${_pk_compiler}" LINKER:-z,now)
      pk_try_link_option(${_pk_target} "${_pk_compiler}" LINKER:-z,noexecstack)
    else()
      pk_try_compile_option(${_pk_target} "${_pk_compiler}" /GS)
      pk_try_compile_option(${_pk_target} "${_pk_compiler}" /guard:cf)
      pk_try_link_option(${_pk_target} "${_pk_compiler}" /guard:cf)
      pk_try_link_option(${_pk_target} "${_pk_compiler}" /NXCOMPAT)
      pk_try_link_option(${_pk_target} "${_pk_compiler}" /DYNAMICBASE)
      pk_try_compile_option(${_pk_target} "${_pk_compiler}" /initall)
      pk_try_link_option(${_pk_target} "${_pk_compiler}" /HIGHENTROPYVA)
    endif()

    if(NOT ${PK_PREFIX}_SANITIZE)
      target_compile_definitions(${_pk_target} INTERFACE
        "$<$<AND:${_pk_gnu_like},$<NOT:$<CONFIG:Debug>>>:_FORTIFY_SOURCE=3>")
      target_compile_definitions(${_pk_target} INTERFACE
        "$<$<AND:${_pk_msvc},$<NOT:$<CONFIG:Debug>>>:_SECURE_SCL=1>")
    endif()

    message(STATUS "${PROJECT_NAME}: hardening enabled")
  endif()

  if(${PK_PREFIX}_COVERAGE)
    if(${PK_PREFIX}_COMPILER_LIKE_GNU)
      target_compile_options(${_pk_target} INTERFACE
        "$<${_pk_gnu_like}:--coverage>"
        "$<${_pk_gnu_like}:-g>"
        "$<${_pk_gnu_like}:-O0>")
      target_link_options(${_pk_target} INTERFACE
        "$<${_pk_gnu_like}:--coverage>")
    else()
      target_compile_options(${_pk_target} INTERFACE
        "$<${_pk_msvc}:/Zi>"
        "$<${_pk_msvc}:/Od>")
      target_link_options(${_pk_target} INTERFACE
        "$<${_pk_msvc}:/DEBUG>")
    endif()

    message(STATUS "${PROJECT_NAME}: coverage instrumentation enabled")
  endif()

  if(${PK_PREFIX}_REPRODUCIBLE)
    if(${PK_PREFIX}_COMPILER_LIKE_GNU)
      pk_try_compile_option(${_pk_target} "${_pk_compiler}"
        "-ffile-prefix-map=${PROJECT_SOURCE_DIR}=.")
      pk_try_compile_option(${_pk_target} "${_pk_compiler}" -fno-ident)
    else()
      pk_try_compile_option(${_pk_target} "${_pk_compiler}"
        "/pathmap:${PROJECT_SOURCE_DIR}=.")
      pk_try_compile_option(${_pk_target} "${_pk_compiler}"
        "/experimental:deterministic")
      pk_try_link_option(${_pk_target} "${_pk_compiler}" "/PDBALTPATH:%_PDB%")
    endif()

    message(STATUS "${PROJECT_NAME}: build paths mapped out of binaries")
  endif()

  if(${PK_PREFIX}_LTO)
    check_ipo_supported(RESULT _pk_ipo_supported OUTPUT _pk_ipo_error)

    if(_pk_ipo_supported)
      set(CMAKE_INTERPROCEDURAL_OPTIMIZATION TRUE)
      message(STATUS
        "${PROJECT_NAME}: interprocedural optimization enabled")
    else()
      message(FATAL_ERROR
        "${PK_PREFIX}_LTO is on but this toolchain cannot do it: "
        "${_pk_ipo_error}")
    endif()
  endif()

  if(${PK_PREFIX}_CCACHE AND NOT CMAKE_CXX_COMPILER_LAUNCHER)
    find_program(${PK_PREFIX}_COMPILER_CACHE NAMES ccache sccache)

    if(${PK_PREFIX}_COMPILER_CACHE)
      set(CMAKE_CXX_COMPILER_LAUNCHER "${${PK_PREFIX}_COMPILER_CACHE}")
      message(STATUS
        "${PROJECT_NAME}: compiler cache ${${PK_PREFIX}_COMPILER_CACHE}")
    endif()
  endif()

  if(${PK_PREFIX}_REDUCE_SIZE)
    if(${PK_PREFIX}_COMPILER_LIKE_GNU)
      pk_try_link_option(${_pk_target} "${_pk_compiler}" "LINKER:--gc-sections")
      pk_try_compile_option(${_pk_target} "${_pk_compiler}" -ffunction-sections)
      pk_try_compile_option(${_pk_target} "${_pk_compiler}" -fdata-sections)
    else()
      pk_try_compile_option(${_pk_target} "${_pk_compiler}" /Gy)
      pk_try_link_option(${_pk_target} "${_pk_compiler}" /OPT:REF)
      pk_try_link_option(${_pk_target} "${_pk_compiler}" /OPT:ICF)
    endif()
  endif()
endmacro()
