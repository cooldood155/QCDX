# Local and Cross-Platform Building Workflows

This project can be build natively or cross-compiled, subject to the
constraints below.

## Native Build Support

A **native-build** is one where the build system is also the system that will
consume the built binaries.

Only the following combinations of software and hardware constraints are
able to build this project:

| OS | Arch | Toolchain | ABI | C runtime | Support runtime | C++ runtime | Dynamic analysis |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| Linux | `x86_64` | GCC 13+ | Itanium | glibc 2.31+ | `libgcc_s` | libstdc++ | ASan, UBSan, TSan, Valgrind |
| Linux | `x86_64` | Clang 18+ | Itanium | glibc 2.31+ | `libgcc_s` or compiler-rt | libstdc++ or libc++ | ASan, UBSan, TSan, MSan, libFuzzer |
| Linux | `aarch64` | GCC 13+ | Itanium | glibc 2.31+ | `libgcc_s` | libstdc++ | ASan, UBSan, TSan, Valgrind |
| Linux | `aarch64` | Clang 18+ | Itanium | glibc 2.31+ | `libgcc_s` or compiler-rt | libstdc++ or libc++ | ASan, UBSan, TSan, libFuzzer |
| macOS 13+ | `arm64`, `x86_64` | AppleClang 15+ | Itanium | libSystem | compiler-rt + libunwind | libc++ | ASan, UBSan, TSan, libFuzzer |
| Windows | `x86_64` | MSVC 19.30+ (VS 2022) | MSVC | UCRT | `vcruntime140` | MSVC STL | ASan, libFuzzer |
| Windows | `arm64` | MSVC 19.30+ (VS 2022) | MSVC | UCRT | `vcruntime140` | MSVC STL | ASan |
| Windows | `x86_64` | MSYS2 UCRT64 (GCC 13+) | MinGW | UCRT | `libgcc_s_seh` | libstdc++ | None |
| Windows | `x86_64` | MSYS2 CLANG64 (Clang 18+) | MinGW | UCRT | compiler-rt + libunwind | libc++ | None |
| Windows | `arm64` | MSYS2 CLANGARM64 (Clang 18+) | MinGW | UCRT | compiler-rt + libunwind | libc++ | None |

Static analysis (`clang-tidy`, `cppcheck`) and coverage instrumentation is
available for row from the table above.

**32-bit targets** are unsupported.

**IntelLLVM** is *not listed*; it builds the project on Linux and Windows
x86_64, but adds nothing not covered by GCC and Clang.

---

### Notes on this table

**Windows:**

- `MinGW` is the only ABI this project supports that does **not** have built-in
  sanitizers..
- `MSVC` and `MSYS2` (toolchains) do **not** produce interchangeble object
  files, static libraries or import libraries; artifacts built by MSVC are
  **not** compatible with MSYS2— and vise versa.

**MSYS2** `MINGW64` is **unsupported.** It links `msvcrt.dll`, which has weak
C99 conformance. Use `UCRT64` for GCC or `CLANG64` for Clang.

**MSYS2** `MSYS` is **unsupported.** It is a POSIX emulation layer for the
shell and builds binaries depending on `msys-2.0.dll` and are **not native**
Windows programs.

## Cross-Compiation Support

A **cross-build** is one where the build systems outputted binaries are
expected to be consumed on a different system.

These toolchain families provide different *mechanisms* for cross-compiling:

| Family | Mechanism | Compiler binaries | Sysroot |
| :-- | :-: | :-: | :-: |
| GCC | One toolchain install per target | `<triple>-gcc`, `<triple>-g++` | *Usually* bundled |
| Clang | One install, `--target=` per build | `clang`, `clang++` | Must be supplied |
| MSVC | Host/target toolset via `vcvarsall` | `cl.exe` | Not applicable |
| AppleClang | `-arch` within Apple platforms | `clang` | Bundled SDK |

Supported cross **targets**:

| Target | GNU triple | Clang quadruple | C runtime | C++ runtime |
| :-- | :-: | :-: | :-: | :-: |
| Linux `x86_64` | `x86_64-linux-gnu` | `x86_64-unknown-linux-gnu` | glibc | libstdc++ |
| Linux `aarch64` | `aarch64-linux-gnu` | `aarch64-unknown-linux-gnu` | glibc | libstdc++ |
| Windows `x86_64` | `x86_64-w64-mingw32` | `x86_64-w64-windows-gnu` | UCRT | libstdc++ |
| Windows `aarch64` | `aarch64-w64-mingw32` | `aarch64-w64-windows-gnu` | UCRT | libstdc++ |

Cross builds cannot run their own tests, so **ctest**, **Valgrind** and
**fuzzing** are disabled automatically when `CMAKE_CROSSCOMPILING` is set.

Code generation tools are built for the build system first.

---

### Notes on this table

#### Target Triples (and "quadruples")

**Target triples are IDs** the compiler uses to identify the system the
binaries need to run on.

Historically, this identifier was called a **target triple** because it
featured only three parts: `[Architecture]-[OS]-[Language/Runtime Environment]`.

As systems grew more complex, a fourth field was intorduced placed after the
OS, the **Vendor** field. Most modern compilers now read a ***quadruple***:
`[Architecture]-[OS]-[Language/Runtime Environment]-[Vendor]`.

No matter the number of elements within a "target triple", it is **always**
referred to as a **triple**

- The **Clang quadruple** and **GNU tirple** columns just provide different
  *spellings* for the same target; GNU expects three elements while Clang
  expects four.

## Actually Building

**TODO:** document Conan install and CMake preset *commands* for native and
cross builds.

## Toolchain Internals

The toolchains above differ in how they are structured internally. **This
matters** when reading error messages, debugging, or trying to correct issues
that your toolchain may be causing.

| Toolchain | Driver | Preprocessor | C front-end | C++ front-end | Assembler | Linker |
| :-- | :-: | :-: | :-: | :-: | :-: | :-: |
| GCC | `gcc`, `g++` | `cpp` | `cc1` | `cc1plus` | `as` (GNU as) | `collect2` wrapping `ld` |
| Clang | `clang`, `clang++` | integrated | `clang -cc1` | `clang -cc1` | integrated (LLVM MC) | `lld`, `ld`, or `link.exe` |
| AppleClang | `clang`, `clang++` | integrated | `clang -cc1` | `clang -cc1` | integrated (LLVM MC) | `ld` (ld64 / ld-prime) |
| MSVC | `cl.exe` | `c1.dll`, `c1xx.dll` | `c1.dll` | `c1xx.dll` | integrated (`ml64.exe` standalone) | `link.exe` |

**Toolchain consequences worth knowing:**

- GCC's stages are separate processes. An error pointing out `cc1plus` came
  from the C++ front-end.
- Clang preprocesses, compiles and assembles in one process. There is no
  separate assembler step to fail.
- Clang *on* MinGW invokes GNU `ld` by default *in* MSYS2 `UCRT64`, but `lld`
  in `CLANG64`. `-fuse-ld=lld` can be used to force the lld linker to be used.

**Supporting toolchains, by family:**

| Purpose | GNU | LLVM | MSVC |
| :-- | :-: | :-: | :-: |
| Archiver | `ar`, `gcc-ar` | `llvm-ar` | `lib.exe` |
| Symbol table | `ranlib` | `llvm-ranlib` | built into `lib.exe` |
| Symbol listing | `nm` | `llvm-nm` | `dumpbin /symbols` |
| Strip | `strip` | `llvm-strip` | `/OPT:REF` at link time |
| Object copy | `objcopy` | `llvm-objcopy` | none |
| Disassembly | `objdump` | `llvm-objdump` | `dumpbin /disasm` |
| Dependency listing | `ldd` | `llvm-readelf -d` | `dumpbin /dependents` |

Wehn cross-compiling with GNU toolchains, every one of these has a
**triple-prefixed** form (e.g., `aarch64-linux-gnu-objcopy`) and the unprefixed
*host* version **cannot** be used on target binaries. LLVM tools are
target-agnostic and need no prefix.

## Runtime Redistribution

What **must** reside alongside produced binaries, when *not statically linked*:

| Target | Files needed at runtime |
| :-- | :-- |
| Linux | `libstdc++.so.6`, `libgcc_s.so.1` (usually present) |
| macOS | None; `libSystem` and `libc++` are OS components |
| Windows MSVC | UCRT (OS component on Windows 10+), `vcruntime140.dll`, `msvcp140.dll` |
| Windows MinGW (GCC) | `libstdc++-6.dll`, `libgcc_s_seh-1.dll`, `libwinpthread-1.dll` |
| Windows MinGW (Clang) | `libc++.dll`, `libunwind.dll`, `libwinpthread-1.dll` |

MinGW binaries that run inside an MSYS2 shell but fail when launched from
Windows Explorer are almost always missing thes DLLs on `PATH`. They can be
statically linked using the following flags:

```plaintext
-static-libgcc -static-libstdc++
```

macOS provides no **static** libc and Apple does not support linking one.
