# qcdx

Template project built on ProjectKit

## Build

Needs CMake 3.30+, Ninja, Conan 2, Python 3.9+ and a C/C++ compiler (GCC 13+,
Clang 18+ or AppleClang 15+).

```bash
pk doctor          # check the tools
pk build           # install dependencies, configure and build (Debug)
pk run             # run the qcdx application
pk test            # build and run the tests
pk build release   # optimized build
```

`pk` is the global command from `pipx install qcdx`; without it, every command
also works as `./scripts/pk.py ...` (`python scripts\pk.py ...` in PowerShell).
`pk help` lists them all, `pk help COMMAND` every flag of one.

## Layout

| Path | Contents |
| :-- | :-- |
| `include/qcdx/` | public headers |
| `src/qcdx/` | library sources and private headers |
| `apps/qcdx/` | the application |
| `tests/qcdx/` | Catch2 tests |
| `tools/` | build-time tools |
| `deps.json`, `conan.lock` | third-party dependencies (`pk dep add ...`) |
| `profiles/` | Conan profiles: native, cross targets, CI |
| `cmake/projectkit/`, `scripts/*.py` | the kit, updated with `pk sync` |

## Releases

Push a tag that matches `project(VERSION)` in `CMakeLists.txt` and CI builds,
tests and archives every target, then creates a draft GitHub release:

```bash
git tag -s v0.1.0 -m "qcdx 0.1.0"
git push origin v0.1.0
```

Settings: `scripts/helpers/release/release.conf`, details in
[`RELEASE.md`](cmake/projectkit/docs/RELEASE.md).

## Documentation

| Document | Covers |
| :-- | :-- |
| [`PK.md`](cmake/projectkit/docs/PK.md) | every `pk` command, flag and setting |
| [`PK_DEP.md`](cmake/projectkit/docs/PK_DEP.md) | `deps.json`, `conan.lock`, `pk dep` |
| [`VERIFY.md`](cmake/projectkit/docs/VERIFY.md) | the verification pipeline (CI) |
| [`RELEASE.md`](cmake/projectkit/docs/RELEASE.md) | tagged releases |
| [`PACKAGE.md`](cmake/projectkit/docs/PACKAGE.md) | Conan packaging |
