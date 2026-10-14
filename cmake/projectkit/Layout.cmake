include_guard(GLOBAL)

# The project tree: where each part of the project lives. A project without
# .pk/tree.conf has the classic tree; one with it reads every part from it.
# The Python side (scripts/pklib/tree.py) writes and reads the same file and
# keeps the same defaults (a test checks they agree).

set(PK_TREE_DEFAULTS
  "kit=cmake/projectkit"
  "scripts=scripts"
  "helpers=scripts/helpers"
  "profiles=profiles"
  "toolchains=cmake/toolchains"
  "cmake=cmake"
  "headers=include"
  "sources=src"
  "apps=apps"
  "tests=tests"
  "tools=tools")

# Reads .pk/tree.conf of the project at ROOT once per configuration; parts
# are kept as global properties keyed by that root, so subprojects each keep
# their own tree.
function(_pk_tree_load ROOT)
  get_property(loaded GLOBAL PROPERTY "PK_TREE_LOADED:${ROOT}" SET)
  if(loaded)
    return()
  endif()
  set_property(GLOBAL PROPERTY "PK_TREE_LOADED:${ROOT}" TRUE)

  foreach(entry IN LISTS PK_TREE_DEFAULTS)
    string(REPLACE "=" ";" pair "${entry}")
    list(GET pair 0 part)
    list(GET pair 1 path)
    set_property(GLOBAL PROPERTY "PK_TREE:${ROOT}:${part}" "${path}")
  endforeach()
  set_property(GLOBAL PROPERTY "PK_TREE_OMIT:${ROOT}" "")

  set(file "${ROOT}/.pk/tree.conf")
  if(NOT EXISTS "${file}")
    return()
  endif()
  set_property(DIRECTORY "${ROOT}" APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${file}")

  file(STRINGS "${file}" lines)
  foreach(line IN LISTS lines)
    string(REGEX REPLACE "[ \t]#.*$" "" line "${line}")
    string(STRIP "${line}" line)
    if(line STREQUAL "" OR line MATCHES "^#")
      continue()
    endif()
    if(NOT line MATCHES "^(export[ \t]+)?(PK_TREE_)?([A-Za-z][A-Za-z0-9_-]*)[ \t]*=[ \t]*(.*)$")
      message(FATAL_ERROR
        "pk tree: ${file}: expected 'part = path', got '${line}'. Run "
        "'pk tree check' (or 'pk tree reset' to go back to the last tree that "
        "worked).")
    endif()
    string(TOLOWER "${CMAKE_MATCH_3}" part)
    string(REPLACE "_" "-" part "${part}")
    set(value "${CMAKE_MATCH_4}")
    string(REGEX REPLACE "^[\"']|[\"']$" "" value "${value}")
    string(STRIP "${value}" value)
    if(part STREQUAL "omit")
      string(REPLACE "," " " value "${value}")
      separate_arguments(value UNIX_COMMAND "${value}")
      set_property(GLOBAL PROPERTY "PK_TREE_OMIT:${ROOT}" "${value}")
    else()
      string(REGEX REPLACE "/+$" "" value "${value}")
      set_property(GLOBAL PROPERTY "PK_TREE:${ROOT}:${part}" "${value}")
    endif()
  endforeach()
endfunction()

# pk_tree_dir(<out-var> <part> [ROOT <dir>])
#   The absolute folder of a part (kit, helpers, profiles, toolchains, cmake,
#   headers, sources, apps, tests, tools) of the current project.
function(pk_tree_dir OUT_VAR PART)
  cmake_parse_arguments(ARG "" "ROOT" "" ${ARGN})
  if(NOT ARG_ROOT)
    set(ARG_ROOT "${PROJECT_SOURCE_DIR}")
  endif()
  _pk_tree_load("${ARG_ROOT}")
  get_property(path GLOBAL PROPERTY "PK_TREE:${ARG_ROOT}:${PART}")
  if(path STREQUAL "")
    message(FATAL_ERROR "pk_tree_dir (func): '${PART}' is not a part of the tree.")
  endif()
  set(${OUT_VAR} "${ARG_ROOT}/${path}" PARENT_SCOPE)
endfunction()

# pk_tree_has(<out-var> <part> [ROOT <dir>])
#   TRUE unless the tree leaves the part out ('omit = ...').
function(pk_tree_has OUT_VAR PART)
  cmake_parse_arguments(ARG "" "ROOT" "" ${ARGN})
  if(NOT ARG_ROOT)
    set(ARG_ROOT "${PROJECT_SOURCE_DIR}")
  endif()
  _pk_tree_load("${ARG_ROOT}")
  get_property(omit GLOBAL PROPERTY "PK_TREE_OMIT:${ARG_ROOT}")
  if(PART IN_LIST omit)
    set(${OUT_VAR} FALSE PARENT_SCOPE)
  else()
    set(${OUT_VAR} TRUE PARENT_SCOPE)
  endif()
endfunction()

# pk_tree_base_dir(<out-var> <part> <dir>)
#   The FILE_SET base of <dir>: the part's folder when <dir> is it or inside
#   it (include/<name>/x.hpp installs as <name>/x.hpp, as always), otherwise
#   the parent of <dir>, which keeps the last folder name in installed paths.
function(pk_tree_base_dir OUT_VAR PART DIR)
  pk_tree_dir(part_dir ${PART})
  cmake_path(IS_PREFIX part_dir "${DIR}" NORMALIZE inside)
  if(inside)
    set(${OUT_VAR} "${part_dir}" PARENT_SCOPE)
  else()
    cmake_path(GET DIR PARENT_PATH parent)
    set(${OUT_VAR} "${parent}" PARENT_SCOPE)
  endif()
endfunction()
