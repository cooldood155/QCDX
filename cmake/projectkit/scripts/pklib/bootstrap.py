"""Rename of a project created from the template: directories, file names and
file contents, in that order.

The cmake/projectkit/ directory is never changed because nothing in it uses a
specific project name. Git is how you undo; the script won't run on a dirty
git repository tree unless the --force flag is given.
"""

from __future__ import annotations

import os
import re
from typing import Iterator, List, Optional, Set

from .common import (C, capture, confirm, detect_project, entry, err, has_file, out, repo_root, run,
                     setup_output)

USAGE = """\
usage: {self} <new-name> [flag...]

Renames every directory, file name and file content occurrence of the current
project name. The kit under cmake/projectkit is excluded.

flags:
  --from=NAME          current name, default: the name in project()
  --description=TEXT   replace DESCRIPTION in CMakeLists.txt and the recipe
  --url=URL            replace url in the recipe
  --version=X.Y.Z      replace VERSION in CMakeLists.txt
  --dry-run            list what would change, touch nothing
  --yes, -y            do not ask for confirmation
  --force              run even when the git tree is dirty
  --help, -h           this message

A name must match [a-z][a-z0-9_]*: the sample sources use it as a C++
namespace, so hyphens would not compile."""

NEXT = """
next:
  git diff --stat
  ./scripts/package.py reference
  ./scripts/package.py install --build_type=Debug
  cmake --preset native-debug
  ./scripts/verify.py run --build_type=Debug

then review by hand:
  CMakeLists.txt   DESCRIPTION and VERSION
  conanfile.py     description, url, package_info libs
  README.md        still describes the template"""

GENERATED = {".git", "build", "stage", "_install", ".conan-cache"}


def die(message: str) -> None:
    err(f"{C.red}error{C.reset}  {message}")
    raise SystemExit(1)


def note(message: str) -> None:
    out(f"{C.bold}--{C.reset} {message}")


def shown_path(path: str) -> str:
    return path.replace(os.sep, "/")


def text_files(top: str, skip: Set[str], suffixes: tuple = ()) -> Iterator[str]:
    for directory, dirs, files in os.walk(top):
        dirs[:] = sorted(d for d in dirs if d not in skip)
        for name in sorted(files):
            path = os.path.join(directory, name)
            if (suffixes and not name.endswith(suffixes)) or os.path.islink(path):
                continue
            yield path


def read_text_bytes(path: str) -> Optional[bytes]:
    try:
        with open(path, "rb") as file:
            data = file.read()
    except OSError:
        return None
    return None if b"\0" in data else data


def files_containing(top: str, skip: Set[str], needles: List[bytes], ignore_case: bool = False,
                     suffixes: tuple = ()) -> List[str]:
    found = []
    for path in text_files(top, skip, suffixes):
        data = read_text_bytes(path)
        if data is None:
            continue
        haystack = data.lower() if ignore_case else data
        if any(needle in haystack for needle in needles):
            found.append(path)
    return found


def in_project_call(text: str, pattern: str, replacement: str) -> str:
    match = re.search(r"^[ \t]*project[ \t]*\(", text, re.MULTILINE)
    if not match:
        return text
    index, depth, quoted = match.end(), 1, False
    while index < len(text) and depth:
        char = text[index]
        if quoted:
            if char == "\\":
                index += 1
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "()":
            depth += 1 if char == "(" else -1
        index += 1
    call = re.sub(pattern, lambda m: m.group(1) + replacement, text[match.start():index])
    return text[:match.start()] + call + text[index:]


def edit(path: str, change) -> None:
    with open(path, encoding="utf-8", newline="") as file:
        text = file.read()
    updated = change(text)
    if updated != text:
        with open(path, "w", encoding="utf-8", newline="") as file:
            file.write(updated)


def main(argv: List[str], root: Optional[str] = None) -> int:
    return entry(_main, argv, root)


def _main(argv: List[str], given_root: Optional[str]) -> int:
    root = repo_root(given_root, has_file("CMakeLists.txt"),
                     "no CMakeLists.txt found above {cwd}: set PK_REPO_ROOT")
    setup_output()
    self_name = "./scripts/bootstrap.py"

    new_name = old_name = description = url = version = ""
    dry_run = assume_yes = force = False
    for arg in argv:
        key, sep, value = arg.partition("=")
        if sep and key == "--from":
            old_name = value
        elif sep and key == "--description":
            description = value
        elif sep and key == "--url":
            url = value
        elif sep and key == "--version":
            version = value
        elif arg == "--dry-run":
            dry_run = True
        elif arg in ("--yes", "-y"):
            assume_yes = True
        elif arg == "--force":
            force = True
        elif arg in ("--help", "-h"):
            out(USAGE.format(self=self_name))
            return 0
        elif arg.startswith("-"):
            err(f"unknown option: {arg}\n")
            err(USAGE.format(self=self_name))
            return 2
        elif not new_name:
            new_name = arg
        else:
            err(f"unexpected argument: {arg}\n")
            err(USAGE.format(self=self_name))
            return 2

    if not new_name:
        err(USAGE.format(self=self_name))
        return 2
    if not re.fullmatch(r"[a-z][a-z0-9_]*", new_name):
        die(f"'{new_name}' must match [a-z][a-z0-9_]*, since the sample sources use it as a C++ namespace")

    old_name = old_name or detect_project(root)
    if not old_name:
        die("cannot determine the current name: pass --from=NAME")
    if old_name == new_name:
        die(f"the project is already called '{new_name}'")

    old_upper, new_upper = old_name.upper(), new_name.upper()
    old_title, new_title = old_name[:1].upper() + old_name[1:], new_name[:1].upper() + new_name[1:]
    replacements = [(old_upper, new_upper), (old_title, new_title), (old_name, new_name)]
    byte_replacements = [(a.encode(), b.encode()) for a, b in replacements]

    os.chdir(root)
    in_git = capture(["git", "rev-parse", "--git-dir"])[0] == 0
    if not force and not dry_run and in_git and capture(["git", "status", "--porcelain"])[1].strip():
        die("the git tree is dirty; commit first so this is revertible, or pass --force")

    def paths_to_rename() -> List[str]:
        found = []
        for directory, dirs, files in os.walk("."):
            dirs[:] = sorted(d for d in dirs if d not in GENERATED and d != "projectkit")
            found.extend(os.path.join(directory, n) for n in dirs + sorted(files) if old_name in n)
        return sorted(found, key=lambda p: p.count(os.sep), reverse=True)

    def files_to_edit() -> List[str]:
        return files_containing(".", GENERATED | {"projectkit"}, [a.encode() for a, _ in replacements])

    renames = paths_to_rename()
    edits = files_to_edit()

    note(f"project name: {old_name} -> {new_name}")
    note(f"identifiers:  {old_upper} -> {new_upper}, {old_title} -> {new_title}")
    out(f"\n{C.bold}paths to rename ({len(renames)}){C.reset}")
    for path in renames:
        out(f"  {shown_path(path)}")
    out(f"\n{C.bold}files to rewrite ({len(edits)}){C.reset}")
    for path in edits:
        out(f"  {shown_path(path)}")
    out()

    if dry_run:
        note("dry run, nothing changed")
        return 0
    if not assume_yes and not confirm(f"rename {old_name} to {new_name}?"):
        note("nothing changed")
        return 0

    for path in renames:
        if not os.path.lexists(path):
            continue
        directory, base = os.path.split(path)
        new_base = base
        for old, new in replacements:
            new_base = new_base.replace(old, new)
        if new_base == base:
            continue
        target = os.path.join(directory, new_base)
        if in_git and capture(["git", "ls-files", "--error-unmatch", path])[0] == 0:
            if run(["git", "mv", path, target]) != 0:
                die(f"git mv failed: {shown_path(path)}")
        else:
            try:
                os.rename(path, target)
            except OSError:
                die(f"mv failed: {shown_path(path)}")

    for path in files_to_edit():
        data = read_text_bytes(path)
        if data is None:
            continue
        updated = data
        for old, new in byte_replacements:
            updated = updated.replace(old, new)
        if updated != data:
            with open(path, "wb") as file:
                file.write(updated)

    if description:
        edit("CMakeLists.txt", lambda t: in_project_call(
            t, r'(DESCRIPTION\s*)"[^"]*"', f'"{description}"'))
        if os.path.isfile("conanfile.py"):
            edit("conanfile.py", lambda t: re.sub(
                r'^([ \t]*description[ \t]*=[ \t]*)".*"', lambda m: f'{m.group(1)}"{description}"',
                t, flags=re.MULTILINE))

    if url and os.path.isfile("conanfile.py"):
        edit("conanfile.py", lambda t: re.sub(
            r'^([ \t]*url[ \t]*=[ \t]*)".*"', lambda m: f'{m.group(1)}"{url}"', t, flags=re.MULTILINE))

    if version:
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
            die("--version must be X.Y.Z, the recipe parses that shape")
        edit("CMakeLists.txt", lambda t: in_project_call(
            t, r"(VERSION\s*)[0-9]+\.[0-9]+\.[0-9]+", version))

    out()
    remaining = files_containing(".", {".git", "build", "projectkit"}, [old_name.lower().encode()],
                                 ignore_case=True)
    if remaining:
        out(f"{C.yellow}warning{C.reset}  still mentioning '{old_name}':")
        for path in remaining:
            out(f"  {shown_path(path)}")
    else:
        out(f"{C.green}no occurrences of {old_name} remain outside the kit{C.reset}")

    kit = os.path.join("cmake", "projectkit")
    kit_hits = files_containing(kit, {"build", "__pycache__"}, [old_name.lower().encode()],
                                ignore_case=True, suffixes=(".cmake", ".in", ".sh", ".py"))
    if kit_hits:
        out(f"{C.yellow}warning{C.reset}  the kit mentions '{old_name}', which is a bug in the kit:")
        for path in kit_hits:
            out(f"  {shown_path(path)}")

    out(NEXT)
    return 0
