# Generated files

Some of a project's C and C++ files are written by CMake instead of by you.
This guide covers the ones the kit writes, `app_paths` in detail, and how to
write your own.

| File | Written by | For |
| --- | --- | --- |
| `<library>/export.hpp` (`.h` in C) | `pk_create_library` | `<LIB>_EXPORT` and `<LIB>_DEPRECATED` macros |
| `<app>/app_paths.hpp` and `.cpp` | `pk_create_app`, or `pk_add_app_paths` | where the program and its files are |
| anything | `pk_add_generated_source` and your own tool | code produced from a spec at build time |

All of them land in `build/<tree>/generated/<name>/`, which is on the include
path of the targets that use them, so code includes them as `<name>/file.hpp`.
Nothing is ever written into the source tree.

## `app_paths`: where the program and its files are

Every C++ application made with `pk_create_app` gets a generated
`<name>/app_paths.hpp`. One call gives every location the program needs, as
absolute paths, without a single path typed into the code:

```cpp
#include <myproject/app_paths.hpp>

const auto& paths = myproject::app_paths();   // first thing in main() or OnInit()

std::ofstream log{paths.logs / "myproject.log", std::ios::app};
auto icon = paths.resources / "icons" / "app.png";
```

| Member        | What it is                              | Windows                          | macOS                                     | Linux (XDG)                     |
|---------------|-----------------------------------------|----------------------------------|-------------------------------------------|---------------------------------|
| `executable`  | the running binary                      | `...\bin\myproject.exe`          | `.../bin/myproject`                       | `.../bin/myproject`             |
| `bin_dir`     | the folder holding it                   | `...\bin`                        | `.../bin`                                 | `.../bin`                       |
| `root`        | the install prefix, or the build tree   | `bin_dir\..`                     | `bin_dir/..`                              | `bin_dir/..`                    |
| `resources`   | files shipped with the app (read only)  | `root\share\myproject`           | `root/share/myproject`                    | `root/share/myproject`          |
| `config`      | settings                                | `%APPDATA%\myproject`            | `~/Library/Application Support/myproject` | `~/.config/myproject`           |
| `data`        | user data, saved state                  | `%LOCALAPPDATA%\myproject`       | same as `config`                          | `~/.local/share/myproject`      |
| `cache`       | safe to delete at any time              | `%LOCALAPPDATA%\myproject\cache` | `~/Library/Caches/myproject`              | `~/.cache/myproject`            |
| `logs`        | log files                               | `%LOCALAPPDATA%\myproject\logs`  | `~/Library/Logs/myproject`                | `~/.local/state/myproject/logs` |
| `home`        | the user's home folder                  | `%USERPROFILE%`                  | `$HOME`                                   | `$HOME`                         |
| `temp`        | the temporary folder                    | `%TEMP%`                         | `$TMPDIR`                                 | `/tmp`                          |
| `startup_cwd` | the working directory at the first call |                                  |                                           |                                 |

The header also has `app_name` and `app_version` as `std::string_view`
constants.

How it behaves:

- **Found once.** The first `app_paths()` call works everything out; every
  later call returns the same object. A program that never calls it runs no
  code for it at all.
- **Call it early.** `startup_cwd` is the working directory at that first call.
- **Per-user folders exist.** The first call creates `config`, `data`, `cache`
  and `logs` if they are missing, so you can open files in them straight away.
  `resources` is not created: it is the app's own files, put there by you.
- **Errors throw.** `std::system_error` or `std::filesystem::filesystem_error`,
  only from the first call.
- **Opting out.** `pk_create_app(... NO_APP_PATHS)`. C-only applications never
  get it, since the code is C++.
- **Other executables.** For a target made with plain `add_executable`:
  `pk_add_app_paths(NAME mytool TARGETS mytool)`.

### Build tree and install tree

The kit builds executables into `build/<tree>/bin/` and installs them into
`<prefix>/bin/`, the same depth below the root. So `root` is `build/<tree>`
while you run from the build, and the install prefix once installed, with no
change to the code.

`resources` follows `root`, so the build tree needs a copy of your resources
too. Keep them in the source tree, for example `apps/myproject/resources/`, and
in `apps/CMakeLists.txt`:

```cmake
set(myproject_resources "${CMAKE_CURRENT_SOURCE_DIR}/myproject/resources")

# Installed: <prefix>/share/myproject
install(DIRECTORY "${myproject_resources}/"
  DESTINATION "${CMAKE_INSTALL_DATADIR}/myproject")

# Build tree: build/<tree>/share/myproject, refreshed on every build of the app
add_custom_command(TARGET myproject_app POST_BUILD
  COMMAND "${CMAKE_COMMAND}" -E copy_directory_if_different
          "${myproject_resources}"
          "${PROJECT_BINARY_DIR}/${CMAKE_INSTALL_DATADIR}/myproject"
  VERBATIM)
```

With a multi-config generator (Visual Studio, Ninja Multi-Config) the build
tree has an extra `bin/<config>/` level, so `root` is only right once
installed. CMake warns about it. The kit's presets use `Ninja`, which doesn't.

## How it works

### Why the program finds its own location

CMake only runs while you configure. The absolute paths it knows, such as
`build/native-debug` or the install prefix, are facts about *this* machine at
*that* moment. Baked into the program, they would be wrong the moment it is
installed somewhere else, moved, or run by another user.

What CMake does know, and what doesn't change, is the *shape* of the layout.
`GNUInstallDirs` (the kit includes it) says executables go in `bin`, shared data
in `share`. So the work is split:

```plaintext
CMake, while configuring              the program, when it runs
------------------------              -------------------------
CMAKE_INSTALL_BINDIR  = bin           asks the OS for its own path:
CMAKE_INSTALL_DATADIR = share           C:\Apps\myproject\bin\myproject.exe
  bin -> root = ".."                  bin_dir   = C:\Apps\myproject\bin
                                      root      = bin_dir\..  = C:\Apps\myproject
writes ".." and "share"               resources = root\share\myproject
into app_paths.cpp
```

The program gets its own path from the OS: `GetModuleFileNameW` on Windows,
`_NSGetExecutablePath` on macOS, `/proc/self/exe` on Linux. Per-user folders
come from the OS too: known folders on Windows (they return Unicode paths,
unlike `getenv`), the standard `~/Library` folders on macOS, and the XDG
variables with their defaults on Linux.

### When a file can be generated

CMake can write a file at three different moments, and choosing the right one
is most of the job:

| When           | Command                                   | It can use                                                                | Use it for                                                                                          |
|----------------|-------------------------------------------|---------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------|
| configure time | `configure_file`, `file(CONFIGURE)`       | CMake variables: `@VAR@` (and `${VAR}` without `@ONLY`)                   | values that only change when CMake re-runs: version, names, options, layout                         |
| generate time  | `file(GENERATE)`                          | generator expressions: `$<CONFIG>`, `$<TARGET_FILE:t>`, target properties | values that depend on the build type or on a target                                                 |
| build time     | `add_custom_command`, `add_custom_target` | anything a program or `cmake -P` script can find out                      | values that change without CMake re-running: the git commit, a data file, a code generator's output |

Configure and generate time both happen during `cmake --preset ...` (or the
re-run a build triggers). Build time happens during `cmake --build`. A value
generated too early goes stale: a git commit captured by `configure_file` stays
the same until something makes CMake run again.

`app_paths` only needs the layout and the names, which only change when CMake
re-runs, so it uses `configure_file`.

### `pk_add_app_paths`, step by step

The whole thing is [`AppPaths.cmake`](../AppPaths.cmake) and two templates in
[`templates/app_paths/`](../templates/app_paths/).

**1. Set the values.** `configure_file` replaces `@NAME@` with the value of the
CMake variable `NAME` visible where it is called. So the function sets plain
variables:

```cmake
string(MAKE_C_IDENTIFIER "${ARG_NAME}" PK_APP_NAMESPACE)   # usable as a C++ namespace
set(PK_APP_NAME    "${ARG_NAME}")
set(PK_APP_VERSION "${PROJECT_VERSION}")
file(RELATIVE_PATH PK_APP_BIN_TO_ROOT                       # ".."
  "${CMAKE_INSTALL_PREFIX}/${CMAKE_INSTALL_BINDIR}" "${CMAKE_INSTALL_PREFIX}")
set(PK_APP_DATADIR "${CMAKE_INSTALL_DATADIR}")              # "share"
```

The install prefix is only an anchor for working out the difference between
two folders; it never reaches the generated code.

**2. Write the files.** For a template line like

```cpp
constexpr const char* bin_to_root = "@PK_APP_BIN_TO_ROOT@";
```

```cmake
configure_file("${template_dir}/app_paths.cpp.in" "${out_dir}/app_paths.cpp" @ONLY)
```

writes

```cpp
constexpr const char* bin_to_root = "..";
```

Three properties of `configure_file` make it the right tool:

- **It only writes when the content changed.** Re-running CMake doesn't touch
  an unchanged output, so nothing recompiles. (`file(WRITE)` always writes,
  which recompiles everything that includes the file on every configure.)
- **The template becomes a configure dependency.** Edit the `.in` file, run the
  build, and CMake re-runs by itself before compiling.
- **`@ONLY` leaves `${...}` alone**, so C++, shell or CMake text that happens to
  contain `${` is copied as is.

**3. Attach them to the target.** The `.cpp` is just another source:

```cmake
target_sources(myproject_app PRIVATE "${out_dir}/app_paths.cpp")
```

The header goes in a header `FILE_SET`. Its `BASE_DIRS` is
`build/<tree>/generated`, which CMake adds to the include path, and the file's
path below it is how code includes it:

```cmake
target_sources(myproject_app PRIVATE
  FILE_SET    pk_app_paths_myproject
  TYPE        HEADERS
  BASE_DIRS   "${PROJECT_BINARY_DIR}/generated"
  FILES       "${PROJECT_BINARY_DIR}/generated/myproject/app_paths.hpp")
```

A file set also shows the header in IDEs, and for a library a `PUBLIC` file set
is installed and exported with it, which is how `export.hpp` reaches the
library's users.

**4. Keep the linters on your code.** `SKIP_LINTING` keeps clang-tidy and
cppcheck off the generated files. On Windows the targets also link `shell32`
and `ole32`, which the known-folder calls need.

**5. The C++ side.** `app_paths()` holds its result in a function-local
`static`:

```cpp
const AppPaths& app_paths() {
    static const AppPaths paths = resolve();
    return paths;
}
```

C++ guarantees that runs exactly once, on the first call, even when several
threads call it at once. It also never runs before `main()`, so it can't hit
the static initialization order problem, and it costs nothing in a program
that doesn't call it. The helpers live in an anonymous namespace so they don't
clash with anything in the program.

## Making your own

**1. Pick the moment** from the table above.

**2. Put the template in your project**, for example
`cmake/templates/build_info.hpp.in`. Never in `cmake/projectkit/`: `pk sync`
replaces the kit and would delete it.

**3. Generate into `${PROJECT_BINARY_DIR}/generated/<name>/`**, and attach the
result with a file set as above.

The three examples below go in `apps/CMakeLists.txt` after `pk_create_app`.

### Configure time: project information

`cmake/templates/build_info.hpp.in`:

```cpp
#pragma once

namespace myproject {

inline constexpr const char* version     = "@PROJECT_VERSION@";
inline constexpr const char* description = R"pk(@PROJECT_DESCRIPTION@)pk";
inline constexpr const char* compiler    = "@CMAKE_CXX_COMPILER_ID@ @CMAKE_CXX_COMPILER_VERSION@";

} // namespace myproject
```

```cmake
set(gen "${PROJECT_BINARY_DIR}/generated")

configure_file(
  "${PROJECT_SOURCE_DIR}/cmake/templates/build_info.hpp.in"
  "${gen}/myproject/build_info.hpp"
  @ONLY)

target_sources(myproject_app PRIVATE
  FILE_SET    build_info
  TYPE        HEADERS
  BASE_DIRS   "${gen}"
  FILES       "${gen}/myproject/build_info.hpp")
```

```cpp
#include <myproject/build_info.hpp>
```

`description` uses a raw string literal, `R"pk(...)pk"`, because free text can
contain `"` or `\`, which would end or break a normal `"..."` literal.

### Generate time: the build type

Generator expressions are only evaluated by `file(GENERATE)`, and
`file(GENERATE)` doesn't do `@VAR@`. To use both, run them one after the other:
`configure_file` fills in the variables, then `file(GENERATE)` the expressions.

`cmake/templates/build_config.hpp.in`:

```cpp
#pragma once

namespace myproject {

inline constexpr const char* build_type = "$<CONFIG>";
inline constexpr const char* app_file   = "$<TARGET_FILE_NAME:myproject_app>";
inline constexpr bool        werror     = @MYPROJECT_WERROR@;

} // namespace myproject
```

```cmake
if(MYPROJECT_WERROR)
  set(MYPROJECT_WERROR true)
else()
  set(MYPROJECT_WERROR false)
endif()

configure_file(
  "${PROJECT_SOURCE_DIR}/cmake/templates/build_config.hpp.in"
  "${gen}/build_config.hpp.step1"
  @ONLY)

file(GENERATE
  OUTPUT "${gen}/$<CONFIG>/myproject/build_config.hpp"
  INPUT  "${gen}/build_config.hpp.step1")

target_sources(myproject_app PRIVATE
  FILE_SET    build_config
  TYPE        HEADERS
  BASE_DIRS   "${gen}/$<CONFIG>"
  FILES       "${gen}/$<CONFIG>/myproject/build_config.hpp")
```

`$<CONFIG>` is in the output path because a multi-config generator writes one
file per build type, and they mustn't overwrite each other. File set paths take
generator expressions too, so the include path follows the build type.

CMake's `ON`/`OFF` aren't valid C++, which is why `MYPROJECT_WERROR` is turned
into `true`/`false` first.

### Build time: the git commit

A value that changes between builds needs a command that runs on every build.
The command is a small CMake script, so it works the same on every platform.

`cmake/GitInfo.cmake`:

```cmake
# Run at build time:
#   cmake -DSOURCE_DIR=<dir> -DOUTPUT=<file> -P GitInfo.cmake
execute_process(
  COMMAND git rev-parse --short HEAD
  WORKING_DIRECTORY "${SOURCE_DIR}"
  OUTPUT_VARIABLE GIT_COMMIT
  OUTPUT_STRIP_TRAILING_WHITESPACE
  ERROR_QUIET)
if(NOT GIT_COMMIT)
  set(GIT_COMMIT "unknown")
endif()

# file(CONFIGURE) only writes when the text changed, so the app only
# recompiles when the commit does.
file(CONFIGURE OUTPUT "${OUTPUT}" CONTENT [[
#pragma once

namespace myproject {
inline constexpr const char* git_commit = "@GIT_COMMIT@";
}
]] @ONLY)
```

```cmake
add_custom_target(myproject_git_info
  COMMAND "${CMAKE_COMMAND}"
          "-DSOURCE_DIR=${PROJECT_SOURCE_DIR}"
          "-DOUTPUT=${gen}/myproject/git_info.hpp"
          -P "${PROJECT_SOURCE_DIR}/cmake/GitInfo.cmake"
  BYPRODUCTS "${gen}/myproject/git_info.hpp"
  COMMENT "Checking the git commit"
  VERBATIM)

add_dependencies(myproject_app myproject_git_info)
```

- `add_custom_target` has no output file to compare against, so it runs on
  every build. That is the point; the script decides whether anything changed.
- `BYPRODUCTS` tells Ninja which target makes the header. Without it, Ninja
  doesn't know the header comes from somewhere and may compile before it
  exists.
- `add_dependencies` makes the app wait for it.
- The header is under `generated/`, which `app_paths` already put on the app's
  include path. In a target without it, add the folder with a file set or
  `target_include_directories`.

### Header or source?

A value in a header recompiles every file that includes it when it changes. A
value that changes often, like the git commit, can live in a generated `.cpp`
behind a function instead, so only that one file recompiles:

```cpp
// git_info.hpp, written by hand
namespace myproject { const char* git_commit(); }

// generated git_info.cpp
namespace myproject { const char* git_commit() { return "@GIT_COMMIT@"; } }
```

`app_paths` does the same: the layout values sit in the `.cpp`, and the header
only declares `AppPaths` and `app_paths()`.

## Pitfalls

- **Writing into the source tree.** Generated files belong in the build tree.
  In the source tree they end up committed, go stale, and differ between
  builds.
- **`file(WRITE)` for generated sources.** It writes on every configure, so
  everything including the file recompiles every time. Use `configure_file`,
  `file(CONFIGURE)` or `file(GENERATE)`.
- **Backslashes and quotes in strings.** A Windows path like `C:\new` contains
  `\n` to the compiler. Use raw string literals, or forward slashes
  (`cmake_path(CONVERT ... TO_CMAKE_PATH_LIST ...)`).
- **Absolute paths in the program.** A path from CMake describes the machine
  that built it. Fine as information (in an about box), wrong as a place to
  look for files at run time; that is what `app_paths` is for.
- **Forgetting `@ONLY`.** Without it, every `${...}` in the template is replaced
  too, usually with nothing.
- **Templates in the kit folder.** `pk sync` replaces `cmake/projectkit/`. Keep
  yours in your own `cmake/` folder.
- **Leftovers.** A file stays in `build/<tree>/generated/` after you stop
  generating it. It is harmless unless something still includes it; a clean
  build removes it.
