# `release.py` Script

Exclusively builds what a release should ship: one archive per target, tested
and ensured that it runs on a clean machine that knows nothing about the build
toolchain, plus cheksums and *notes* (a dynamic list of strings used to collect
crucial compatibility metadata about compiled binaries).
`.github/workflows/release.yml` only sets up its runners and calls the
`release.py` script, so all steps run locally.

### Important files

```plaintext
cmake/projectkit/scripts/pklib/release.py  // the implementation
cmake/projectkit/scripts/pklib/targets.py  // target registry, shared with verify.py
.github/actions/pk-setup/action.yml        // toolchain + Conan per target, shared with verify.yml
.github/workflows/release.yml              // CI release pipeline
scripts/release.py                         // rlease.py implementation wrapper
scripts/helpers/release/release.conf       // project settings
scripts/helpers/release/NOTES.md           // release notes template (optional)
```

## Releasing

```bash
# first, set the version in CMakeLists.txt: project(myproject VERSION 1.2.0 ...)
git commit -am "Release 1.2.0"
git tag -s v1.2.0 -m "myproject 1.2.0"
git push origin main v1.2.0
```

The CI rlease workflow will then build every release target and create a
**draft** release. Check it on GitHub Releases page and *Piblish* it when
ready. A tag with a suffix (`v1.2.0-rc.1`) will become a pre-release.

Before building, the release is planned; the `plan` job catches issues early:

- the tag does not match `project(VERSION *.*.* ...)`
- a target is unknown, or a cross target has no profile
- signing is enabled, however, a repository variable or secret is missing
- `RELEASES_REPO` points to another repository but `RELEASES_TOKEN` is not set

If a tag is pushed *again* via `git tag -f v...` and `git push -f origin v...`,
the release workflow re-runs and updates the previous draft made.

To test a pipeline change without releasing it, manually invoke the workflow on
GitHub (*Actions > release > Run workflow*). It will build and upload the
artifacts, **signing nothing**.

## Commands

#### plan [--tag=TAG] [--targets=LIST]

- check TAG against project(VERSION) and print the matrix (in CI it's also
written to $GITHUB_OUTPUT)

#### stage \<target>

- build, test and install \<target> into build/release/TARGET/stage, then run
the hook and portability checks

#### pack \<target> [--plain]

- archive the staged \<target> into build/release/dist/; --plain keeps
PK_RELEASE_ASSETS names as they are

#### finalize [--tag=TAG]

- add PK_RELEASE_EXTRA, write SHA256SUMS and build/release/notes.md

#### list

- every target, its CI runner and if it's capable of building here

#### help

- show this message

### **Examples:**

```bash
$release = ./scripts/release.py
$release list
$release plan --tag=v1.2.0
$release stage linux-x86_64
$release pack linux-x86_64
$release finalize --tag=v1.2.0
```

## CI Pipeline

| job | runs on | does |
| :-- | :-- | :-- |
| `plan` | ubuntu | `release.py plan` |
| `build` (one per target) | the target's runner | setup, `stage`, sign (Windows, optional), `pack`, upload |
| `publish` (tags only) | ubuntu | download, `finalize`, attest, create/update the draft, sync the releases README |

Time and storage saved:

- `plan` catches tag and settings mistakes before any build starts.
- `fail-fast`: one failing target cancels the whole CI, no release.
- Conan cache is **restored only** from the entries `verify.yml` saved on
  `main` (tags are able to read them). Releases never store a second copy of
  the Conan as a result.
- Cross targets build without tests (they cannot run them).
- Intermediate artifacts are stored uncompressed (archives already are) and
  expire after one day.
- apt only runs when a package is missing and `verify.yml` skips commits that
  only change the release files.

## Release Settings

All settings reside within the file `scripts/helpers/release/release.conf`.
Every key is optional (as you can see if you view the file). A key not set by
the file is read from the environment.

| key | default | meaning |
| :-- | :-- | :-- |
| `PK_RELEASE_TARGETS` | `linux-x86_64 linux-armv8 macos-armv8 windows-ucrt64 windows-clangarm64` | targets released on a tag |
| `PK_RELEASE_TYPE` | `Release` | CMake build type |
| `PK_RELEASE_TESTS` | `ON` | run ctest on native targets before shipping |
| `PK_RELEASE_STRIP` | `ON` | `cmake --install --strip` |
| `PK_RELEASE_ARCHIVE` | `ON` | one archive per target |
| `PK_RELEASE_RUNTIME` | `bundle` | Windows toolchain DLLs: `bundle`, `forbid`, `ignore` |
| `PK_RELEASE_NAME` | `{project}-{version}-{target}` | archive name (and top folder) |
| `PK_RELEASE_FILES` | `LICENSE` | repository files added to every archive |
| `PK_RELEASE_NOTES` | `scripts/helpers/release/NOTES.md` | notes template, built-in one when missing |
| `PK_RELEASE_DRAFT` | `ON` | create the release as a draft |
| `PK_RELEASE_RUNNERS` | | `TARGET=RUNNER` overrides of the runner table |
| `PK_RELEASE_PK_FLAGS` | | extra `pk build` flags, e.g. `--lto` |
| `PK_RELEASE_EXCLUDE` | | globs removed from the install tree |
| `PK_RELEASE_HOOK` | | Python script run on the install tree |
| `PK_RELEASE_MACOS_MIN` | | `MACOSX_DEPLOYMENT_TARGET` for macOS targets |
| `PK_RELEASE_ASSETS` | | install-tree files also attached on their own |
| `PK_RELEASE_EXTRA` | | repository files attached once |
| `PK_RELEASE_HASH_LINK` | | `{sha256}` URL each hash in the notes links to |
| `PK_RELEASE_README` | | file synced to the releases repository's `README.md` |

### Targets and runners

### Notes template

### Hook

## Portability checks

Ran via `stage` on the installed tree; a failure stops the release. What each release binary needs to function is written to the job summary.

| system | checked | reported |
| :-- | :-- | :-- |
| Windows | Every imported DLL is shipped, a system DLL, or a toolchain runtime handled by `PK_RELEASE_RUNTIME`. | DLLs that were bundled |
| Linux | `ldd`: nothing missing, nothing outside the system library folders unless shipped (native targets). | newest `GLIBC_` and `GLIBCXX_` versions needed |
| macOS | `otool -L`: only `/usr/lib`, `/System/Library`, or `@rpath` libraries that are shipped. | minimum macOS version |

Toolchain DLLs on Windows (`libstdc++-6.dll`, `libgcc_s_seh-1.dll`,
`libwinpthread-1.dll`, `libc++.dll`, `libunwind.dll`) are **found in** the
compiler's folders. With `bundle` they are copied next to the binaries that
import them; with `forbid` the release fails, used by projects that link with
`-static` and want to ensure it is taking effect.

A Linux binary build on Ubuntu 24.04 needs that rlease's glibc (2.39), and with
GCC 14 a newer libstdc++ than older distributions ship. Link with
`-static-libstdc++ -static-libgcc` to drop the second requirement. To drop the
first requirement, build on an older runner via the `PK_RELEASE_RUNNERS` setting.

## Repository settings

| kind | name | used for |
| :-- | :-- | :-- |
| variable | `RELEASES_REPO` | release into another repository, e.g., public releases of a private project |
| secret | `RELEASES_TOKEN` | fine-grained token with *Contents: read and write* on `RELEASES_REPO` |
| variable | `SIGNING_ENABLED` | `true` turns on Windows signing (tags only) |
| variables | `SIGNING_ENDPOINT`, `SIGNING_ACCOUNT`, `SIGNING_PROFILE` | Azure Artifact Signing account |
| secrets | `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` | OIDC login of the signing identity |

Without any of these settings set, releases default to go to the same
repository using the workflow's token.

Public repositories also get a build provenance attestation covering every
asset which anyone is able to check:

```bash
gh attestation verify myproject-1.2.0-linux-x86_64.tar.gz -R owner/myproject
```

## Extending / Customizing

| to add | change |
| :-- | :-- |
| a file inside every archive | `PK_RELEASE_FILES`, or created within the hook |
| a release-wide file | `PK_RELEASE_EXTRA` |
| a build step on the installed files | `PK_RELEASE_HOOK` |
| targets/runners | `PK_RELEASE_TARGETS` (and `PK_RELEASE_RUNNERS` for a new runner) |
| an entire new kind of target | a record in `targets.py`, a runner in `release.py`, and its setup in `pk-setup` |
| a new CI step | `release.yml`; prefer to keep all project logic in the hook so `pk sync` and template updates continue to be mergeable |
