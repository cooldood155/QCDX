"""Release builds: .github/workflows/release.yml uses this script entirely for
releases, runnable locally.

  plan      check the tag against project(VERSION) from CMake and print the CI
            build matrix
  stage     build (and test) a target, install it into
            build/release/<target>/stage and run the project hook, and finally
            check that it runs on *user* machine (no non-native deps)
  pack      archive one staged target into build/release/dist/
  finalize  add release-wide files and write the SHA256SUMS and release notes
  list      every target, its CI runner and if is is capable of being built
            under the current shell

Project release settings reside at 'scripts/helpers/release/release.conf';
every setting has a default, projects will only list set settings differing
from their defualts.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import zipfile
from typing import Dict, List, Optional, Set, Tuple

from . import targets
from .common import (BUILD_TYPES, C, capture, detect_project, entry, err, have, load_conf, out, remove,
                     repo_root, run, has_file, setup_output, walk_files)

CONF = "scripts/helpers/release/release.conf"
WORK = os.path.join("build", "release")
DIST = os.path.join(WORK, "dist")

# Override an entry with the PK_RELEASE_RUNNERS release setting!
RUNNERS = {
    "linux-x86_64": "ubuntu-24.04",
    "linux-armv8": "ubuntu-24.04-arm",
    "macos-x86_64": "macos-15-intel",
    "macos-armv8": "macos-15",
    "windows-ucrt64": "windows-2022",
    "windows-clang64": "windows-2022",
    "windows-clangarm64": "windows-11-arm",
    "cross-x86_64-linux-gnu": "ubuntu-24.04-arm",
    "cross-aarch64-linux-gnu": "ubuntu-24.04",
    "cross-x86_64-mingw-w64": "ubuntu-24.04",
    "cross-aarch64-mingw-llvm-w64": "ubuntu-24.04",
}

DEFAULTS = {
    "PK_RELEASE_TARGETS": "linux-x86_64 linux-armv8 macos-armv8 windows-ucrt64 windows-clangarm64",
    "PK_RELEASE_RUNNERS": "",
    "PK_RELEASE_TYPE": "Release",
    "PK_RELEASE_TESTS": "ON",
    "PK_RELEASE_PK_FLAGS": "",
    "PK_RELEASE_STRIP": "ON",
    "PK_RELEASE_EXCLUDE": "",
    "PK_RELEASE_HOOK": "",
    "PK_RELEASE_RUNTIME": "bundle",
    "PK_RELEASE_MACOS_MIN": "",
    "PK_RELEASE_ARCHIVE": "ON",
    "PK_RELEASE_NAME": "{project}-{version}-{target}",
    "PK_RELEASE_FILES": "LICENSE",
    "PK_RELEASE_ASSETS": "",
    "PK_RELEASE_EXTRA": "",
    "PK_RELEASE_NOTES": "scripts/helpers/release/NOTES.md",
    "PK_RELEASE_HASH_LINK": "",
    "PK_RELEASE_DRAFT": "ON",
    "PK_RELEASE_README": "",
}

DEFAULT_NOTES = """\
{assets}

Verify a download with `sha256sum -c SHA256SUMS --ignore-missing`.
"""

USAGE = """\
usage: {self} command [args...]

commands:
  plan [--tag=TAG] [--targets=LIST]
                    check TAG against project(VERSION) and print the matrix
                    (in CI it's also written to $GITHUB_OUTPUT)
  stage <target>
                    build, test and install <target> into
                    build/release/TARGET/stage, then run the hook and
                    portability checks
  pack <target> [--plain]
                    archive the staged <target> into build/release/dist/;
                    --plain keeps PK_RELEASE_ASSETS names as they are
  finalize [--tag=TAG]
                    add PK_RELEASE_EXTRA, write SHA256SUMS and
                    build/release/notes.md
  list
                    every target, its CI runner and if it's capable of building
                    here
  help
                    show this message

settings: {conf} (see cmake/projectkit/docs/RELEASE.md)

examples:
  {self} list
  {self} stage linux-x86_64 && {self} pack linux-x86_64
  {self} plan --tag=v1.2.0
  {self} finalize --tag=v1.2.0"""

SELF = "./scripts/release.py"


class Failure(Exception):
    pass


def fail(message: str) -> None:
    raise Failure(message)


def is_on(value: str) -> bool:
    return value.strip().upper() in ("ON", "1", "TRUE", "YES")


def commas_to_spaces(value: str) -> List[str]:
    return value.replace(",", " ").split()


def gh_output(**values: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return

    with open(path, "a", encoding="utf-8", newline="\n") as file:
        for name, value in values.items():
            file.write(f"{name}={value}\n")


def gh_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return

    with open(path, "a", encoding="utf-8", newline="\n") as file:
        file.write(text.rstrip("\n") + "\n\n")


def format_disk_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB"):
        if value < 1024 or unit == "MiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def sha256(path: str) -> str:
    hash_obj = hashlib.sha256()
    with open(path, "rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            hash_obj.update(block)
    return hash_obj.hexdigest()


class Release:
    def __init__(self, root: str) -> None:
        self.root = root
        self.conf = load_conf(root, CONF)
        self.project = detect_project(root)
        self.version = self.read_version()

    def get(self, name: str) -> str:
        """Get the release configuration setting `name`."""
        return self.conf.get(name, DEFAULTS[name])

    def read_version(self) -> str:
        with open(os.path.join(self.root, "CMakeLists.txt"), encoding="utf-8", errors="replace") as file:
            match = re.search(r"project\s*\([^)]*\bVERSION\s+([0-9]+(?:\.[0-9]+){0,3})", file.read(),
                              re.IGNORECASE)
        if not match:
            fail("no VERSION in the top-level project() call of CMakeLists.txt")
        return match.group(1) if match else ""

    def runners(self) -> Dict[str, str]:
        table = dict(RUNNERS)
        for pair in commas_to_spaces(self.get("PK_RELEASE_RUNNERS")):
            name, sep, runner = pair.partition("=")
            if not sep or not runner:
                fail(f"PK_RELEASE_RUNNERS: expected TARGET=RUNNER, got '{pair}'")
            table[name] = runner
        return table

    # targets -----------------------------------------------------------------

    @staticmethod
    def target_os(name: str) -> str:
        entry_ = targets.record(name)
        if entry_ and entry_[2] != "any":
            return entry_[2]
        return "windows" if "mingw" in name else "macos" if "apple" in name else "linux"

    @staticmethod
    def is_cross(name: str) -> bool:
        entry_ = targets.record(name)
        return bool(entry_ and entry_[1] == "cross")

    def stage_dir(self, target: str) -> str:
        return os.path.join(self.root, WORK, target, "stage")

    def matrix_entry(self, target: str, runner: str, plain: bool) -> Dict[str, object]:
        entry_ = targets.record(target)
        msystem = entry_[4] if entry_ and entry_[4] != "-" else ""
        windows_runner = runner.startswith("windows")
        return {
            "target": target,
            "runner": runner,
            "shell": "msys2 {0}" if msystem else "bash",
            "msystem": msystem,
            "signable": self.target_os(target) == "windows" and windows_runner,
            "timeout": 90 if windows_runner else 60,
            "plain": plain,
        }

    # plan --------------------------------------------------------------------

    def cmd_plan(self, args: List[str]) -> int:
        tag, chosen = "", ""
        for arg in args:
            if arg.startswith("--tag="):
                tag = arg.split("=", 1)[1]
            elif arg.startswith("--targets="):
                chosen = arg.split("=", 1)[1]
            else:
                fail(f"plan: unknown argument '{arg}'")

        names = commas_to_spaces(chosen) or commas_to_spaces(self.get("PK_RELEASE_TARGETS"))
        if not names:
            fail("no targets: set PK_RELEASE_TARGETS in " + CONF)

        runners = self.runners()
        problems = []
        for name in names:
            if targets.record(name) is None:
                problems.append(f"unknown target '{name}' (known: {' '.join(r[0] for r in targets.RECORDS)})")
            elif name not in runners:
                problems.append(f"no CI runner for '{name}', add it to PK_RELEASE_RUNNERS")
            elif self.is_cross(name) and not os.path.isfile(
                    os.path.join(self.root, "profiles", name[len("cross-"):])):
                problems.append(f"'{name}' needs profiles/{name[len('cross-'):]}")
        if len(set(names)) != len(names):
            problems.append("a target is listed twice")

        prerelease = False
        if tag:
            match = re.fullmatch(r"v([0-9]+(?:\.[0-9]+){0,3})(-[0-9A-Za-z.-]+)?", tag)
            if not match:
                problems.append(f"tag '{tag}' is not vMAJOR.MINOR.PATCH[-suffix]")
            elif match.group(1) != self.version:
                problems.append(f"tag '{tag}' but project(VERSION) is {self.version}: update VERSION in "
                                "CMakeLists.txt then move the tag and push it again")
            else:
                prerelease = bool(match.group(2))

        signing = is_on(os.environ.get("PK_SIGNING", ""))
        if signing:
            if not is_on(os.environ.get("PK_SIGNING_READY", "ON")):
                problems.append("SIGNING_ENABLED is true but a secret (AZURE_*) or a variable (SIGNING_*) is empty")

            for name in names:
                if self.target_os(name) == "windows" and not runners.get(name, "").startswith("windows"):
                    problems.append(f"'{name}' is built on {runners.get(name)}, Windows signing needs a "
                                    "Windows runner")

        repo = os.environ.get("PK_RELEASES_REPO", "")
        if tag and repo and repo != os.environ.get("GITHUB_REPOSITORY", repo):
            if not is_on(os.environ.get("PK_HAS_RELEASES_TOKEN", "ON")):
                problems.append(f"releases go to {repo} but it's RELEASES_TOKEN secret is not set")

        if problems:
            for problem in problems:
                annotate(problem)
            return 1

        plain = len(names) == 1
        matrix = {"include": [self.matrix_entry(n, runners[n], plain) for n in names]}
        draft = is_on(self.get("PK_RELEASE_DRAFT"))
        out(f"{C.bold}{self.project} {self.version}{C.reset}  tag {tag or '(none, build only)'}")
        out(f"{'TARGET':<30} RUNNER")
        for item in matrix["include"]:
            out(f"{item['target']:<30} {item['runner']}")

        gh_output(project=self.project, version=self.version, tag=tag,
                  prerelease=str(prerelease).lower(), draft=str(draft).lower(),
                  matrix=json.dumps(matrix, separators=(",", ":")))

        rows = "\n".join(f"| `{i['target']}` | `{i['runner']}` |" for i in matrix["include"])
        gh_summary(f"### {self.project} {self.version} {tag}\n\n| Target | Runner |\n| :-- | :-- |\n{rows}")
        return 0

    # stage -------------------------------------------------------------------

    def pk(self, *args: str, env: Optional[Dict[str, str]] = None) -> None:
        if run([sys.executable,
                os.path.join(self.root, "scripts", "pk.py"), *args],
               cwd=self.root, env=env) != 0:
            fail(f"pk {' '.join(args)} failed")

    def build_tree(self, target: str, build_type: str) -> str:
        from .pk import preset_query

        prefix = target[len("cross-"):] if self.is_cross(target) else "native"
        preset = f"{prefix}-{build_type.lower()}"
        binary = next((line[len("binary|"):] for line in
                       preset_query("dirs", preset) if
                       line.startswith("binary|")), "")
        if not binary:
            fail(f"CMakePresets.json has no configure preset '{preset}'")
        return os.path.join(self.root, binary)

    def cmd_stage(self, args: List[str]) -> int:
        if len(args) != 1:
            fail("stage takes one TARGET")

        target = args[0]
        result = targets.availability(target, self.root, "strict")
        if result is None:
            fail(f"unknown target '{target}', view available targets via '{SELF} list'")
        if result and not result[0]:
            fail(f"{target} cannot build in this shell: {result[1]}")

        build_type = self.get("PK_RELEASE_TYPE")
        if build_type not in BUILD_TYPES:
            fail(f"PK_RELEASE_TYPE='{build_type}' is not one of {', '.join(BUILD_TYPES)}")
        cross = self.is_cross(target)
        target_os = self.target_os(target)

        env = dict(os.environ)
        macos_min = self.get("PK_RELEASE_MACOS_MIN")
        if target_os == "macos" and macos_min:
            env["MACOSX_DEPLOYMENT_TARGET"] = macos_min

        flags = [build_type, *self.get("PK_RELEASE_PK_FLAGS").split()]
        if cross:
            self.pk("build", *flags, "-x", target[len("cross-"):], "--no-tests", env=env)
        elif is_on(self.get("PK_RELEASE_TESTS")):
            self.pk("test", *flags, env=env)
        else:
            self.pk("build", *flags, "--no-tests", env=env)

        stage = self.stage_dir(target)
        if not remove(stage):
            fail(f"cannot empty {stage}")

        install = ["cmake", "--install", self.build_tree(target, build_type), "--prefix", stage]
        if is_on(self.get("PK_RELEASE_STRIP")):
            install.append("--strip")
        if run(install, cwd=self.root) != 0:
            fail("cmake --install failed")

        self.exclude(stage)
        self.hook(target, stage)
        if not any(True for _ in walk_files(stage)):
            fail(f"nothing was installed into {stage}: check install() rules and PK_RELEASE_EXCLUDE setting")

        notes = Portability(self, target, target_os, stage, cross).check()
        report = self.report(target, stage, notes)
        with open(os.path.join(self.root, WORK, target, "report.md"), "w", encoding="utf-8",
                  newline="\n") as file:
            file.write(report)

        out("\n" + report)
        gh_summary(report)
        gh_output(stage=os.path.abspath(stage))
        return 0

    def exclude(self, stage: str) -> None:
        patterns = commas_to_spaces(self.get("PK_RELEASE_EXCLUDE"))
        if not patterns:
            return

        for path in sorted(walk_files(stage)):
            relative = os.path.relpath(path, stage).replace(os.sep, "/")
            if any(fnmatch.fnmatchcase(relative, pattern) for pattern in patterns):
                os.remove(path)

        # Bottom-up
        for directory, _dirs, _files in os.walk(stage, topdown=False):
            if directory != stage and not os.listdir(directory):
                os.rmdir(directory)

    def hook(self, target: str, stage: str) -> None:
        script = self.get("PK_RELEASE_HOOK")
        if not script:
            return

        path = os.path.join(self.root, script)
        if not os.path.isfile(path):
            fail(f"PK_RELEASE_HOOK: no file {script}")

        out(f"\n{C.bold}hook{C.reset} {script}")

        env = dict(os.environ, PK_RELEASE_TARGET=target, PK_RELEASE_STAGE=stage,
                   PK_RELEASE_PROJECT=self.project, PK_RELEASE_VERSION=self.version, PK_REPO_ROOT=self.root)
        if run([sys.executable, path, target, stage], cwd=self.root, env=env) != 0:
            fail(f"PK_RELEASE_HOOK {script} failed")

    def report(self, target: str, stage: str, notes: List[str]) -> str:
        files = sorted(walk_files(stage))
        total = sum(os.path.getsize(path) for path in files)
        rows = "\n".join(f"| `{os.path.relpath(p, stage).replace(os.sep, '/')}` | {format_disk_size(os.path.getsize(p))} |"
                         for p in files[:40])
        more = f"\n\n{len(files) - 40} more files not shown." if len(files) > 40 else ""
        lines = "".join(f"- {note}\n" for note in notes)
        return (f"#### {target}: {len(files)} files, {format_disk_size(total)}\n\n{lines}\n"
                f"| File | Size |\n| :-- | --: |\n{rows}{more}\n")

    # pack --------------------------------------------------------------------

    def cmd_pack(self, args: List[str]) -> int:
        plain = "--plain" in args
        names = [a for a in args if a != "--plain"]
        if len(names) != 1 or names[0].startswith("-"):
            fail("pack takes one TARGET and optionally --plain")

        target = names[0]
        stage = self.stage_dir(target)
        if not os.path.isdir(stage):
            fail(f"{target} is not staged, run '{SELF} stage {target}' first")

        dist = os.path.join(self.root, DIST)
        os.makedirs(dist, exist_ok=True)
        windows = self.target_os(target) == "windows"
        made: List[str] = []

        if is_on(self.get("PK_RELEASE_ARCHIVE")):
            name = self.get("PK_RELEASE_NAME")
            for key, value in (("project", self.project), ("version", self.version), ("target", target)):
                name = name.replace("{" + key + "}", value)

            extras = []
            for relative in commas_to_spaces(self.get("PK_RELEASE_FILES")):
                path = os.path.join(self.root, relative)
                if not os.path.isfile(path):
                    fail(f"PK_RELEASE_FILES: no file {relative}")
                extras.append(path)

            archive = os.path.join(dist, name + (".zip" if windows else ".tar.gz"))
            remove(archive)
            if windows:
                write_zip(archive, name, stage, extras)
            else:
                write_tar(archive, name, stage, extras)
            made.append(archive)

        for relative in commas_to_spaces(self.get("PK_RELEASE_ASSETS")):
            source = os.path.join(stage, relative)
            if windows and not os.path.isfile(source) and os.path.isfile(source + ".exe"):
                source += ".exe"
            if not os.path.isfile(source):
                fail(f"PK_RELEASE_ASSETS: {relative} is not in the staged {target}")

            stem, ext = os.path.splitext(os.path.basename(source))
            asset = os.path.join(dist, f"{stem}{ext}" if plain else f"{stem}-{target}{ext}")
            shutil.copy2(source, asset)
            made.append(asset)

        if not made:
            fail("nothing to pack: PK_RELEASE_ARCHIVE is OFF and PK_RELEASE_ASSETS is empty")
        for path in made:
            out(f"{format_disk_size(os.path.getsize(path)):>10}  {os.path.relpath(path, self.root)}")
        return 0

    # finalize ----------------------------------------------------------------

    def cmd_finalize(self, args: List[str]) -> int:
        tag = ""
        for arg in args:
            if arg.startswith("--tag="):
                tag = arg.split("=", 1)[1]
            else:
                fail(f"finalize: unknown argument '{arg}'")
        tag = tag or f"v{self.version}"
        dist = os.path.join(self.root, DIST)
        os.makedirs(dist, exist_ok=True)

        for relative in commas_to_spaces(self.get("PK_RELEASE_EXTRA")):
            source = os.path.join(self.root, relative)
            if not os.path.isfile(source):
                fail(f"PK_RELEASE_EXTRA: no file {relative}")

            target = os.path.join(dist, os.path.basename(source))
            if os.path.exists(target):
                fail(f"PK_RELEASE_EXTRA: {os.path.basename(source)} clashes with a built asset")
            shutil.copy2(source, target)

        sums = os.path.join(dist, "SHA256SUMS")
        remove(sums)
        assets = sorted(name for name in os.listdir(dist) if os.path.isfile(os.path.join(dist, name)))
        if not assets:
            fail(f"{DIST} is empty, nothing to release")

        hashes = {name: sha256(os.path.join(dist, name)) for name in assets}
        with open(sums, "w", encoding="ascii", newline="\n") as file:
            file.writelines(f"{hashes[name]}  {name}\n" for name in assets)

        link = self.get("PK_RELEASE_HASH_LINK")
        rows = []
        for name in assets:
            digest = f"`{hashes[name]}`"
            if link:
                digest = f"[{digest}]({link.replace('{sha256}', hashes[name])})"
            rows.append(f"| `{name}` | {format_disk_size(os.path.getsize(os.path.join(dist, name)))} | {digest} |")
        table = "| File | Size | SHA-256 |\n| :-- | --: | :-- |\n" + "\n".join(rows)

        template_path = os.path.join(self.root, self.get("PK_RELEASE_NOTES"))
        template = DEFAULT_NOTES
        if os.path.isfile(template_path):
            with open(template_path, encoding="utf-8") as file:
                template = file.read()
        notes = template
        for key, value in (("project", self.project), ("version", self.version), ("tag", tag),
                           ("assets", table), ("repository", os.environ.get("GITHUB_REPOSITORY", ""))):
            notes = notes.replace("{" + key + "}", value)

        notes_path = os.path.join(self.root, WORK, "notes.md")
        with open(notes_path, "w", encoding="utf-8", newline="\n") as file:
            file.write(notes)

        readme = self.get("PK_RELEASE_README")
        if readme and not os.path.isfile(os.path.join(self.root, readme)):
            fail(f"PK_RELEASE_README: no file {readme}")

        out(notes)
        gh_output(notes=notes_path, sums=sums, dist=dist, readme=readme,
                  title=f"{self.project} {tag[1:] if tag.startswith('v') else tag}")
        return 0

    # list --------------------------------------------------------------------

    def cmd_list(self) -> int:
        chosen = set(commas_to_spaces(self.get("PK_RELEASE_TARGETS")))
        runners = self.runners()
        out(f"{self.project} {self.version}, released targets marked *\n")
        out(f"  {'TARGET':<30} {'CI RUNNER':<18} {'HERE':<5} NOTE")

        for name, *_rest in targets.RECORDS:
            ok, reason = targets.availability(name, self.root, "strict") or (False, "")
            mark = "*" if name in chosen else " "
            out(f"{mark} {name:<30} {runners.get(name, '-'):<18} {'yes' if ok else 'no':<5} {reason}")
        return 0


# archives --------------------------------------------------------------------

def archive_members(stage: str, extras: List[str]) -> List[Tuple[str, str]]:
    members = [(path, os.path.relpath(path, stage).replace(os.sep, "/")) for path in sorted(walk_files(stage))]
    taken = {name for _path, name in members}

    for path in extras:
        name = os.path.basename(path)
        if name in taken:
            fail(f"PK_RELEASE_FILES: {name} is already in the install tree")

        members.append((path, name))
    return members


def write_zip(archive: str, top: str, stage: str, extras: List[str]) -> None:
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as handle:
        for path, name in archive_members(stage, extras):
            handle.write(path, f"{top}/{name}")


def write_tar(archive: str, top: str, stage: str, extras: List[str]) -> None:
    def clean(info: tarfile.TarInfo) -> tarfile.TarInfo:
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        return info

    with tarfile.open(archive, "w:gz", compresslevel=9) as handle:
        for path, name in archive_members(stage, extras):
            handle.add(path, f"{top}/{name}", recursive=False, filter=clean)


# portability -----------------------------------------------------------------

WINDOWS_TRIPLES = ("x86_64-w64-mingw32", "aarch64-w64-mingw32", "i686-w64-mingw32")


def pe_imports(path: str) -> Optional[List[str]]:
    """*Portable Executable (Windows-like).*

    Retrieves DLLs implicitly linked by a PE.

    **Returns** a list of DLL names loaded automatically at startup, or None if
    the file is not a valid PE binary."""
    try:
        with open(path, "rb") as file:
            data = file.read()
    except OSError:
        return None
    if len(data) < 0x40 or data[:2] != b"MZ":
        return None

    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if pe + 24 > len(data) or data[pe:pe + 4] != b"PE\0\0":
        return None

    sections, optional_size = struct.unpack_from("<H12xH", data, pe + 6)
    optional = pe + 24
    magic = struct.unpack_from("<H", data, optional)[0]
    directories = optional + (112 if magic == 0x20B else 96)
    if magic not in (0x10B, 0x20B) or directories + 16 > optional + optional_size:
        return []

    import_rva = struct.unpack_from("<I", data, directories + 8)[0]
    table = optional + optional_size
    spans = [struct.unpack_from("<8xII4xI", data, table + 40 * i) for i in range(sections)]

    def offset(rva: int) -> int:
        for virtual_size, address, raw in spans:
            if address <= rva < address + max(virtual_size, 1):
                return rva - address + raw
        return -1

    names: List[str] = []
    cursor = offset(import_rva) if import_rva else -1
    while 0 <= cursor and cursor + 20 <= len(data):
        name_rva = struct.unpack_from("<12xI", data, cursor)[0]
        if not name_rva:
            break

        start = offset(name_rva)
        if start < 0:
            break

        names.append(data[start:data.index(b"\0", start)].decode("ascii", "replace"))
        cursor += 20
    return names


def elf_like(path: str) -> bool:
    """*Executable and Linkable Format (Unix-like).*

    Checks if a file is an ELF binary by reading its *magic number*.

    **Returns** True if the file signature is of ELF format, or False if the
    file is not an ELF binary or cannot be read."""
    try:
        with open(path, "rb") as file:
            return file.read(4) == b"\x7fELF"
    except OSError:
        return False


def macho_like(path: str) -> bool:
    """*Mach Object (Apple-like).*

    Checks if a file is a Mach-O binary by matching 32-bit, 64-bit, or
    Universal Fat binary *magic numbers*.

    **Returns** True if the signature matches Mach-O format, or False if it
    doesn't match or cannot be read."""
    try:
        with open(path, "rb") as file:
            return file.read(4) in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe")
    except OSError:
        return False


def version_key(text: str) -> Tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


class Portability:
    """Prove the staged tree runs on a machine without the dev toolchain, reporting what it needs."""

    def __init__(self, release: Release, target: str, target_os: str, stage: str, cross: bool) -> None:
        self.release = release
        self.target = target
        self.target_os = target_os
        self.stage = stage
        self.cross = cross
        self.notes: List[str] = []

    def check(self) -> List[str]:
        out(f"\n{C.bold}portability{C.reset} {self.target}")
        if self.target_os == "windows":
            self.windows()
        elif self.target_os == "linux":
            self.linux()
        elif self.target_os == "macos":
            self.macos()
        return self.notes

    def compilers(self) -> List[str]:
        """Paths to available profile cross-compilers, fallback to system
        compilers (CC, gcc, clang, cc)."""

        found: List[str] = []
        if self.cross:
            with open(os.path.join(self.release.root, "profiles", self.target[len("cross-"):]),
                      encoding="utf-8") as file:
                text = file.read()
            found += re.findall(r'"c":\s*"([^"]+)"', text)
            found += re.findall(r'detect_\w+_compiler\("([^"]+)"\)', text)
        else:
            found += [os.environ.get("CC", ""), "gcc", "clang", "cc"]
        return [path for path in (shutil.which(name) for name in found if name) if path]

    def runtime_finder(self):
        compilers = self.compilers()
        directories: List[str] = []
        for compiler in compilers:
            bin_dir = os.path.dirname(os.path.realpath(compiler))
            directories.append(bin_dir)
            for triple in WINDOWS_TRIPLES:
                directories.append(os.path.join(os.path.dirname(bin_dir), triple, "bin"))

        listing: Dict[str, str] = {}
        for directory in directories:
            if os.path.isdir(directory):
                for name in os.listdir(directory):
                    listing.setdefault(name.lower(), os.path.join(directory, name))

        def find(dll: str) -> str:
            if dll.lower() in listing:
                return listing[dll.lower()]

            for compiler in compilers:
                code, text = capture([compiler, f"-print-file-name={dll}"])
                text = text.strip()
                if code == 0 and os.path.isabs(text) and os.path.isfile(text):
                    return text
            return ""
        return find

    def windows(self) -> None:
        """Ensures PE binaries resolve dependencies and bundles toolchain DLLs 
        according to the PK_RELEASE_RUNTIME setting."""

        mode = self.release.get("PK_RELEASE_RUNTIME").lower()
        if mode not in ("bundle", "forbid", "ignore"):
            fail(f"PK_RELEASE_RUNTIME='{mode}' is not bundle, forbid or ignore")

        find = self.runtime_finder()
        bundled: List[str] = []
        missing: Set[str] = set()
        queue = sorted(walk_files(self.stage))
        seen: Set[str] = set()
        while queue:
            binary = queue.pop(0)
            if binary in seen:
                continue

            seen.add(binary)
            imports = pe_imports(binary)
            if not imports:
                continue

            shipped = {name.lower() for name in os.listdir(os.path.dirname(binary))}
            for dll in imports:
                if dll.lower() in shipped:
                    continue

                source = find(dll)
                if not source:
                    continue

                if mode != "bundle":
                    missing.add(dll)
                else:
                    copy = os.path.join(os.path.dirname(binary), os.path.basename(source))
                    shutil.copy2(source, copy)
                    bundled.append(os.path.relpath(copy, self.stage).replace(os.sep, "/"))
                    queue.append(copy)

        if missing and mode == "forbid":
            fail(f"{self.target} needs toolchain DLLs not shipped: {', '.join(sorted(missing))}. "
                 "Link them statically (e.g. -static) or set the setting PK_RELEASE_RUNTIME=bundle")

        if missing:
            self.notes.append(f"NOT shipped (PK_RELEASE_RUNTIME=ignore): {', '.join(sorted(missing))}")
        elif bundled:
            self.notes.append(f"bundled toolchain runtime: {', '.join(f'`{name}`' for name in bundled)}")
        else:
            self.notes.append("no toolchain DLLs needed, only Windows system DLLs")

    def linux(self) -> None:
        """Ensure ELF binaries used libraries resolve **and nothing** points
        into the build machine and reports the newest glibc/libstdc++ symbol
        versions."""

        glibc, glibcxx = "", ""
        problems: List[str] = []
        system = ("/lib/", "/lib64/", "/usr/lib/", "/usr/lib64/", "/usr/lib32/")
        binaries = [path for path in sorted(walk_files(self.stage)) if elf_like(path)]
        for binary in binaries:
            with open(binary, "rb") as file:
                data = file.read()

            for match in re.findall(rb"GLIBC_([0-9]+\.[0-9]+(?:\.[0-9]+)?)", data):
                text = match.decode()
                if not glibc or version_key(text) > version_key(glibc):
                    glibc = text
            for match in re.findall(rb"GLIBCXX_(3\.4\.[0-9]+)", data):
                text = match.decode()
                if not glibcxx or version_key(text) > version_key(glibcxx):
                    glibcxx = text

            if self.cross or not have("ldd"):
                continue

            _code, text = capture(["ldd", binary], merge=True)
            shipped = {os.path.basename(p) for p in binaries}
            for line in text.splitlines():
                name, arrow, where = line.strip().partition(" => ")
                if not arrow:
                    continue

                where = where.split(" (", 1)[0].strip()
                relative = os.path.relpath(binary, self.stage)
                if where == "not found":
                    problems.append(f"{relative}: {name} not found")
                elif not where.startswith(system) and name not in shipped:
                    problems.append(f"{relative}: {name} resolves to {where}, which users will not have")

        if problems:
            fail(f"{self.target} is not self-contained:\n  " + "\n  ".join(problems))
        if glibc:
            self.notes.append(f"needs glibc {glibc} or newer")
        if glibcxx:
            self.notes.append(f"needs libstdc++ with GLIBCXX_{glibcxx} (link with -static-libstdc++ to drop this)")
        if not binaries:
            self.notes.append("no ELF binaries")

    def macos(self) -> None:
        """Ensures Mach-O binaries only use system libraries or
        shipped/packaged libraries and reports the minimum macOS version
        required."""

        if not have("otool"):
            self.notes.append("otool not found, dependency check skipped")
            return

        problems: List[str] = []
        minimum = ""
        binaries = [path for path in sorted(walk_files(self.stage)) if macho_like(path)]
        shipped = {os.path.basename(p) for p in binaries}
        for binary in binaries:
            relative = os.path.relpath(binary, self.stage)
            _code, text = capture(["otool", "-L", binary])
            for line in text.splitlines()[1:]:
                library = line.strip().split(" (", 1)[0]
                if not library or library.startswith(("/usr/lib/", "/System/Library/")):
                    continue

                if library.startswith(("@rpath/", "@loader_path/", "@executable_path/")):
                    if os.path.basename(library) not in shipped:
                        problems.append(f"{relative}: {library} is not shipped")
                    continue
                problems.append(f"{relative}: {library} is outside the system, users will not have it")

            _code, text = capture(["otool", "-l", binary])
            for match in re.findall(r"\bminos\s+([0-9.]+)", text):
                if not minimum or version_key(match) > version_key(minimum):
                    minimum = match

        if problems:
            fail(f"{self.target} is not self-contained:\n  " + "\n  ".join(problems))
        if minimum:
            self.notes.append(f"needs macOS {minimum} or newer (PK_RELEASE_MACOS_MIN lowers it)")


def annotate(message: str) -> None:
    first, _, rest = message.partition("\n")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        err(f"::error::{first}" + (f"%0A{rest.replace(chr(10), '%0A')}" if rest else ""))
    else:
        err(f"{C.red}error{C.reset}: {message}")


def usage() -> None:
    out(USAGE.format(self=SELF, conf=CONF))


def main(argv: List[str], root: Optional[str] = None) -> int:
    return entry(_main, argv, root)


def _main(argv: List[str], given_root: Optional[str]) -> int:
    root = repo_root(given_root, has_file("CMakeLists.txt", "CMakePresets.json"),
                     "no CMakeLists.txt + CMakePresets.json above {cwd}: set PK_REPO_ROOT")
    setup_output()
    os.chdir(root)
    command, args = (argv[0], argv[1:]) if argv else ("help", [])

    try:
        release = Release(root)
        if command == "plan":
            return release.cmd_plan(args)
        if command == "stage":
            return release.cmd_stage(args)
        if command == "pack":
            return release.cmd_pack(args)
        if command == "finalize":
            return release.cmd_finalize(args)
        if command == "list":
            return release.cmd_list()
        if command in ("help", "-h", "--help"):
            usage()
            return 0
        err(f"unknown command: {command}\n")
        usage()
        return 2

    except Failure as failure:
        annotate(str(failure))
        return 1
    except subprocess.CalledProcessError as error:
        annotate(str(error))
        return 1
