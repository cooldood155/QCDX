# package.sh

The Conan 2 lifecycle for a ProjectKit project: create, inspect, edit, delete,
publish. The recipe is the single source of truth. Name and version come from
`conan inspect`, so nothing in the script is tied to a project.

```text
cmake/projectkit/scripts/package.sh       entry point, kit side
cmake/projectkit/test_package/            generic test package
scripts/package.sh                        wrapper, project side
scripts/helpers/package/package.conf      project settings
```

## 1. CRUD, in Conan terms

Conan does not use the CRUD names, so here is the mapping.

| operation | command | notes |
| --------- | ------------------------------ | ----- |
| create | `create`, `export`, `export-pkg` | `create` builds, packages and runs the test package. `export` publishes the recipe only. `export-pkg` packages a tree you already built. |
| read | `list`, `info`, `path`, `reference` | Cache contents, dependency graph, cache folder, detected reference. |
| update | `editable add`, re-`create` | A packaged binary is immutable. You either supersede it with a new revision or develop in place with an editable. |
| delete | `remove`, `cache-clean`, `editable remove` | `remove` drops recipe and binaries. `cache-clean` only drops build and source folders. |
| publish | `upload` | Needs a remote. |

## 2. Commands

```bash
./scripts/package.sh reference
./scripts/package.sh install --build_type=Debug
./scripts/package.sh create --build_type=Debug,Release
./scripts/package.sh build
./scripts/package.sh export
./scripts/package.sh export-pkg
./scripts/package.sh list
./scripts/package.sh info
./scripts/package.sh path
./scripts/package.sh editable add
./scripts/package.sh editable remove
./scripts/package.sh editable list
./scripts/package.sh remove --yes
./scripts/package.sh upload --remote=myremote
./scripts/package.sh cache-clean
./scripts/package.sh help
```

| command | conan command | purpose |
| ------------ | ----------------------------------- | ------- |
| `reference` | `conan inspect` | Prints `name/version` as the recipe reports it. Useful for scripts and CI. |
| `install` | `conan install` | Installs dependencies into `build/<type>/generators`, which is exactly what the CMake presets consume. Run this before configuring by hand. |
| `create` | `conan create` | Full cycle: build, package, then the test package. Once per build type. |
| `build` | `conan build` | Local build flow, no packaging. |
| `export` | `conan export` | Recipe into the cache, no build. |
| `export-pkg` | `conan export-pkg` | Package an already built local tree, for when a build is expensive. |
| `list` | `conan list <ref>:*` | Revisions and package ids in the cache, or in `--remote`. |
| `info` | `conan graph info` | Dependency graph for the first build type. |
| `path` | `conan cache path` | Where the package landed in the cache. |
| `editable` | `conan editable add/remove/list` | Develop against your working tree without packaging. |
| `remove` | `conan remove <ref> -c` | Deletes recipe and binaries. Asks first unless `--yes`. |
| `upload` | `conan upload <ref> -r R --confirm` | Publish. Fails fast without a remote. |
| `cache-clean` | `conan cache clean <ref>` | Reclaim disk without losing the package. |

## 3. Flags

| flag | meaning |
| --------------------- | ------- |
| `--build_type=T[,T]` | Build types, separated by `,` or `;`. Default `Release`. Commands that build run once per type. |
| `--profile=NAME` | Build profile. A path, a name under `profiles/`, or a globally installed profile name. |
| `--host-profile=NAME` | Host profile. Giving this switches the call from `-pr:a` to `-pr:b` plus `-pr:h`, which is what cross packaging needs. |
| `--remote=NAME` | Remote for `list`, `remove` and `upload`. |
| `--version=X` | Override the version the recipe reports, for a one-off build. |
| `--test-folder=DIR` | Test package folder. `--test-folder=` with an empty value disables the test stage. |
| `--yes`, `-y` | Do not ask before deleting. |
| `--dry-run` | Print the `conan` commands without running them. |
| `--` | Everything after this is passed to `conan` unchanged. |

Passthrough covers anything the script does not wrap:

```bash
./scripts/package.sh create -- -o shared=True
./scripts/package.sh create -- -c tools.build:skip_test=True
./scripts/package.sh list -- --format=json
```

Every command prints the exact `conan` invocation before running it, prefixed
with `+`, so the script never hides what it did.

## 4. Exit codes

| code | meaning |
| ---- | ------- |
| `0` | The conan command, or every command in a multi-type run, succeeded. |
| `1` | A conan command failed, or a required input is missing, for example `upload` without a remote. |
| `2` | Usage error: unknown command, unknown flag, invalid build type. |

## 5. Profile resolution

`--profile` and `PK_PROFILE` are resolved in this order:

1. An existing file at the given path.
2. `profiles/<name>` in the project.
3. The name as given, which lets Conan resolve a profile from its own folder.

With nothing given, the script uses `profiles/native` if the project has one,
and otherwise Conan's `default` profile. So a fresh clone works before you have
written any profiles, and an established project picks up its own automatically.

Cross packaging:

```bash
./scripts/package.sh create --profile=native --host-profile=x86_64-mingw-w64
```

## 6. The test package

`conan create` ends by building a small consumer against the package it just
made. That is the strongest check available, because it only sees installed
files.

The script picks a test folder in this order:

1. `--test-folder=DIR`, or the empty value to disable it.
2. `PK_TEST_FOLDER` from the config file.
3. `test_package/` in the project, if it exists.
4. The kit's generic `cmake/projectkit/test_package/`.

The generic one is package-agnostic. Its recipe takes the name from
`self.tested_reference_str` and passes it to CMake as `PK_TESTED_PACKAGE`, so
its `CMakeLists.txt` can do:

```cmake
find_package(${PK_TESTED_PACKAGE} REQUIRED)
add_executable(test_package "${PK_TEST_SOURCE}")
target_link_libraries(test_package PRIVATE
  ${PK_TESTED_PACKAGE}::${PK_TESTED_PACKAGE})
```

`PK_TEST_SOURCE` defaults to a stub `int main() { return 0; }`, which still
proves that `find_package` resolves and the imported target links. Set it to a
real smoke test to also prove the package runs. Pointing it at the same file
the verify script uses means one file covers both:

```bash
PK_TEST_SOURCE="${PK_REPO_ROOT}/scripts/helpers/verify/consumer.cpp"
```

Write your own `test_package/` in the project when you need more than one
executable, a components check, or a runtime fixture. The moment that directory
exists, it wins over the kit's.

## 7. Configuration

`scripts/helpers/package/package.conf` is sourced if present. Every setting is
a shell variable, so it can also be given as an environment variable.

| variable | default | purpose |
| ----------------- | ------------------------------------------ | ------- |
| `PK_REPO_ROOT` | set by the wrapper | Project root. Without it the script walks up from the working directory looking for `conanfile.py`. |
| `PK_PROFILE` | `profiles/native`, else `default` | Build profile. |
| `PK_HOST_PROFILE` | empty | Host profile. Setting it switches to `-pr:b` plus `-pr:h`. |
| `PK_REMOTE` | empty | Default remote. |
| `PK_BUILD_TYPES` | `Release` | Space separated after parsing. |
| `PK_TEST_FOLDER` | empty | Test package folder override. |
| `PK_TEST_SOURCE` | empty | Exported to the test recipe, which forwards it to CMake. |
| `PK_CONAN` | `conan` | The Conan executable, for pinned or wrapped installations. |
| `PK_TEST_BUILD_DIR` | `$PK_REPO_ROOT/build/test_package` | Where `create` builds the test package. Inside `build/` so the verify cleanup removes it. |

A typical project config:

```bash
PK_PROFILE="native"
PK_BUILD_TYPES="Release"
PK_TEST_SOURCE="${PK_REPO_ROOT}/scripts/helpers/verify/consumer.cpp"
```

## 8. Typical sessions

Day to day development, where the package never enters the cache:

```bash
./scripts/package.sh install --build_type=Debug
cmake --preset native-debug
cmake --build build/native-debug
```

Before publishing, or before another project consumes it:

```bash
./scripts/package.sh create --build_type=Debug,Release
./scripts/package.sh list
```

Developing two projects together, so the consumer picks up your edits with no
packaging step at all:

```bash
cd /k/Practice/etesca
./scripts/package.sh editable add

cd /k/Practice/consumer-project
./scripts/package.sh install --build_type=Debug

cd /k/Practice/etesca
./scripts/package.sh editable remove
```

Publishing, then cleaning up:

```bash
./scripts/package.sh create --build_type=Release
./scripts/package.sh upload --remote=myremote
./scripts/package.sh cache-clean
```

Starting over after a recipe change that Conan will not notice on its own:

```bash
./scripts/package.sh remove --yes
./scripts/package.sh create
```

## 9. Notes on the recipe

The script reads the recipe, so the recipe has to be right.

`set_version` parsing `project(... VERSION ...)` from `CMakeLists.txt` keeps
one version number in the project. `reference` will show whatever that parse
produced, which makes it a quick check that the parse still works after you
edit the top-level file.

`package_info` must describe what the build actually installed. Hardcoding a
single library name only holds while the library type is locked:

```python
def package_info(self):
    self.cpp_info.set_property("cmake_file_name", "etesca")
    self.cpp_info.set_property("cmake_target_name", "etesca::etesca")
    self.cpp_info.libs = ["etesca-shared"] if self.options.shared else ["etesca"]
    if not self.options.shared:
        self.cpp_info.defines.append("ETESCA_STATIC_DEFINE")
```

The `shared` option must also reach CMake, which the kit does through
`BUILD_SHARED_LIBS` and the intent file that `pk_check_shared_intent` compares
against. If Conan and the CMake cache disagree about shared, the configure
stops rather than producing the wrong binaries.

## 10. Troubleshooting

| symptom | cause |
| ---------------------------------------------------------- | ----- |
| `the recipe reports no name` | `conan inspect` failed. Run it directly to see the Python error in the recipe. |
| `ERROR: Package 'x' not resolved` | The dependency is not in the cache and the remote is unreachable. Try `-- -nr` for a fully offline run. |
| `conan is not on PATH` | The script refuses to guess. Activate the environment that has Conan. |
| Editable changes are ignored | Consumers must re-run `install`. An editable is resolved at graph time, not at build time. |
| `create` rebuilds everything every time | Usually `exports_sources` pulling in a build directory, or a recipe field that changes each run. Check `conan list <ref>` for a new revision each build. |
| Test package cannot find the package | `cmake_file_name` or `cmake_target_name` in `package_info` does not match what the test package looks for. |
