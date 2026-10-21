# Supported Platforms

*Every system the compiled code of a QCDX (`pk new`) project can be built for
and run on.*

Platforms are only listed if the project ships a target for it:

- record in `cmake/projectkit/scripts/pklib/targets.py`
- Conan profile(s) for cross targets.

Tools needed on the **development machine** are listed within the
[`REQUIREMENTS.md`](REQUIREMENTS.md) document.

## Overview

| OS            | Arch      | Natively built by                     | Built by cross-compiled with   | Released by default          |
| :--           | :--       | :--                                   | :--                            | :--                          |
| Linux (glibc) | `x86_64`  | `linux-x86_64`                        | `cross-x86_64-linux-gnu`       | yes                          |
| Linux (glibc) | `aarch64` | `linux-armv8`                         | `cross-aarch64-linux-gnu`      | yes                          |
| macOS         | `arm64`   | `macos-armv8`                         | -                              | yes                          |
| macOS         | `x86_64`  | `macos-x86_64`                        | -                              | no                           |
| Windows       | `x86_64`  | `windows-ucrt64`, `windows-clang64`   | `cross-x86_64-mingw-w64`       | yes (`windows-ucrt64`)       |
| Windows       | `arm64`   | `windows-clangarm64`                  | `cross-aarch64-mingw-llvm-w64` | yes (`windows-clangarm64`)   |

"Released by default" corrosponds to the variable `PK_RELEASE_TARGETS` within
`scripts/helpers/releases/release/release.conf`

## Native Targets

Native targets build on the machine its binaries are meant to run on, and runs
tests on the binaries.

| Target | Build machine | Toolchain | ABI | C runtime | C++ runtime |
| :-- | :-- | :-- | :-- | :-- | :-- |
| `linux-x86_64` | Linux `x86_64` | GCC 14+ or Clang 18+ | Itanium | glibc | libstdc++ (GCC), libstdc++ or libc++ (Clang) |
| `linux-armv8` | Linux `aarch64` | GCC 14+ or Clang 18+ | Itanium | glibc | same as above |
| `macos-armv8` | macOS, Apple silicon | AppleClang | Itanium | libSystem | libc++ |
| `macos-x86_64` | macOS, Intel | AppleClang | Itanium | libSystem | libc++ |
| `windows-ucrt64` | Windows `x86_64`, MSYS2 UCRT64 | GCC 14+ | MinGW | UCRT | libstdc++ |
| `windows-clang64` | Windows `x86_64`, MSYS2 CLANG64 | Clang 18+ | MinGW | UCRT | libc++ |
| `windows-clangarm64` | Windows on Arm, MSYS2 CLANGARM64 | Clang 18+ | MinGW | UCRT | libc++ |

## Cross Targets

| Target | Sanitizers | Valgrind | Fuzzing |
| :-- | :-- | :-- | :-- |
| `linux-x86_64` | address, undefined, thread, leak; memory with Clang only | yes | libFuzzer (Clang), AFL++ |
| `linux-armv8` | address, undefined, thread, leak | yes | libFuzzer (Clang), AFL++ |
| `macos-armv8`, `macos-x86_64` | address, undefined, thread | no | AFL++; AppleClang ships no libFuzzer |
| `windows-ucrt64` | none (MinGW GCC ships no sanitizer runtimes) | no | no |
| `windows-clang64` | address, undefined | no | not checked |
| `windows-clangarm64` | not checked | no | not checked |

The table lists what the toolchains provides. The kit does not trust it.
Therefore, each sanitizer and libFuzzer is probed during configuration, and a
missing runtime stops the configuration **with a message**. "Not checked" means
no QCDX target has tried it yet.

clang-tidy, cppcheck, coverage, hardening and LTO are options on every target.
`thread` cannot be combined with `address`, `leak` or `memory` and MSVC only
accepts `address`.

## What Binaries Require at Runtime

| Target | Runs on | Minimum set by | C runtime | C++ runtime | Toolchain DLLs shipped |
| :-- | :-- | :-- | :-- | :-- | :-- |
| `linux-x86_64`, `linux-armv8` | Linux with glibc and libstdc++ at least as new as the toolchain's | the build machine (`PK_RELEASE_RUNNERS`) | glibc (system) | libstdc++ (system), or static with `-static-libstdc++` | none |
| `macos-armv8` | the deployment target, and macOS 11 at the earliest | `PK_RELEASE_MACOS_MIN` | libSystem (system) | libc++ (system) | none |
| `macos-x86_64` | the deployment target | `PK_RELEASE_MACOS_MIN` | libSystem (system) | libc++ (system) | none |
| `windows-ucrt64` | Windows 10 and 11, `x86_64` | fixed | UCRT (system) | libstdc++ | `libstdc++-6.dll`, `libgcc_s_seh-1.dll`, `libwinpthread-1.dll` |
| `windows-clang64` | Windows 10 and 11, `x86_64` | fixed | UCRT (system) | libc++ | `libc++.dll`, `libunwind.dll` |
| `windows-clangarm64` | Windows 11 on Arm | fixed | UCRT (system) | libc++ | `libc++.dll`, `libunwind.dll` |

"(system)" means the library is part of the OS and isn't shipped. Any other
shared library a binary loads (like from a dependency) must be shipped next to
it on every OS.

Cross targets have the same requirements as the native target for their OS and
architecture, except that on Linux the glibc and libstdc++ versions come from
the cross toolchain and not the build machine.

### Linux

A binary needs the newest `GLIBC_x.y` and `GLIBCXX_3.4.x` symbol versions it
references. Those are dependant on the toolchain that built it, not on the
project, and must never be newer than that toolchain's glibc and libstdc++:

- A binary linked against glibc 2.34 or newer needs at least glibc 2.34, which
  rules out distributions older than Ubuntu 22.04, Debian 12 and RHEL 9.
- The default `ubuntu-24.04` runner has glibc 2.39. Building on `ubuntu-22.04`
  instead (`PK_RELEASE_RUNNERS`, e.g. `linux-x86_64=ubuntu-22.04`) lowers that
  to 2.35, but not below 2.34.
- libstdc++ can be a tight limit: GCC 14 builds can reference
  `GLIBCXX_3.4.33`, newer than the libstdc++ in Debian 12 or RHEL 9.
  `-static-libstdc++` removes dependency.

`release.py stage` prints the exact versions for every release and fails when a
binary loads a library from outside the system directories (not shipped next to
it).

### macOS

Unless `PK_RELEASE_MACOS_MIN` sets it (as `MACOSX_DEPLOYMENT_TARGET`), the
deployment target is usually the build machine's SDK version. C++23 library
features can need a newer macOS than the deployment target; the compiler
reports those as availability errors. `release.py stage` reads the `minos` of
every binary and reports the highest.

### Windows

`PK_RELEASE_RUNTIME=bundle` (the default) copies the toolchain DLLs in the
table next to the binaries that load them. `forbid` fails the release instead,
for projects linked with `-static`. A binary that runs inside an MSYS2 shell
but not from Explorer is missing these DLLs.

MSVC and MinGW binaries are not interchangeable: object files, static
libraries and import libraries from one cannot be linked by the other!

## CI/CD Machines

### Verification (`.github/workflows/verify.yml`)

| Target                            | Runner                        |
| :--                               | :--                           |
| `linux-x86_64`                    | `ubuntu-24.04`                |
| `linux-armv8`                     | `ubuntu-24.04-arm`            |
| `macos-armv8`                     | `macos-15`                    |
| `windows-ucrt64`                  | `windows-2022` (MSYS2 UCRT64) |
| `cross-x86_64-mingw-w64`          | `ubuntu-24.04`                |
| `cross-aarch64-mingw-llvm-w64`    | `ubuntu-24.04`                |

### Releases (`release.py`)

| Target                            | Runner                |
| :--                               | :--                   |
| `linux-x86_64`                    | `ubuntu-24.04`        |
| `linux-armv8`                     | `ubuntu-24.04-arm`    |
| `macos-x86_64`                    | `macos-15-intel`      |
| `macos-armv8`                     | `macos-15`            |
| `windows-ucrt64`                  | `windows-2022`        |
| `windows-clang64`                 | `windows-2022`        |
| `windows-clangarm64`              | `windows-11-arm`      |
| `cross-x86_64-linux-gnu`          | `ubuntu-24.04-arm`    |
| `cross-aarch64-linux-gnu`         | `ubuntu-24.04`        |
| `cross-x86_64-mingw-w64`          | `ubuntu-24.04`        |
| `cross-aarch64-mingw-llvm-w64`    | `ubuntu-24.04`        |

`PK_RELEASE_RUNNERS`, within ProjectKit's `scripts/pklib/release.py`, can
replace any of these. Windows signing needs a Windows runner, so the two
`mingw` cross targets cannot create signed releases.

## Unsupported

*Could change in the future.*

| Platform or toolchain             | Reasoning                                                                                          |
| :--                               | :--                                                                                                |
| 32-bit anything                   | no target, profile or toolchain file                                                               |
| MSVC                              | `profiles/native` sets `compiler.cstd=23`, which Conan rejects for MSVC; no target in `targets.py` |
| MSYS2 MINGW64                     | links `msvcrt.dll`, with weak C99 conformance                                                      |
| MSYS2 MSYS                        | builds against `msys-2.0.dll`, not native Windows programs                                         |
| Linux with musl                   | no target                                                                                          |
| macOS universal binaries          | each architecture is a separate target                                                             |
| Windows 8.1 and older             | UCRT is not part of the OS, and nothing is tested there                                            |
| iOS, Android, BSDs, WebAssembly   | no target                                                                                          |

Dependencies could narrow this further. A GUI library such as wxWidgets, for
example, needs the system's GUI libraries on Linux at run time.
