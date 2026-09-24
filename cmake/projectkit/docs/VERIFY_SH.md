# verify.sh

Build verification for a ProjectKit project. It drives one or more *targets*
(native or cross) through a fixed pipeline of *stages*, once per requested
CMake build type, and reports a table of results.

The script knows nothing about any particular project. The project name comes
from the top-level `project()` call; everything else is derived from it or set
in a config file.

```text
cmake/projectkit/scripts/verify.sh entry point, kit side
cmake/projectkit/scripts/helpers/verify/verify_base.sh stages and defaults
cmake/projectkit/scripts/helpers/verify/targets.sh target registry
scripts/verify.sh wrapper, project side
scripts/helpers/verify/verify.conf project settings
scripts/helpers/verify/consumer.cpp optional smoke test
```

## 1. Commands

```bash
./scripts/verify.sh list
./scripts/verify.sh list-possible
./scripts/verify.sh run
./scripts/verify.sh run-possible
./scripts/verify.sh clean
./scripts/verify.sh help
```

| command | what it does |
| --------------- | ------------------------------------------------------------------- |
| `list` | Targets that can run in this shell right now. |
| `list-possible` | Targets this machine could host, ignoring the active MSYS2 environment and missing toolchains. |
| `run` | Verify every runnable target. This is the default when no command is given. |
| `run-possible` | Queue every possible target. Each still re-checks its environment strictly before building. |
| `clean` | Remove generated output only. Verifies nothing. |
| `help` | Usage text. |

The `-possible` variants widen what is *listed and queued*, never what is
*built*. A CLANG64 target queued from a UCRT64 shell stops at the environment
stage rather than compiling against the wrong toolchain, because `MSYSTEM` is
fixed by whichever MSYS2 launcher started the shell and cannot be changed by
assigning to the variable.

## 2. Flags

Flags apply to `run` and `run-possible`.

| flag | meaning |
| --------------------- | ------------------------------------------------------------ |
| `--native` | Only native targets. |
| `--cross` | Only cross targets. |
| `--all` | Both. This is the default. |
| `--keep` | Leave generated output in place instead of running the reset stage. |
| `--build_type=T[,T]` | Build types to verify, separated by `,` or `;`. Default `Debug,Release`. Valid values: `Debug`, `Release`, `RelWithDebInfo`, `MinSizeRel`. |

Only one of `--native`, `--cross` and `--all` may be given.

A `;` list must be quoted, because an unquoted `;` ends the command in bash and
the shell tries to run the second build type as a program. Commas avoid that:

```bash
./scripts/verify.sh run --build_type=Debug,RelWithDebInfo
./scripts/verify.sh run --build_type='Debug;RelWithDebInfo'
```

Naming one or more targets selects exactly those, ignores the kind filters, and
runs them even when they are unavailable. The script prints a warning first:

```bash
./scripts/verify.sh run windows-ucrt64
./scripts/verify.sh run --build_type=MinSizeRel windows-ucrt64 cross-x86_64-mingw-w64
```

## 3. Exit codes

| code | meaning |
| ---- | --------------------------------------------------------- |
| `0` | Every selected target passed every stage. |
| `1` | At least one stage failed. |
| `2` | Usage error: unknown command, unknown target, bad build type, no target selected. |

## 4. The pipeline

Setup stages run once, type stages run once per build type as a self-contained
pipeline, final stages run once at the end.

```text
PK_SETUP_STAGES environment, clean_slate
PK_TYPE_STAGES workflow, library_matrix, auto_discovery, install,
 consumer, cpack, host_tools
PK_FINAL_STAGES reset
```

Cross targets replace the type stages with a shorter list, because they cannot
execute what they build:

```text
PK_TYPE_STAGES host_tools_for_cross, cross_build, library_matrix
```

| stage | what it proves |
| --------------------- | -------------------------------------------------------------------- |
| `environment` | Required tools are on PATH and the target is actually available here. A failure here stops everything; later failures would be noise. |
| `clean_slate` | Removes `build/`, `stage/`, `_install/`, `compile_commands.json`, the scratch directory and the consumer directory. |
| `workflow` | `conan install` for the build type, then `cmake --workflow --preset <prefix>-<type>`, which configures, builds and tests. Also checks that `<PREFIX>_BUILD_TESTS` is not off. |
| `library_matrix` | Configures, builds and runs ctest once per entry in `PK_LIBRARY_TYPES`, so `STATIC`, `SHARED` and `STATIC+SHARED` are all exercised. |
| `auto_discovery` | Writes a probe source into the scratch directory, rebuilds, and checks the file was picked up. This is what proves `CONFIGURE_DEPENDS` globbing works. |
| `install` | Installs to `stage/`, checks every file from `pk_expected_install_files`, prints the `.pc` file and runs `pkg-config` on it when available. |
| `consumer` | Generates a throwaway project that sees only installed files and the Conan dependency configs, calls `find_package`, links the imported target and runs the result. |
| `cpack` | Builds the binary and source packages. |
| `host_tools` | Configures the `host-tools` preset with the current build type and its matching toolchain, which also proves `<PREFIX>_LIBRARY_TYPE=NONE` is guarded. |
| `host_tools_for_cross` | Same, but with the native profile, since host tools run on the build machine. |
| `cross_build` | `conan install`, configure and build with the cross preset. No tests. |
| `reset` | Removes generated output unless `--keep` was given. |

A stage that later stages depend on stops the rest of its list when it
fails. `environment` stops the whole target; `workflow`, `cross_build` and
`host_tools_for_cross` stop the remaining stages for that build type, which
is recorded as a single skip, and the next build type still runs. Any other
stage reports its failure and continues on with the other stages.

Each target runs in a subshell, so per-target configuration and pass/fail
counters cannot leak into the next target.

## 5. Output

Stage headers carry the build type, so a multi-type run is readable:

```text
================ linux-x86_64 [Debug Release] ================

---- 3. [Debug] Workflow ----
OK conan install (Debug)
OK WIDGET_BUILD_TESTS is ON
OK workflow native-debug
```

Failures are recorded with their build type and summarised per target, then
once more as a table across all targets:

```text
---- Linux x86_64, native toolchain ----
passed: 36 skipped: 0
 Debug passed
 Release failed (1)
 - [Release] configure SHARED

======== Overall ========
TARGET BUILD TYPE RESULT
linux-x86_64 Debug passed
linux-x86_64 Release failed (1)
```

The table is assembled through a temporary file, because each target runs in a
subshell whose variables die with it. The file is removed by an `EXIT` trap.

After the run the script prints `git status --short` and `git clean -nd` so you
can see whether anything was left behind. Nothing is deleted by those two.

## 6. Configuration

The base sources the first file that exists from this list, so the settings can
live wherever a project keeps its helper files:

```text
$PK_VERIFY_CONF
$PK_REPO_ROOT/scripts/helpers/verify/verify.conf
$PK_REPO_ROOT/scripts/verify.conf
$PK_REPO_ROOT/.verify.conf
```

Every setting is a plain shell variable, so anything in the config file can
also be given on the command line as an environment variable:

```bash
PK_BUILD_TYPES="Debug" ./scripts/verify.sh run linux-x86_64
```

### 6.1 Identity

| variable | default | purpose |
| ------------------- | ----------------------------------------- | ------- |
| `PK_REPO_ROOT` | set by the project wrapper | Project root. Without it the entry point walks up from the working directory looking for `CMakeLists.txt`. |
| `PK_PROJECT` | the name in `project()` | Project name. Used for the scratch path and the consumer directory. |
| `PK_PACKAGE` | `$PK_PROJECT` | Package name for `find_package`, the installed config files and the `.pc` file. |
| `PK_PREFIX` | `PK_PROJECT` uppercased | Cache variable prefix, as in `ETESCA_LIBRARY_TYPE` and `ETESCA_BUILD_TESTS`. Derived, do not set. |
| `PK_LINK_TARGET` | `$PK_PACKAGE::$PK_PACKAGE` | Imported target the consumer project links. |

### 6.2 Layout

| variable | default | purpose |
| ------------------- | ---------------------------------------------- | ------- |
| `PK_SCRATCH_DIR` | `$PK_REPO_ROOT/src/$PK_PROJECT/scratch` | Where the auto-discovery stage drops its probe source. Point this at a directory that the library globs. |
| `PK_CONSUMER_DIR` | `$TMPDIR/$PK_PROJECT-consumer` | Throwaway consumer project location. |
| `PK_CONSUMER_SOURCE` | empty | Path to a real smoke test. Empty means the consumer is `int main() { return 0; }`, which still proves the package resolves and links. |
| `PK_BUILD_PROFILE` | `$PK_REPO_ROOT/profiles/native` | Conan build profile. |
| `PK_HOST_PROFILE` | empty, set per cross target | Conan host profile. |

### 6.3 Pipeline

| variable | default | purpose |
| --------------------- | -------------------------------------------- | ------- |
| `PK_BUILD_TYPES` | `Debug Release` | Space separated. `--build_type` overwrites it. |
| `PK_PRESET_PREFIX` | `native`, or the triple for cross targets | Preset names are `<prefix>-<lowercase type>`. |
| `PK_HOST_TOOLS_PRESET` | `host-tools` | Preset used by the host tools stages. |
| `PK_LIBRARY_TYPES` | `STATIC SHARED STATIC+SHARED` | Matrix entries. Cross targets drop `STATIC+SHARED`. |
| `PK_REQUIRED_TOOLS` | `conan cmake ctest ninja git` | Checked in the environment stage. |
| `PK_SETUP_STAGES` | see section 4 | Stage list, whitespace separated. |
| `PK_TYPE_STAGES` | see section 4 | Stage list run once per build type. |
| `PK_FINAL_STAGES` | `reset` | Stage list run once at the end. |
| `PK_KEEP` | `0` | `--keep` sets this to `1`. |

A minimal project config:

```bash
PK_CONSUMER_SOURCE="${PK_REPO_ROOT}/scripts/helpers/verify/consumer.cpp"
```

A config that verifies one build type, skips packaging and adds a header-only
library type:

```bash
PK_BUILD_TYPES="Release"
PK_LIBRARY_TYPES="STATIC SHARED"
PK_TYPE_STAGES="workflow library_matrix auto_discovery install consumer"
```

## 7. Hooks

Redefine any of these in the config file. Each default is a no-op or a generic
implementation.

| hook | when it runs |
| --------------------------- | --------------------------------------------- |
| `pk_platform_check` | In the environment stage. Return non-zero to abort the whole target. |
| `pk_platform_setup` | After the environment stage, before anything is built. |
| `pk_platform_teardown` | At the very end, before the summary. |
| `pk_expected_install_files` | Prints the files that must exist under `stage/` after installing. |

Overriding the expected install list, for a project that also installs a
manual page:

```bash
pk_expected_install_files() {
 printf '%s\n' \
 "lib/cmake/${PK_PACKAGE}/${PK_PACKAGE}Config.cmake" \
 "lib/cmake/${PK_PACKAGE}/${PK_PACKAGE}ConfigVersion.cmake" \
 "lib/cmake/${PK_PACKAGE}/${PK_PACKAGE}Targets.cmake" \
 "lib/pkgconfig/${PK_PACKAGE}.pc" \
 "share/man/man1/${PK_PACKAGE}.1"
}
```

## 8. The target registry

`targets.sh` holds one record per target:

```text
name|kind|os|arch|env|probe|description
```

| field | meaning |
| ------------- | ------------------------------------------------------------ |
| `name` | Target name, as typed on the command line. Cross targets must be named `cross-<triple>`. |
| `kind` | `native` or `cross`, which the `--native` and `--cross` filters select on. |
| `os` | Required host OS family: `linux`, `macos`, `windows`, `any`. |
| `arch` | Required host architecture: `x86_64`, `armv8`, `any`. |
| `env` | Required `MSYSTEM` value, or `-`. |
| `probe` | Executable that must be on PATH, or `-`. |
| `description` | Shown in the listing and used as the target label. |

Availability is decided in two modes. In `strict` mode every field must be
satisfied. In `possible` mode only `os` and `arch` are checked, because those
are properties of the machine, while an environment or a toolchain is something
you could install or a terminal you could open.

A cross target additionally requires `profiles/<triple>` to exist, and its
preset names come from the same triple, so adding a cross target means three
things: a record here, a Conan profile at `profiles/<triple>`, and configure
presets named `<triple>-debug`, `<triple>-release` and so on.

```text
cross-riscv64-linux-gnu|cross|any|any|-|riscv64-linux-gnu-gcc|Cross to Linux riscv64
```

## 9. Typical sessions

```bash
./scripts/verify.sh list
./scripts/verify.sh run --build_type=Debug windows-ucrt64
./scripts/verify.sh run --build_type=Debug,Release,RelWithDebInfo,MinSizeRel
./scripts/verify.sh run --cross
./scripts/verify.sh run --keep --build_type=Debug windows-ucrt64
./scripts/verify.sh clean
```

`--keep` is the one to use while debugging a failure, since the reset stage
would otherwise delete the build tree you want to inspect.

## 10. Troubleshooting

| symptom | cause |
| --------------------------------------------------------- | ----- |
| `no targets selected` | No target matched the filters in this shell. Run `list` to see why each one was rejected, or `run-possible`. |
| `needs MSYSTEM=CLANG64, this shell is UCRT64` | Expected. Open the CLANG64 shell; `MSYSTEM` cannot be reassigned, because PATH was set by the launcher. |
| `Conan has not generated dependencies for X yet` | The build type was never installed. Run `./scripts/package.sh install --build_type=X`. |
| `<PREFIX>_BUILD_TESTS=OFF` | `tools.build:skip_test` is set in your Conan profile, so the test stage would silently do nothing. |
| `probe.cpp was not picked up` | `CONFIGURE_DEPENDS` is not working, or `PK_SCRATCH_DIR` points outside the globbed source directory. |
| `cannot determine the project name` | No `project()` call found. Set `PK_PROJECT` in the config file. |
| Everything fails right after `clean_slate` | Usually a stale `CMakeUserPresets.json` or a toolchain and build type mismatch. Configure once by hand to see the real error. |
