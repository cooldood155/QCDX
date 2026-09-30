# Answers queries about CMakePresets.json from pk.sh, the shell  is never
# required to parse JSON. Every result is printed as a "-- pk|<payload>" line.
#
#   cmake -DPK_QUERY=dirs -DPK_PRESET=native-debug -P presets.cmake
#   cmake -DPK_QUERY=configure-presets -P presets.cmake
#   cmake -DPK_QUERY=test-presets -P presets.cmake
#
# Paths come back relative to the source directory, "${sourceDir}/" is
# stripped; no-need to convert a paths back-and-forth.

cmake_minimum_required(VERSION 3.25)

if(NOT DEFINED PK_PRESETS_FILE)
  set(PK_PRESETS_FILE "CMakePresets.json")
endif()

if(NOT EXISTS "${PK_PRESETS_FILE}")
  message(STATUS "pk|missing")
  return()
endif()

file(READ "${PK_PRESETS_FILE}" pk_json)

function(pk_status text)
  message(STATUS "pk|${text}")
endfunction()

function(pk_length out)
  string(JSON length ERROR_VARIABLE error LENGTH "${pk_json}" ${ARGN})
  if(error)
    set(length 0)
  endif()
  set(${out} "${length}" PARENT_SCOPE)
endfunction()

function(pk_find section name out)
  set(${out} -1 PARENT_SCOPE)
  pk_length(length "${section}")
  if(length EQUAL 0)
    return()
  endif()

  math(EXPR last "${length} - 1")
  foreach(index RANGE ${last})
    string(JSON candidate GET "${pk_json}" "${section}" ${index} name)
    if(candidate STREQUAL name)
      set(${out} ${index} PARENT_SCOPE)
      return()
    endif()
  endforeach()
endfunction()

# Preset's own 'field' value OR the first one found depth first through
# 'inherits' in the same order as CMake.
function(pk_resolve name field out)
  set(${out} "" PARENT_SCOPE)
  pk_find(configurePresets "${name}" index)
  if(index EQUAL -1)
    return()
  endif()

  string(JSON value ERROR_VARIABLE error
    GET "${pk_json}" configurePresets ${index} "${field}")
  if(NOT error)
    set(${out} "${value}" PARENT_SCOPE)
    return()
  endif()

  string(JSON kind ERROR_VARIABLE error
    TYPE "${pk_json}" configurePresets ${index} inherits)
  if(error)
    return()
  endif()

  set(parents "")
  if(kind STREQUAL "STRING")
    string(JSON parents GET "${pk_json}" configurePresets ${index} inherits)
  elseif(kind STREQUAL "ARRAY")
    pk_length(count configurePresets ${index} inherits)
    if(count GREATER 0)
      math(EXPR last "${count} - 1")
      foreach(position RANGE ${last})
        string(JSON parent GET "${pk_json}" configurePresets ${index} inherits ${position})
        list(APPEND parents "${parent}")
      endforeach()
    endif()
  endif()

  foreach(parent IN LISTS parents)
    pk_resolve("${parent}" "${field}" inherited)
    if(NOT inherited STREQUAL "")
      set(${out} "${inherited}" PARENT_SCOPE)
      return()
    endif()
  endforeach()
endfunction()

function(pk_expand text preset out)
  string(REPLACE "\${sourceDir}/" "" text "${text}")
  string(REPLACE "\${sourceDir}" "." text "${text}")
  string(REPLACE "\${presetName}" "${preset}" text "${text}")
  set(${out} "${text}" PARENT_SCOPE)
endfunction()

function(pk_list_names section)
  pk_length(length "${section}")
  if(length EQUAL 0)
    return()
  endif()

  math(EXPR last "${length} - 1")
  foreach(index RANGE ${last})
    string(JSON hidden ERROR_VARIABLE error
      GET "${pk_json}" "${section}" ${index} hidden)
    if(NOT error AND hidden)
      continue()
    endif()
    string(JSON name GET "${pk_json}" "${section}" ${index} name)
    pk_status("${name}")
  endforeach()
endfunction()

if(PK_QUERY STREQUAL "dirs")
  pk_find(configurePresets "${PK_PRESET}" index)
  if(index EQUAL -1)
    pk_status("missing")
    return()
  endif()

  pk_resolve("${PK_PRESET}" binaryDir binary_dir)
  pk_resolve("${PK_PRESET}" toolchainFile toolchain)
  pk_expand("${binary_dir}" "${PK_PRESET}" binary_dir)
  pk_expand("${toolchain}" "${PK_PRESET}" toolchain)
  pk_status("binary|${binary_dir}")
  pk_status("toolchain|${toolchain}")
elseif(PK_QUERY STREQUAL "configure-presets")
  pk_list_names(configurePresets)
elseif(PK_QUERY STREQUAL "test-presets")
  pk_list_names(testPresets)
else()
  message(FATAL_ERROR "presets.cmake: unknown PK_QUERY '${PK_QUERY}'")
endif()
