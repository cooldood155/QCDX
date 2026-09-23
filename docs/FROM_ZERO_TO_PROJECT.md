# From an empty directory to a working project

This is the whole path: install the tools, start a repository from the QCDX
template, rename it, build it, add code, verify it, package it, and consume it
from somewhere else.

```text
template: https://github.com/cooldood155/QCDX
```

The template carries ProjectKit under `cmake/projectkit/`, the two driver
scripts, CMake presets, Conan profiles, and a tiny working library, app, test
and tool so that a fresh clone builds before you have written a line of code.
Where this guide uses `qcdx` as the template's own project name, substitute
whatever the template actually uses if it differs.

## 1. Prerequisites

### 1.1 Windows, MSYS2 UCRT64

```bash
pacman -S --needed \
  mingw-w64-ucrt-x86_64-toolchain \
  mingw-w64-ucrt-x86_64-cmake \
  mingw-w64-ucrt-x86_64-ninja \
  mingw-w64-ucrt-x86_64-python-pip \
  git
pip install --user conan
conan --version
```

Everything below runs in the UCRT64 shell. The shell you open decides
`MSYSTEM`, which decides which toolchain is on PATH, which is why the verify
script refuses to build a CLANG64 target from a UCRT64 shell rather than
producing a broken binary.

### 1.2 Linux or macOS

```bash
python3 -m pip install --user conan
conan --version
cmake --version
ninja --version
```

### 1.3 One-time Conan setup

```bash
conan profile detect --force
conan profile show
```

The template ships its own profiles under `profiles/`, and the scripts prefer
`profiles/native` when it exists, so the detected default profile is only a
fallback.

## 2. Create the repository

### 2.1 With the GitHub CLI

```bash
gh repo create cooldood155/my-project \
  --template cooldood155/QCDX \
  --public \
  --clone
cd my-project
```

### 2.2 Without it

Open the template page, press "Use this template", create the repository, then:

```bash
git clone https://github.com/cooldood155/my-project.git
cd my-project
```

### 2.3 Without GitHub at all

```bash
git clone --depth 1 https://github.com/cooldood155/QCDX.git my-project
cd my-project
rm -rf .git
git init
git add -A
git commit -m "start from QCDX template"
```

## 3. Rename the project

```bash
git add -A && git commit -m "start from QCDX template"
./scripts/bootstrap.sh myproject \
  --description="What this project is" \
  --version=0.1.0
git diff --stat
```

The script renames directories, file names and file contents, and refuses to
run on a dirty tree so that `git diff` is a usable review. Add `--dry-run`
first if you want to see the plan. The kit under `cmake/projectkit` is never
touched, because nothing in it carries a project name.

Then check `conanfile.py` for `url` and `package_info`, and rewrite
`README.md`, which still describes the template.

## 4. First build

```bash
./scripts/package.sh install --build_type=Debug
cmake --preset native-debug
cmake --build build/native-debug
ctest --test-dir build/native-debug --output-on-failure
```

What each step is for:

`package.sh install` runs `conan install`, which writes
`build/Debug/generators/conan_toolchain.cmake` plus the dependency data files.
The presets point at that toolchain, so this must happen first.

`cmake --preset native-debug` configures. The pre-`project()` module checks
that the Conan output exists for this build type and that the toolchain file
belongs to it, so a mismatch stops here with a readable message instead of a
confusing error later.

The same thing in one command, which is what the verify script uses:

```bash
cmake --workflow --preset native-debug
```

## 5. Add your own code

### 5.1 A library

Put sources in `src/<project>/` and public headers in `include/<project>/`,
then in `src/CMakeLists.txt`:

```cmake
pk_create_library(
  NAME myproject
  REQUIRE_SOURCES
  REQUIRE_PUBLIC_HEADERS)
```

The kind is deduced from what exists: sources mean a compiled library, public
headers with no sources mean header-only, nothing means an interface library.
Add `LOCKED_STATIC`, `LOCKED_SHARED` or `LOCKED_STATIC_SHARED` to pin the
linkage instead of following `<PREFIX>_LIBRARY_TYPE`.

Public headers need the generated export macro, or a shared build exports
nothing:

```cpp
#include <myproject/export.hpp>

MYPROJECT_EXPORT const char* myproject_version();
```

### 5.2 An application

Sources in `apps/<project>/`, and in `apps/CMakeLists.txt`:

```cmake
pk_create_app(
  NAME myproject
  DEFAULT_DIRS
  LINK_PRIVATE myproject::myproject)
```

`TARGET_NAME` accepts several names when one set of sources should produce more
than one executable, with `OUTPUT_NAME` matched to it one for one.

### 5.3 Tests

Sources in `tests/<project>/`, and in `tests/CMakeLists.txt`:

```cmake
find_package(Catch2 3 REQUIRED)
include(Catch)

pk_create_test(NAME myproject)
```

The creator builds one test executable per library variant, so a
`STATIC+SHARED` build tests both.

### 5.4 A build-time tool

Sources in `tools/`, and in `tools/CMakeLists.txt`:

```cmake
pk_create_tool(
  NAME myproject_codegen
  EXPORT_FILE "${PROJECT_BINARY_DIR}/myprojectHostToolsConfig.cmake"
  SOURCES "codegen.cpp")
```

Tools run on the build machine. When cross compiling, configure a native build
first and point `<project>HostTools_DIR` at its binary directory, which is what
`pk_require_host_tools` looks for.

## 6. Verify

```bash
./scripts/verify.sh list
./scripts/verify.sh run --build_type=Debug
./scripts/verify.sh run --build_type=Debug,Release,RelWithDebInfo,MinSizeRel
```

This runs the full pipeline per build type: workflow, library type matrix,
auto-discovery probe, install, a consumer project that only sees installed
files, CPack, and host tools. Full detail in `VERIFY_SH.md`.

Use `--keep` while debugging so the reset stage does not delete the build tree
you are inspecting.

## 7. Package

```bash
./scripts/package.sh create --build_type=Debug,Release
./scripts/package.sh list
```

`create` builds, packages, and then builds a small consumer against the
packaged result. Full detail in `PACKAGE_SH.md`.

## 8. Consume it from another project

From the cache, in the other project's `conanfile.py`:

```python
def requirements(self):
    self.requires("myproject/0.1.0")
```

Then:

```cmake
find_package(myproject REQUIRED)
target_link_libraries(other PRIVATE myproject::myproject)
```

While developing both at once, skip packaging entirely:

```bash
cd /k/Practice/myproject
./scripts/package.sh editable add

cd /k/Practice/other-project
./scripts/package.sh install --build_type=Debug
```

Remember that consumers resolve an editable at graph time, so re-run `install`
in the consumer after changing the recipe. Source edits alone do not need it.

## 9. Cross builds

Each cross target needs three things, named after one triple:

1. A Conan profile at `profiles/<triple>`.
2. Configure presets named `<triple>-debug`, `<triple>-release` and so on.
3. A record in `cmake/projectkit/scripts/helpers/verify/targets.sh`.

Then:

```bash
./scripts/verify.sh list-possible
./scripts/verify.sh run --cross
./scripts/package.sh create --profile=native --host-profile=x86_64-mingw-w64
```

Cross presets keep Conan output in a per-triple directory rather than
`build/<Type>/`. The pre-`project()` module reads the directory from the
toolchain file rather than guessing it from the build type, which is what makes
that layout work.

## 10. Static analysis

```bash
cmake --preset native-debug -DMYPROJECT_SA_ALL=ON
cmake --preset native-debug -DMYPROJECT_SA_ALL=ON -DMYPROJECT_SA_OUTPUT=files
```

Reports land under `build/native-debug/analysis/`. Full detail in
`ANALYSER_LAUNCHER_SH.md`.

## 11. Updating ProjectKit later

The kit is self-contained, so updating is replacing one directory. Pick one
mechanism per project and stay with it:

```bash
# vendored copy, the template's default
rm -rf cmake/projectkit
git clone --depth 1 https://github.com/cooldood155/QCDX.git /tmp/qcdx
cp -r /tmp/qcdx/cmake/projectkit cmake/projectkit
git add -A && git commit -m "update projectkit"
```

```bash
# submodule, when you want a recorded version
git rm -r cmake/projectkit
git submodule add https://github.com/cooldood155/QCDX.git extern/qcdx
# then point the module path at extern/qcdx/cmake/projectkit in CMakeLists.txt
# and the script wrappers at extern/qcdx/cmake/projectkit/scripts
```

Whatever you choose, the only project-side references to the kit are the
`CMAKE_MODULE_PATH` line in the top-level `CMakeLists.txt` and the `exec` line
in each of the two wrapper scripts.

## 12. Layout reference

```text
my-project/
  CMakeLists.txt                  project(), pk_project_setup, subdirectories
  CMakePresets.json               native-<type>, host-tools, cross presets
  conanfile.py                    recipe, version parsed from CMakeLists.txt
  cmake/
    <project>Config.cmake.in      package config, overrides the kit template
    projectkit/                   the kit, never edited per project
      scripts/
        verify.sh
        package.sh
        analyser-launcher.sh
        helpers/verify/{verify_base.sh,targets.sh}
      templates/
      test_package/
    toolchains/                   cross toolchain files
  profiles/                       conan profiles, one per target
  include/<project>/              public headers
  src/<project>/                  library sources and private headers
  apps/<project>/                 application sources
  tests/<project>/                test sources
  tools/                          build-machine tools
  scripts/
    verify.sh                     wrapper, sets PK_REPO_ROOT
    package.sh                    wrapper, sets PK_REPO_ROOT
    helpers/verify/{verify.conf,consumer.cpp}
    helpers/package/package.conf
```

## 13. First-run checklist

```text
[ ] conan profile detect --force
[ ] rename done and the diff reviewed
[ ] ./scripts/package.sh reference prints <project>/<version>
[ ] ./scripts/package.sh install --build_type=Debug
[ ] cmake --preset native-debug
[ ] cmake --build build/native-debug
[ ] ctest --test-dir build/native-debug
[ ] ./scripts/verify.sh run --build_type=Debug
[ ] ./scripts/package.sh create
[ ] git commit
```

## 14. Troubleshooting the first hour

| symptom | cause |
| ------------------------------------------------------------ | ----- |
| `A build type must be specified` | Configured without a preset. Use `cmake --preset native-debug`. |
| `Conan has not generated dependencies for Debug yet` | `package.sh install --build_type=Debug` has not been run for this build type. |
| `is not the Conan output for that build type` | The preset's toolchain belongs to another build type. Use the matching preset, or pass `-DCMAKE_TOOLCHAIN_FILE` explicitly. |
| `no sources found for '<project>'` | Sources are not under `src/<project>/`, or the rename left a directory behind. |
| Shared build links but the consumer sees undefined symbols | Public headers are missing the `<PROJECT>_EXPORT` macro. |
| `cannot determine the project name` from a script | The script was run outside the project, or `project()` is not in the top-level `CMakeLists.txt`. |
| Two projects in one tree fight over options | They do not. Options are prefixed per project. Check that you are setting `<PROJECT>_BUILD_TESTS`, not a bare `BUILD_TESTS`. |
