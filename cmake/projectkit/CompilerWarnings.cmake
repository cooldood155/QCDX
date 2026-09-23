include_guard(GLOBAL)

function(pk_add_warnings_target)
  pk_project_prefix(prefix)
  set(target "${PROJECT_NAME}_warnings")

  add_library(${target} INTERFACE)
  add_library(${PROJECT_NAME}::warnings ALIAS ${target})
  set_target_properties(${target} PROPERTIES EXPORT_NAME warnings)

  set(gnu_like
    -Wall
    -Wextra
    -Wpedantic
    -Wshadow
    -Wnon-virtual-dtor
    -Wold-style-cast
    -Wcast-align
    -Wsign-conversion
    -Wnull-dereference
    -Wdouble-promotion
    -Wformat=2
    -Wimplicit-fallthrough)

  set(msvc_like
    /W4
    /permissive-
    /w14640
    /w14826)

  target_compile_options(${target} INTERFACE
    "$<$<COMPILE_LANG_AND_ID:CXX,GNU,Clang,AppleClang,IntelLLVM>:${gnu_like}>"
    "$<$<COMPILE_LANG_AND_ID:CXX,MSVC>:${msvc_like}>")

  if(${prefix}_WERROR)
    target_compile_options(${target} INTERFACE
      "$<$<COMPILE_LANG_AND_ID:CXX,GNU,Clang,AppleClang,IntelLLVM>:-Werror>"
      "$<$<COMPILE_LANG_AND_ID:CXX,MSVC>:/WX>")
  endif()
endfunction()
