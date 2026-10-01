include_guard(GLOBAL)

# deps.json is the source for third-party packages. Conan reads it in
# conanfile.py (what to install), this module reads it (what to find and link),
# and 'pk dep' edits it.
#
#   pk_deps_find(<name>...)       # find_package() exactly following deps.json
#   pk_deps_link(TARGETS <t>... ROLE <r> [PUBLIC <n>...] [PRIVATE <n>...]
#                [INTERFACE <n>...])   # find + link + check, used by DEPS_*
#   pk_deps_export_find_calls(<out> <targets>...)
#                                      # find_dependency() lines for installs
#
# Every configuration generates <build>/pk-deps-usage.json: which target uses
# which package, directly and through other targets. 'pk dep ls|why|tree' read
# from the pk-deps-usage.json file.
#
# Schema and rules documented at: cmake/projectkit/docs/PK_DEP.md.

set(PK_DEPS_KINDS requires test tool)

function(_pk_json_quote OUT_VAR value)
  string(REPLACE "\\" "\\\\" value "${value}")
  string(REPLACE "\"" "\\\"" value "${value}")
  set(${OUT_VAR} "\"${value}\"" PARENT_SCOPE)
endfunction()

# Reads one optional member; missing members give 'default'.
function(_pk_json_get OUT_VAR json default)
  string(JSON value ERROR_VARIABLE err GET "${json}" ${ARGN})
  if(err)
    set(value "${default}")
  endif()
  set(${OUT_VAR} "${value}" PARENT_SCOPE)
endfunction()

function(_pk_json_array OUT_VAR json)
  set(items "")
  string(JSON type ERROR_VARIABLE err TYPE "${json}" ${ARGN})
  if(NOT err)
    if(NOT type STREQUAL "ARRAY")
      string(JOIN "." where ${ARGN})
      message(FATAL_ERROR "deps.json: '${where}' must be an array of strings.")
    endif()

    string(JSON count LENGTH "${json}" ${ARGN})
    if(count GREATER 0)
      math(EXPR last "${count} - 1")
      foreach(i RANGE ${last})
        string(JSON item GET "${json}" ${ARGN} ${i})
        list(APPEND items "${item}")
      endforeach()
    endif()
  endif()

  set(${OUT_VAR} "${items}" PARENT_SCOPE)
endfunction()

function(_pk_deps_fail name message_text)
  pk_get_state(DEPS_MANIFEST manifest)
  message(FATAL_ERROR "${manifest}: package '${name}': ${message_text}")
endfunction()

# Loads and validates deps.json once per project. Called from pk_project_setup;
# a malformed manifest stops configuration.
function(_pk_deps_load)
  pk_get_state(DEPS_LOADED loaded)
  if(loaded)
    return()
  endif()
  pk_set_state(DEPS_LOADED TRUE)

  if(DEFINED PK_DEPS_MANIFEST)
    set(manifest "${PK_DEPS_MANIFEST}")
  else()
    set(manifest "${PROJECT_SOURCE_DIR}/deps.json")
  endif()
  pk_set_state(DEPS_MANIFEST "${manifest}")
  pk_set_state(DEPS_NAMES "")

  cmake_language(DEFER DIRECTORY "${PROJECT_SOURCE_DIR}"
    CALL _pk_deps_write_report "${PROJECT_NAME}")

  if(NOT EXISTS "${manifest}")
    pk_set_state(DEPS_HAVE_MANIFEST FALSE)
    return()
  endif()
  pk_set_state(DEPS_HAVE_MANIFEST TRUE)
  set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${manifest}")

  file(READ "${manifest}" json)
  string(JSON schema ERROR_VARIABLE err GET "${json}" schema)
  if(err)
    message(FATAL_ERROR "${manifest}: not valid JSON or no 'schema': ${err}")
  endif()
  if(NOT schema EQUAL 1)
    message(FATAL_ERROR "${manifest}: unsupported schema '${schema}', expected 1.")
  endif()

  string(JSON count ERROR_VARIABLE err LENGTH "${json}" packages)
  if(err)
    message(FATAL_ERROR "${manifest}: needs a 'packages' object: ${err}")
  endif()

  set(names "")
  set(all_targets "")
  if(count GREATER 0)
    math(EXPR last "${count} - 1")
    foreach(i RANGE ${last})
      string(JSON name MEMBER "${json}" packages ${i})
      if(NOT name MATCHES "^[a-z0-9_][a-z0-9_.+-]*$")
        _pk_deps_fail("${name}" "names are lowercase Conan package names.")
      endif()

      _pk_json_get(ref "${json}" "" packages "${name}" ref)
      string(FIND "${ref}" "${name}/" at)
      if(NOT at EQUAL 0)
        _pk_deps_fail("${name}" "'ref' must start with '${name}/', got '${ref}'.")
      endif()

      _pk_json_get(kind "${json}" "requires" packages "${name}" kind)
      if(NOT kind IN_LIST PK_DEPS_KINDS)
        string(JOIN ", " kinds ${PK_DEPS_KINDS})
        _pk_deps_fail("${name}" "'kind' is '${kind}', expected one of: ${kinds}.")
      endif()

      string(JSON cmake_type ERROR_VARIABLE err TYPE "${json}" packages "${name}" cmake)
      if(err)
        set(cmake_type "NULL")
      endif()

      set(pkg "")
      set(version "")
      set(components "")
      set(targets "")
      if(cmake_type STREQUAL "OBJECT")
        if(kind STREQUAL "tool")
          _pk_deps_fail("${name}" "tool packages run at build time and have no 'cmake' section.")
        endif()
        _pk_json_get(pkg "${json}" "" packages "${name}" cmake package)
        _pk_json_get(version "${json}" "" packages "${name}" cmake version)
        _pk_json_array(components "${json}" packages "${name}" cmake components)
        _pk_json_array(targets "${json}" packages "${name}" cmake targets)
        _pk_json_array(extra_targets "${json}" packages "${name}" cmake extra_targets)
        if(pkg STREQUAL "" OR NOT targets)
          _pk_deps_fail("${name}" "'cmake' needs 'package' and a non-empty 'targets' list "
            "(run 'pk dep set ${name} --discover' to fill them from Conan).")
        endif()
        foreach(t IN LISTS targets extra_targets)
          if(t IN_LIST all_targets)
            _pk_deps_fail("${name}" "CMake target '${t}' is claimed by two packages.")
          endif()
          list(APPEND all_targets "${t}")
          pk_set_state(DEPS_TARGET_OWNER_${t} "${name}")
        endforeach()
      elseif(cmake_type STREQUAL "BOOLEAN" OR cmake_type STREQUAL "NULL")
        if(NOT kind STREQUAL "tool")
          _pk_json_get(flag "${json}" "missing" packages "${name}" cmake)
          if(flag STREQUAL "missing")
            _pk_deps_fail("${name}" "needs a 'cmake' section, or \"cmake\": false for a "
              "package that is not used through find_package().")
          endif()
        endif()
      else()
        _pk_deps_fail("${name}" "'cmake' must be an object or false.")
      endif()

      _pk_json_get(transitive_headers "${json}" "OFF"
        packages "${name}" traits transitive_headers)

      pk_set_state(DEPS_${name}_REF "${ref}")
      pk_set_state(DEPS_${name}_KIND "${kind}")
      pk_set_state(DEPS_${name}_PACKAGE "${pkg}")
      pk_set_state(DEPS_${name}_VERSION "${version}")
      pk_set_state(DEPS_${name}_COMPONENTS "${components}")
      pk_set_state(DEPS_${name}_TARGETS "${targets}")
      pk_set_state(DEPS_${name}_TRANSITIVE_HEADERS "${transitive_headers}")
      list(APPEND names "${name}")
    endforeach()
  endif()

  pk_set_state(DEPS_NAMES "${names}")
endfunction()

function(_pk_deps_require name)
  _pk_deps_load()
  pk_get_state(DEPS_NAMES names)

  if(NOT name IN_LIST names)
    pk_get_state(DEPS_HAVE_MANIFEST have)
    pk_get_state(DEPS_MANIFEST manifest)
    if(NOT have)
      message(FATAL_ERROR
        "'${name}' is used as a dependency but there is no ${manifest}; "
        "create it with 'pk dep add <ref>'.")
    endif()

    string(REPLACE ";" ", " known "${names}")
    message(FATAL_ERROR
      "'${name}' is not in ${manifest} (known: ${known}). Add it with "
      "'pk dep add ${name}/<version-or-range>'.")
  endif()
endfunction()

# find_package() for manifest packages within the calling dir. Imported targets
# are directory scoped.
function(pk_deps_find)
  foreach(name IN LISTS ARGN)
    _pk_deps_require("${name}")
    pk_get_state(DEPS_${name}_KIND kind)
    pk_get_state(DEPS_${name}_PACKAGE pkg)
    pk_get_state(DEPS_${name}_VERSION version)
    pk_get_state(DEPS_${name}_COMPONENTS components)
    pk_get_state(DEPS_${name}_TARGETS targets)

    if(kind STREQUAL "tool")
      message(FATAL_ERROR
        "'${name}' is a tool dependency: it runs during the build and cannot "
        "be found or linked from CMake.")
    endif()
    if(pkg STREQUAL "")
      message(FATAL_ERROR
        "'${name}' has \"cmake\": false in deps.json, so CMake cannot find it.")
    endif()

    set(missing FALSE)
    foreach(t IN LISTS targets)
      if(NOT TARGET ${t})
        set(missing TRUE)
      endif()
    endforeach()
    if(NOT missing)
      continue()
    endif()

    set(find_args ${pkg})
    if(NOT version STREQUAL "")
      list(APPEND find_args ${version})
    endif()
    list(APPEND find_args REQUIRED)
    if(components)
      list(APPEND find_args COMPONENTS ${components})
    endif()
    find_package(${find_args})

    # Behaves like the caller ran find_package() themselves.
    set(CMAKE_MODULE_PATH "${CMAKE_MODULE_PATH}" PARENT_SCOPE)
    set(CMAKE_PREFIX_PATH "${CMAKE_PREFIX_PATH}" PARENT_SCOPE)
    string(TOUPPER "${pkg}" pkg_upper)
    string(TOLOWER "${pkg}" pkg_lower)
    string(REGEX REPLACE "([][+*?^$().|\\-])" "\\\\\\1" pkg_re "${pkg}")
    string(REGEX REPLACE "([][+*?^$().|\\-])" "\\\\\\1" pkg_upper_re "${pkg_upper}")
    string(REGEX REPLACE "([][+*?^$().|\\-])" "\\\\\\1" pkg_lower_re "${pkg_lower}")
    get_cmake_property(vars_after VARIABLES)
    foreach(var IN LISTS vars_after)
      if(var MATCHES "^(${pkg_re}|${pkg_upper_re}|${pkg_lower_re})_")
        set(${var} "${${var}}" PARENT_SCOPE)
      endif()
    endforeach()

    foreach(t IN LISTS targets)
      if(NOT TARGET ${t})
        get_directory_property(seen IMPORTED_TARGETS)
        list(FILTER seen EXCLUDE REGEX "(^CONAN_LIB::|_DEPS_TARGET$)")
        string(REPLACE ";" ", " seen "${seen}")
        message(FATAL_ERROR
          "deps.json says '${name}' provides '${t}', but find_package(${pkg}) "
          "did not create it. Imported targets here: ${seen}. Fix 'cmake.targets' "
          "or run 'pk dep set ${name} --discover'.")
      endif()
    endforeach()
  endforeach()
endfunction()

# Finds and links manifest packages.
function(pk_deps_link)
  cmake_parse_arguments(ARG "" "ROLE" "TARGETS;PUBLIC;PRIVATE;INTERFACE" ${ARGN})
  if(ARG_UNPARSED_ARGUMENTS)
    message(FATAL_ERROR "pk_deps_link: unrecognized arguments: ${ARG_UNPARSED_ARGUMENTS}")
  endif()
  if(NOT ARG_ROLE MATCHES "^(LIBRARY|APPLICATION|TEST)$")
    message(FATAL_ERROR "pk_deps_link: ROLE must be LIBRARY, APPLICATION or TEST.")
  endif()

  set(all ${ARG_PUBLIC} ${ARG_PRIVATE} ${ARG_INTERFACE})
  if(NOT all)
    return()
  endif()
  list(REMOVE_DUPLICATES all)

  foreach(name IN LISTS all)
    _pk_deps_require("${name}")
    pk_get_state(DEPS_${name}_KIND kind)
    if(kind STREQUAL "test" AND NOT ARG_ROLE STREQUAL "TEST")
      string(JOIN ", " where ${ARG_TARGETS})
      message(FATAL_ERROR
        "'${name}' is a test dependency (kind \"test\") and cannot be linked "
        "by ${where}. Change its kind with 'pk dep set ${name} --kind requires' "
        "if it is really needed outside the tests.")
    endif()
  endforeach()

  pk_deps_find(${all})

  foreach(t IN LISTS ARG_TARGETS)
    get_target_property(type ${t} TYPE)
    foreach(scope IN ITEMS PUBLIC PRIVATE INTERFACE)
      foreach(name IN LISTS ARG_${scope})
        pk_get_state(DEPS_${name}_TARGETS dep_targets)
        set(keyword ${scope})
        if(type STREQUAL "INTERFACE_LIBRARY")
          set(keyword INTERFACE)
        endif()
        target_link_libraries(${t} ${keyword} ${dep_targets})

        pk_get_state(DEPS_${name}_TRANSITIVE_HEADERS th)
        if(ARG_ROLE STREQUAL "LIBRARY" AND keyword MATCHES "PUBLIC|INTERFACE" AND NOT th)
          message(WARNING
            "${t} uses '${name}' as ${keyword}, so its headers are part of your "
            "API, but deps.json does not give '${name}' the Conan trait "
            "transitive_headers. Consumers of the Conan package would not see "
            "them. Run: pk dep set ${name} --trait transitive_headers=true")
        endif()
      endforeach()
    endforeach()
  endforeach()
endfunction()

# -----------------------------------------------------------------------------
# Link graph walking: Imported targets are directory scoped, not available from
# this script. Link items are classified by name as a result: project targets
# walked, names deps.json defines are packages, other 'X::Y' names are imported
# targets deps.json does not know about.
# -----------------------------------------------------------------------------

function(_pk_deps_clean_items OUT_VAR)
  set(out "")
  foreach(item IN LISTS ARGN)
    if(item MATCHES "^::@")
      continue()
    endif()

    string(REGEX REPLACE "^\\$<LINK_ONLY:(.*)>$" "\\1" item "${item}")
    string(REGEX REPLACE "^\\$<BUILD_INTERFACE:(.*)>$" "\\1" item "${item}")
    string(REGEX REPLACE "^\\$<LINK_ONLY:(.*)>$" "\\1" item "${item}")

    if(item MATCHES "^\\$<" OR item STREQUAL "")
      continue()
    endif()

    list(APPEND out "${item}")
  endforeach()

  set(${OUT_VAR} "${out}" PARENT_SCOPE)
endfunction()

# Resolves ALIAS targets; sets OUT_VAR to "" if not a project target.
function(_pk_deps_project_target OUT_VAR item)
  set(result "")
  if(TARGET "${item}")
    get_target_property(aliased "${item}" ALIASED_TARGET)
    if(aliased)
      set(item "${aliased}")
    endif()

    get_target_property(imported "${item}" IMPORTED)
    if(NOT imported)
      set(result "${item}")
    endif()
  endif()

  set(${OUT_VAR} "${result}" PARENT_SCOPE)
endfunction()

function(_pk_deps_link_items OUT_VAR target property)
  set(items "")
  get_target_property(type ${target} TYPE)
  if(property STREQUAL "LINK_LIBRARIES" AND type STREQUAL "INTERFACE_LIBRARY")
    set(${OUT_VAR} "" PARENT_SCOPE)
    return()
  endif()

  get_target_property(raw ${target} ${property})
  if(raw)
    _pk_deps_clean_items(items ${raw})
  endif()
  set(${OUT_VAR} "${items}" PARENT_SCOPE)
endfunction()

# Manifest packages the given (exported) targets pass on to consumers through
# their INTERFACE_LINK_LIBRARIES, including $<LINK_ONLY:...> from static libs.
function(pk_deps_export_find_calls OUT_VAR)
  _pk_deps_load()
  set(queue ${ARGN})
  set(seen "")
  set(packages "")

  while(queue)
    list(POP_FRONT queue target)
    if(target IN_LIST seen)
      continue()
    endif()
    list(APPEND seen ${target})

    _pk_deps_link_items(items ${target} INTERFACE_LINK_LIBRARIES)
    foreach(item IN LISTS items)
      pk_get_state(DEPS_TARGET_OWNER_${item} owner)
      if(owner)
        list(APPEND packages ${owner})
        continue()
      endif()

      _pk_deps_project_target(project_target "${item}")
      if(project_target)
        list(APPEND queue ${project_target})
      endif()
    endforeach()
  endwhile()

  set(lines "")
  if(packages)
    list(REMOVE_DUPLICATES packages)
    list(SORT packages)
  endif()

  foreach(name IN LISTS packages)
    pk_get_state(DEPS_${name}_KIND kind)
    if(NOT kind STREQUAL "requires")
      message(FATAL_ERROR
        "'${name}' (kind \"${kind}\") reaches the installed package's interface; "
        "only kind \"requires\" packages can be exported to consumers.")
    endif()

    pk_get_state(DEPS_${name}_PACKAGE pkg)
    pk_get_state(DEPS_${name}_VERSION version)
    pk_get_state(DEPS_${name}_COMPONENTS components)
    set(line "find_dependency(${pkg}")

    if(NOT version STREQUAL "")
      string(APPEND line " ${version}")
    endif()
    if(components)
      list(JOIN components " " joined)
      string(APPEND line " COMPONENTS ${joined}")
    endif()
    string(APPEND line ")  # deps.json: ${name}")
    list(APPEND lines "${line}")
  endforeach()

  set(${OUT_VAR} "${lines}" PARENT_SCOPE)
endfunction()

# -----------------------------------------------------------------------------
# pk-deps-usage.json, written once during the project's first configuration
# -----------------------------------------------------------------------------

function(_pk_deps_write_report project)
  set(PROJECT_NAME "${project}")
  pk_get_state(DEPS_NAMES names)
  pk_get_state(DEPS_MANIFEST manifest)
  set(json "{}")

  string(JSON json SET "${json}" schema 1)
  _pk_json_quote(q "${PROJECT_NAME}")
  string(JSON json SET "${json}" project "${q}")
  _pk_json_quote(q "${CMAKE_BUILD_TYPE}")
  string(JSON json SET "${json}" build_type "${q}")
  _pk_json_quote(q "${manifest}")
  string(JSON json SET "${json}" manifest "${q}")
  string(JSON json SET "${json}" targets "{}")
  string(JSON json SET "${json}" packages "{}")

  foreach(name IN LISTS names)
    set(pkg_json "{}")
    foreach(field IN ITEMS REF KIND PACKAGE)
      pk_get_state(DEPS_${name}_${field} value)
      string(TOLOWER "${field}" key)
      _pk_json_quote(q "${value}")
      string(JSON pkg_json SET "${pkg_json}" ${key} "${q}")
    endforeach()

    string(JSON json SET "${json}" packages "${name}" "${pkg_json}")
  endforeach()

  set(used "")
  foreach(role IN ITEMS LIBRARY APPLICATION TEST TOOL)
    pk_get_targets(${role} role_targets)
    foreach(root IN LISTS role_targets)
      get_target_property(type ${root} TYPE)
      set(t_json "{}")
      _pk_json_quote(q "${role}")
      string(JSON t_json SET "${t_json}" role "${q}")
      _pk_json_quote(q "${type}")
      string(JSON t_json SET "${t_json}" type "${q}")
      string(JSON t_json SET "${t_json}" direct "{}")
      string(JSON t_json SET "${t_json}" effective "{}")
      string(JSON t_json SET "${t_json}" unmanaged "[]")

      # Direct: the root's own link items. Visibility depends on the lists
      # holding them; $<LINK_ONLY:x> in the interface is how a static library
      # passes on a PRIVATE dependency, it does not make x public.
      _pk_deps_link_items(private_items ${root} LINK_LIBRARIES)
      set(interface_items "")
      get_target_property(raw_interface ${root} INTERFACE_LINK_LIBRARIES)
      if(raw_interface)
        foreach(raw IN LISTS raw_interface)
          if(NOT raw MATCHES "^\\$<LINK_ONLY:")
            _pk_deps_clean_items(cleaned "${raw}")
            list(APPEND interface_items ${cleaned})
          endif()
        endforeach()
      endif()
      set(direct_seen "")
      set(unmanaged "")
      foreach(item IN LISTS private_items interface_items)
        pk_get_state(DEPS_TARGET_OWNER_${item} owner)
        if(owner)
          if(owner IN_LIST direct_seen)
            continue()
          endif()
          list(APPEND direct_seen ${owner})
          if(item IN_LIST private_items AND item IN_LIST interface_items)
            set(vis PUBLIC)
          elseif(item IN_LIST interface_items)
            set(vis INTERFACE)
          else()
            set(vis PRIVATE)
          endif()
          _pk_json_quote(q "${vis}")
          string(JSON t_json SET "${t_json}" direct "${owner}" "${q}")
        elseif(item MATCHES "::")
          _pk_deps_project_target(project_target "${item}")
          if(NOT project_target AND NOT item IN_LIST unmanaged)
            list(APPEND unmanaged "${item}")
          endif()
        endif()
      endforeach()

      set(index 0)
      foreach(item IN LISTS unmanaged)
        _pk_json_quote(q "${item}")
        string(JSON t_json SET "${t_json}" unmanaged ${index} "${q}")
        math(EXPR index "${index} + 1")
      endforeach()

      # Every link list counts: a package a dependency links privately is
      # still something this target relies on!
      #
      # breadth first over project targets, 'via' is the shortest chain (kept
      # '|'-joined so it stays as a one list element).
      set(queue "${root}")
      set(chains "${root}")
      set(visited "")
      while(queue)
        list(POP_FRONT queue current)
        list(POP_FRONT chains chain)
        if(current IN_LIST visited)
          continue()
        endif()
        list(APPEND visited ${current})
        _pk_deps_link_items(a ${current} LINK_LIBRARIES)
        _pk_deps_link_items(b ${current} INTERFACE_LINK_LIBRARIES)
        foreach(item IN LISTS a b)
          pk_get_state(DEPS_TARGET_OWNER_${item} owner)
          if(owner)
            string(JSON existing ERROR_VARIABLE err GET "${t_json}" effective "${owner}")
            if(err)
              string(REPLACE "|" " -> " via "${chain}")
              _pk_json_quote(q "${via}")
              string(JSON t_json SET "${t_json}" effective "${owner}" "${q}")
              list(APPEND used ${owner})
            endif()
            continue()
          endif()
          _pk_deps_project_target(project_target "${item}")
          if(project_target AND NOT project_target IN_LIST visited)
            list(APPEND queue ${project_target})
            list(APPEND chains "${chain}|${project_target}")
          endif()
        endforeach()
      endwhile()

      string(JSON json SET "${json}" targets "${root}" "${t_json}")
    endforeach()
  endforeach()

  file(WRITE "${CMAKE_BINARY_DIR}/pk-deps-usage.json.tmp" "${json}\n")
  file(COPY_FILE "${CMAKE_BINARY_DIR}/pk-deps-usage.json.tmp"
    "${CMAKE_BINARY_DIR}/pk-deps-usage.json" ONLY_IF_DIFFERENT)
  file(REMOVE "${CMAKE_BINARY_DIR}/pk-deps-usage.json.tmp")

  foreach(name IN LISTS names)
    pk_get_state(DEPS_${name}_KIND kind)
    if(kind STREQUAL "requires" AND NOT name IN_LIST used)
      message(STATUS
        "${PROJECT_NAME}: deps.json package '${name}' is not linked by any "
        "target in this configuration.")
    endif()
  endforeach()
  message(STATUS "${PROJECT_NAME}: dependency usage written to "
    "${CMAKE_BINARY_DIR}/pk-deps-usage.json")
endfunction()
