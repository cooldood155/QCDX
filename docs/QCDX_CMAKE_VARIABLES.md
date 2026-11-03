# QCDX / ProjectKit: every CMake variable

A reference for every CMake variable the QCDX kit (ProjectKit, `cmake/projectkit/`)
and the project template create, read or pass around, grouped by the file each
one comes from.

- **Part 1** lists what you may set, override or read in your own project.
- **Part 2** lists what belongs to the kit: values it computes for itself,
  scratch variables, template placeholders and its internal state.
- **Part 3** is the appendix: every function-local variable, and the problems
  found while writing this.

Written against QCDX 0.2.0 (`cmake/projectkit/VERSION`), commit `056ff5b`, plus
the `app_paths` change (`AppPaths.cmake`). Line numbers are left out on purpose,
because they drift; search for the variable name in the named file.

## Contents

- [Conventions](#conventions)
- [The pipeline](#the-pipeline)
- [Who wins when a value is set twice](#who-wins-when-a-value-is-set-twice)
- **[Part 1: Variables you can set or read](#part-1-variables-you-can-set-or-read)**
  - [How pk turns flags into variables](#how-pk-turns-flags-into-variables)
  - [ProjectSetup.cmake](#projectsetupcmake-pk_project_setup)
  - [ProjectOptions.cmake](#projectoptionscmake-pk_add_options_target)
  - [StaticAnalysis.cmake](#staticanalysiscmake-pk_setup_static_analysis)
  - [Tooling.cmake](#toolingcmake-pk_setup_tooling)
  - [Dependencies.cmake](#dependenciescmake)
  - [HostTools.cmake and cross builds](#hosttoolscmake-and-cross-builds)
  - [AppPaths.cmake](#apppathscmake)
  - [The template project](#the-template-project)
  - [The QCDX package (find_package(QCDX))](#the-qcdx-package-find_packageqcdx)
  - [test_package](#test_package)
  - [Standard CMake variables the kit reacts to](#standard-cmake-variables-the-kit-reacts-to)
  - [Preprocessor definitions your code receives](#preprocessor-definitions-your-code-receives)
- **[Part 2: Kit-internal variables](#part-2-kit-internal-variables)**
  - [Kit-wide internals](#kit-wide-internals)
  - [Cached internals and check results](#cached-internals-and-check-results)
  - [Variables the setup macros leave in your top-level scope](#variables-the-setup-macros-leave-in-your-top-level-scope)
  - [Standard CMake variables the kit sets](#standard-cmake-variables-the-kit-sets)
  - [Values passed between functions](#values-passed-between-functions)
  - [Template placeholders](#template-placeholders)
  - [Kit state in global properties](#kit-state-in-global-properties)
  - [presets.cmake (the pk query script)](#presetscmake-the-pk-query-script)
  - [QCDXConfigVersion.cmake](#qcdxconfigversioncmake)
- **[Part 3: Appendix](#part-3-appendix)**
  - [Function-local variables](#function-local-variables)
  - [Problems found while documenting](#problems-found-while-documenting)

---

## Conventions

| Written here         | Means                                                                 | In MinnesotaCardboard |
|----------------------|-----------------------------------------------------------------------|-----------------------|
| `<PREFIX>`           | `PROJECT_NAME` upper-cased and made a C identifier (`pk_project_prefix`) | `MNCB`             |
| `<project>`          | `PROJECT_NAME` as written in `project()`                              | `mncb`                |
| `<name>`             | the `NAME` given to a creator (`pk_create_library`, `pk_create_app`, ...) | `mncb`            |
| `<NAME>`             | `<name>` upper-cased                                                  | `MNCB`                |
| `QCDX_*` / `qcdx*`   | in `template/` only: `pk new` renames them to `<PREFIX>_*` / `<project>*` | `MNCB_*`, `mncb*` |

**Kinds** used in the tables:

| Kind              | Lives in                         | Survives reconfigure | How you change it |
|-------------------|----------------------------------|----------------------|-------------------|
| cache BOOL        | `CMakeCache.txt` (from `option()`) | yes                | `-D<VAR>=ON/OFF`, preset `cacheVariables`, `pk -O`, ccmake/cmake-gui |
| cache STRING / PATH / FILEPATH | `CMakeCache.txt`    | yes                  | same as above |
| cache INTERNAL    | `CMakeCache.txt`, hidden from GUIs, rewritten every configure | yes | don't |
| normal            | the directory scope it was set in, and below | no         | `set()` before/after the kit call, depending on the variable |
| local             | one function call                | no                   | n/a |
| placeholder       | a variable read by `configure_file`/`configure_package_config_file` as `@VAR@` | no | n/a |
| global property   | `set_property(GLOBAL ...)`, the kit's state store | no (rebuilt each configure) | n/a |

A cache variable and a normal variable may share a name. The normal variable
then hides the cache value in that scope and below; the cache entry is
untouched. The kit relies on this in a few places, called out below.

---

## The pipeline

What runs, in order, during one `pk run` (or `cmake --preset ...`), and which
variables each step creates.

```
pk.py (Python)                    reads CMakePresets.json through presets.cmake
  | -D<PREFIX>_BUILD_TESTS=..     (PK_QUERY / PK_PRESET / PK_PRESETS_FILE)
  | -D<from -O/-D/--lib/...>      compares each -D with CMakeCache.txt to decide
  v                               whether to reconfigure
conan install (conanfile.py)      generators/conan_toolchain.cmake:
  |                                 BUILD_SHARED_LIBS (cache), CMAKE_POSITION_INDEPENDENT_CODE (cache)
  |                                 CMAKE_CXX_STANDARD / CMAKE_C_STANDARD (normal, from compiler.cppstd/cstd)
  |                                 <PREFIX>_BUILD_TESTS (cache, from tools.build:skip_test)
  |                               generators/<project>_intent.cmake:
  |                                 <PREFIX>_TOOLCHAIN_SHARED
  v
cmake --preset <preset>           preset cacheVariables: CMAKE_BUILD_TYPE, CMAKE_EXPORT_COMPILE_COMMANDS,
  |                                 (host-tools) <PREFIX>_BUILD_APPS/BUILD_TESTS/LIBRARY_TYPE/SA_ALL,
  |                                 (cross) <project>HostTools_DIR; toolchainFile -> CMAKE_TOOLCHAIN_FILE
  v
CMakeLists.txt, before project()  pk_require_conan_build_dir -> <PREFIX>_BUILD_TYPE (unused),
  |                                 <project>_conan_dir -> CONAN_BUILD_DIR (cache INTERNAL)
  v
project()                         loads the toolchain file(s): Conan's, then for cross profiles the
  |                                 user_toolchain (cmake/toolchains/*.cmake: <PREFIX>_TARGET_TRIPLE,
  |                                 CMAKE_SYSTEM_NAME, compilers, find-root modes)
  v
include(ProjectKit)               PK_MODULE_DIR (cache INTERNAL), PK_TREE_DEFAULTS, PK_DEPS_KINDS,
  |                                 GNUInstallDirs -> CMAKE_INSTALL_*DIR
  v
pk_project_setup() (macro)        <PREFIX>_BUILD_APPS/_BUILD_TESTS/_INSTALL/_WERROR/_LIBRARY_TYPE,
  |                                 <PREFIX>_CXX_STANDARD/_C_STANDARD, CMAKE_*_STANDARD*, output dirs, RPATH
  |-- pk_add_warnings_target      target <project>_warnings
  |-- pk_add_options_target       <PREFIX>_SANITIZE/_HARDENING/_COVERAGE/_REPRODUCIBLE/_LTO/_CCACHE/
  |   (macro)                       _REDUCE_SIZE, compiler-family flags, probe results, launcher
  |-- pk_setup_static_analysis    <PREFIX>_SA_*, analyser paths -> state CLANG_TIDY_COMMAND/CPPCHECK_COMMAND
  |-- pk_setup_tooling (macro)    <PREFIX>_VALGRIND*, _FUZZER, _FUZZ_SECONDS -> state VALGRIND_COMMAND
  |-- pk_set_state(DEFAULT_LINKS) <project>::warnings, <project>::options
  '-- _pk_deps_load()             reads deps.json (or PK_DEPS_MANIFEST) -> state DEPS_*;
                                    defers the pk-deps-usage.json report to the end
pk_check_shared_intent()          compares BUILD_SHARED_LIBS with <PREFIX>_TOOLCHAIN_SHARED
pk_require_host_tools()           cross only: find_package(<project>HostTools) via <project>HostTools_DIR
if(<PREFIX>_LIBRARY_TYPE ...)     add_subdirectory(src)   -> pk_create_library (export header)
if(<PREFIX>_BUILD_APPS)           add_subdirectory(apps)  -> pk_create_app (app_paths)
if(<PREFIX>_BUILD_TESTS OR fuzz)  enable_testing(); add_subdirectory(tests) -> pk_create_test
if(<PREFIX>_INSTALL AND lib)      pk_install_package -> PK_PACKAGE_NAME, PK_EXPORT_FILE, PK_PC_*
pk_link_compile_commands()        reads CMAKE_EXPORT_COMPILE_COMMANDS
pk_enable_cpack() (macro)         CPACK_* then include(CPack)
end of top-level directory        deferred _pk_deps_write_report -> build/<tree>/pk-deps-usage.json
```

---

## Who wins when a value is set twice

From strongest to weakest, for the kit's cache variables (`<PREFIX>_*`):

1. **A normal variable of the same name** set in a scope that the kit reads
   from. It hides the cache. The kit does this itself for
   `<PREFIX>_CXX_STANDARD`, `<PREFIX>_C_STANDARD` and `<PREFIX>_LIBRARY_TYPE`.
2. **`-D` on the command line**, which includes everything `pk` passes. A `-D`
   beats the preset's `cacheVariables` and replaces what is in the cache.
3. **The preset's `cacheVariables`**, on a configure that doesn't pass `-D` for it.
4. **What is already in `CMakeCache.txt`.**
5. **Conan's toolchain.** It writes `set(<VAR> <value> CACHE ...)` without
   `FORCE`, so it only fills in a value that isn't cached yet
   (`<PREFIX>_BUILD_TESTS`, `BUILD_SHARED_LIBS`).
6. **The kit's own default** in `option()`/`set(... CACHE ...)`, used only when
   nothing above set it.

Two exceptions are worth knowing:

- **The C++ and C standards.** Conan's toolchain sets `CMAKE_CXX_STANDARD`
  (and `CMAKE_C_STANDARD`) as *normal* variables whenever the Conan profile
  has `compiler.cppstd` (`compiler.cstd`). `pk_project_setup` then copies it
  over `<PREFIX>_CXX_STANDARD`. So in a pk project the **profile decides the
  standard**; `-D<PREFIX>_CXX_STANDARD=20` changes nothing while the profile
  says 23.
- **`<PREFIX>_LIBRARY_TYPE` empty.** It then follows `BUILD_SHARED_LIBS`,
  which in a pk project comes from Conan's `shared` option.

---

# Part 1: Variables you can set or read

## How pk turns flags into variables

`pk` builds a list of `-D` definitions and passes them to `cmake --preset`.
`-O NAME=VALUE` is shorthand for `-D<PREFIX>_NAME=VALUE`; `-D` passes anything
through as is. Before configuring, pk compares every definition with the
tree's `CMakeCache.txt` and reconfigures only when one differs.

| pk flag or command              | Becomes                                  |
|---------------------------------|------------------------------------------|
| (always)                        | `-D<PREFIX>_BUILD_TESTS=ON/OFF` (from `--tests`, the command's needs, the cached value, else `OFF`) |
| `--tests` / `--no-tests`        | `<PREFIX>_BUILD_TESTS=ON` / `OFF`        |
| `--apps` / `--no-apps`          | `<PREFIX>_BUILD_APPS=ON` / `OFF`         |
| `--werror` / `--no-werror`      | `<PREFIX>_WERROR=ON` / `OFF`             |
| `--lto` / `--no-lto`            | `<PREFIX>_LTO=ON` / `OFF`                |
| `--coverage` / `--no-coverage`  | `<PREFIX>_COVERAGE=ON` / `OFF`           |
| `--analyze` / `--no-analyze`    | `<PREFIX>_SA_ALL=ON` / `OFF`             |
| `--sanitize <list>` / `--no-sanitize` | `<PREFIX>_SANITIZE=<list>` / empty |
| `--lib static\|shared\|both\|none` | `<PREFIX>_LIBRARY_TYPE=STATIC\|SHARED\|STATIC+SHARED\|NONE` |
| `-O NAME=VALUE`                 | `<PREFIX>_NAME=VALUE`                    |
| `-D NAME=VALUE`                 | `NAME=VALUE`                             |
| `pk analyze`                    | `<PREFIX>_SA_ALL=ON` in tree `build/<preset>-analyze` |
| `pk memcheck`                   | `<PREFIX>_VALGRIND=ON` in tree `build/<preset>-memcheck` |
| `pk sanitize`                   | `<PREFIX>_SANITIZE=address,undefined` (unless given) in `build/<preset>-sanitize` |
| host tools for a cross build    | `cmake --preset host-tools -DCMAKE_BUILD_TYPE=<type> -DCMAKE_TOOLCHAIN_FILE=<native Conan toolchain>` |

`pk status` shows these: `BUILD_TESTS`, `BUILD_APPS`, `LIBRARY_TYPE`, `WERROR`,
`SANITIZE`, `SA_ALL`, `LTO`, `COVERAGE`, `VALGRIND`.

`verify.py` passes `-D<PREFIX>_LIBRARY_TYPE=<type>` for each type of its
library matrix, the same host-tools pair as above, and
`CMAKE_BUILD_TYPE`/`CMAKE_TOOLCHAIN_FILE`/`CMAKE_PREFIX_PATH` for its consumer
test.

---

## ProjectSetup.cmake (`pk_project_setup`)

`pk_project_setup` is a **macro**, so everything it sets lands in the calling
scope, normally your top-level `CMakeLists.txt`. Its arguments set the
defaults of three of these cache variables:

```cmake
pk_project_setup(CXX_STANDARD 23 C_STANDARD 23 LIBRARY_TYPE STATIC)
```

### `<PREFIX>_BUILD_APPS`

- **Kind:** cache BOOL (`option`). **Default:** `PROJECT_IS_TOP_LEVEL` (ON for
  your project, OFF when it is pulled in with `add_subdirectory`/FetchContent).
- **Why:** lets a consumer, or the host-tools build, skip your applications.
- **Set by:** `pk --apps/--no-apps`, `-O BUILD_APPS=...`; the `host-tools`
  preset sets it OFF.
- **Read by:** the template's top-level `CMakeLists.txt`:
  `if(<PREFIX>_BUILD_APPS) add_subdirectory(apps)`. Nothing in the kit reads it.

### `<PREFIX>_BUILD_TESTS`

- **Kind:** cache BOOL. **Default:** `PROJECT_IS_TOP_LEVEL`, but in a pk
  project Conan's toolchain fills it first: ON, or OFF when the Conan profile
  or command has `tools.build:skip_test=True`.
- **Why:** tests need Catch2 and take build time; consumers and host tools
  don't want them.
- **Set by:** `conanfile.py` `generate()` (`tc.variables`), pk on every
  configure (`--tests`, or ON for `pk test`), the `host-tools` preset (OFF).
- **Read by:** the template's top-level `CMakeLists.txt` (`enable_testing()`
  and `add_subdirectory(tests)`); pk reads it back from the cache for its
  banner (`(tests ON)`) and to decide whether to install Catch2. `verify.py`
  fails its workflow stage when Conan reports it OFF.

### `<PREFIX>_INSTALL`

- **Kind:** cache BOOL. **Default:** `PROJECT_IS_TOP_LEVEL`.
- **Why:** install rules from a subproject would install into its parent's
  prefix.
- **Read by:** `pk_create_library`, `pk_create_app` (skip `install()` when
  OFF), the template (`pk_install_package` only when ON and a library is
  built), pk's package stage (`verify`/`release` skip package checks when OFF).

### `<PREFIX>_WERROR`

- **Kind:** cache BOOL. **Default:** OFF.
- **Read by:** `pk_add_warnings_target` (`-Werror` / `/WX` on
  `<project>::warnings`), `pk_setup_static_analysis` (clang-tidy
  `--warnings-as-errors=*`, cppcheck `--error-exitcode=1`).
- **Set by:** `pk --werror`, CI.

### `<PREFIX>_LIBRARY_TYPE`

- **Kind:** cache STRING. **Values:** `STATIC`, `SHARED`, `STATIC+SHARED`,
  `NONE`, or empty. **Default:** the `LIBRARY_TYPE` argument of
  `pk_project_setup`, empty when not given.
- **Why:** one switch for which library artifacts to build.
- **Flow:** when empty, `pk_project_setup` sets a *normal* variable of the
  same name to `SHARED` or `STATIC` from `BUILD_SHARED_LIBS`, and sets
  `<PREFIX>_LIBRARY_TYPE_FOLLOWS_BUILD_SHARED_LIBS` (Part 2). The cache stays
  empty. `pk_create_library` uses it as the linkage of a COMPILED library that
  has no `LOCKED_*` flag; the template skips `add_subdirectory(src)` and
  `pk_install_package` for `NONE`. `STATIC+SHARED` makes
  `<name>_static` and `<name>_shared` targets.
- **Set by:** `pk --lib`, `verify.py`'s matrix, the `host-tools` preset (`NONE`).
- **Note:** `LOCKED_STATIC` / `LOCKED_SHARED` / `LOCKED_STATIC_SHARED` on a
  library ignore this variable. MinnesotaCardboard's `mncb` library is
  `LOCKED_STATIC`.

### `<PREFIX>_CXX_STANDARD` and `<PREFIX>_C_STANDARD`

- **Kind:** cache STRING. **Values:** C++ `17 20 23 26`; C `99 11 17 23`.
  **Default:** the `CXX_STANDARD` / `C_STANDARD` arguments of
  `pk_project_setup`, else `23`.
- **Flow:** if `CMAKE_CXX_STANDARD` already has a value (Conan's toolchain
  sets it from the profile's `compiler.cppstd`), a normal variable
  `<PREFIX>_CXX_STANDARD` is set to it and wins; otherwise
  `CMAKE_CXX_STANDARD` is set from the cache value. The result is validated,
  then used as `cxx_std_<N>` / `c_std_<N>` compile features by every creator
  (`pk_configure_libraries`, `pk_create_app`, `pk_create_test`).
- **In practice:** change the standard in the Conan profile
  (`compiler.cppstd=20`), not here.

---

## ProjectOptions.cmake (`pk_add_options_target`)

Called by `pk_project_setup`, also a **macro**. All of these add flags to the
`INTERFACE` target `<project>_options` (`<project>::options`), which every
creator links through the default links (unless `NO_DEFAULT_LINKS`).

| Variable                    | Kind         | Default | What it does |
|-----------------------------|--------------|---------|--------------|
| `<PREFIX>_SANITIZE`         | cache STRING | empty   | Comma list of `address`, `undefined`, `thread`, `leak`, `memory`. `-fsanitize=<list> -fno-omit-frame-pointer -g` (GNU-like) or `/fsanitize=address /Zi /Oy-` (MSVC: address only). `thread` can't combine with address/leak/memory. Checked with a test compile; MinGW GCC has no sanitizer runtimes and stops with a hint. Also turns off `_FORTIFY_SOURCE`/`_SECURE_SCL` from hardening. Set by `pk sanitize`, `--sanitize`. |
| `<PREFIX>_HARDENING`        | cache BOOL   | ON      | GNU-like: `-fstack-protector-strong`, `-fstack-clash-protection`, `-fcf-protection=full`, `-ftrivial-auto-var-init=zero`, `_GLIBCXX_ASSERTIONS`, linker `-z relro/now/noexecstack`; `_FORTIFY_SOURCE=3` outside Debug. MSVC: `/GS /guard:cf /NXCOMPAT /DYNAMICBASE /initall /HIGHENTROPYVA`, `_SECURE_SCL=1` outside Debug. Each flag is probed first (the `*_has_*` cache entries, Part 2). On MinGW the three `-z` checks fail, which is the "Failed" you see in the configure log. |
| `<PREFIX>_COVERAGE`         | cache BOOL   | OFF     | `--coverage -g -O0` (GNU-like) or `/Zi /Od` + `/DEBUG` (MSVC). `pk --coverage`. |
| `<PREFIX>_REPRODUCIBLE`     | cache BOOL   | OFF     | Maps `PROJECT_SOURCE_DIR` to `.` (`-ffile-prefix-map`, `/pathmap`), `-fno-ident`, `/experimental:deterministic`, `/PDBALTPATH:%_PDB%`. |
| `<PREFIX>_LTO`              | cache BOOL   | OFF     | Checks IPO support, then sets `CMAKE_INTERPROCEDURAL_OPTIMIZATION` TRUE in the top-level scope (so every target below gets it). Stops configure if unsupported. `pk --lto`. |
| `<PREFIX>_CCACHE`           | cache BOOL   | ON      | Looks for `ccache` or `sccache` and sets `CMAKE_C_COMPILER_LAUNCHER`/`CMAKE_CXX_COMPILER_LAUNCHER` to it, unless you already set a launcher. Turn off with `CCACHE_DISABLE=1` in the environment for one build (ccache's own switch), or `-O CCACHE=OFF` for the tree. |
| `<PREFIX>_COMPILER_CACHE`   | cache FILEPATH (`find_program`) | found path | The ccache/sccache found. Preset it to choose a specific program; to stop using one, turn `<PREFIX>_CCACHE` off instead. |
| `<PREFIX>_REDUCE_SIZE`      | cache BOOL   | ON      | `-ffunction-sections -fdata-sections` + linker `--gc-sections` (GNU-like) or `/Gy /OPT:REF /OPT:ICF` (MSVC). This is where the `-Wl,--gc-sections` in your link line comes from. |

---

## StaticAnalysis.cmake (`pk_setup_static_analysis`)

Builds one clang-tidy command and one cppcheck command, stores them as kit
state, and `pk_enable_static_analysis` puts them on every library, app, test
and tool target as `C_/CXX_CLANG_TIDY` and `C_/CXX_CPPCHECK`. Generated files
(`app_paths`, `pk_add_generated_source` output) are skipped through `SKIP_LINTING`.

| Variable                       | Kind | Default | What it does |
|--------------------------------|------|---------|--------------|
| `<PREFIX>_SA_ALL`              | cache BOOL | OFF | Both analysers. `pk analyze`, `--analyze`. The `host-tools` preset sets it OFF. |
| `<PREFIX>_SA_CLANG_TIDY`       | cache BOOL | OFF | clang-tidy only. |
| `<PREFIX>_SA_CPPCHECK`         | cache BOOL | OFF | cppcheck only. |
| `<PREFIX>_SA_OUTPUT`           | cache STRING | `console` | `console`, or `files` to also write per-source reports. See the [launcher problem](#problems-found-while-documenting): `files` with clang-tidy currently fails to configure. |
| `<PREFIX>_SA_OUTPUT_DIR`       | cache PATH | `${PROJECT_BINARY_DIR}/analysis` | Report folder for `files` (`clang-tidy/` and `cppcheck/` below it). |
| `<PREFIX>_SA_MESSAGE_FORMAT`   | cache STRING | `default` | cppcheck `--template=`: `default`, `gcc`, `vs`. |
| `<PREFIX>_SA_LAUNCHER`         | cache STRING | `<python>;<kit>/scripts/analyser_launcher.py` | The wrapper used in `files` mode. A list, not a path. |
| `<PREFIX>_CLANG_TIDY_PATH`     | cache FILEPATH (`find_program`) | found | `clang-tidy`, `clang-tidy-22` ... `-18`. Preset it to pick a version. |
| `<PREFIX>_CPPCHECK_PATH`       | cache FILEPATH | found | `cppcheck`. |
| `<PREFIX>_SH_PATH`             | cache FILEPATH | found | `sh`, only looked up for clang-tidy in `files` mode. |

`find_program` results are cached, so a path found once is reused; delete the
entry (or the tree) after installing a different version.

---

## Tooling.cmake (`pk_setup_tooling`)

Also a **macro** called by `pk_project_setup`.

| Variable                   | Kind | Default | What it does |
|----------------------------|------|---------|--------------|
| `<PREFIX>_VALGRIND`        | cache BOOL | OFF | Adds a `<test>: valgrind` test (label `valgrind`, 900 s timeout) next to every test executable, through `pk_add_valgrind_test` in `pk_create_test` (unless `NO_VALGRIND`). Not on Windows, not for cross builds. `pk memcheck`. |
| `<PREFIX>_VALGRIND_TOOL`   | cache STRING | `memcheck` | `memcheck` (adds `--leak-check=full --errors-for-leak-kinds=definite,possible --track-origins=yes`), `helgrind`, `drd`. `tests/valgrind.supp` is used when it exists (tests folder from the tree). |
| `<PREFIX>_VALGRIND_PATH`   | cache FILEPATH | found | The valgrind binary. |
| `<PREFIX>_FUZZER`          | cache STRING | `off` | `off`, `libfuzzer`, `afl`. Creates `INTERFACE` target `<project>_fuzzing` (`<project>::fuzzing`) with `-fsanitize=fuzzer-no-link` / `-fsanitize=fuzzer` (or MSVC `/fsanitize=fuzzer`); `afl` requires `CXX=afl-clang-fast++`/`afl-g++-fast`. The template also calls `enable_testing()` when it isn't `off`. Nothing in the kit creates fuzz targets yet; link `<project>::fuzzing` yourself. |
| `<PREFIX>_FUZZ_SECONDS`    | cache STRING | `45` | Meant as the run time of each fuzz target under ctest. **Not read anywhere yet.** |

---

## Dependencies.cmake

| Variable             | Kind | Default | What it does |
|----------------------|------|---------|--------------|
| `PK_DEPS_MANIFEST`   | normal or cache, set by you | `${PROJECT_SOURCE_DIR}/deps.json` | Read once by `_pk_deps_load` (`if(DEFINED PK_DEPS_MANIFEST)`). Points CMake at another manifest. Conan's `conanfile.py` always reads `deps.json` from the recipe folder, so changing only this makes CMake and Conan disagree. Undocumented. |

Everything else in this file is state (Part 2). What you control is
`deps.json` itself and the `DEPS`, `DEPS_PUBLIC`, `DEPS_PRIVATE`,
`DEPS_INTERFACE` arguments of the creators; `pk_deps_find(<name>)` and
`pk_deps_link` turn them into `find_package` calls and links.

`pk_deps_find` copies the variables a `find_package` defines back to the
caller, so after `pk_deps_find(sqlite3)` you see `SQLite3_FOUND`,
`SQLite3_VERSION` and the like, plus the updated `CMAKE_MODULE_PATH` and
`CMAKE_PREFIX_PATH`, exactly as if you had called `find_package` yourself.

---

## HostTools.cmake and cross builds

| Variable                      | Kind | Set by | What it does |
|-------------------------------|------|--------|--------------|
| `<project>HostTools_DIR`      | cache PATH | the `cross-base` preset: `${sourceDir}/build/host-tools` | Where `find_package(<project>HostTools)` (in `pk_require_host_tools`, cross builds only) finds `<project>HostToolsConfig.cmake`, which `pk_create_tool(... EXPORT_FILE ...)` wrote in the native `host-tools` tree. That file defines the imported `<project>::codegen` used by `pk_add_generated_source`. |
| `<PREFIX>_TARGET_TRIPLE`      | normal, in `cmake/toolchains/<target>.cmake` | you, per cross target | The compiler prefix (`x86_64-w64-mingw32`, `aarch64-linux-gnu`, ...) the toolchain file uses to find `-gcc`, `-g++`, `-ar`, `-ranlib`, `-strip`, `-objcopy` (and `-windres` as `CMAKE_RC_COMPILER` for the LLVM MinGW one). Edit it when adding a cross target. |
| `CMAKE_SYSROOT`               | standard | the Conan profile / you | When set, appended to `CMAKE_FIND_ROOT_PATH` by the toolchain files. |

Each cross toolchain file (`cmake/toolchains/<target>.cmake`, loaded through the Conan profile's `user_toolchain`) also sets, from `<PREFIX>_TARGET_TRIPLE`:

| Variable | Value |
|----------|-------|
| `CMAKE_SYSTEM_NAME`, `CMAKE_SYSTEM_PROCESSOR` | the target (`Windows`/`Linux`, `x86_64`/`aarch64`) |
| `CMAKE_C_COMPILER`, `CMAKE_CXX_COMPILER` | `<triple>-gcc`, `<triple>-g++` (or the LLVM MinGW clang drivers), required |
| `CMAKE_AR`, `CMAKE_RANLIB`, `CMAKE_STRIP`, `CMAKE_OBJCOPY` | GCC targets: `<triple>-gcc-ar`, `-gcc-ranlib`, `-strip`, `-objcopy`. LLVM MinGW: `<triple>-ar` and `-ranlib` (required, it has no `-gcc-ar`), `-strip`, no `objcopy` |
| `CMAKE_RC_COMPILER` | `<triple>-windres` (LLVM MinGW only) |
| `CMAKE_FIND_ROOT_PATH` | gets `CMAKE_SYSROOT` appended (GCC targets) or `/usr/<triple>` when it exists (LLVM MinGW) |
| `CMAKE_FIND_ROOT_PATH_MODE_PROGRAM` | `NEVER`: build tools come from the host |
| `CMAKE_FIND_ROOT_PATH_MODE_LIBRARY`, `CMAKE_FIND_ROOT_PATH_MODE_INCLUDE`, `CMAKE_FIND_ROOT_PATH_MODE_PACKAGE` | `BOTH`: Conan's packages live outside the sysroot |

`pk_require_host_tools(PACKAGE <name>)` takes the package name as an argument;
the default is `<project>HostTools`.

---

## AppPaths.cmake

Nothing to set: the layout comes from `CMAKE_INSTALL_BINDIR` and
`CMAKE_INSTALL_DATADIR` (below), the name from the app's `NAME`, the version
from `PROJECT_VERSION`. Opt out with `pk_create_app(... NO_APP_PATHS)`. The
values it computes are in [Template placeholders](#template-placeholders).

---

## The template project

These live in your project's own files (created by `pk new`), so they are
yours to change.

| Variable                        | Where                         | What it does |
|---------------------------------|-------------------------------|--------------|
| `CMAKE_BUILD_TYPE`              | presets `debug-base` ... `minsizerel-base`; pk `-t` | Required: `pk_require_conan_build_dir` stops without it, accepts any case, and picks the matching Conan output. |
| `CMAKE_EXPORT_COMPILE_COMMANDS` | preset `base`: ON             | `compile_commands.json`, linked into the source root by `pk_link_compile_commands` for clangd. |
| `CMAKE_TOOLCHAIN_FILE`          | preset `toolchainFile`        | Conan's `build/<Type>/generators/conan_toolchain.cmake` (cross presets: `build/<os>-<arch>-<type>/...`). Its folder also locates `<project>_intent.cmake` and the Conan output. |
| `<PREFIX>_BUILD_TYPE`           | top-level `CMakeLists.txt`, `OUT_BUILD_TYPE` of `pk_require_conan_build_dir` | The build type spelled canonically (`Debug`, ...). **Set but never read.** Free for your own use. |
| `<project>_conan_dir`           | same, `OUT_DIR`               | Conan's output folder for this build type (`build/Debug`), copied into `CONAN_BUILD_DIR`. |
| `CONAN_BUILD_DIR`               | same, cache INTERNAL          | Same folder, cached. Nothing in the kit reads it; it is there for your code (for example to locate generated Conan files). Read it, don't set it. |
| host-tools preset values        | preset `host-tools`           | `<PREFIX>_BUILD_APPS=OFF`, `<PREFIX>_BUILD_TESTS=OFF`, `<PREFIX>_LIBRARY_TYPE=NONE`, `<PREFIX>_SA_ALL=OFF`: a tools-only native build. |

`conanfile.py` options `shared` and `fPIC` become `BUILD_SHARED_LIBS` and
`CMAKE_POSITION_INDEPENDENT_CODE` through Conan's toolchain; `shared` is also
written to `<project>_intent.cmake` (see `<PREFIX>_TOOLCHAIN_SHARED`).

---

## The QCDX package (`find_package(QCDX)`)

For using the kit in a project that wasn't made by `pk new`.

| Variable                 | Kind | Where | What it does |
|--------------------------|------|-------|--------------|
| `QCDX_INSTALL_CMAKEDIR`  | cache STRING, default `share/qcdx/cmake` | root `CMakeLists.txt` | Where `cmake --install` puts `QCDXConfig.cmake` and `projectkit/`. |
| `QCDX_DIR`               | standard `find_package` cache PATH | you, or root `CMakeLists.txt` (FORCE) when QCDX is a subproject | Where `QCDXConfig.cmake` is. |
| `QCDX_FOUND`             | normal, output | `QCDXConfig.cmake` | TRUE once loaded. |
| `QCDX_VERSION`           | normal, output | `QCDXConfig.cmake` | The kit version, from `projectkit/VERSION`. |
| `QCDX_MODULE_DIR`        | normal, output | `QCDXConfig.cmake` | Absolute `projectkit/` folder; appended to `CMAKE_MODULE_PATH` so `include(ProjectKit)` works. |
| `CMAKE_FIND_PACKAGE_REDIRECTS_DIR` | standard, read | root `CMakeLists.txt` | When set (FetchContent), the kit writes `qcdx-extra.cmake` redirect files there. |

---

## test_package

Used by `conan create` (`package.py`, `pk package`) to check the packaged
library from a consumer's point of view.

| Variable              | Kind | Set by | What it does |
|-----------------------|------|--------|--------------|
| `PK_TEST_SOURCE`      | cache (Conan `cache_variables`) | the `PK_TEST_SOURCE` **environment variable**, if set | A `.cpp` to compile instead of `test_package/src/example.cpp`. This is how you test with your own consumer code. |
| `PK_TESTED_PACKAGE`   | cache | `test_package/conanfile.py`, from the reference under test | Package name to `find_package` and link (`<pkg>::<pkg>`). Internal; the build stops when it is missing. |

---

## Standard CMake variables the kit reacts to

Set these the usual way; the kit reads them.

| Variable | Read by | Effect |
|----------|---------|--------|
| `BUILD_SHARED_LIBS` | `pk_project_setup`, `pk_check_shared_intent`, the template's `<project>Config.cmake.in` | Decides `<PREFIX>_LIBRARY_TYPE` when that is empty; must match Conan's `shared` (checked); picks `<project>::shared` vs `::static` for consumers. |
| `CMAKE_CXX_STANDARD`, `CMAKE_C_STANDARD` | `pk_project_setup` | Override `<PREFIX>_CXX_STANDARD`/`_C_STANDARD` when set before it (Conan does). |
| `CMAKE_BUILD_TYPE` | `pk_require_conan_build_dir`, the deps report | Required, see above. |
| `CMAKE_TOOLCHAIN_FILE` | `pk_require_conan_build_dir`, `pk_check_shared_intent` | Locates Conan's output and the intent file. |
| `CMAKE_INSTALL_PREFIX` | `pk_add_app_paths` (as an anchor only), `pk_write_pkgconfig` | Relative layout and `.pc` paths. |
| `CMAKE_INSTALL_BINDIR`, `CMAKE_INSTALL_LIBDIR`, `CMAKE_INSTALL_INCLUDEDIR`, `CMAKE_INSTALL_DATADIR` | install rules of every creator, `pk_install_package`, `pk_write_pkgconfig`, RPATH in `pk_project_setup`, `pk_add_app_paths` | Where things install. Keep them relative; `app_paths` and `.pc` files depend on it. |
| `CMAKE_EXPORT_COMPILE_COMMANDS` | `pk_link_compile_commands` | Links `compile_commands.json` into the source root (top-level project only). |
| `CMAKE_C_COMPILER_LAUNCHER`, `CMAKE_CXX_COMPILER_LAUNCHER` | `pk_add_options_target` | If you set one, the kit leaves it alone instead of adding ccache. |
| `CMAKE_CROSSCOMPILING_EMULATOR` | `pk_create_test` | Without one, cross-built tests are registered but disabled. |
| `CMAKE_CROSSCOMPILING` | `pk_project_setup` (RPATH), `pk_require_host_tools`, `pk_setup_tooling`, `pk_create_test`, template | Cross-build behaviour. Set by the toolchain. |
| `CMAKE_CXX_COMPILER_ID`, `CMAKE_CXX_COMPILER_FRONTEND_VARIANT`, `CMAKE_CXX_COMPILER`, `CMAKE_C_COMPILER` | `pk_project_setup`, `pk_add_options_target`, `pk_setup_tooling`, `pk_toolchain_dll_dirs` | Compiler family (GNU-like or MSVC), AFL wrapper check, MinGW DLL folder for test discovery. |
| `CMAKE_RUNTIME_OUTPUT_DIRECTORY` | `pk_add_app_paths` | Checked against the install layout. The kit sets it (Part 2). |
| `CMAKE_CXX_COMPILER_LOADED` | `pk_add_app_paths` | The generated code is C++; stops with a clear error when CXX isn't enabled. |
| `Python3_EXECUTABLE` | `pk_setup_static_analysis` (after `find_package(Python3 3.8)`) | First item of `<PREFIX>_SA_LAUNCHER`. Python 3.8+ is required to configure. |
| `CMAKE_GENERATOR` | `pk_add_app_paths` (warning text) | Multi-config generators get a warning. |
| `CMAKE_SYSTEM_NAME`, `CMAKE_SYSTEM_PROCESSOR` | `pk_enable_cpack` | Default package file name. |
| `PROJECT_NAME`, `PROJECT_VERSION`, `PROJECT_VERSION_MAJOR`, `PROJECT_DESCRIPTION` | everywhere | Prefix, target names, `<PREFIX>_VERSION_STRING`, library `VERSION`/`SOVERSION`, package metadata, `app_version`. |
| `PROJECT_SOURCE_DIR`, `PROJECT_BINARY_DIR`, `CMAKE_BINARY_DIR`, `CMAKE_CURRENT_SOURCE_DIR` | everywhere | Tree lookups, generated files, relative paths in creator arguments. |
| `PROJECT_IS_TOP_LEVEL` | `pk_project_setup`, `pk_link_compile_commands`, `pk_enable_cpack` | Defaults of `BUILD_APPS/TESTS/INSTALL`; only the top project links compile commands and sets up CPack. |
| `WIN32`, `APPLE`, `MINGW`, `MSVC`, `CMAKE_HOST_WIN32`, `CMAKE_HOST_APPLE`, `CMAKE_HOST_UNIX` | various | Platform branches (RPATH style, sanitizer errors, Valgrind, Windows libs for `app_paths`, MinGW test DLL paths, toolchain hints). |

---

## Preprocessor definitions your code receives

Not CMake variables, but made from them, and the way their values reach C++.

| Definition | On | From |
|------------|----|------|
| `<PREFIX>_VERSION_STRING="<PROJECT_VERSION>"` | every compiled library (PRIVATE) and app (PRIVATE) | `pk_configure_libraries`, `pk_create_app` |
| `<NAME>_STATIC_DEFINE` | static libraries, PUBLIC (consumers get it too) | `pk_configure_libraries`; also in the `.pc` file's `Cflags` and Conan's `package_info` |
| `<NAME>_SHARED_DEFINE` | shared libraries, PUBLIC | `pk_configure_libraries` |
| `<name>_EXPORTS` | the `<name>_shared` target while it builds (`DEFINE_SYMBOL`) | `pk_add_library_targets`; a single SHARED target gets CMake's default `<name>_EXPORTS` |
| `_GLIBCXX_ASSERTIONS`, `_FORTIFY_SOURCE=3`, `_SECURE_SCL=1` | everything linking `<project>::options` | `<PREFIX>_HARDENING` |
| `<NAME>_EXPORT`, `<NAME>_NO_EXPORT`, `<NAME>_DEPRECATED`, ... | code including `<name>/export.hpp` | `generate_export_header` in `pk_create_library` |
| `<name>::app_name`, `<name>::app_version` (C++ constants) | code including `<name>/app_paths.hpp` | `pk_add_app_paths` |

---

# Part 2: Kit-internal variables

These are set and read by the kit for its own use. Changing them breaks
assumptions the kit makes; reading them from your code ties you to kit
internals that may change between releases.

## Kit-wide internals

| Variable | Kind | Origin | Purpose and flow |
|----------|------|--------|------------------|
| `PK_MODULE_DIR` | cache INTERNAL | `ProjectKit.cmake` (`CMAKE_CURRENT_LIST_DIR`) | The kit folder. Read by `pk_write_pkgconfig` and `pk_install_package` (default templates), `pk_setup_static_analysis` (launcher path), `pk_add_app_paths` (app_paths templates). Cache so it is right from any function, whatever directory calls it. |
| `PK_PREFIX` | normal | `pk_project_setup`, `pk_add_options_target`, `pk_setup_tooling` (macros) | `<PREFIX>` for the macros, which can't use a local. Left in your top-level scope afterwards. Functions use a local `prefix` from `pk_project_prefix` instead. |
| `PK_TREE_DEFAULTS` | normal (file scope of `Layout.cmake`, visible everywhere after `include(ProjectKit)`) | `Layout.cmake` | `part=path` pairs of the classic tree (`kit=cmake/projectkit`, `headers=include`, `sources=src`, `apps=apps`, `tests=tests`, ...). `_pk_tree_load` starts from them, then applies `.pk/tree.conf`. `scripts/pklib/tree.py` keeps the same list; a test checks they agree. |
| `PK_DEPS_KINDS` | normal | `Dependencies.cmake` | `requires test tool`: the valid `kind` values in `deps.json`. |

## Cached internals and check results

| Variable | Kind | Origin | Purpose and flow |
|----------|------|--------|------------------|
| `<PREFIX>_COMPILER_LIKE_GNU` | cache INTERNAL | `pk_add_options_target` | ON when `CMAKE_CXX_COMPILER_FRONTEND_VARIANT` is `GNU` (GCC, Clang, AppleClang, IntelLLVM). Chooses GNU or MSVC flags in options, sanitizers, coverage, reproducibility, size reduction; read by `pk_setup_tooling`. |
| `<PREFIX>_COMPILER_IS_MSVC` | cache INTERNAL | same | ON for the MSVC front end (cl, clang-cl). Restricts sanitizers to `address`, picks MSVC fuzz flags, refuses Valgrind/AFL. |
| `<project>_has_c_<flag>` | cache INTERNAL (`check_cxx_compiler_flag`) | `pk_try_compile_option` | One per probed compile flag, for example `mncb_has_c__fstack_protector_strong`. Cached, so each flag is tested once per tree. |
| `<project>_has_l_<flag>` | cache INTERNAL (`check_linker_flag`) | `pk_try_link_option` | Same for link flags, for example `mncb_has_l_LINKER__z_relro` (fails on MinGW). |
| `<PREFIX>_HAS_SANITIZE_<list>` | cache INTERNAL | `pk_add_options_target` | Whether the toolchain can build and link with the requested sanitizers. |
| `<PREFIX>_HAS_LIBFUZZER` | cache INTERNAL | `pk_setup_tooling` | Whether a libFuzzer program links. |
| `<PREFIX>_LIBRARY_TYPE_FOLLOWS_BUILD_SHARED_LIBS` | normal (top-level scope) | `pk_project_setup` | TRUE when `<PREFIX>_LIBRARY_TYPE` was empty and derived from `BUILD_SHARED_LIBS`. `pk_check_shared_intent` only checks the Conan intent in that case. |
| `<PREFIX>_TOOLCHAIN_SHARED` | normal | `include()` of `<generators>/<project>_intent.cmake`, written by `conanfile.py` `generate()` | Conan's `shared` option (`ON`/`OFF`) at the last `conan install`. `pk_check_shared_intent` stops configure when it differs from the cached `BUILD_SHARED_LIBS`, because CMake never overwrites a cached `BUILD_SHARED_LIBS` and the tree would link the wrong binaries. |

## Variables the setup macros leave in your top-level scope

`pk_project_setup`, `pk_add_options_target`, `pk_setup_tooling` and
`pk_enable_cpack` are macros, so their scratch variables stay visible after
they return. They are prefixed `_pk_`/`_PK_` to avoid clashes; don't rely on
them.

| From | Variables |
|------|-----------|
| `pk_project_setup` | `_pk_one_value_args`, `_PK_CXX_STANDARD`, `_PK_C_STANDARD`, `_PK_LIBRARY_TYPE`, `_PK_UNPARSED_ARGUMENTS`, `_PK_KEYWORDS_MISSING_VALUES` (the last two from `cmake_parse_arguments`, only when there are any), `PK_PREFIX` |
| `pk_add_options_target` | `_pk_target` (`<project>_options`), `_pk_gnu_ids`, `_pk_gnu_like`, `_pk_msvc`, `_pk_compiler` (the matching generator expression), `_pk_sanitizer_list`, `_pk_sanitizer`, `_pk_conflict`, `_pk_sanitize_flag`, `_pk_sanitize_probe`, `_pk_lang`, `_pk_config`, `_pk_flags_var`, `_pk_ipo_supported`, `_pk_ipo_error` |
| `pk_setup_tooling` | `_pk_tooling_labels`, `_pk_valgrind_command`, `_pk_tests_dir`, `_pk_fuzz_flag`, `_pk_fuzz_no_link_flag`, `_pk_compiler_name`, `_pk_tooling_summary` |
| `pk_enable_cpack` | `_pk_one_value_args`, `_pk_multi_value_args`, `_PK_PACKAGE_FILE_NAME`, `_PK_VENDOR`, `_PK_GENERATORS`, `_PK_SOURCE_GENERATORS`, `_PK_SOURCE_IGNORE_FILES`, `_PK_UNPARSED_ARGUMENTS` |

## Standard CMake variables the kit sets

Normal variables set in your top-level scope (so they apply to every target
created afterwards). You *can* change them after `pk_project_setup`, but the
kit's other parts assume these values.

| Variable | Value | Set in | Why |
|----------|-------|--------|-----|
| `CMAKE_CXX_STANDARD`, `CMAKE_C_STANDARD` | `<PREFIX>_CXX_STANDARD`/`_C_STANDARD`, if not already set | `pk_project_setup` | One standard for the whole project. |
| `CMAKE_CXX_STANDARD_REQUIRED`, `CMAKE_C_STANDARD_REQUIRED` | ON | `pk_project_setup` | No silent fallback to an older standard. |
| `CMAKE_CXX_EXTENSIONS`, `CMAKE_C_EXTENSIONS` | OFF | `pk_project_setup` | `-std=c++23`, not `gnu++23`. |
| `CMAKE_CXX_SCAN_FOR_MODULES` | OFF | `pk_project_setup` | No C++20 module scanning step. |
| `CMAKE_RUNTIME_OUTPUT_DIRECTORY` | `${PROJECT_BINARY_DIR}/bin` | `pk_project_setup` | Executables and DLLs in one folder, mirroring the install `bin/` (what `app_paths` relies on). |
| `CMAKE_LIBRARY_OUTPUT_DIRECTORY`, `CMAKE_ARCHIVE_OUTPUT_DIRECTORY` | `${PROJECT_BINARY_DIR}/lib` | `pk_project_setup` | Mirrors the install `lib/`. Also why your exe's import library lands in `lib/`. |
| `CMAKE_INSTALL_RPATH` | `$ORIGIN/../<libdir>` (`@loader_path/...` on macOS) | `pk_project_setup` | Installed programs find their shared libraries relative to themselves. |
| `CMAKE_INSTALL_RPATH_USE_LINK_PATH` | TRUE native, FALSE cross | `pk_project_setup` | Native installs keep paths to dependencies outside the prefix. |
| `CMAKE_BUILD_WITH_INSTALL_RPATH` | TRUE (cross only) | `pk_project_setup` | Cross binaries use the install RPATH from the start. |
| `CMAKE_INTERPROCEDURAL_OPTIMIZATION` | TRUE | `pk_add_options_target`, when `<PREFIX>_LTO` | LTO for every target below. |
| `CMAKE_C_COMPILER_LAUNCHER`, `CMAKE_CXX_COMPILER_LAUNCHER` | `<PREFIX>_COMPILER_CACHE` | `pk_add_options_target`, when `<PREFIX>_CCACHE` and none set | ccache/sccache. |
| `CMAKE_<LANG>_FLAGS_<CONFIG>` (`RELEASE`, `RELWITHDEBINFO`, `MINSIZEREL`) | `/O2` -> `/O2 /Oy-`, `/O1` -> `/O1 /Oy-` | `pk_add_options_target`, MSVC + sanitizers | Keeps frame pointers for ASan stack traces. |
| `CMAKE_REQUIRED_LINK_OPTIONS`, `CMAKE_REQUIRED_FLAGS` | the flag under test, then `unset` | `pk_add_options_target`, `pk_setup_tooling` | Inputs to `check_cxx_compiler_flag`/`check_cxx_source_compiles`. |
| `CMAKE_MODULE_PATH`, `CMAKE_PREFIX_PATH` | whatever `find_package` changed | `pk_deps_find` (`PARENT_SCOPE`) | Behave as if you called `find_package`. |
| `<Pkg>_*`, `<PKG>_*`, `<pkg>_*` | `find_package` results | `pk_deps_find` (`PARENT_SCOPE`) | Same. |
| `CPACK_PACKAGE_NAME`, `CPACK_PACKAGE_VERSION`, `CPACK_PACKAGE_DESCRIPTION_SUMMARY`, `CPACK_VERBATIM_VARIABLES` | from `PROJECT_*`, ON | `pk_enable_cpack` (top-level project only) | Package metadata. |
| `CPACK_PACKAGE_VENDOR` | `VENDOR` argument | `pk_enable_cpack` | Only when given. |
| `CPACK_PACKAGE_FILE_NAME` | `PACKAGE_FILE_NAME` argument, else `<project>-<version>-<system>-<processor>` | `pk_enable_cpack` | Archive name. |
| `CPACK_GENERATOR`, `CPACK_SOURCE_GENERATOR` | `GENERATORS` / `SOURCE_GENERATORS` arguments, else `TGZ;ZIP` / `TGZ` | `pk_enable_cpack` | |
| `CPACK_SOURCE_IGNORE_FILES` | `.git`, `build`, `stage`, `_install`, `.conan-cache`, `.vscode` + `SOURCE_IGNORE_FILES` | `pk_enable_cpack` | Keeps generated output out of source packages. |

Control the `CPACK_*` values through `pk_enable_cpack`'s arguments: they are
set right before `include(CPack)`, so a `set()` after the call is too late.

## Values passed between functions

| Variable | Kind | Set by | Read by | Purpose |
|----------|------|--------|---------|---------|
| `<NAME>_LIBRARY_TARGETS` | local of the caller (`PARENT_SCOPE`) | `pk_add_library_targets` | `pk_create_library` | The real targets: `<name>`, or `<name>_static` + `<name>_shared`. |
| `<NAME>_EXPORT_HEADER_TARGET` | same | `pk_add_library_targets` | `pk_create_library` | Target `generate_export_header` runs on (the shared one for `STATIC+SHARED`); empty for header-only/interface. |
| `PROJECT_NAME` (shadowed) | local | `_pk_deps_write_report` | the same function | The deferred report runs after the project's scope is gone, so it sets `PROJECT_NAME` from its argument to make `pk_get_state` find the project's state. |
| `ARG_*` | local | `cmake_parse_arguments(ARG ...)` in each function | the same function | One per keyword of the function's signature. |
| `OUT_VAR`-style outputs | caller's variable | helpers such as `pk_tree_dir`, `pk_resolve_files`, `pk_get_state` | the caller | The kit's way of returning values. |

## Template placeholders

Variables set only so that `configure_file` / `configure_package_config_file`
can substitute them as `@VAR@`.

### `templates/app_paths/*.in` (`pk_add_app_paths`)

| Placeholder | Value | Example |
|-------------|-------|---------|
| `PK_APP_NAMESPACE` | `NAME` as a C identifier | `mncb` |
| `PK_APP_NAME` | `NAME`; per-user folder name and `app_name` | `mncb` |
| `PK_APP_VERSION` | `PROJECT_VERSION` | `0.1.0` |
| `PK_APP_BIN_TO_ROOT` | `bin` dir -> root, relative, from `CMAKE_INSTALL_BINDIR` | `..` |
| `PK_APP_DATADIR` | `CMAKE_INSTALL_DATADIR` (or `share` if absolute) | `share` |

### `templates/pkgconfig.pc.in` (`pk_write_pkgconfig`)

| Placeholder | Value |
|-------------|-------|
| `PK_PC_PREFIX` | `${pcfiledir}/<relative path to the prefix>`, or the absolute prefix when `CMAKE_INSTALL_LIBDIR` is absolute |
| `PK_PC_EXEC_PREFIX` | `${prefix}` |
| `PK_PC_LIBDIR`, `PK_PC_INCLUDEDIR` | `${prefix}/<libdir>`, `${prefix}/<includedir>` (or absolute) |
| `PK_PC_NAME`, `PK_PC_DESCRIPTION`, `PK_PC_VERSION` | package name, description, `PROJECT_VERSION` |
| `PK_PC_REQUIRES` | `PKGCONFIG_REQUIRES` joined with `, ` |
| `PK_PC_LIBRARY_NAME` | the target's `OUTPUT_NAME`, else the package name |
| `PK_PC_CFLAGS` | ` -D<NAME>_STATIC_DEFINE` for a static library |

### `templates/PackageConfig.cmake.in` (`pk_install_package`)

| Placeholder | Value |
|-------------|-------|
| `PACKAGE_INIT` | from `configure_package_config_file` (CMake) |
| `PK_PACKAGE_NAME` | the package name (`<project>`) |
| `PK_EXPORT_FILE` | `<export set>.cmake` (`<project>Targets.cmake`) |
| `PK_PACKAGE_DEPENDENCIES` | set to empty, **not used** by the template (the dependencies go to `<package>Dependencies.cmake` instead) |

A project's own `cmake/<package>Config.cmake.in` or `cmake/<package>.pc.in`
replaces the kit's template and sees the same variables.

## Kit state in global properties

The kit keeps per-project state in global properties instead of variables, so
any function in any directory can reach it. `pk_set_state(KEY ...)` writes
`PK_<project>_<KEY>`; `pk_get_state(KEY out)` reads it.

| Property | Written by | Read by | Holds |
|----------|-----------|---------|-------|
| `PK_<project>_DEFAULT_LINKS` | `pk_project_setup` | `pk_link_targets` | `<project>::warnings;<project>::options`, linked into every created target unless `NO_DEFAULT_LINKS` |
| `PK_<project>_CLANG_TIDY_COMMAND` | `pk_setup_static_analysis` | `pk_enable_static_analysis` | the full clang-tidy command, or empty |
| `PK_<project>_CPPCHECK_COMMAND` | same | same | the full cppcheck command, or empty |
| `PK_<project>_VALGRIND_COMMAND` | `pk_setup_tooling` | `pk_add_valgrind_test` | the valgrind command, or empty |
| `PK_<project>_TOOLING_LABELS` | `pk_setup_tooling` | **nothing** | `valgrind`, `fuzz` |
| `PK_<project>_LIBRARY_TARGETS` | `pk_register_targets(LIBRARY ...)` (`pk_create_library`) | `pk_create_test`, `pk_pkgconfig_target`, deps report | library targets |
| `PK_<project>_INSTALLED_LIBRARY_TARGETS` | `pk_create_library` when installing | `pk_install_package` | targets whose dependencies go into `<package>Dependencies.cmake` |
| `PK_<project>_APPLICATION_TARGETS`, `PK_<project>_TEST_TARGETS`, `PK_<project>_TOOL_TARGETS` | the creators | deps report | targets per role |
| `PK_<project>_DEPS_LOADED` | `_pk_deps_load` | `_pk_deps_load` | load-once guard |
| `PK_<project>_DEPS_MANIFEST` | `_pk_deps_load` | error messages, report | manifest path |
| `PK_<project>_DEPS_HAVE_MANIFEST` | `_pk_deps_load` | `_pk_deps_require` | whether it exists |
| `PK_<project>_DEPS_NAMES` | `_pk_deps_load` | everything in `Dependencies.cmake` | package names |
| `PK_<project>_DEPS_<pkg>_REF`, `_KIND`, `_PACKAGE`, `_VERSION`, `_COMPONENTS`, `_TARGETS`, `_TRANSITIVE_HEADERS` | `_pk_deps_load` | `pk_deps_find`, `pk_deps_link`, `pk_deps_export_find_calls`, report | one `deps.json` entry |
| `PK_<project>_DEPS_TARGET_OWNER_<target>` | `_pk_deps_load` | link-graph walk, export, report | which package owns an imported target |
| `PK_TREE_LOADED:<root>` | `_pk_tree_load` | `_pk_tree_load` | load-once guard per project root |
| `PK_TREE:<root>:<part>` | `_pk_tree_load` | `pk_tree_dir`, `pk_tree_base_dir` | a part's folder, relative to `<root>` |
| `PK_TREE_OMIT:<root>` | `_pk_tree_load` | `pk_tree_has` | parts the tree leaves out |

Two directory properties are also appended: `CMAKE_CONFIGURE_DEPENDS` gets
`.pk/tree.conf` and `deps.json`, so editing either re-runs CMake.

## presets.cmake (the pk query script)

`scripts/helpers/pk/presets.cmake`, run by pk with `cmake -P` so Python never
parses `CMakePresets.json` itself.

| Variable | Kind | Purpose |
|----------|------|---------|
| `PK_QUERY` | `-D` from pk | `dirs` (binary dir and toolchain file of a preset), `configure-presets`, `test-presets` |
| `PK_PRESET` | `-D` from pk | the preset name for `dirs` |
| `PK_PRESETS_FILE` | `-D` from pk, default `CMakePresets.json` | the file to read |
| `pk_json` | normal | the file's text |

The script's own scope also holds `index`, `binary_dir` and `toolchain` for the `dirs` query. Results are printed as `-- pk|<value>` lines, which pk picks out.

## QCDXConfigVersion.cmake

Implements `find_package(QCDX <version>)` compatibility: before 1.0 the
minor version must match, from 1.0 the major version.

| Variable | Kind | Purpose |
|----------|------|---------|
| `PACKAGE_VERSION` | standard output | from `projectkit/VERSION` |
| `PACKAGE_VERSION_COMPATIBLE`, `PACKAGE_VERSION_EXACT` | standard outputs | the answer |
| `PACKAGE_FIND_VERSION`, `PACKAGE_FIND_VERSION_MAJOR`, `PACKAGE_FIND_VERSION_MINOR`, `PACKAGE_FIND_VERSION_RANGE`, `PACKAGE_FIND_VERSION_MIN`, `PACKAGE_FIND_VERSION_MAX`, `PACKAGE_FIND_VERSION_RANGE_MAX` | standard inputs | what the caller asked for |
| `_qcdx_ok`, `_qcdx_major`, `_qcdx_minor`, `_qcdx_have`, `_qcdx_want` | scratch, unset at the end | |

The root `CMakeLists.txt` also uses a scratch `_qcdx_version` (the version
read for `project()`).

The toolchain file `aarch64-linux-gnu.cmake` has one scratch variable,
`helpful_hint`, the install hint shown when the cross compiler isn't found.

---

# Part 3: Appendix

## Function-local variables

Every variable that exists only inside one function call. `ARG_*` stands for
the `cmake_parse_arguments` results, one per keyword of the function (plus
`ARG_UNPARSED_ARGUMENTS`); the `ARG_` names listed separately are keywords the
function *rewrites* (fills in defaults or resolves to absolute paths) before
using them.

| File | Function | Locals |
|------|----------|--------|
| Layout.cmake | `_pk_tree_load` | `entry`, `pair`, `part`, `path`, `file`, `lines`, `line`, `value`, `loaded` |
| Layout.cmake | `pk_tree_dir` | `ARG_*`, `ARG_ROOT`, `path` |
| Layout.cmake | `pk_tree_has` | `ARG_*`, `ARG_ROOT`, `omit` |
| Layout.cmake | `pk_tree_base_dir` | `part_dir`, `inside`, `parent` |
| ConanBuildDir.cmake | `pk_require_conan_build_dir` | `ARG_*`, `one_value_args`, `given_type`, `given_type_lower`, `known_types`, `build_type`, `candidate`, `candidate_lower`, `build_type_lower`, `toolchain`, `generators_dir`, `conan_dir`, `build_root`, `dependency_data`, `matching`, `data_file`, `data_name` |
| ProjectSetup.cmake | `pk_project_prefix` | `prefix` |
| ProjectSetup.cmake | `pk_register_targets` | `ARG_*` |
| ProjectSetup.cmake | `pk_get_targets`, `pk_get_state` | `found` |
| ProjectSetup.cmake | `pk_link_targets` | `ARG_*`, `options`, `multi_value_args`, `default_links`, `t`, `target_type`, `pub`, `priv` |
| ProjectSetup.cmake | `pk_check_shared_intent` | `prefix`, `generators_dir`, `intent`, `cached_shared` |
| CompilerWarnings.cmake | `pk_add_warnings_target` | `prefix`, `target`, `gnu_ids`, `gnu_common`, `gnu_c`, `gnu_cxx`, `msvc_c`, `msvc_cxx` |
| ProjectOptions.cmake | `pk_try_compile_option`, `pk_try_link_option` | `probe` (the cache entry name) |
| StaticAnalysis.cmake | `pk_analyser_version` | `version_banner` |
| StaticAnalysis.cmake | `pk_setup_static_analysis` | `prefix`, `clang_tidy_command`, `cppcheck_command`, `tidy_version`, `cppcheck_version` |
| StaticAnalysis.cmake | `pk_enable_static_analysis` | `clang_tidy_command`, `cppcheck_command` |
| Tooling.cmake | `pk_add_valgrind_test` | `valgrind_command` |
| HostTools.cmake | `pk_require_host_tools` | `ARG_*`, `ARG_PACKAGE`, `one_value_args` |
| HostTools.cmake | `pk_add_generated_source` | `ARG_*`, `ARG_TOOL`, `one_value_args`, `multi_value_args`, `out`, `target`, `target_type` |
| FileCollection.cmake | `pk_collect_components` | `ARG_*`, `options`, `one_value_args`, `sources`, `private_headers`, `public_headers` |
| FileCollection.cmake | `pk_resolve_files` | `resolved`, `path`, `path_lower` |
| FileCollection.cmake | `pk_resolve_language` | `source_languages`, `path`, `language` |
| LibraryCreator.cmake | `pk_add_library_targets` | `ARG_*`, `one_value_args`, `multi_value_args`, `NAME_UPPER`, `local_library_targets`, `local_export_target` |
| LibraryCreator.cmake | `pk_configure_libraries` | `ARG_*`, `ARG_LANGUAGE`, `ARG_PUBLIC_BASE_DIR`, `ARG_PRIVATE_BASE_DIR`, `one_value_args`, `multi_value_args`, `prefix`, `std_C`, `std_CXX`, `BASE_NAME`, `BASE_NAME_UPPER`, `target`, `target_type`, `pub`, `source_language` |
| LibraryCreator.cmake | `pk_create_library` | `ARG_*`, `ARG_EXPORT_SET`, `ARG_KIND`, `ARG_SOURCE_DIR`, `ARG_INCLUDE_DIR`, `ARG_SOURCES`, `ARG_PUBLIC_HEADERS`, `ARG_PRIVATE_HEADERS`, `ARG_NAME_UPPER`, `options`, `one_value_args`, `multi_value_args`, `prefix`, `flags_selected`, `linkage`, `require_sources`, `require_public_headers`, `require_private_headers`, `header`, `source_dir_given`, `include_dir_given`, `sources_dir`, `headers_dir`, `globbed_sources`, `globbed_public_headers`, `globbed_private_headers`, `explicit_files`, `globbed`, `language`, `source_languages`, `target_list_var`, `export_target_var`, `export_header`, `public_base_dir`, `private_base_dir`, `default_links`, `install_file_sets`, plus `<NAME>_LIBRARY_TARGETS` and `<NAME>_EXPORT_HEADER_TARGET` |
| AppPaths.cmake | `pk_add_app_paths` | `ARG_*`, `one_value_args`, `multi_value_args`, the `PK_APP_*` placeholders, `build_bin_to_root`, `multi_config`, `template_dir`, `generated_root`, `out_dir`, `target`, `target_type` |
| ApplicationCreator.cmake | `pk_create_app` | `ARG_*`, `ARG_TARGET_NAME`, `ARG_OUTPUT_NAME`, `ARG_SOURCES`, `ARG_PUBLIC_HEADERS`, `ARG_PRIVATE_HEADERS`, `ARG_SOURCE_DIR`, `ARG_INCLUDE_DIR`, `options`, `one_value_args`, `multi_value_args`, `prefix`, `target_count`, `output_count`, `unique_targets`, `unique_outputs`, `unique_target_count`, `unique_output_count`, `header`, `source_dir_given`, `include_dir_given`, `apps_dir`, `source_where`, `include_where`, `globbed_sources`, `globbed_public_headers`, `globbed_private_headers`, `explicit_files`, `globbed`, `language`, `source_languages`, `app_languages`, `app_language`, `std_C`, `std_CXX`, `public_base_dir`, `private_base_dir`, `target`, `output`, `default_links`, `target_list` |
| TestCreator.cmake | `pk_toolchain_dll_dirs` | `dirs`, `compiler`, `compiler_dir` |
| TestCreator.cmake | `pk_create_test` | `ARG_*`, `ARG_LABEL`, `ARG_SOURCE_DIR`, `ARG_BASE_DIR`, `ARG_SOURCES`, `options`, `one_value_args`, `multi_value_args`, `prefix`, `tests_dir`, `globbed_sources`, `globbed_private_headers`, `libraries`, `library_variants`, `library`, `default_links`, `dll_dirs`, `discover_args`, `test_target` |
| ToolCreator.cmake | `pk_create_tool` | `ARG_*`, `ARG_NAME_SEPARATORS`, `ARG_SOURCES`, `ARG_ALIAS`, `ARG_ROUT_DIR`, `ARG_EXPORT_NAME`, `ARG_EXPORT_NAMESPACE`, `ARG_EXPORT_FILE`, `options`, `one_value_args`, `multi_value_args`, `escaped_separators`, `separator`, `escaped`, `separator_regex`, `name_pieces`, `source_files`, `globbed_sources`, `globbed_private_headers`, `globbed`, `export_name_piece`, `pieces_length`, `namespace_length`, `namespace_pieces`, `namespace_string`, `file_prefix` |
| Dependencies.cmake | `_pk_json_quote`, `_pk_json_get` | `value` (+ `err`) |
| Dependencies.cmake | `_pk_json_array` | `items`, `type`, `err`, `where`, `count`, `last`, `i`, `item` |
| Dependencies.cmake | `_pk_deps_fail` | `manifest` |
| Dependencies.cmake | `_pk_deps_load` | `loaded`, `manifest`, `json`, `schema`, `err`, `count`, `names`, `all_targets`, `last`, `i`, `name`, `ref`, `at`, `kind`, `kinds`, `cmake_type`, `pkg`, `version`, `components`, `targets`, `extra_targets`, `t`, `flag`, `transitive_headers` |
| Dependencies.cmake | `_pk_deps_require` | `names`, `have`, `manifest`, `known` |
| Dependencies.cmake | `pk_deps_find` | `name`, `kind`, `pkg`, `version`, `components`, `targets`, `missing`, `t`, `find_args`, `pkg_upper`, `pkg_lower`, `pkg_re`, `pkg_upper_re`, `pkg_lower_re`, `vars_after`, `var`, `seen` |
| Dependencies.cmake | `pk_deps_link` | `ARG_*`, `all`, `name`, `kind`, `where`, `t`, `type`, `scope`, `dep_targets`, `keyword`, `th` |
| Dependencies.cmake | `_pk_deps_clean_items` | `out`, `item` |
| Dependencies.cmake | `_pk_deps_project_target` | `result`, `item`, `aliased`, `imported` |
| Dependencies.cmake | `_pk_deps_link_items` | `items`, `type`, `raw` |
| Dependencies.cmake | `pk_deps_export_find_calls` | `queue`, `seen`, `packages`, `item`, `items`, `project_target`, `owner`, `lines`, `name`, `kind`, `pkg`, `version`, `components`, `line` |
| Dependencies.cmake | `_pk_deps_write_report` | `PROJECT_NAME` (shadow), `names`, `manifest`, `json`, `q`, `name`, `pkg_json`, `field`, `value`, `key`, `used`, `role`, `role_targets`, `root`, `type`, `t_json`, `interface_items`, `raw_interface`, `private_items`, `raw`, `direct_seen`, `unmanaged`, `item`, `owner`, `project_target`, `vis`, `cleaned`, `existing`, `index`, `queue`, `chains`, `visited`, `via`, `kind` |
| Packaging.cmake | `pk_pkgconfig_target` | `libraries`, `chosen`, `library`, `library_type` |
| Packaging.cmake | `pk_write_pkgconfig` | `ARG_*`, `ARG_PACKAGE`, `ARG_DESCRIPTION`, `ARG_TEMPLATE`, `ARG_TARGET`, `one_value_args`, `multi_value_args`, `cmake_dir`, `package_upper`, `target_type`, the `PK_PC_*` placeholders |
| Packaging.cmake | `pk_install_package` | `ARG_*`, `ARG_PACKAGE`, `ARG_NAMESPACE`, `ARG_EXPORT_SET`, `ARG_COMPATIBILITY`, `ARG_DESCRIPTION`, `ARG_CONFIG_TEMPLATE`, `options`, `one_value_args`, `multi_value_args`, `cmake_dir`, `PK_PACKAGE_NAME`, `PK_EXPORT_FILE`, `PK_PACKAGE_DEPENDENCIES`, `exported_targets`, `find_calls`, `dependency`, `dependencies_file`, `dependencies_text`, `call`, `config_template_text`, `includes_dependencies`, `call_count` |
| Packaging.cmake | `pk_link_compile_commands` | `link_result` |
| presets.cmake | `pk_length` | `length`, `error` |
| presets.cmake | `pk_find` | `length`, `last`, `index`, `candidate` |
| presets.cmake | `pk_resolve` | `index`, `value`, `error`, `kind`, `parents`, `count`, `last`, `position`, `parent`, `inherited` |
| presets.cmake | `pk_expand` | `text` |
| presets.cmake | `pk_list_names` | `length`, `last`, `index`, `name`, `hidden`, `error` |

## Function parameters

Named parameters are variables inside their function too. `ARGN` (the
arguments after the named ones) is used by the functions that take variable
lists, and `cmake_parse_arguments` reads from it.

| File | Function | Parameters |
|------|----------|------------|
| Layout.cmake | `_pk_tree_load` | `ROOT` |
| Layout.cmake | `pk_tree_dir`, `pk_tree_has` | `OUT_VAR`, `PART` |
| Layout.cmake | `pk_tree_base_dir` | `OUT_VAR`, `PART`, `DIR` |
| ProjectSetup.cmake | `pk_project_prefix` | `OUT_VAR` |
| ProjectSetup.cmake | `pk_register_targets` | `KIND` |
| ProjectSetup.cmake | `pk_get_targets` | `KIND`, `OUT_VAR` |
| ProjectSetup.cmake | `pk_set_state` | `KEY` (value in `ARGN`) |
| ProjectSetup.cmake | `pk_get_state` | `KEY`, `OUT_VAR` |
| ProjectOptions.cmake | `pk_try_compile_option`, `pk_try_link_option` | `target`, `condition`, `flag` |
| StaticAnalysis.cmake | `pk_analyser_version` | `OUT_VAR`, `program` |
| StaticAnalysis.cmake | `pk_enable_static_analysis` | `target` |
| Tooling.cmake | `pk_add_valgrind_test` | `target` |
| FileCollection.cmake | `pk_collect_components` | `NAME` |
| FileCollection.cmake | `pk_resolve_files` | `OUT_VAR`, `LABEL`, `PATTERN` (files in `ARGN`) |
| FileCollection.cmake | `pk_resolve_language` | `OUT_LANGUAGE`, `OUT_SOURCE_LANGUAGES`, `LABEL`, `REQUESTED` (sources in `ARGN`) |
| LibraryCreator.cmake | `pk_add_library_targets` | `NAME` |
| TestCreator.cmake | `pk_toolchain_dll_dirs` | `out_var` |
| Dependencies.cmake | `_pk_json_quote` | `OUT_VAR`, `value` |
| Dependencies.cmake | `_pk_json_get` | `OUT_VAR`, `json`, `default` (path in `ARGN`) |
| Dependencies.cmake | `_pk_json_array` | `OUT_VAR`, `json` (path in `ARGN`) |
| Dependencies.cmake | `_pk_deps_fail` | `name`, `message_text` |
| Dependencies.cmake | `_pk_deps_require` | `name` |
| Dependencies.cmake | `_pk_deps_clean_items`, `pk_deps_export_find_calls` | `OUT_VAR` (items in `ARGN`) |
| Dependencies.cmake | `_pk_deps_project_target` | `OUT_VAR`, `item` |
| Dependencies.cmake | `_pk_deps_link_items` | `OUT_VAR`, `target`, `property` |
| Dependencies.cmake | `_pk_deps_write_report` | `project` |
| Packaging.cmake | `pk_pkgconfig_target` | `OUT_VAR`, `PACKAGE` |
| presets.cmake | `pk_status` | `text` |
| presets.cmake | `pk_length` | `out` (JSON path in `ARGN`) |
| presets.cmake | `pk_find` | `section`, `name`, `out` |
| presets.cmake | `pk_resolve` | `name`, `field`, `out` |
| presets.cmake | `pk_expand` | `text`, `preset`, `out` |
| presets.cmake | `pk_list_names` | `section` |

The public creators (`pk_create_library`, `pk_create_app`, `pk_create_test`,
`pk_create_tool`, `pk_add_app_paths`, `pk_add_generated_source`,
`pk_install_package`, `pk_write_pkgconfig`, `pk_enable_cpack`,
`pk_require_conan_build_dir`, `pk_require_host_tools`, `pk_deps_link`) take
only keyword arguments, which arrive as the `ARG_<KEYWORD>` (or `_PK_<KEYWORD>`
for the macros) variables listed above.

## Problems found while documenting

1. **`<PREFIX>_SA_OUTPUT=files` with clang-tidy fails to configure.**
   `<PREFIX>_SA_LAUNCHER` is a two-item list (`<python>;<launcher.py>`), but
   `pk_setup_static_analysis` checks it with `EXISTS` as if it were one path,
   which is always false, and then would prepend `sh` to it. Reproduced:
   `-D<PREFIX>_SA_CLANG_TIDY=ON -D<PREFIX>_SA_OUTPUT=files` stops with
   "the launcher script is missing". It looks like a leftover from the bash
   launcher; checking only the second item and dropping the `sh` prefix would
   fix it. cppcheck's `files` mode doesn't use the launcher and is unaffected.
2. **`<PREFIX>_FUZZ_SECONDS` is never read**, and nothing creates fuzz targets
   or links `<project>::fuzzing`. The state `PK_<project>_TOOLING_LABELS` is
   also written and never read.
3. **`PK_PACKAGE_DEPENDENCIES`** is set for `PackageConfig.cmake.in` but the
   template doesn't use it.
4. **`<PREFIX>_BUILD_TYPE`** (the template's `OUT_BUILD_TYPE`) is set and never
   read, and `CONAN_BUILD_DIR` is cached but never read by the kit.
5. **`PK_DEPS_MANIFEST`** only changes the CMake side; Conan keeps reading
   `deps.json`. It is also undocumented.
6. **`<PREFIX>_CXX_STANDARD`** looks like the switch for the C++ standard, but
   in a pk project the Conan profile's `compiler.cppstd` always overrides it.
7. **`<PREFIX>_REDUCE_SIZE`'s description** says "and unroll loops"; it does no
   loop unrolling (and has the typo "unecessary").
8. **The setup macros leave about thirty `_pk_*`/`_PK_*` variables** in the
   top-level scope. Harmless today, but functions (or a final `unset`) would
   keep the scope clean.
