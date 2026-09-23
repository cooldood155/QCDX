# analyser-launcher.sh

A wrapper that CMake runs in place of the static analyser, so findings land in
a per-source report file as well as on the console.

```text
cmake/projectkit/scripts/analyser-launcher.sh
```

You never call this script yourself. `StaticAnalysis.cmake` prepends it to the
analyser command when `<PREFIX>_SA_OUTPUT` is `files`, and CMake invokes the
result once per translation unit.

## 1. Why it exists

CMake runs an analyser through the `CXX_CLANG_TIDY` and `CXX_CPPCHECK` target
properties. Those properties take a command line, and CMake appends the source
file and the compile flags to it. There is no hook for redirecting output, and
no place to put a shell redirect, because the property is a list of arguments
rather than a shell command.

The way to get a report file is therefore to make the *command* a script that
does the redirect itself. The script has to be transparent: same arguments,
same console output, same exit code. Anything else would break
`--warnings-as-errors`, which relies on the analyser's status reaching CMake.

## 2. Contract

```text
analyser-launcher.sh <report-dir> <analyser> [analyser args...]
```

| position | meaning |
| -------------- | ------- |
| `<report-dir>` | Directory for reports. Created if missing. |
| `<analyser>` | The real analyser executable. |
| rest | Everything else, executed unchanged. CMake supplies most of it. |

What it does, in order:

1. Creates the report directory.
2. Finds the source file in the arguments: the argument before a bare `--`,
   otherwise the first argument with a source extension. Clang-tidy is invoked
   as `clang-tidy <args> <source> -- <compile flags>`, which is why the `--`
   rule comes first.
3. Runs the analyser with output captured.
4. Prints that output, so the build log still shows findings.
5. Writes the report when there was output, with a short header naming the
   command, the source and the exit status.
6. Deletes the report when the run was clean, so the report directory only
   contains files that need attention.
7. Exits with the analyser's own status.

Report names are `<basename>.<checksum>.log`, where the checksum comes from the
full source path. Two files called `core.cpp` in different directories get
different reports.

```text
build/analysis/clang-tidy/core.cpp.2145291537.log
```

A report looks like this:

```text
command: /usr/bin/clang-tidy --extra-arg=-Wno-unknown-warning-option /k/proj/src/etesca/core.cpp -- -O2
source:  /k/proj/src/etesca/core.cpp
status:  3

warning: something in core.cpp
```

It is POSIX `sh` with no bashisms, since MSYS2, Linux and macOS all have to run
it, and CMake invokes it through whatever `sh` is found.

## 3. Controlling it from CMake

All of these are cache variables created by `pk_setup_static_analysis`, with
`<PREFIX>` being the uppercased project name.

| variable | default | purpose |
| ---------------------------- | ---------------------- | ------- |
| `<PREFIX>_SA_ALL` | `OFF` | Turn on every analyser. |
| `<PREFIX>_SA_CLANG_TIDY` | `OFF` | Turn on clang-tidy only. |
| `<PREFIX>_SA_CPPCHECK` | `OFF` | Turn on cppcheck only. |
| `<PREFIX>_SA_OUTPUT` | `console` | `console`, or `files` to also write reports. The launcher is only used for `files`. |
| `<PREFIX>_SA_OUTPUT_DIR` | `${PROJECT_BINARY_DIR}/analysis` | Report root. Clang-tidy writes to `<dir>/clang-tidy`, cppcheck to `<dir>/cppcheck`. |
| `<PREFIX>_SA_MESSAGE_FORMAT` | `default` | cppcheck template: `default`, `gcc` or `vs`. Pick `gcc` for editors that parse GCC diagnostics. |
| `<PREFIX>_SA_LAUNCHER` | the kit's script | Override to use your own wrapper. |
| `<PREFIX>_WERROR` | `OFF` | Adds `--warnings-as-errors=*` for clang-tidy and `--error-exitcode=1` for cppcheck. |

Typical invocations:

```bash
cmake --preset native-debug -DETESCA_SA_CLANG_TIDY=ON
cmake --preset native-debug -DETESCA_SA_ALL=ON -DETESCA_SA_OUTPUT=files
cmake --preset native-debug -DETESCA_SA_ALL=ON -DETESCA_SA_OUTPUT=files -DETESCA_WERROR=ON
```

Note that cppcheck does not go through the launcher. It has a native
`--plist-output` option, so `files` mode points that at
`<output-dir>/cppcheck` instead of wrapping the command.

## 4. Behaviour worth knowing

Findings appear twice: once on the console, because the script echoes the
captured output, and once in the report file. That is deliberate, so turning on
`files` never makes the build quieter than before.

An empty report is removed rather than written, so `ls build/analysis/clang-tidy`
is a list of files that still have findings.

The exit code passes through unchanged. With `<PREFIX>_WERROR=ON` a finding
fails the build exactly as it would without the launcher.

Compilation is unaffected. CMake runs the analyser as a side process for each
translation unit, so a non-zero analyser status fails that build step, but the
object file is still produced by the compiler itself.

## 5. Using a different wrapper

Point the cache variable at your own script. It must keep the same contract:
first argument is the report directory, the rest is the command to run, output
goes to stdout, exit code passes through.

```bash
cmake --preset native-debug \
  -DETESCA_SA_ALL=ON \
  -DETESCA_SA_OUTPUT=files \
  -DETESCA_SA_LAUNCHER=/k/tools/my-launcher.sh
```

The configure fails immediately if that file does not exist, rather than
failing later on the first compiled file.

## 6. Running it by hand

Useful when the wrapper itself is suspect:

```bash
sh cmake/projectkit/scripts/analyser-launcher.sh /tmp/reports \
  clang-tidy src/etesca/core.cpp -- -std=c++23 -Iinclude
echo "exit=$?"
ls /tmp/reports
```

## 7. Troubleshooting

| symptom | cause |
| --------------------------------------------------- | ----- |
| Configure fails with `the launcher script is missing` | `<PREFIX>_SA_LAUNCHER` points at a path that does not exist. |
| Reports never appear | `<PREFIX>_SA_OUTPUT` is still `console`, or the analyser found nothing, in which case the empty report is deleted on purpose. |
| Report named `unknown-source` | The analyser was invoked without a recognisable source argument. Check what CMake put in `CXX_CLANG_TIDY`. |
| The build no longer fails on findings | `<PREFIX>_WERROR` is off. The launcher does not add severity of its own. |
| `sh: not found` on Windows | The configure looks for `sh` on PATH. In MSYS2 it is present; outside MSYS2 it may not be. |
