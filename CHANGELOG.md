# Changelog

All notable changes to this project, directly impacting users, are recorded here.

The format is [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) and
the version numbers follow [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).

What a major, minor or patch bump *means* for this project's ABI is in
[`docs/DISTRIBUTION.md`](docs/DISTRIBUTION.md); the release procedure is in
[`docs/RELEASING.md`](docs/RELEASING.md).

Add your entry under `## [Unreleased]` in the same pull request that changes
the behaviour. Your pull request will be rejected if you implement features
and/or fixes that directly impact users and is not logged in this document.

<!-- Example of section headings:

## [Unreleased]

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security -->

## [Unreleased]

## [0.2.0] - 2026-10-14

### Added

- Project trees: where each part of a project lives (the kit, scripts,
  settings, profiles, headers, sources, apps, tests and the rest), kept in
  `.pk/tree.conf`. A project without one has the classic tree, the same as
  before. CMake, `pk`, the scripts, CI and `pk sync` all follow it. See
  [`TREE.md`](cmake/projectkit/docs/TREE.md).
- `pk new --tree=NAME|FILE`: `classic` (the default), `minimal` (the kit,
  scripts, settings and profiles in `.pk/`, with tools, clangd and pre-commit
  left out), a tree of your own in `~/.pk/trees/` or a drawing.
  `--omit=PART,...` leaves parts out of any tree.
- `pk tree` inside a project: shows the tree, and `check`, `draw`,
  `apply FILE|NAME` (moves the files and updates every file naming them, as
  one commit) and `reset` (back to the last tree that worked). Outside a
  project `pk tree` lists the trees `pk new` takes.
- `pk_tree_dir()`, `pk_tree_has()` and `pk_tree_base_dir()` in
  `Layout.cmake`. The creators' default folders come from the tree.

### Changed

- `scripts/*.py`: the project root is the nearest folder with a
  `CMakePresets.json`, and the kit is found through `.pk/tree.conf`. The
  global `pk` and the `pk` function of `pk shell-init` find `pk.py` wherever
  the tree puts the scripts.
- Project names: `pk new` and `pk rename` both rely on the same rules
  (`pklib/names.py`). A name is 2 to 101 characters matching
  `[a-z][a-z0-9_]*`, without `__`, and cannot be a C++ keyword, `std`,
  `posix`, a target name CMake reserves (`test`, `install`, ...), a macro
  GCC/Clang predefine (`linux`, `unix`) or Windows device name (`con`, `nul`,
  ...). `pk new` will note if the kit uses the name as a word.
- `pk new`: a missing NAME and an option written with a space (`--tree
  minimal`) are now reported as such. An interrupted first commit is reported
  instead of just ending `pk new` silently.. (the files stay staged).

### Fixed

- `pk rename` replaced every occurrence of the old name (including substrings).
  Renaming a project named `test` (when pk didn't block it) would change
  the `tests/` directory and `skip_test` Conan profile setting. Now only whole
  parts of identifiers are renamed (`test_app`, `TEST_BUILD_TESTS`,
  `testConfig`). Setting a projects name to one the kit uses as a word of its
  own is stopped without changing anything (`--allow-ambiguous` renames it
  anyways).

## [0.1.1] - 2026-10-14

### Added

- `pk list` outside a project: every project the global `pk` knows, with its
  name, kit version, last use and path. `pk new` remembers a project, and so
  does every `pk` command run inside one. Moved or deleted projects show as
  missing; `pk list --prune` forgets them. The registry is
  `~/.pk/projects.json` (`PK_HOME` moves it).
- `pre-commit-config.yaml`: every commit is linted before being staged. The
  template gets its own pre-commit-config as well, which is optional and can be
  deleted by users in their new projects if wanted.
- `template-sync.yml`: after every successful release (or when ran by hand),
  generates the project with `pk new qcdx` and pushes the difference to
  [QCDX-template](https://github.com/cooldood155/QCDX-template) as one commit,
  with the template repository's own README, plus LICENSE, CHANGELOG and docs.
  This requires the `TEMPLATE_REPO_TOKEN` secret.
- `PK_RELEASE_SYNC` release setting: repository files (e.g. `CHANGELOG.md`)
  kept in sync with the root of the releases repository under their own names,
  the same way `PK_RELEASE_README` keeps its `README.md` in sync.

### Fixed

- `pk new`: `--description` and `--version` were ignored when NAME was the
  template's own name (`qcdx`). Both are now always applied to `CMakeLists.txt`
  and the Conan recipe.
- `pk new`: file modes are copied from source. Inside `pk.pyz`, where modes
  cannot be read, files starting with `#!` are made executable.
- `pk_create_test`: on Windows with MinGW or MSYS2 Clang, `pk test` failed
  with `0xc0000139` (entry point not found) when the calling shell's `PATH`
  listed an older `libstdc++-6.dll` first, e.g. a MINGW64 shell after a GCC
  update. Test discovery and every test now run with the compiler's own
  folder first on `PATH` (Catch2 `DL_PATHS`).
- clang-tidy: a stray comma in `StaticAnalysis.cmake`, after
  `--extra-arg=-Wno-unused-command-line-argument`, reached clang-tidy as its
  own argument and caused a CMake dev warning on every configuration.
- README: release badge link.
- CHANGELOG: notable changes made, scoped to each release.

## [0.1.0] - 2026-10-10

The first release. QCDX is no longer only a GitHub template! It's a package
with a global `pk` command that creates projects and works inside them.

### Added

- **The `qcdx` package** on PyPI, for Python 3.9 and newer, with no
  dependencies. `pipx install qcdx` (or `uv tool install qcdx`, or pip)
  installs `pk` (and the same command as `qcdx`). The `tools` extra,
  `qcdx[tools]`, also installs Conan, CMake and Ninja.
- **`pk.pyz`**: all of QCDX inside of one file, only needing Python. It is
  attached to every GitHub release.
- **The global `pk`**:
  - `pk new NAME [DIR]` creates a project from `template/` plus the vendored
    kit, renames it, fills in the recipe's author, url and license, records
    the QCDX commit in `scripts/helpers/pk/upstream.conf` and makes the first
    commit.
  - `pk --version` prints the QCDX version, and inside a project the kit
    version too.
  - `pk cmake-dir` prints the QCDX CMake package directory.
  - When inside a project every command runs the project's own `scripts/pk.py`.
  The kit version the project vendors is the version dictating pk's
  functionality, never the installed QCDX version.
- **The CMake package**: `find_package(QCDX)` after `cmake --install`, through
  `pk cmake-dir` *or* with FetchContent from the sdist. `QCDXConfigVersion`
  only accepts 0.1.x for 0.1, as long as QCDX is before 1.0.
- **The Conan package** (`build-scripts`, for `tool_requires`).
- **The project `pk` CLI** (`scripts/pk.py`), in Python, running the same from
  PowerShell, cmd, MSYS2, macOS and Linux:
  - build and run: `configure`, `build`, `rebuild`, `run`, `test`
  - dependencies: `deps`, and `dep` (`ls`, `add`, `set`, `rm`, `update`,
    `lock`, `check`, `why`, `tree`) over `deps.json` and `conan.lock`
  - install and ship: `install`, `stage` (a checked install with a parseable
    report), `verify`, `package`, `release`
  - code quality: `analyze` (clang-tidy, cppcheck), `sanitize`, `memcheck`
    (Valgrind), `format` (clang-format)
  - cleanup: `clean`, `full-clean`
  - inspect: `status`, `list`, `doctor`
  - project and shell: `sync` (a 3-way merge of kit updates from QCDX),
    `rename`, `help`, `shell-init` (a `pk` function with tab completion for
    bash and PowerShell)
- **projectkit, the CMake kit**:
  - `pk_create_library`, `pk_create_app`, `pk_create_test` and
    `pk_create_tool`, with `DEPS_PUBLIC`, `DEPS_PRIVATE` and `DEPS_INTERFACE`
    for libraries and `DEPS` for apps and tests
  - **first-class C targets**: `export.h`, C flags, visibility and analysis
  - dependencies from `deps.json` (`pk_deps_find`, `pk_deps_link`), pinned in
    `conan.lock`
  - installed package configs call `find_dependency()` for what the link
    graph needs
- **Cross builds** with pinned toolchains and Conan profiles for
  `x86_64-linux-gnu`, `aarch64-linux-gnu`, `x86_64-mingw-w64` and
  `aarch64-mingw-llvm-w64`.
- **Project releases**: a `v*.*.*` tag builds, tests and archives every target
  in `scripts/helpers/release/release.conf` (also locally, `pk release`),
  checks the installed tree's portability (Windows DLL imports, Linux glibc
  and GLIBCXX versions, the macOS minimum version) and publishes a GitHub
  release with `SHA256SUMS`. Code signing and provenance attestations are
  optional.
- **QCDX's own CI**: `ci.yml` runs pytest (Python 3.9 and 3.13, on Linux,
  macOS and Windows), builds the sdist, wheel and `pk.pyz`, runs `pk.pyz` on
  Python 3.9, builds and tests a project made by `pk new` on Linux, macOS and
  Windows (UCRT64), and checks the CMake install, FetchContent and
  `conan create`.
- **QCDX's release**: `release.yml` requires the tag to match `VERSION`, runs
  `ci.yml`, then publishes the tested files to PyPI (trusted publishing) and
  GitHub Releases, with `SHA256SUMS` and provenance attestations.

[Unreleased]: https://github.com/cooldood155/QCDX/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/cooldood155/QCDX/releases/tag/v0.2.0
[0.1.1]: https://github.com/cooldood155/QCDX/releases/tag/v0.1.1
[0.1.0]: https://github.com/cooldood155/QCDX/releases/tag/v0.1.0
