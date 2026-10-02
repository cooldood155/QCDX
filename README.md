# QCDX

[![verify](https://github.com/cooldood155/QCDX/actions/workflows/verify.yml/badge.svg)](https://github.com/cooldood155/QCDX/actions/workflows/verify.yml)

A template for C and C++ projects built on **projectkit**, a set of CMake
modules and scripts under `cmake/projectkit/`. A fresh copy already contains a
working library, application, test and build-time tool, so it configures,
builds, tests, installs and packages before you start writting code.

- **CMake 3.30+, Ninja and Conan 2**, with presets for native builds, host
  tools and cross builds.
- **One call per target**: `pk_create_library`, `pk_create_app`,
  `pk_create_test` and `pk_create_tool` find their sources, headers and
  settings by convention.
- **C and C++**: C++ libraries, C libraries, and C interfaces implemented in
  C++, each with a generated export header (`export.hpp` or `export.h`).
- **Static, shared or both** from one build, chosen per project or pinned per
  library.
- **Checks built in**: warnings, hardening, sanitizers, clang-tidy, cppcheck,
  Valgrind and coverage, each one option away.
- **`pk`**, one command line for all of it, Conan and CMake never have to be
  typed by hand.

## Requirements

| Tool | Version |
| :-- | :-- |
| CMake | 3.30 or newer |
| Ninja | any recent |
| Conan | 2.x |
| Git | any recent |
| Compiler | GCC 13+, Clang 18+, AppleClang 15+ or MSVC 19.30+ |

The default standards are C++23 and C23. Every supported OS, architecture and
toolchain combination is listed in [`docs/BUILDING.md`](docs/BUILDING.md).

## Quick start

Create a repository from the template, then clone it:

```bash
gh repo create my-project --template cooldood155/QCDX --public --clone
cd my-project
```

Without the GitHub CLI, press **Use this template** on GitHub and clone the
new repository.

Give the project its own name. The rename covers directories, file names and
file contents, and refuses to run on a dirty tree so `git diff` shows exactly
what it changed:

```bash
./scripts/pk.sh rename myproject --description="What this project is" --version=0.1.0
git diff --stat
```

Check the tools, then build, run and test:

```bash
./scripts/pk.sh doctor
./scripts/pk.sh build
./scripts/pk.sh run
./scripts/pk.sh test
```

The first `build` installs the Conan dependencies and configures CMake; later
builds only rebuild. Every Conan and CMake command `pk` runs is printed before
it runs, and `-n` prints them without running anything.

Then replace this README with your own project's.

## Everyday commands

| Command | What it does |
| :-- | :-- |
| `pk build [TYPE]` | install dependencies, configure and build, each only when needed |
| `pk run [APP] -- ARGS` | build one application and run it |
| `pk test [TYPE]` | build with tests and run them with ctest |
| `pk stage` | install into `stage/`, check the package and write a report |
| `pk dep ...` | add, change, remove, update and inspect third-party packages |
| `pk status` | the build trees, their options and dependency state |
| `pk sync` | pull projectkit updates from this template |
| `pk full-clean` | remove everything the build generated |
| `pk help COMMAND` | every flag a command accepts |

Build types are `debug` (default), `release`, `relwithdebinfo` and
`minsizerel`. Options such as `--werror`, `--lib=shared` or
`--sanitize=address,undefined` are remembered per build tree.

To type `pk` instead of `./scripts/pk.sh` from anywhere inside any project
made from this template, install the shell function once, as described in
[`PK_SH.md`](cmake/projectkit/docs/PK_SH.md#install-as-a-shell-command).

### Without pk

`pk` only decides which of these steps are needed. They can always be run by
hand:

```bash
./scripts/package.sh install --build_type=Debug
cmake --preset native-debug
cmake --build build/native-debug
ctest --test-dir build/native-debug --output-on-failure
```

## Adding code

Each kind of target lives in its own directory, named after the target:

| Target | Sources | Declared in |
| :-- | :-- | :-- |
| Library | `src/<name>/`, public headers in `include/<name>/` | `src/CMakeLists.txt` |
| Application | `apps/<name>/` | `apps/CMakeLists.txt` |
| Tests (Catch2) | `tests/<name>/` | `tests/CMakeLists.txt` |
| Build-time tool | `tools/` | `tools/CMakeLists.txt` |

```cmake
pk_create_library(NAME myproject REQUIRE_SOURCES REQUIRE_PUBLIC_HEADERS)
pk_create_app(NAME myproject DEFAULT_DIRS LINK_PRIVATE myproject::myproject)
pk_create_test(NAME myproject)
```

A library with a C interface and a C++ implementation takes `LANGUAGE C`: its
public headers are `.h` files, its export header becomes `export.h`, and its
private headers in `src/<name>/` can be C++.

The full walkthrough, including tools and cross builds, is in
[`docs/FROM_ZERO_TO_PROJECT.md`](docs/FROM_ZERO_TO_PROJECT.md).

## Dependencies

Third-party packages are declared once, in `deps.json`, and pinned in
`conan.lock`; both are committed. `conanfile.py` and the CMake creators read
the deps.json.

```bash
pk dep add "sqlite3/[>=3.45 <4]"   # declare, lock (pin) and discover package/target
pk dep ls                          # what is declared, locked and used by what
pk dep why zlib                    # who pulls this package in and who uses it
pk dep update sqlite3              # newest version within the range
pk dep check                       # deps.json, CMake and the lock all match
```

```cmake
pk_create_library(NAME myproject ... DEPS_PRIVATE sqlite3)
```

Versions only change when you ask (`add`, `update`, or a new range); builds
fail rather than resolve past the lock. Details:
[`PK_DEP.md`](cmake/projectkit/docs/PK_DEP.md).

## Cross builds

Each cross target is a Conan profile in `profiles/` plus matching presets:

```bash
pk list
pk build -x x86_64-mingw-w64
```

`pk` builds the host tools natively first, then the cross build. Binaries built
for another system cannot run here, tests are built but not run on cross
builds.

## Verification and CI

`verify.sh` runs the full pipeline for each build type: the preset workflow,
every library type, installation, a consumer project that sees only the
installed files, CPack and the host tools.

```bash
./scripts/verify.sh list
./scripts/verify.sh run --build_type=Debug,Release
```

The same script runs in CI for every push and pull request to `main` that
changes code: on Linux (`x86_64`, `armv8`), macOS (`armv8`) and Windows (MSYS2
UCRT64), and as cross builds for Windows `x86_64` (MinGW-w64) and `arm64`
(llvm-mingw).

## Packaging

```bash
./scripts/package.sh create --build_type=Debug,Release
```

This builds the Conan package, then builds a small consumer against it. Other
projects use it like any Conan package:

```cmake
find_package(myproject REQUIRED)
target_link_libraries(other PRIVATE myproject::myproject)
```

## Keeping projectkit up to date

Every project made from this template carries its own copy of the kit. When
the template improves, bring the changes in with one command:

```bash
pk sync -n
pk sync
```

Only the template's changes are applied, as a 3-way merge, changes made to the
kit in your project are kept. The result is a single commit.

## Layout

```text
my-project/
  CMakeLists.txt           project(), pk_project_setup and the subdirectories
  CMakePresets.json        native, host-tools and cross presets
  conanfile.py             Conan recipe, version read from CMakeLists.txt
  profiles/                Conan profiles: native, cross targets, CI
  include/<name>/          public headers
  src/<name>/              library sources and private headers
  apps/<name>/             applications
  tests/<name>/            tests
  tools/                   build-time tools
  cmake/projectkit/        the kit, updated with pk sync
  scripts/                 pk.sh, verify.sh, package.sh and their settings
  docs/                    guides
```

## Documentation

| Document | Covers |
| :-- | :-- |
| [`docs/FROM_ZERO_TO_PROJECT.md`](docs/FROM_ZERO_TO_PROJECT.md) | from an empty directory to a packaged project |
| [`docs/BUILDING.md`](docs/BUILDING.md) | supported platforms, toolchains and cross targets |
| [`PK_SH.md`](cmake/projectkit/docs/PK_SH.md) | every `pk` command, flag and setting |
| [`PK_DEP.md`](cmake/projectkit/docs/PK_DEP.md) | `deps.json`, `conan.lock`, `pk dep` and `DEPS_*` |
| [`VERIFY_SH.md`](cmake/projectkit/docs/VERIFY_SH.md) | the verification pipeline and its targets |
| [`PACKAGE_SH.md`](cmake/projectkit/docs/PACKAGE_SH.md) | Conan packaging, editable mode and uploads |
| [`ANALYSER_LAUNCHER_SH.md`](cmake/projectkit/docs/ANALYSER_LAUNCHER_SH.md) | clang-tidy and cppcheck integration |

## License

MIT, see [`LICENSE`](LICENSE).
