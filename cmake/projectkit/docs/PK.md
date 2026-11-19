# pk.py

One command line for every day-to-day workflow of a projectkit'd project. `pk`
decides which Conan and CMake steps a request needs and runs only those, one
line per step (`--verbose` shows every command and all of its output). When
something fails it says why, how to fix it and where to read more, and
`pk fix` applies the fix.

```bash
./scripts/pk.py build            # deps + configure + build, Debug
./scripts/pk.py run -- --help    # build the app and run it
./scripts/pk.py test release     # Release, tests on, then ctest
./scripts/pk.py stage            # install into stage/, check it, write a report
./scripts/pk.py full-clean       # remove everything the project generated
./scripts/pk.py sync             # pull kit updates from the QCDX template
./scripts/pk.py help build       # every flag 'build' accepts
```

## Install as a shell command

```bash
echo 'eval "$(/path/to/project/scripts/pk.py shell-init)"' >> ~/.bashrc
```

This defines a `pk` function that runs the nearest `scripts/pk.py` above the
**current directory** (or the `pk.py` wherever `.pk/tree.conf` puts the
scripts), `pk build` then works anywhere inside the project, with
tab completion for commands, flags, build types and app names.

If you want to define a `pk` function that works in any `QCDX` templated
project, save the funtion to a file once, then nothing depends on where the
script is located. Replace `$HOME` with any absolute prefix you wish:

```bash
grep -n '.pk.bash' ~/.bashrc
/path/to/project_or_global/scripts/pk.py shell-init > "$HOME/.pk.bash"
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
| `dep`       | manage `deps.json` and `conan.lock`, see `PK_DEP.md`            |
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
| `fix`       | apply the last error's fix, then run the failed command again   |
| `explain`   | what an error code means (`why` too); the last error without one|
| `sync`      | update the kit from the QCDX template, as one commit            |
| `tree`      | show, check, draw or change where each part lives (`TREE.md`)   |
| `verify`    | runs `scripts/verify.py` with the given arguments               |
| `package`   | runs `scripts/package.py` with the given arguments              |
| `release`   | runs `scripts/release.py` with the given arguments              |
| `rename`    | runs `scripts/bootstrap.py` with the given arguments            |
| `shell-init`| prints the `pk` function and completion for `~/.bashrc`         |

Shortcuts: `b` build, `r` run, `t` test, `c` configure, `i` install, `st`
`st` status, `ls` list, `fmt` format, `purge` or `distclean` full-clean,
`upgrade` sync, plus any *unambiguous* prefix.

Build types are `debug` (`d`), `release` (`r`), `relwithdebinfo` (`rwd`) and
`minsizerel` (`msr`), given as a bare word or with `-t`. The default is Debug.

## What pk decides for you

**Dependencies.** After each install pk writes `build/<Type>/pk-deps.stamp`
with a checksum of `conanfile.py`, `deps.json`, `conan.lock` and the profiles
used. Conan runs again only when that checksum changes, the toolchain is
missing, `--update` is given, or the tests need Catch2 and the last install
skipped it. Without tests pk passes `tools.build:skip_test=True` and
`tools.graph:skip_test=True`, so Catch2 is neither downloaded nor built.

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

## Output and errors

Each step is one line; the time is added once it is done:

```text
demo  build  Debug  native  tree build/native-debug
==> deps Debug (native): not installed yet  2.1s
==> configure native-debug: new tree  1.6s
src/demo/core.cpp: In function 'int unused(int)':
src/demo/core.cpp:15:28: warning: unused variable 'y' [-Wunused-variable]
==> build build/native-debug  1.4s, 1 warning
done in 5.3s
```

On a terminal the step's line shows what the tool is doing right now. Only
what needs reading is printed: compiler and CMake warnings when they happen,
messages your own `CMakeLists.txt` prints, failing tests, and the error. The
whole output of every step is kept in `build/pk-logs/<tree>.<step>.log`
(`native-debug.build.log`, ...), overwritten by the next run of that step. On
GitHub Actions a failed step also prints its whole output, folded in a group.

`-v`/`--verbose` shows everything instead: each command line and every line
of its output, live, with the tools at their most detailed (Conan `-vvv`,
CMake `--log-level=TRACE`, `cmake --build -v`, `ctest -VV`). `PK_VERBOSE=1`
in `pk.conf` or the environment makes it the default. `-n` prints the
commands without running them.

When a step fails, the tool's own lines that matter come first (Conan's
`ERROR` lines, CMake's `CMake Error` block, the failed compile), then the
error, always in this shape:

```text
error[PK401]: conan install failed for Debug (native)
   why  Conan's profile plugin rejects compiler.cstd=23 for gcc 13; it takes 99, gnu99, 11, gnu11, 17, gnu17
   fix  set compiler.cstd=17 in profiles/native
        'pk fix' does it for you, then runs the failed command again
    or  use a newer gcc, one Conan allows compiler.cstd=23 for
   log  build/pk-logs/native-debug.deps.log
  docs  https://docs.conan.io/2/reference/extensions/profile_plugin.html
        https://docs.conan.io/2/reference/config_files/profiles.html
        pk explain PK401
```

`why` is the cause pk read from the output, `fix` what to do (commands to
copy, or a change pk can make), `docs` where to read more: this kit's
documents, CMake's and Conan's. Paths and links are clickable in terminals
that support it (`PK_LINKS=0` turns that off).

**pk fix.** The last error is kept in `build/pk-last-error.json`. `pk fix`
shows what it will do, asks, does it (runs the command, or edits the file),
then runs the command that failed again. Typos are fixed the same way:
`pk biuld` and `pk build --wererror` record the command they most likely
meant. Errors only you can fix, like a compile error, are shown again
instead. `pk fix -n` only shows the plan, `pk fix --yes` does not ask. A
command that works afterwards forgets the error.

**pk explain.** Every error has a code; `pk explain PK401` (or `401`) says what
it means, the usual causes and links to read more, online ones included.
Without a code it explains the last error; `pk explain --list` lists them.
The global `pk` explains codes outside a project too.

**Readers.** pk's core knows steps (deps, configure, build, test, install),
not tools. What a tool prints is read by one module per tool in
`scripts/pklib/readers/`: `cmake.py`, `ninja.py`, `compilers.py` (GCC, Clang,
MSVC and their linkers, under any build tool), `ctest.py` and `conan.py`. A
reader explains an error (code, why, fix), picks what a quiet step prints and
which of the tool's lines go above the error, and names the tool's own
documents for `pk explain`. A tool without a reader still works: its output
is printed in full and a failure gets the step's general code. Supporting
another package manager, build tool or compiler is one more module there.

A project can add its own in `scripts/helpers/pk/readers/*.py` (wherever
`pk tree` puts the helpers), loaded after the kit's, e.g. to explain an
error of its own CMake code:

```python
from pklib.problems import fix_hint
from pklib.readers import Diagnosis, reader

@reader("configure", order=5)  # lower runs first; the kit's run at 10 to 70
def no_assets(text, context):
    if "assets/ is missing" in text:
        return Diagnosis("PK500", "the assets were not downloaded", [fix_hint("./get-assets.sh")])
```

| Codes   | About                                                           |
|---------|-----------------------------------------------------------------|
| `PK1xx` | what was typed: commands, flags, values                         |
| `PK2xx` | the project: its tree, presets, settings, cross targets         |
| `PK3xx` | tools and the machine                                           |
| `PK4xx` | dependencies: Conan, `pk dep`, `pk package`                     |
| `PK5xx` | configure: CMake                                                |
| `PK6xx` | build and install: the compiler and linker                      |
| `PK7xx` | run and test                                                    |
| `PK8xx` | `sync` and git                                                  |
| `PK9xx` | the other tools: `tree`, `rename`, `release`, `verify`, `new`   |

## stage: a checked install you can parse

`stage` builds the tree you work in (remembered options untouched), then runs
the same checks as `verify.py`'s install and consumer stages:

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
- `cmake/projectkit/test_package/build/` from `package.py create`
- `.cache/clangd/` (clangd's index), `CMakeUserPresets.json`,
  `ConanPresets.json`, `.ninja_deps`, `.ninja_log`
- other CMake build directories: `build-*`, `cmake-build-*`
- sanitizer logs in the project root: `asan.log.*`, `ubsan.log.*`

`--keep-deps` deletes all of that except Conan's output: every folder in
`build/` that has Conan's toolchain (`build/Debug/`, `build/Release/`, a cross
target's...) and the presets Conan wrote (`CMakeUserPresets.json`,
`ConanPresets.json`). The next build only configures and compiles, nothing is
reinstalled.

`--cache` also removes this package from the local Conan cache (what
`package.py create` put there). `-n` only lists, `-y` skips the question, and
without a terminal pk refuses to delete unless `-y` is given.

The list is explicit on purpose. `git clean -X` would also delete ignored files
the build does not own, like `.vscode/` or `docs/notes/`; those are printed
afterwards as "left alone".

## sync: kit updates from the template

Every project made from QCDX carries its own copy of the kit. `pk sync` brings
the template's later kit changes into it, from anywhere, with nothing but Git:

```bash
pk sync -n                       # what would change, nothing touched
pk sync                          # fetch, merge, commit
pk sync --from /k/Templates/QCDX # a local clone, including unpushed commits
```

1. The template's branch is fetched into `refs/projectkit/upstream`, a ref
   that is never pushed and never checked out.
2. The base is the template commit the kit was last synced to, read from
   `scripts/helpers/pk/upstream.conf`. On the first sync pk finds it: the
   template commit whose kit is closest to this project's, and it lists the
   files that differ locally.
3. Only the template's changes from that base to its newest commit, and only
   in the synced paths (`cmake/projectkit`, `scripts/pk.py`,
   `scripts/verify.py`, `scripts/package.py`), are applied with
   `git apply --3way`. Changes made to the kit in this project are kept.
   In a project whose tree puts the kit or the scripts elsewhere (see
   `TREE.md`), each QCDX path is mapped to where it lives here, and a left
   out `pk-setup` action is skipped.
4. The result is committed as `Sync projectkit from QCDX <commit>`, together
   with the updated `upstream.conf`. Your other uncommitted work is left
   alone and is not part of the commit.

If both sides changed the same lines, the files get conflict markers; resolve
them, `git add` the files and commit with the printed message, or undo the
whole sync with `git reset --merge`.

A sync refuses to start with staged changes, or with uncommitted changes in
the synced paths. In the template repository itself it does nothing. A URL
given with `--from` is remembered for everyone; a local path is used for that
one sync only, so the committed file never points at one person's disk.

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
| `--keep-deps`                       | `full-clean` keeps Conan's output in `build/`   |
| `--cache`                           | `full-clean` also empties the Conan cache entry |
| `-y`, `--yes`                       | do not ask first (delete, `fix`)                |
| `--from=URL\|PATH`                  | `sync` from another template URL or local clone |
| `--branch=NAME`                     | `sync` from another template branch             |
| `--base=COMMIT`                     | `sync` from this template commit, not the guess |
| `--no-commit`                       | `sync` stages the update instead of committing  |
| `-n`, `--dry-run`                   | print commands only                             |
| `-v`, `--verbose`                   | every command and all of its output, live       |

Each command accepts only the flags that mean something to it; anything else
is an error that names the command's help page.

## Configuration

`scripts/helpers/pk/pk.conf` is sourced when present (the paths here are the
classic tree's; `pk tree` shows where they are in this project):

```bash
PK_DEFAULT_TYPE=Release                  # instead of Debug
PK_DEFAULT_JOBS=8                        # default -j
PK_STAGE_DIR=stage                       # install's default prefix
PK_NATIVE_PROFILE=native                 # profiles/<name> for native builds
PK_FORMAT_EXCLUDE="cmake/projectkit/ build/ stage/ _install/"
PK_UPSTREAM_URL=https://github.com/cooldood155/QCDX.git # sync's template
PK_UPSTREAM_BRANCH=main
PK_SYNC_PATHS="cmake/projectkit scripts/pk.py scripts/verify.py scripts/package.py scripts/release.py scripts/bootstrap.py .github/actions/pk-setup"
PK_VERBOSE=1                             # --verbose by default
```

A fork of the template should set `PK_UPSTREAM_URL` to its own repository.

`NO_COLOR=1` turns colors off, `PK_LINKS=0` the clickable links.

## Limits

- Changes to `~/.conan2/profiles/default` are not tracked; use `--update`.
- `build/host-tools` is one tree for every build type (following `verify.py`),
  switching a cross build's type rebuilds it.
- `compile_commands.json` follows the most recently configured tree, variant
  trees included.
- `tools.graph:skip_test` is marked experimental by Conan.

Compatible with bash 3.2 (macOS `/bin/bash`), like the rest of the kit.
