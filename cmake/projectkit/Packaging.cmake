include_guard(GLOBAL)

include(GNUInstallDirs)
include(CMakePackageConfigHelpers)

function(pk_pkgconfig_target OUT_VAR PACKAGE)
  pk_get_targets(LIBRARY libraries)

  set(chosen "")
  foreach(library IN LISTS libraries)
    if(NOT library MATCHES "^${PACKAGE}(_static|_shared)?$")
      continue()
    endif()

    get_target_property(library_type ${library} TYPE)
    if(library_type STREQUAL "SHARED_LIBRARY")
      set(chosen ${library})
      break()
    endif()
    if(NOT chosen)
      set(chosen ${library})
    endif()
  endforeach()

  set(${OUT_VAR} "${chosen}" PARENT_SCOPE)
endfunction()

function(pk_write_pkgconfig)
  set(one_value_args PACKAGE DESCRIPTION TARGET TEMPLATE)
  set(multi_value_args REQUIRES)
  cmake_parse_arguments(ARG "" "${one_value_args}" "${multi_value_args}" ${ARGN})

  if(NOT ARG_PACKAGE)
    set(ARG_PACKAGE "${PROJECT_NAME}")
  endif()
  if(NOT ARG_DESCRIPTION)
    set(ARG_DESCRIPTION "${PROJECT_DESCRIPTION}")
  endif()
  if(NOT ARG_TEMPLATE)
    if(EXISTS "${PROJECT_SOURCE_DIR}/cmake/${ARG_PACKAGE}.pc.in")
      set(ARG_TEMPLATE "${PROJECT_SOURCE_DIR}/cmake/${ARG_PACKAGE}.pc.in")
    else()
      set(ARG_TEMPLATE "${PK_MODULE_DIR}/templates/pkgconfig.pc.in")
    endif()
  endif()
  if(NOT ARG_TARGET)
    pk_pkgconfig_target(ARG_TARGET "${ARG_PACKAGE}")
  endif()

  if(NOT ARG_TARGET)
    message(STATUS
      "${PROJECT_NAME}: no '${ARG_PACKAGE}' library target registered, "
      "skipping ${ARG_PACKAGE}.pc")
    return()
  endif()

  string(TOUPPER "${ARG_PACKAGE}" package_upper)
  string(MAKE_C_IDENTIFIER "${package_upper}" package_upper)

  get_target_property(PK_PC_LIBRARY_NAME ${ARG_TARGET} OUTPUT_NAME)
  get_target_property(target_type ${ARG_TARGET} TYPE)

  if(NOT PK_PC_LIBRARY_NAME)
    set(PK_PC_LIBRARY_NAME "${ARG_PACKAGE}")
  endif()

  set(PK_PC_CFLAGS "")
  if(target_type STREQUAL "STATIC_LIBRARY")
    set(PK_PC_CFLAGS " -D${package_upper}_STATIC_DEFINE")
  endif()

  set(PK_PC_NAME "${ARG_PACKAGE}")
  set(PK_PC_DESCRIPTION "${ARG_DESCRIPTION}")
  set(PK_PC_VERSION "${PROJECT_VERSION}")
  set(PK_PC_REQUIRES "")
  if(ARG_REQUIRES)
    string(JOIN ", " PK_PC_REQUIRES ${ARG_REQUIRES})
    set(PK_PC_REQUIRES " ${PK_PC_REQUIRES}")
  endif()

  set(PK_PC_EXEC_PREFIX "\${prefix}")

  if(IS_ABSOLUTE "${CMAKE_INSTALL_LIBDIR}")
    set(PK_PC_PREFIX "${CMAKE_INSTALL_PREFIX}")
    set(PK_PC_LIBDIR "${CMAKE_INSTALL_LIBDIR}")
  else()
    file(RELATIVE_PATH PK_PC_PREFIX
      "${CMAKE_INSTALL_PREFIX}/${CMAKE_INSTALL_LIBDIR}/pkgconfig"
      "${CMAKE_INSTALL_PREFIX}")
    string(REGEX REPLACE "/+$" "" PK_PC_PREFIX "${PK_PC_PREFIX}")
    set(PK_PC_PREFIX "\${pcfiledir}/${PK_PC_PREFIX}")
    set(PK_PC_LIBDIR "\${prefix}/${CMAKE_INSTALL_LIBDIR}")
  endif()

  if(IS_ABSOLUTE "${CMAKE_INSTALL_INCLUDEDIR}")
    set(PK_PC_INCLUDEDIR "${CMAKE_INSTALL_INCLUDEDIR}")
  else()
    set(PK_PC_INCLUDEDIR "\${prefix}/${CMAKE_INSTALL_INCLUDEDIR}")
  endif()

  configure_file("${ARG_TEMPLATE}"
    "${PROJECT_BINARY_DIR}/${ARG_PACKAGE}.pc" @ONLY)

  install(FILES "${PROJECT_BINARY_DIR}/${ARG_PACKAGE}.pc"
    DESTINATION "${CMAKE_INSTALL_LIBDIR}/pkgconfig")
endfunction()

function(pk_install_package)
  set(options NO_PKGCONFIG)
  set(one_value_args
    PACKAGE
    NAMESPACE
    EXPORT_SET
    COMPATIBILITY
    CONFIG_TEMPLATE
    PKGCONFIG_TEMPLATE
    PKGCONFIG_TARGET
    DESCRIPTION)
  set(multi_value_args INTERFACE_TARGETS DEPENDENCIES PKGCONFIG_REQUIRES)
  cmake_parse_arguments(ARG
    "${options}" "${one_value_args}" "${multi_value_args}" ${ARGN})

  if(ARG_UNPARSED_ARGUMENTS)
    message(FATAL_ERROR
      "pk_install_package (func): unrecognized arguments: "
      "${ARG_UNPARSED_ARGUMENTS}")
  endif()

  if(NOT ARG_PACKAGE)
    set(ARG_PACKAGE "${PROJECT_NAME}")
  endif()
  if(NOT ARG_NAMESPACE)
    set(ARG_NAMESPACE "${ARG_PACKAGE}::")
  endif()
  if(NOT ARG_EXPORT_SET)
    set(ARG_EXPORT_SET "${ARG_PACKAGE}Targets")
  endif()
  if(NOT ARG_COMPATIBILITY)
    set(ARG_COMPATIBILITY SameMajorVersion)
  endif()
  if(NOT ARG_DESCRIPTION)
    set(ARG_DESCRIPTION "${PROJECT_DESCRIPTION}")
  endif()
  if(NOT ARG_CONFIG_TEMPLATE)
    if(EXISTS "${PROJECT_SOURCE_DIR}/cmake/${ARG_PACKAGE}Config.cmake.in")
      set(ARG_CONFIG_TEMPLATE
        "${PROJECT_SOURCE_DIR}/cmake/${ARG_PACKAGE}Config.cmake.in")
    else()
      set(ARG_CONFIG_TEMPLATE
        "${PK_MODULE_DIR}/templates/PackageConfig.cmake.in")
    endif()
  endif()

  set(cmake_dir "${CMAKE_INSTALL_LIBDIR}/cmake/${ARG_PACKAGE}")

  if(ARG_INTERFACE_TARGETS)
    install(TARGETS ${ARG_INTERFACE_TARGETS} EXPORT ${ARG_EXPORT_SET})
  endif()

  install(EXPORT ${ARG_EXPORT_SET}
    NAMESPACE   "${ARG_NAMESPACE}"
    FILE        "${ARG_EXPORT_SET}.cmake"
    DESTINATION "${cmake_dir}")

  set(PK_PACKAGE_NAME "${ARG_PACKAGE}")
  set(PK_EXPORT_FILE "${ARG_EXPORT_SET}.cmake")
  set(PK_PACKAGE_DEPENDENCIES "${ARG_DEPENDENCIES}")

  configure_package_config_file(
    "${ARG_CONFIG_TEMPLATE}"
    "${PROJECT_BINARY_DIR}/${ARG_PACKAGE}Config.cmake"
    INSTALL_DESTINATION "${cmake_dir}")

  write_basic_package_version_file(
    "${PROJECT_BINARY_DIR}/${ARG_PACKAGE}ConfigVersion.cmake"
    COMPATIBILITY ${ARG_COMPATIBILITY})

  install(FILES
    "${PROJECT_BINARY_DIR}/${ARG_PACKAGE}Config.cmake"
    "${PROJECT_BINARY_DIR}/${ARG_PACKAGE}ConfigVersion.cmake"
    DESTINATION "${cmake_dir}")

  if(NOT ARG_NO_PKGCONFIG)
    pk_write_pkgconfig(
      PACKAGE     "${ARG_PACKAGE}"
      DESCRIPTION "${ARG_DESCRIPTION}"
      TARGET      "${ARG_PKGCONFIG_TARGET}"
      TEMPLATE    "${ARG_PKGCONFIG_TEMPLATE}"
      REQUIRES    ${ARG_PKGCONFIG_REQUIRES})
  endif()
endfunction()

function(pk_link_compile_commands)
  if(NOT PROJECT_IS_TOP_LEVEL OR NOT CMAKE_EXPORT_COMPILE_COMMANDS)
    return()
  endif()

  file(CREATE_LINK
    "${CMAKE_BINARY_DIR}/compile_commands.json"
    "${PROJECT_SOURCE_DIR}/compile_commands.json"
    RESULT link_result
    COPY_ON_ERROR SYMBOLIC)

  if(NOT link_result EQUAL 0)
    message(WARNING
      "Failed to link ${CMAKE_BINARY_DIR}/compile_commands.json to "
      "${PROJECT_SOURCE_DIR}/compile_commands.json, direct copy also failed: "
      "${link_result}")
  endif()
endfunction()

macro(pk_enable_cpack)
  set(_pk_one_value_args PACKAGE_FILE_NAME VENDOR)
  set(_pk_multi_value_args GENERATORS SOURCE_GENERATORS SOURCE_IGNORE_FILES)
  cmake_parse_arguments(_PK "" "${_pk_one_value_args}"
    "${_pk_multi_value_args}" ${ARGN})

  if(PROJECT_IS_TOP_LEVEL)
    set(CPACK_PACKAGE_NAME "${PROJECT_NAME}")
    set(CPACK_PACKAGE_VERSION "${PROJECT_VERSION}")
    set(CPACK_PACKAGE_DESCRIPTION_SUMMARY "${PROJECT_DESCRIPTION}")
    set(CPACK_VERBATIM_VARIABLES ON)

    if(_PK_VENDOR)
      set(CPACK_PACKAGE_VENDOR "${_PK_VENDOR}")
    endif()

    if(_PK_PACKAGE_FILE_NAME)
      set(CPACK_PACKAGE_FILE_NAME "${_PK_PACKAGE_FILE_NAME}")
    else()
      set(CPACK_PACKAGE_FILE_NAME
        "${PROJECT_NAME}-${PROJECT_VERSION}-${CMAKE_SYSTEM_NAME}-${CMAKE_SYSTEM_PROCESSOR}")
    endif()

    if(_PK_GENERATORS)
      set(CPACK_GENERATOR "${_PK_GENERATORS}")
    else()
      set(CPACK_GENERATOR "TGZ;ZIP")
    endif()

    if(_PK_SOURCE_GENERATORS)
      set(CPACK_SOURCE_GENERATOR "${_PK_SOURCE_GENERATORS}")
    else()
      set(CPACK_SOURCE_GENERATOR "TGZ")
    endif()

    set(CPACK_SOURCE_IGNORE_FILES
      "/\\\\.git/"
      "/build/"
      "/stage/"
      "/_install/"
      "/\\\\.conan-cache/"
      "/\\\\.vscode/"
      ${_PK_SOURCE_IGNORE_FILES})

    include(CPack)
  endif()
endmacro()
