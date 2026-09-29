include_guard(GLOBAL)

function(pk_add_warnings_target)
  pk_project_prefix(prefix)
  set(target "${PROJECT_NAME}_warnings")

  add_library(${target} INTERFACE)
  add_library(${PROJECT_NAME}::warnings ALIAS ${target})
  set_target_properties(${target} PROPERTIES EXPORT_NAME warnings)

  set(gnu_ids "GNU,Clang,AppleClang,IntelLLVM")

  set(gnu_common
    -Wall
    -Wextra
    -Wpedantic
    -Wshadow
    -Wcast-align
    -Wsign-conversion
    -Wnull-dereference
    -Wdouble-promotion
    -Wformat=2
    -Wimplicit-fallthrough)

  set(gnu_c ${gnu_common}
    -Wstrict-prototypes
    -Wmissing-prototypes)

  set(gnu_cxx ${gnu_common}
    -Wnon-virtual-dtor
    -Wold-style-cast)

  set(msvc_c
    /W4
    /w14826)

  set(msvc_cxx ${msvc_c}
    /permissive-
    /w14640)

  target_compile_options(${target} INTERFACE
    "$<$<COMPILE_LANG_AND_ID:C,${gnu_ids}>:${gnu_c}>"
    "$<$<COMPILE_LANG_AND_ID:CXX,${gnu_ids}>:${gnu_cxx}>"
    "$<$<COMPILE_LANG_AND_ID:C,MSVC>:${msvc_c}>"
    "$<$<COMPILE_LANG_AND_ID:CXX,MSVC>:${msvc_cxx}>")

  if(${prefix}_WERROR)
    target_compile_options(${target} INTERFACE
      "$<$<COMPILE_LANG_AND_ID:C,${gnu_ids}>:-Werror>"
      "$<$<COMPILE_LANG_AND_ID:CXX,${gnu_ids}>:-Werror>"
      "$<$<COMPILE_LANG_AND_ID:C,MSVC>:/WX>"
      "$<$<COMPILE_LANG_AND_ID:CXX,MSVC>:/WX>")
  endif()
endfunction()
