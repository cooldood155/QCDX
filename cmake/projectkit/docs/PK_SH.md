# pk.sh

One command line for every day-to-day workflow of a projectkit'd project. `pk`
decides which Conan and CMake steps a request needs, runs only those, and
prints every command before it runs it.

```bash
./scripts/pk.sh build            # deps + configure + build, Debug
./scripts/pk.sh run -- --help    # build the app and run it
./scripts/pk.sh test release     # Release, tests on, then ctest
./scripts/pk.sh stage            # install into stage/, check it, write a report
./scripts/pk.sh full-clean       # remove everything the project generated
./scripts/pk.sh help build       # every flag 'build' accepts
```

## Install as a shell command

```bash
echo 'eval "$(/path/to/project/scripts/pk.sh shell-init)"' >> ~/.bashrc
```

This defines a `pk` function that runs the nearest `scripts/pk.sh` above the
**current directory**, `pk build` then works anywhere inside the project, with
tab completion for commands, flags, build types and app names.

If you want to define a `pk` function that works in any `QCDX` templated
project, save the funtion to a file once, then nothing depends on where the
script is located. Replace `$HOME` with any absolute prefix you wish:

```bash
grep -n '.pk.bash' ~/.bashrc
/path/to/project_or_global/scripts/pk.sh shell-init > "$HOME/.pk.bash"
printf '\n# ProjectKit pk command\n[ -f "$HOME/.pk.bash" ] && . "$HOME/.pk.bash"\n' >> "$HOME/.bashrc"
source "$HOME/.bashrc"
type pk
```

## Commands

| Command     | What it does                                                    |
|-------------|-----------------------------------------------------------------|
| `build`     | deps, configure and build, each only when needed                |
| `run`       | build one app (`<name>_app`) and run it, args after `--`        |
| `test`      | turn tests on, build, run ctest (`-R`, `-L`, args after `--`)   |
| `configure` | deps, then always reconfigure (args after `--` go to CMake)     |
| `deps`      | Conan install for one build type (args after `--` go to Conan)  |
| `install`   | build, then `cmake --install` into `stage/` or `--prefix`       |
| `stage`     | fresh install into `stage/`, checked like verify, with a report |
| `rebuild`   | delete the build tree, then build                               |
| `clean`     | delete one tree; `--deps` also its Conan output                 |
| `full-clean`| delete everything the project generates (`clean --all` too)     |
| `analyze`   | clang-tidy + cppcheck build in `build/<preset>-analyze`         |
| `memcheck`  | Valgrind-labelled tests in `build/<preset>-memcheck` (Linux)    |
| `sanitize`  | tests with sanitizers in `build/<preset>-sanitize`              |
| `format`    | clang-format all C/C++ files, `--check` only reports            |
| `status`    | build trees, their options, Conan output, compile_commands.json |
| `list`      | build types, apps, cross targets and whether each is ready      |
| `doctor`    | required and optional tools; `--fix` creates Conan's profile    |
| `verify`    | runs `scripts/verify.sh` with the given arguments               |
| `package`   | runs `scripts/package.sh` with the given arguments              |
| `rename`    | runs `scripts/bootstrap.sh` with the given arguments            |
| `shell-init`| prints the `pk` function and completion for `~/.bashrc`         |

Shortcuts: `b` build, `r` run, `t` test, `c` configure, `i` install,
`st` status, `ls` list, `fmt` format, `purge` or `distclean` full-clean,
plus any *unambiguous* prefix.

Build types are `debug` (`d`), `release` (`r`), `relwithdebinfo` (`rwd`) and
`minsizerel` (`msr`), given as a bare word or with `-t`. The default is Debug.

## What pk decides for you

**Dependencies.** After each install pk writes `build/<Type>/pk-deps.stamp`
with a checksum of `conanfile.py` and the profiles used. Conan runs again only
when that checksum changes, the toolchain is missing, `--update` is given, or
the tests need Catch2 and the last install skipped it. Without tests pk passes
`tools.build:skip_test=True` and `tools.graph:skip_test=True`, so Catch2 is
neither downloaded nor built.

**Configure.** CMake is configured only when the tree is new, its last
configure did not finish, the dependencies were reinstalled, `--reset` is
given, or a flag asks for a value the CMake cache does not already define.
Repeating a flag **costs nothing**.

**Options are remembered per tree.** They live in the tree's CMake cache,
`pk build --werror` followed by `pk run` keeps `-Werror` without rebuilding.
`--reset` returns the tree to its defaults. Tests start off; `test`,
`memcheck` and `sanitize` turn them on, and they stay on until `--no-tests`.

**Cross builds.** `-x NAME` uses `profiles/NAME` and the `NAME-<type>` preset.
pk first builds the host tools natively in the same build type (the
`host-tools` preset), then installs the cross dependencies and builds. Binaries
cannot be run: `run`, `test`, `memcheck` and `sanitize` refuse `-x`.

**Variants.** `--variant=NAME` builds in `build/<preset>-NAME`, a separate tree
with its own remembered options. `analyze`, `memcheck` and `sanitize` use one
automatically so your normal tree keeps compiling quick.

## stage: a checked install you can parse

`stage` builds the tree you work in (remembered options untouched), then runs
the same checks as `verify.sh`'s install and consumer stages:

1. `stage/` is emptied and the tree is installed into it; every file is listed.
2. The package files `pk_expected_install_files` names (Config, ConfigVersion,
   Targets, `.pc`) must exist, and `pkg-config` must read the `.pc` when it is
   installed. Skipped when `<PREFIX>_LIBRARY_TYPE=NONE` or `<PREFIX>_INSTALL=OFF`.
3. verify's consumer project is built against `stage/` with `find_package` and
   run. Skipped for cross builds and with `--no-consumer`.

Everything, including each check, is written to `stage/pk-stage.txt`, one
`kind|field|value` record per line:

```text
meta|type|Release
meta|preset|native-release
file|lib/cmake/qcdx/qcdxConfig.cmake
check|pkg-config reads qcdx.pc|pass
check|run consumer (Release)|pass
result|passed
```

```bash
grep '^check|' stage/pk-stage.txt | grep -v '|pass$'   # anything not passing
sed -n 's/^file|//p' stage/pk-stage.txt                # installed files
sed -n 's/^result|//p' stage/pk-stage.txt              # passed or failed
```

The exit status is non-zero when any check fails. `pk status` shows the last
report's type, preset, time and result. `install` stays the quick version: no
emptying, no checks, any `--prefix`.

## full-clean: everything the project generates

`full-clean` lists what exists, with sizes, asks, then removes:

- `build/` (every tree, variant, host-tools tree and Conan output)
- `stage/` (or `PK_STAGE_DIR`), `_install/` and `compile_commands.json`
- verify's scratch directory and its consumer project under `$TMPDIR`
- `cmake/projectkit/test_package/build/` from `package.sh create`
- `.cache/clangd/` (clangd's index), `CMakeUserPresets.json`,
  `ConanPresets.json`, `.ninja_deps`, `.ninja_log`
- other CMake build directories: `build-*`, `cmake-build-*`
- sanitizer logs in the project root: `asan.log.*`, `ubsan.log.*`

`--cache` also removes this package from the local Conan cache (what
`package.sh create` put there). `-n` only lists, `-y` skips the question, and
without a terminal pk refuses to delete unless `-y` is given.

The list is explicit on purpose. `git clean -X` would also delete ignored files
the build does not own, like `.vscode/` or `docs/notes/`; those are printed
afterwards as "left alone" so nothing is hidden, but never touched.

## Flags

| Flag                                | Meaning                                         |
|-------------------------------------|-------------------------------------------------|
| `-t`, `--type=TYPE`                 | build type                                      |
| `-x`, `--cross=NAME`                | cross target from `profiles/`                   |
| `--variant=NAME`                    | separate build tree                             |
| `--tests`, `--no-tests`             | build the test suite                            |
| `--apps`, `--no-apps`               | build `apps/`                                   |
| `--lib=static\|shared\|both\|none`  | library artifacts                               |
| `--werror`, `--lto`, `--coverage`   | project options (each has `--no-...`)           |
| `--sanitize=LIST`, `--no-sanitize`  | e.g. `address,undefined`                        |
| `--analyze`, `--no-analyze`         | clang-tidy + cppcheck in this tree              |
| `-O`, `--option NAME=VALUE`         | sets `<PREFIX>_NAME`, e.g. `-O LTO=ON`          |
| `-D NAME=VALUE`                     | any CMake cache variable                        |
| `--reset`                           | reconfigure from scratch                        |
| `--update`                          | reinstall dependencies                          |
| `-j`, `--jobs=N`                    | parallel jobs for build and ctest               |
| `--target=NAME`                     | build one target, repeatable                    |
| `-R`, `--filter` / `-L`, `--label`  | ctest selection                                 |
| `--prefix=DIR`                      | install location                                |
| `--no-consumer`                     | `stage` without the consumer project            |
| `--cache`                           | `full-clean` also empties the Conan cache entry |
| `-y`, `--yes`                       | delete without asking                           |
| `-n`, `--dry-run`                   | print commands only                             |
| `-v`, `--verbose`                   | full compiler command lines                     |

Each command accepts only the flags that mean something to it; anything else
is an error that names the command's help page.

## Configuration

`scripts/helpers/pk/pk.conf` is sourced when present:

```bash
PK_DEFAULT_TYPE=Release                  # instead of Debug
PK_DEFAULT_JOBS=8                        # default -j
PK_STAGE_DIR=stage                       # install's default prefix
PK_NATIVE_PROFILE=native                 # profiles/<name> for native builds
PK_FORMAT_EXCLUDE="cmake/projectkit/ build/ stage/ _install/"
```

`NO_COLOR=1` turns colors off.

## Limits

- Changes to `~/.conan2/profiles/default` are not tracked; use `--update`.
- `build/host-tools` is one tree for every build type (following `verify.sh`),
  switching a cross build's type rebuilds it.
- `compile_commands.json` follows the most recently configured tree, variant
  trees included.
- `tools.graph:skip_test` is marked experimental by Conan.

Compatible with bash 3.2 (macOS `/bin/bash`), like the rest of the kit.
