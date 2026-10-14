# The project tree (`pk tree`)

Every part of a QCDX project has a place: the kit, the scripts, the settings,
the Conan profiles, your headers and sources, the apps, the tests. Where each
part lives is the project's *tree*. A project without `.pk/tree.conf` has the
**classic** tree, the one every QCDX project had before trees existed. A
project with one reads every part's folder from it, and everything (CMake, pk,
the scripts, CI, `pk sync`) follows it.

A tree can also leave optional parts out entirely, such as the build-time tool
sample, `.clangd` or the pre-commit hooks.

```bash
pk new rocket --tree=minimal            # kit, scripts, settings, profiles in .pk/
pk new rocket --omit=tools,pre-commit   # classic places, two parts left out
pk tree                                 # this project's tree, drawn
pk tree apply minimal                   # move an existing project to a tree
pk tree draw                            # write .pk/tree.txt to edit
pk tree apply .pk/tree.txt              # move the project to the edited drawing
pk tree reset                           # go back to the last tree that worked
```

## Parts

| Part           | Classic place                  | What it holds                                   | Optional |
|----------------|--------------------------------|-------------------------------------------------|----------|
| `kit`          | `cmake/projectkit`             | ProjectKit, the CMake kit (`pk sync` updates it) |          |
| `scripts`      | `scripts`                      | `pk.py`, `verify.py`, `package.py`, `release.py`, `bootstrap.py` | |
| `helpers`      | `scripts/helpers`              | settings: pk, release, verify and package       |          |
| `profiles`     | `profiles`                     | Conan profiles: native, cross targets, CI       |          |
| `toolchains`   | `cmake/toolchains`             | CMake toolchain files of the cross profiles     |          |
| `cmake`        | `cmake`                        | package config templates (`<name>Config.cmake.in`) |       |
| `headers`      | `include`                      | public headers, one folder per library          |          |
| `sources`      | `src`                          | library sources, one folder per library         |          |
| `apps`         | `apps`                         | applications, one folder per app                | yes      |
| `tests`        | `tests`                        | Catch2 tests, one folder per library            | yes      |
| `tools`        | `tools`                        | build-time tools (code generators)              | yes      |
| `clang-format` | `.clang-format`                | clang-format style (`pk format`)                | yes      |
| `clang-tidy`   | `.clang-tidy`                  | clang-tidy checks (`pk analyze`)                | yes      |
| `clangd`       | `.clangd`                      | clangd editor settings                          | yes      |
| `pre-commit`   | `.pre-commit-config.yaml`      | pre-commit hooks                                | yes      |
| `verify-ci`    | `.github/workflows/verify.yml` | CI: verify every push                           | yes      |
| `release-ci`   | `.github/workflows/release.yml`| CI: release on a `v*.*.*` tag                   | yes      |

The folder parts can live anywhere inside the project. The single files stay
where their tools look for them; they can only be kept or left out. Leaving
out both CI workflows also leaves out `.github/actions/pk-setup`.

These always stay at the root, since CMake, Conan and git only look for them
there: `CMakeLists.txt`, `CMakePresets.json`, `conanfile.py`, `deps.json`,
`conan.lock`, `README.md`, `.gitignore`, `.gitattributes`.

## Trees by name

| Name      | What it does                                                          |
|-----------|-----------------------------------------------------------------------|
| `classic` | everything at the root, nothing left out (the default)                |
| `minimal` | kit, scripts, settings, profiles, toolchains and cmake files in `.pk/`; `tools`, `clangd` and `pre-commit` left out |

A project made with `--tree=minimal` has this root:

```plaintext
rocket/
|-- .github/        CI
|-- .pk/            the kit, scripts, settings, profiles (and tree.conf)
|-- apps/
|-- include/
|-- src/
|-- tests/
|-- .clang-format
|-- .clang-tidy
|-- CMakeLists.txt
|-- CMakePresets.json
|-- conan.lock
|-- conanfile.py
|-- deps.json
`-- README.md
```

Your own trees go in `~/.pk/trees/NAME.conf` (or a drawing, `NAME.tree`);
`PK_HOME` moves `~/.pk`. `pk new rocket --tree=NAME` and `pk tree apply NAME`
find them. `pk tree list` (in a project) or `pk tree` (outside one) lists
every name.

## Writing a tree

### As a .conf file

One `part = path` line per part that is not in its classic place, plus
`omit = part ...` for the parts to leave out. Paths are relative to the
project root and use `/`. `#` starts a comment.

```ini
# ~/.pk/trees/mine.conf
kit      = .pk/projectkit
scripts  = .pk/scripts
helpers  = .pk/settings
profiles = conan/profiles
omit     = tools clangd
```

`PK_TREE_PROFILES=conan/profiles`, the spelling of the other settings files,
works too. A part in `omit` can be named by its key (`clangd`) or its classic
path (`.clangd`, `tools/`).

### As a drawing

A drawing is a picture of the tree. `pk tree draw` writes the current one to
`.pk/tree.txt`; outside a project `pk tree minimal > my.tree` prints one to
start from.

```plaintext
rocket/
|-- .pk/
|   |-- projectkit/                      <kit>
|   |-- scripts/                         <scripts>
|   `-- settings/                        <helpers>
|-- code/
|   |-- include/                         <headers>
|   `-- src/                             <sources>
|-- profiles/                            <profiles>
|-- tests/                               <tests> optional
...
```

- A line ending in `<part>` places that part where the line is. Every other
  line is only a picture: renaming or moving it changes nothing.
- To move a part, put its line under another folder, or rename its folder.
- To leave an optional part out, delete its line. A required part with no
  line is an error.
- Indentation decides nesting. `|--`, `` `-- ``, `+--` and the box drawing
  characters of `tree` are all read; spacer lines with only `|` are fine.

## pk tree apply

`pk tree apply FILE|NAME` moves an existing project to another tree:

1. The new tree is checked first. A tree that cannot be used (an unknown
   part, a missing required part, two parts in one folder, a part inside the
   kit, a path outside the project) stops here with every problem listed and
   **nothing changed**.
2. The plan is shown: which folders move and what is left out.
3. Every file of every moved part is moved (a part inside another part, such
   as the kit inside `cmake/`, moves on its own). Left-out parts are deleted.
4. Files that name those paths are updated: `CMakeLists.txt` (module path,
   `add_subdirectory`), `CMakePresets.json`, the recipe's `exports_sources`,
   the CI workflows, the profiles (the path to the toolchain files),
   the settings files, `.gitignore`, the pre-commit config and `README.md`.
5. `.pk/tree.conf` is written (or removed, for the plain classic tree), and
   checked against the files.
6. In a git repository the change is one commit, `pk tree: <tree>`
   (`--no-commit` only stages it).

If anything fails on the way, every file is put back where it was. Other
files that still name an old path (your own scripts, docs) are left alone and
listed with their line numbers. Build trees remember the old paths: run
`pk rebuild` (or `pk full-clean`) before the next build.

Flags: `--omit=PART,...` leaves more parts out, `--dry-run` shows the plan
only, `--yes` skips the question, `--no-commit` stages without committing.
Applying needs no uncommitted changes in the files that move.

A part left out cannot be brought back by `apply`: its files are gone from
the project. Make a scratch project with it (`pk new tmp`) and copy the files
over, then add the part's line back.

## When a tree breaks

`.pk/tree.conf` is written by pk only, and it is always a tree that matched
the files. Two things can still go wrong, and both have one answer:

- An edited drawing does not apply: nothing changed, and the error says which
  line is wrong. `pk tree reset` redraws `.pk/tree.txt` as the tree that
  works now.
- `.pk/tree.conf` was edited by hand, or a part's folder was moved without pk:
  every pk command stops with a message instead of failing halfway.
  `pk tree check` lists what does not match; `pk tree reset` restores the last
  tree that matches the files (`.pk/tree.conf` itself, else the committed one,
  else the classic tree).

`.pk/tree.txt` is a scratch file: the template's `.gitignore` ignores it.

## How the rest of the kit reads the tree

| Reader                         | Reads                                          |
|--------------------------------|------------------------------------------------|
| CMake (`Layout.cmake`)         | `pk_tree_dir(<var> <part>)` for the creators' default folders |
| `pk.py`, `verify.py`, `release.py`, `package.py`, `pk dep` | profiles, settings, apps, tests |
| the wrappers in `scripts/`     | where the kit is                               |
| the global `pk`                | where the project's `pk.py` is                 |
| `pk shell-init`'s `pk` function| where the project's `pk.py` is                 |
| `pk-setup` (CI)                | where the profiles are, for the Conan cache key |
| `pk sync`                      | where the kit and the scripts are             |

`pk sync` maps QCDX's paths (always the classic tree) to this project's: an
upstream change to `cmake/projectkit/X` lands in `.pk/projectkit/X`. The kit's
own docs keep naming the classic paths.
