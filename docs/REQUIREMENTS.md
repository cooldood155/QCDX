# Development Requirements

*External tools needed to develope a QCDX (`pk new`) project, along with their
oldest and newest supported versions.*

Every single number in this document comes from a file in *this* repository
(QCDX) or from the tool's source, listed under the **Enforced by** column of
of the table below.

The machines and operating systems the **compiled code runs on** are listed in
[`PLATFORMS.md`](PLATFORMS.md)

## Required

| Tool | Minimum | Maximum | Enforced by |
| :-- | :-- | :-- | :-- |
| Python | 3.9 | none declared | `pyproject.toml` `requires-python`; CI tests 3.9 and 3.13 |
| CMake | 3.30 | none declared | `cmake_minimum_required`, `CMakePresets.json` `cmakeMinimumRequired`, `pk doctor` |
| Conan | 2.4, raised by systems compiler (see below) | < 3 | `pyproject.toml` `tools` extra; features used by the profiles and recipe |
| Ninja | none declared | none declared | every profile sets `generator=Ninja` |
| Git | none declared | none declared | `pk doctor`, `pk new`, `pk sync` |
| C and C++ compiler | see [Compilers](#compilers) | see [Compilers](#compilers) | Conan's profile checks on `compiler.cppstd=23` and `compiler.cstd=23` |

#### `pk doctor`

checks that each of these is on `PATH` and that CMake is version 3.30 or
higher. It does not check the Python, Conan or compiler versions.

#### `pipx install "qcdx[tools]"`

installs Conan, CMake and Ninja along with `pk`, within the same limits
(`conan>=2.0,<3`, `cmake>=3.30`, `ninja`). The system is responsible for
providing a compiler.

### Python

`pk`, `verify.py`, `package.py`, `release.py` and `bootstrap.py` only use the
standard library. Code still parses on Python 3.5, but 3.9 is the version the
package declares and CI tests. The one 3.12-only call
(`shutil.rmtree(onexc=...)`) sits behind version checks.

Configuration with static analysis on (`pk analyze`) looks for `Python3 3.8`
through CMake's `find_package`, and any interpreter that runs `pk` already
satisfies it.

### CMake

| What | Minimum | Why |
| :-- | :-- | :-- |
| A `pk new` project | 3.30 | presets |
| Kit as a CMake package (`find_package(QCDX)`, `cmake --install`) | 3.25 | QCDX's own `CMakeLists.txt` |
| Kit through `FetchContent` | 3.25 | same file; it also uses `CMAKE_FIND_PACKAGE_REDIRECTS_DIR` (3.24) |
| CMake that Conan builds dependencies with | 3.30 to < 5 | `deps.json`: `cmake/[>=3.30 <5]` as a `tool_requires` |

The last row of the table is a Conan package (not CMake on `PATH`). The systems
CMake has no upper bound in the project files (e.g., CMake 4.x works).

### Conan

`pyproject.toml` accepts any Conan 2 version greater than or equal to 2.4.

Conan doesn't accept a `compiler.version` its `settings.yml` doesn't list. The
native profile reads the version from the compiler; newer compilers need newer
Conan:

| Compiler (major) | Oldest Conan version listing it |
| :-- | :-- |
| GCC 14 | 2.3 |
| GCC 15 | 2.16 |
| GCC 16 | 2.29 |
| Clang 18 | 2.2 |
| Clang 19 | 2.8 |
| Clang 20 | 2.14 |
| Clang 21 | 2.20 |
| Clang 22 | 2.27 |
| Clang 23 | 2.33 |
| AppleClang 16 | 2.7 |
| AppleClang 17 | 2.15 |
| AppleClang 21 | 2.28 |

CI pins Conan **2.33.0** (`.github/actions/pk-setup/action.yml`) to cover it
all.

Compilers to oldest supported Conan version (the table above) were found by
checking the last patch release of every Conan 2.x minor line (e.g., the 2.29
lines 2.29.1 patch).

`conan profile detec --force` ran after intalling Conan will generate a default
Conan profile on the system, representing the systems environment details. This
profile serves as a fallback in-case the project's `profiles/native` profile
cannot be found.

## Compilers

Projects build as C++23 by default (`pk_project_setup`). The native profile
sets `compiler.cpstd=23` and `compiler.cstd=23`, and Conan's profile check
only accepts compilers that can provide both. That Conan profile check is what
sets the floor for toolchains below:

| Toolchain | Minimum | Newest Conan 2.33 knows | Limited by |
| :-- | :-- | :-- | :-- |
| GCC | 14 | 16.2 | Conan accepts `cstd=23` only from GCC 14 |
| Clang | 18 | 23 | Conan accepts `cstd=23` only from Clang 18 |
| AppleClang | 15 | 21 | `cppstd=23` from AppleClang 13; 15 is the oldest any QCDX doc lists |
| MSVC | not supported | - | Conan accepts `cstd` 11 and 17 only for MSVC; no verify target uses it |

GCC 13 still works through the profiles that leave out `ompmiler.cstd`:

- Linux cross profiles
- `x86_64-mingw-w64` (Ubuntu 24.04's cross GCC is 13)

`pk_project_setup(C_STANDARD 23)`, in the root CMakeLists.txt file, will still
compile C as C23 there.

`<PREFIX>_CXX_STANDARD` and `<PREFIX>_C_STANDARD` accept 17, 20, 23, 26 and 99,
11, 17, 23. Picking 26 would raise the compiler floor past the table above.

### Cross Toolchains

| Cross target | Toolchain | Version | Source |
| :-- | :-- | :-- | :-- |
| `x86_64-linux-gnu` | `x86_64-linux-gnu-gcc` | GCC 13 (written into profile) | Debian/Ubuntu `g++-x86-64-linux-gnu` |
| `aarch64-linux-gnu` | `aarch64-linux-gnu-gcc` | GCC 13 (written into profile) | Debian/Ubuntu `g++-aarch64-linux-gnu` |
| `x86_64-mingw-w64` | `x86_64-w64-mingw32-gcc` (posix threads) | detected | Debian/Ubuntu `g++-mingw-w64-x86-64` |
| `aarch64-mingw-llvm-w64` | `aarch64-w64-mingw32-clang` | llvm-mingw 20260616 (LLVM 22.1.8), UCRT build | pinned with its SHA-256 in `pk-setup` |

The two Linux cross profiles hard-code `compiler.version=13`. A different GCC
version will build fine, but the produced binaries will still be cached under
GCC 13's package ID until the profile is edited.

## Optional

| Tool | Used by | Minimum | Maximum | Notes |
| :-- | :-- | :-- | :-- | :-- |
| clang-format | `pk format` | 16 | none | `.clang-format` uses `LineEnding` and `InsertNewlineAtEOF` (16) |
| clang-tidy | `pk analyze` | 18 when found by a versioned name | 22 by versioned name | found as `clang-tidy`, or `clang-tidy-22` down to `clang-tidy-18` |
| cppcheck | `pk analyze` | none declared | none | |
| sh | `pk analyze -O SA_OUTPUT=files` | any | - | runs the report launcher |
| ccache or sccache | every build when installed | any | - | turned off with `<PREFIX>_CCACHE=OFF` |
| pkg-config / pkgconf | verify's pkg-config stage | any | - | |
| Valgrind | `pk memcheck` | any | - | Linux only |
| AFL++ | `<PREFIX>_FUZZER=afl` | any | - | needs `afl-clang-fast++` or `afl-g++-fast` as the compiler |
| libFuzzer | `<PREFIX>_FUZZER=libfuzzer` | ships with Clang | - | checked by compiling a probe |
| pre-commit | `.pre-commit-config.yaml` | 3.2.0 | none | hook versions are pinned, see below |
| pipx or uv | installing `pk` globally | any | - | `uvx qcdx` and `pipx run qcdx` run it without installing |
| GitHub CLI (`gh`) | creating a repository from the template | any | - | only for that step |

### Pre-Commit Hooks

The hooks run in pre-commit's environments; these versions don't have to be
installed:

| Hook repository | Pinned revision |
| :-- | :-- |
| `pre-commit/pre-commit-hooks` | v6.0.0 |
| `pre-commit/mirrors-clang-format` | v23.1.3 |
| `astral-sh/ruff-pre-commit` | v0.17.0 |
| `python-jsonschema/check-jsonschema` | 0.38.2 |

## Per Dev Machine

### Linux

```bash
sudo apt install g++-14 cmake ninja-build git python3-pip pipx
pipx install "conan>=2.4,<3"
```

```bash
export CC=gcc-14 CXX=g++-14
```

This is for Ubuntu 24.04, same as CI uses. Its default `cc` is GCC 13, which
the native profile would detect and Conan would then reject for `cstd=23`; the
`export` sends detection to GCC 14 instead of GCC 13. A distribution providing
packaged CMake older than 3.30 needs CMake from `pipx install cmake`, the
`qcdx[tools]` extra, or Kitware's packages.

### macOS

```bash
xcode-select --install
brew install cmake ninja pipx
pipx install "conan>=2.4,<3"
```

AppleClang comes fom Xcode or the Command Line Tools. If `CC` is unset, the
native profile detects AppleClang. Setting `CC` to a Homebrew causes `clang` to
switch the profiles to `compiler=clang`, which `macos-*` targets don't expect
to get.

### Windows (MSYS2)

| MSYS2 environment | Status | Compiler | C++ runtime |
| :-- | :-- | :-- | :-- |
| `UCRT64` | supported, primary | GCC | libstdc++ |
| `CLANG64` | supported | Clang | libc++ |
| `CLANGARM64` | supported (Windows on Arm) | Clang | libc++ |
| `MINGW64` | **unsupported** | GCC | links `msvcrt.dll` |
| `MSYS` | **unsupported** | GCC | links `msys-2.0.dll`, not a native Windows program |

```bash
pacman -S --needed git \
  mingw-w64-ucrt-x86_64-toolchain \
  mingw-w64-ucrt-x86_64-cmake \
  mingw-w64-ucrt-x86_64-ninja \
  mingw-w64-ucrt-x86_64-python-pip \
  mingw-w64-ucrt-x86_64-pkgconf
python -m pip install --break-system-packages "conan>=2.29,<3"
```

Swap `ucrt-x86_64` for `clang-x86_64` (CLANG64) or `clang-aarch64`
(CLANGARM64). MSYS2's Python is marked as *externally managed* (PEP 668), this
is why `pip` needs `--break-system-packages`; `pipx` avoids this.

`pk` chooses the MSYS2 environment from the first compiler found on `PATH`.

`profiles/native` behaves differently outside of an MSYS2 shell. Without
`MSYSTEM` it will fall back to Conan's default detection, which prefers
`CC`/`CXX` and then **MSVC** if Visual Studio is installed. MSVC fails the
`cstd=23` check. From PowerShell or cmd, set `CC`/`CXX` to the MSYS2 compiler
first (CI does also).

## Versions Pinned in CI

| What | Version | Where |
| :-- | :-- | :-- |
| Conan | 2.33.0 | `.github/actions/pk-setup/action.yml` |
| Python (pk-setup, Linux and macOS) | 3.12 | same |
| Python (QCDX pytest) | 3.9 and 3.13 | `.github/workflows/ci.yml` |
| GCC (Linux runners) | 14 (`g++-14`) | `pk-setup` sets `CC=gcc-14` |
| llvm-mingw | 20260616 (LLVM 22.1.8) | `pk-setup` |
| CMake (Linux and macOS) | latest from `lukka/get-cmake` v4.4.2 | `pk-setup` |
| MSYS2 packages | latest at run time (`update: true`) | `pk-setup` |
