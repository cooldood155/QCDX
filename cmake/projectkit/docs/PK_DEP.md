# pk dep: Dependencies

Every third-party package the project uses is declared in one file,
`deps.json`, at the repo root. Nothing else declares them; everything that
needs to know about them (the readers) reads it:

| Reader | Uses it for |
| :-- | :-- |
| `conanfile.py` | installing packages: `requires`, `test_requires`, `tool_requires`, options, traits |
| ProjectKit CMake | which `find_package()` to call and which imported targets `DEPS_*` links |
| `pk_install_package` | the `find_dependency()` calls in the installed package config |
| `pk dep` | editing, locking, checking and reporting |

Versions are pinned in `conan.lock` (also at the root), and both files get
committed. Conan picks up a `conan.lock` sitting next to the conanfile on its
own, which means `pk build`, `scripts/package.py`, `scripts/verify.py` and CI
all build the pinned versions **exactly**. An install whose graph doesn't
match the lock just fails.

"deps.json" and "the manifest" mean the same thing here, and in `deps.py`
anything that touches it has "manifest" in its name.

## Why it's made like this

Without a manifest, one dependency ends up written in (up to) four places: the
conanfile, a `find_package()` call, the target names on `LINK_*`, and the
`DEPENDENCIES` of the installed config. Nothing keeps those four agreeing with
each other or keeps versions pinned, and sooner or later they drift.

- **One file, easy to read and easy to parse.** JSON is the one format both
  Python and CMake (3.19+) can read with nothing extra. `conandata.yml` would
  be more Conan-like, but CMake can't read YAML natively.
- **Usage lives in CMake.** Which target uses which package is written right
  where the target is created, as an argument to the creator call. Keeping a
  second list in `deps.json` would just be one more thing that can drift (the
  exact thing the manifest exists to get rid of btw). The *who uses what*
  report is generated during configuration from the link graph.
- **CMake names are discovered.** A package has three names: its Conan name
  (`sqlite3`), the name `find_package()` takes (`SQLite3`), and the imported
  target you link (`SQLite::SQLite3`). The recipe picks the last two and
  nothing derives them from the Conan name. `pk dep add` installs the package
  once, reads both from the files CMakeDeps actually generated, and records
  them in `deps.json`. The Conan name is the only one you ever have to write!
- **Only *you* change versions.** The lock pins every package (transitive ones
  too) by version and recipe revision. Commands that aren't about versions keep
  the pins; see [What can change a version](#what-can-change-a-version).
- **Python.** `pk dep` has to edit JSON transactionally, and since Conan
  already needs Python it adds nothing new to install (standard library only,
  Python 3.8+). The rest of `pk` is Python for the same reason.

## deps.json

```json
{
  "schema": 1,
  "packages": {
    "catch2": {
      "ref": "catch2/[>=3.7.1 <4]",
      "kind": "test",
      "cmake": {
        "package": "Catch2",
        "version": "3",
        "targets": ["Catch2::Catch2WithMain"],
        "extra_targets": ["Catch2::Catch2"]
      },
      "notes": "Unit tests; linked by pk_create_test automatically."
    },
    "cmake": {
      "ref": "cmake/[>=3.30 <5]",
      "kind": "tool"
    },
    "sqlite3": {
      "ref": "sqlite3/[>=3.45 <4]",
      "kind": "requires",
      "options": {"shared": false},
      "traits": {"transitive_headers": true},
      "cmake": {"package": "SQLite3", "targets": ["SQLite::SQLite3"]}
    }
  }
}
```

| Key | Required | Meaning |
| :-- | :-- | :-- |
| `schema` | yes | always `1` |
| `packages.<name>` | | the key is the Conan package name, lowercase |
| `ref` | yes | `<name>/<version>` or `<name>/[<range>]`; has to start with the key |
| `kind` | no | `requires` (default), `test` or `tool` |
| `options` | no | Conan options for this package, applied in `configure()` |
| `traits` | no | requirement traits, `requires` only: `headers`, `libs`, `run`, `visible`, `transitive_headers`, `transitive_libs`, `force`, `override` |
| `cmake` | yes, except tools | the object below, or `false` for a package not used through `find_package()` |
| `cmake.package` | yes | the name given to `find_package()` |
| `cmake.version` | no | version passed to `find_package()` |
| `cmake.components` | no | `COMPONENTS` passed to `find_package()` |
| `cmake.targets` | yes | imported targets that `DEPS_*` links |
| `cmake.extra_targets` | no | other targets the package creates; only used to attribute hand-written `LINK_*` usage |
| `notes` | no | free text, shown by `pk dep why` |

A target can only belong to one package; listing the same target under two
entries is a validation error.

| Kind | Conan | CMake |
| :-- | :-- | :-- |
| `requires` | `self.requires()` | any target can use it |
| `test` | `self.test_requires()` | only `pk_create_test` targets (and `pk_deps_find`) |
| `tool` | `self.tool_requires()` | never; it runs during Conan builds |

`pk dep` writes the file with sorted package names, keys in a fixed order,
two-space indent and ASCII only to keep diffs small. Editing it by hand is
fine too: configuration and `pk dep check` both validate it, and Conan refuses
an install the lock doesn't cover.

## Commands

Every command takes `-n`/`--dry-run` (prints what would change and the Conan
commands it would run, changes nothing) and `--profile NAME` (repeatable; a
file under `profiles/` or a named Conan profile, default `native`). Read-only
Conan queries, like the `graph info` behind `check`, `why` and `tree`, still
run under `--dry-run` since they don't change anything.

Commands that edit are transactions: if any step fails, `deps.json` and
`conan.lock` are both put back exactly how they were.

`pk dep help` lists everything and `pk dep <command> --help` shows a command's
flags. `ls`/`list`, `rm`/`remove` and `update`/`up` are aliases.

### Adding

```bash
pk dep add "sqlite3/[>=3.45 <4]"
pk dep add "catch2/[>=3.7 <4]" --kind test
pk dep add "ninja/[>=1.12 <2]" --kind tool
pk dep add "fmt/11.0.2" --option header_only=True --notes "Formatting"
```

`add` writes the entry, extends `conan.lock` (existing pins stay put), then
installs the package once with the CMakeDeps generator into
`build/.pk-dep/discover/<name>/` and records the `find_package()` name and
targets that actually got generated. If there's no binary yet that install
builds one, which the next `pk build` would've done anyway.

To skip discovery, give the names yourself: `--cmake-package NAME --target T
[--target T2] [--component C] [--cmake-version V]`. `--no-discover` without
them is an error. `--no-cmake` is for a package that isn't used through CMake
at all.

Discovery stops on a recipe that sets `cmake_find_mode` to `none`, since it
generates no CMake config to read. Use `--no-cmake` for those, or give the
names by hand if you know them.

Once it's added, `add` prints how to link it:

```cmake
pk_create_library(NAME mylib ... DEPS_PRIVATE sqlite3)
pk_create_app(NAME mylib ... DEPS sqlite3)
```

### Changing

```bash
pk dep set sqlite3 --range "[>=3.46 <4]"
pk dep set sqlite3 --option shared=True
pk dep set sqlite3 --unset-option shared
pk dep set sqlite3 --trait transitive_headers=true
pk dep set sqlite3 --kind test
pk dep set sqlite3 --discover
pk dep set sqlite3 --notes "Storage backend"
```

`--range` takes just the version part and `--ref` a whole reference, which has
to keep the same name (renaming is `pk dep rm` + `pk dep add`). `--discover`
refreshes the CMake names from what Conan generates, e.g. after a recipe
changed them. Switching to `--kind tool` drops the `cmake` section, since
tools don't have one.

### Removing

```bash
pk dep rm sqlite3
```

`rm` refuses while any CMake file still uses the package (`DEPS_*`,
`pk_deps_find`, `pk_deps_link`, or one of its target names written by hand)
and lists each `file:line`. After it's removed `conan.lock` is pruned, and
transitive packages only it needed go with it. `--force` removes it anyway,
but then the next configuration fails until those uses are gone.

### Versions

```bash
pk dep update sqlite3 # newest version in its range
pk dep update         # everything, as a fresh lock
pk dep lock           # add missing entries, keep every pin
pk dep lock --profile x86_64-mingw-w64 --profile aarch64-linux-gnu
pk dep lock --clean   # also drop entries nothing needs
```

Every change prints old and new versions with short recipe revisions; a
revision change on the same version still shows up:

```text
  catch2               3.7.1 (rev 283819d) -> 3.7.1 (rev 634074b)
```

Build and test after an update (`pk test`), then commit `conan.lock`.

### What can change a version

| Action | Versions |
| :-- | :-- |
| `pk build`, `pk test`, `package.py`, CI | never; the lock is enforced |
| `pk dep lock` | adds entries for packages not locked yet; existing pins stay |
| `pk dep add` | resolves the new package (newest in range); other pins stay |
| `pk dep set --option/--trait/--notes` | never; a relock only adds what an option newly pulls in |
| `pk dep set --kind` | never; the exact pinned ref moves to its new lock section |
| `pk dep set --range/--ref` | that package re-resolves to the newest in the new range |
| `pk dep update <name>` | that package re-resolves; others stay |
| `pk dep update` | everything re-resolves |

Heads up: if a lock ever holds two versions of the same package (after a
hand-merge, say), Conan uses the highest one the range allows. `pk dep check`
reports the unused one and `pk dep lock --clean` drops it.

### Reports

```bash
pk dep ls               # packages, locked versions, users
pk dep ls --all         # plus transitive packages from the lock
pk dep ls --json
pk dep why zlib         # who pulls it in and which targets rely on it
pk dep tree             # per target: packages and their Conan trees
pk dep tree mylib_app
pk dep tree --packages  # the Conan graph alone; --build adds tools
```

```text
NAME     KIND      RANGE         LOCKED  CMAKE    USED BY
-------  --------  ------------  ------  -------  ------------------------------
catch2   test      [>=3.7.1 <4]  3.7.1   Catch2   mylib_tests (private)
cmake    tool      [>=3.30 <5]   3.31.0  -        (build tool)
sqlite3  requires  [>=3.45 <4]   3.46.1  SQLite3  mylib (private), mylib_app (via)
```

```text
zlib
  locked: 1.3.1
  pulled in by Conan:
    conanfile.py (mylib/0.1.0) -> sqlite3/3.46.1 -> zlib/1.3.1
  targets (through sqlite3):
    mylib                        library private (links it directly)
    mylib_app                    application via mylib_app -> mylib
```

`USED BY` and the target sections come from the usage report of the most
recently configured build tree (`--tree DIR` picks a specific one). If
`deps.json` or a CMake file is newer than that report `pk dep` tells you, and
`pk configure` refreshes it.

The Conan graph is cached in `build/.pk-dep/`, keyed on the contents of
`conanfile.py`, `deps.json`, `conan.lock` and the profiles. Everything in
`build/.pk-dep/` is scratch and safe to delete.

### Checking

```bash
pk dep check          # exit 1 on any problem
pk dep check --strict # unused packages are problems too
pk dep check --profile ci-linux-x86_64
```

`check` doesn't build anything. It makes sure that:

1. `deps.json` is valid.
2. Every name used by `DEPS_*`, `pk_deps_find` or `pk_deps_link` in the CMake
   sources is declared, and its kind fits the target (no `test` package on a
   library or app, no `tool` package anywhere).
3. Every declared package is in `conan.lock`, and `conan graph info` loads the
   whole graph strictly from the lock for each profile. That's the same
   strictness as `conan install`. `conan lock create` isn't used for this
   because it would resolve past the lock.
4. Notes (not failures): a hand-written `find_package()` of a declared
   package, lock entries no profile uses, and packages nothing uses (those
   become problems with `--strict`).

CI runs `pk dep check` on the Linux x86_64 job.

## CMake

`deps.json` is loaded and validated by `pk_project_setup`. A broken manifest
stops configuration before any target exists, and editing it re-runs
configuration.

### On the creators

```cmake
pk_create_library(
  NAME mylib
  DEPS_PUBLIC    fmt        # in mylib's public headers
  DEPS_PRIVATE   sqlite3    # implementation only
  DEPS_INTERFACE range-v3)  # consumers only
pk_create_app(NAME mylib DEFAULT_DIRS LINK_PRIVATE mylib::mylib DEPS cli11)
pk_create_test(NAME mylib DEPS trompeloeil)
```

`DEPS_*` finds each package in the calling directory, links its
`cmake.targets`, and checks the kind against the target's role. `INTERFACE`
libraries get every entry as `INTERFACE`, same as `LINK_*`. `LINK_*` still
works for project targets and anything that isn't from Conan.

A `DEPS_PUBLIC` or `DEPS_INTERFACE` package on a library whose entry doesn't
have the `transitive_headers` trait gives a warning, because consumers of the
Conan package wouldn't see its headers. `pk dep set <name> --trait
transitive_headers=true` fixes it.

### Directly

```cmake
pk_deps_find(catch2)  # find_package() exactly how deps.json says
include(Catch)

pk_deps_link(TARGETS my_target ROLE APPLICATION PRIVATE sqlite3)
```

`pk_deps_find` acts like the caller ran `find_package()` itself: it hands back
`CMAKE_MODULE_PATH`, `CMAKE_PREFIX_PATH` and the package's `<Pkg>_*`
variables (Catch2's `include(Catch)` needs the module path). It fails if a
target listed in `cmake.targets` wasn't created, and names the ones that were.

`DEPS_*` on a creator only links. When a directory needs a package's CMake
modules or variables, call `pk_deps_find` there.

### Installed packages

`pk_install_package` writes `<package>Dependencies.cmake` next to the config
file, with one `find_dependency()` per declared package that reaches an
installed target's interface. That includes a static library's private
dependencies, since they show up as `$<LINK_ONLY:...>` and consumers have to
link them. Extra `DEPENDENCIES` given by hand get appended. Both config
templates include the file:

```cmake
include("${CMAKE_CURRENT_LIST_DIR}/@PK_PACKAGE_NAME@Dependencies.cmake")
```

A custom template that doesn't include it fails configuration as soon as
there's a dependency to pass on, instead of quietly producing a package
consumers can't use.

### The usage report

Every configuration writes `<build tree>/pk-deps-usage.json`:

```json
{
  "schema": 1,
  "project": "mylib",
  "build_type": "Debug",
  "targets": {
    "mylib":     {"role": "LIBRARY", "direct": {"sqlite3": "PRIVATE"},
                  "effective": {"sqlite3": "mylib"}, "unmanaged": []},
    "mylib_app": {"role": "APPLICATION", "direct": {},
                  "effective": {"sqlite3": "mylib_app -> mylib"}, "unmanaged": []}
  },
  "packages": {"sqlite3": {"ref": "sqlite3/[>=3.45 <4]", "kind": "requires",
                           "package": "SQLite3"}}
}
```

- `direct`: packages a target links itself, with the visibility from its link
  lists (a static library's `$<LINK_ONLY:x>` counts as `PRIVATE`).
- `effective`: everything it relies on through other project targets, with
  the shortest chain. Every link list counts, since a package a dependency
  links privately is still needed at link or run time.
- `unmanaged`: imported `X::Y` targets that no `deps.json` entry lists, like
  `Threads::Threads` or something from a hand-written `find_package()`.

Attribution goes by target name. Packages linked by hand through `LINK_*` get
reported too, as long as `deps.json` lists the target.

## Moving an existing project over

`pk sync` brings over the kit parts (`cmake/projectkit/`, the scripts). Four
files the project owns need a one-time change:

1. **`deps.json`**: create it from the current conanfile's requirements. For
   each `self.requires(...)` / `test_requires` / `tool_requires`, run
   `pk dep add <ref> --kind ...` *after* step 2, or write the entries by hand
   and run `pk dep set <name> --discover` for each `requires`/`test` entry.
2. **`conanfile.py`**: replace the hand-written `requirements()` and
   `build_requirements()` with the manifest-reading block from the QCDX
   template (`_pk_deps`, `requirements`, `build_requirements`, and the loop at
   the end of `configure`), then add `exports = "deps.json"` and put
   `"deps.json"` in `exports_sources`.
3. **CMake**: replace `find_package(X)` + `LINK_PRIVATE X::X` pairs with
   `DEPS_PRIVATE <name>` on the creator, and `find_package(Catch2 3
   REQUIRED)` in `tests/` with `pk_deps_find(catch2)`.
4. **`cmake/<project>Config.cmake.in`** (if the project has its own): add the
   `include(... <project>Dependencies.cmake)` line before the targets file is
   included.

Then:

```bash
pk dep lock
pk dep check
pk test
git add deps.json conan.lock
```

## Environment

| Variable | Default | Meaning |
| :-- | :-- | :-- |
| `PK_REPO_ROOT` | the first directory at or above the current one with both `conanfile.py` and `CMakeLists.txt` | the repository root |
| `PK_CONAN` | `conan` | the Conan executable to run |
| `PK_NATIVE_PROFILE` | `native` | the build machine's profile, and the default `--profile` |
| `NO_COLOR` | unset | any value turns colored output off (it's only on for a terminal anyway) |

## Limits

- `pk_create_tool` has no `DEPS`. Tools are built for the build machine, and
  in a cross build the host packages are a different architecture.
- Discovery uses the first `--profile`. CMake names almost never differ
  between platforms, but if one does, give the names explicitly.
- The source scan behind `rm` and `check` reads `DEPS_*`, `pk_deps_find` and
  `pk_deps_link` calls and target names. Names built from variables during
  configuration are invisible to it; the checks that run during configuration
  still catch those.
- `pkgconfig` `Requires` aren't derived from `deps.json`; pass
  `PKGCONFIG_REQUIRES` to `pk_install_package` by hand when you need them.
