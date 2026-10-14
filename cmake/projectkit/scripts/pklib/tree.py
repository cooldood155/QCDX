"""The project tree: where each part of a project lives.

A project without '.pk/tree.conf' has the classic tree, the one the template
has always had. A project with one reads every part's folder from it, so the
kit, the scripts, the settings and the profiles can live out of sight (in
'.pk/', for example) and optional parts can be left out entirely.

Two ways to write a tree, both read by 'pk tree apply' and 'pk new --tree':

  tree.conf    one 'part = path' line per part, plus 'omit = part part ...'
  drawing      a picture of the tree; a line ending in '<part>' places that
               part, deleting an optional part's line leaves it out

'.pk/tree.conf' is written by pk only: it is the tree that works right now,
which is also what 'pk tree reset' goes back to. CMake (Layout.cmake), the
wrappers in scripts/ and the pk-setup action read the same file.

Standard library only, Python 3.9+.
"""

from __future__ import annotations

import os
import re
from typing import Dict, Iterable, List, NamedTuple, Optional, Set, Tuple

TREE_FILE = ".pk/tree.conf"
DRAWING_FILE = ".pk/tree.txt"

KIT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRESETS_DIR = os.path.join(KIT_DIR, "trees")


class Part(NamedTuple):
    key: str
    default: str
    folder: bool    # a folder (moved as a whole) or a single file
    movable: bool   # False: fixed where tools look for it, can only be omitted
    optional: bool  # may be left out
    about: str


# Order is the order of tree.conf and of the drawing's tagged lines.
PARTS: Tuple[Part, ...] = (
    Part("kit", "cmake/projectkit", True, True, False, "ProjectKit, the CMake kit ('pk sync' updates it)"),
    Part("scripts", "scripts", True, True, False, "pk.py, verify.py, package.py, release.py, bootstrap.py"),
    Part("helpers", "scripts/helpers", True, True, False, "settings: pk, release, verify and package"),
    Part("profiles", "profiles", True, True, False, "Conan profiles: native, cross targets, CI"),
    Part("toolchains", "cmake/toolchains", True, True, False, "CMake toolchain files of the cross profiles"),
    Part("cmake", "cmake", True, True, False, "package config templates (<project>Config.cmake.in)"),
    Part("headers", "include", True, True, False, "public headers, one folder per library"),
    Part("sources", "src", True, True, False, "library sources, one folder per library"),
    Part("apps", "apps", True, True, True, "applications, one folder per app"),
    Part("tests", "tests", True, True, True, "Catch2 tests, one folder per library"),
    Part("tools", "tools", True, True, True, "build-time tools (code generators)"),
    Part("clang-format", ".clang-format", False, False, True, "clang-format style ('pk format')"),
    Part("clang-tidy", ".clang-tidy", False, False, True, "clang-tidy checks ('pk analyze')"),
    Part("clangd", ".clangd", False, False, True, "clangd editor settings"),
    Part("pre-commit", ".pre-commit-config.yaml", False, False, True, "pre-commit hooks"),
    Part("verify-ci", ".github/workflows/verify.yml", False, False, True, "CI: verify every push"),
    Part("release-ci", ".github/workflows/release.yml", False, False, True, "CI: release on a v*.*.* tag"),
)
BY_KEY: Dict[str, Part] = {part.key: part for part in PARTS}

# Always at the root: CMake, Conan and git only look for them there.
FIXED = ("CMakeLists.txt", "CMakePresets.json", "conanfile.py", "deps.json", "conan.lock", "README.md",
         ".gitignore", ".gitattributes")

# Folders no part may live in: generated, or owned by git and GitHub.
RESERVED = ("build", "stage", "_install", ".git", ".github", ".pk/tree.conf", ".pk/tree.txt")

# Parts CMake globs for sources: nothing of the kit may land inside them.
CODE = ("headers", "sources", "apps", "tests", "tools")
INFRA = ("kit", "scripts", "helpers", "profiles", "toolchains", "cmake")

# The synced kit files, by part ('pk sync' maps them through the tree).
SCRIPT_NAMES = ("pk.py", "verify.py", "package.py", "release.py", "bootstrap.py")
PK_SETUP = ".github/actions/pk-setup"

_SEGMENT = re.compile(r"[A-Za-z0-9_.+-]+")
_CONF_LINE = re.compile(r"(?:export[ \t]+)?(?:PK_TREE_)?([A-Za-z][A-Za-z0-9_-]*)[ \t]*=[ \t]*(.*)", re.IGNORECASE)
_TAG = re.compile(r"<([A-Za-z][A-Za-z0-9_-]*)>")
# ASCII ('|-- ', '`-- ', '+-- ', '\-- ') and the box drawing 'tree' prints.
_GLYPHS = "|`+\\- \u2502\u251c\u2514\u2500\u252c\u2570"


class TreeError(Exception):
    """A tree that cannot be used; the message says where and why."""


def _key(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _clean(path: str) -> str:
    """Quotes, '\\' and trailing '/' go; a leading '/' stays, so absolute paths fail the check."""
    return path.strip().strip("\"'").replace("\\", "/").rstrip("/")


def _inside(path: str, folder: str) -> bool:
    """True when path is folder itself or below it (case-insensitive, like
    Windows and macOS file systems)."""
    path, folder = path.lower(), folder.lower()
    return path == folder or path.startswith(folder + "/")


def omit_key(word: str) -> Optional[str]:
    """A part named by its key ('clangd') or its classic path ('.clangd',
    'tools/')."""
    word = _clean(word)
    if _key(word) in BY_KEY:
        return _key(word)
    for part in PARTS:
        if word.lower() == part.default.lower():
            return part.key
    return None


class Tree:
    """Where every part is, relative to the project root, with '/'."""

    def __init__(self, paths: Optional[Dict[str, str]] = None, omit: Iterable[str] = (), origin: str = "classic"):
        self.paths = {part.key: part.default for part in PARTS}
        self.paths.update(paths or {})
        self.omit: Set[str] = set(omit)
        self.origin = origin

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Tree) and self.paths == other.paths and self.omit == other.omit

    def __repr__(self) -> str:
        return f"Tree({self.origin})"

    def has(self, key: str) -> bool:
        return key not in self.omit

    def rel(self, key: str, *parts: str) -> str:
        """A part's path (or a path inside it), relative, with '/'."""
        return "/".join([self.paths[key], *(p.strip("/") for p in parts if p)])

    def path(self, root: str, key: str, *parts: str) -> str:
        """A part's path (or a path inside it) as a native absolute path."""
        return os.path.join(root, *self.rel(key, *parts).split("/"))

    def is_classic(self) -> bool:
        return self == Tree()

    def moved(self) -> Dict[str, str]:
        return {key: path for key, path in self.paths.items() if path != BY_KEY[key].default}

    # -- checks ---------------------------------------------------------------

    def problems(self) -> List[str]:
        found = []
        for key in self.omit:
            if key not in BY_KEY:
                found.append(f"omit: '{key}' is not a part")
            elif not BY_KEY[key].optional:
                found.append(f"omit: '{key}' cannot be left out, every project needs it")
        for part in PARTS:
            path = self.paths[part.key]
            if not part.movable:
                if path != part.default:
                    found.append(f"{part.key}: stays at '{part.default}' (tools only look there); "
                                 "it can only be left out")
                continue
            segments = path.split("/")
            if not path or any(not _SEGMENT.fullmatch(s) or s in (".", "..") for s in segments):
                found.append(f"{part.key}: '{path}' is not a relative path of plain names "
                             "(letters, digits and _ . + -)")
                continue
            if any(_inside(path, reserved) for reserved in RESERVED):
                found.append(f"{part.key}: '{path}' is inside a folder pk keeps for itself or for git")
            if path.lower() in (name.lower() for name in FIXED):
                found.append(f"{part.key}: '{path}' is a file that stays at the root")
        movable = [part.key for part in PARTS if part.movable and self.has(part.key)]
        for index, first in enumerate(movable):
            for second in movable[index + 1:]:
                if self.paths[first].lower() == self.paths[second].lower():
                    found.append(f"{first} and {second}: both are '{self.paths[first]}'")
        for key in movable:
            if key != "kit" and _inside(self.paths[key], self.paths["kit"]):
                found.append(f"{key}: '{self.paths[key]}' is inside the kit, which 'pk sync' replaces")
        for key in INFRA:
            for code in CODE:
                if self.has(code) and _inside(self.paths[key], self.paths[code]):
                    found.append(f"{key}: '{self.paths[key]}' is inside {code} ('{self.paths[code]}'), "
                                 "where CMake looks for sources")
        return sorted(set(found))

    def check(self) -> "Tree":
        found = self.problems()
        if found:
            raise TreeError(f"{self.origin}:\n  " + "\n  ".join(found))
        return self

    def missing(self, root: str, required_only: bool = False) -> List[str]:
        """Parts this tree places that are not on disk. An optional single file
        (.clangd, a workflow) that is gone harms nothing and is not counted."""
        found = []
        for part in PARTS:
            if not self.has(part.key) or (part.optional and (not part.folder or required_only)):
                continue
            path = self.path(root, part.key)
            if part.folder and not os.path.isdir(path):
                found.append(f"{part.key}: no folder '{self.rel(part.key)}/'")
            elif not part.folder and not os.path.isfile(path):
                found.append(f"{part.key}: no file '{self.rel(part.key)}'")
        return found

    # -- writing --------------------------------------------------------------

    def to_conf(self) -> str:
        width = max(len(part.key) for part in PARTS)
        lines = [
            "# The tree of this project: where each part lives, relative to the root.",
            "# Written by pk; change it with 'pk tree apply FILE' (which also moves the",
            "# files), never by hand. 'pk tree' shows it, 'pk tree reset' restores it.",
            "",
        ]
        for part in PARTS:
            if part.movable and self.has(part.key):
                lines.append(f"{part.key:<{width}} = {self.paths[part.key]}")
        omitted = [part.key for part in PARTS if part.key in self.omit]
        lines.append(f"{'omit':<{width}} = {' '.join(omitted)}".rstrip())
        return "\n".join(lines) + "\n"

    def draw(self, name: str = "project") -> str:
        """The tree as an editable picture (ASCII only)."""
        nodes: Dict[str, Dict] = {}

        def add(path: str, tag: str = "", folder: bool = True) -> None:
            node = nodes
            segments = path.split("/")
            for index, segment in enumerate(segments):
                last = index == len(segments) - 1
                label = segment + ("/" if (folder or not last) else "")
                entry = node.setdefault(label, {"tags": [], "children": {}})
                if last and tag:
                    entry["tags"].append(tag)
                node = entry["children"]

        for part in PARTS:
            if not self.has(part.key):
                continue
            mark = f"<{part.key}>" + (" optional" if part.optional else "")
            add(self.paths[part.key], mark, part.folder)
        for fixed in FIXED:
            add(fixed, "", False)

        def order(label: str) -> Tuple[int, str]:
            return (0 if label.endswith("/") else 1, label.lower())

        lines: List[str] = []

        def walk(node: Dict, prefix: str) -> None:
            labels = sorted(node, key=order)
            for index, label in enumerate(labels):
                last = index == len(labels) - 1
                text = prefix + ("`-- " if last else "|-- ") + label
                tags = " ".join(node[label]["tags"])
                if tags:
                    text = f"{text:<40} {tags}"
                lines.append(text)
                walk(node[label]["children"], prefix + ("    " if last else "|   "))

        walk(nodes, "")
        omitted = [part for part in PARTS if part.key in self.omit]
        header = [
            "# pk tree: a drawing of this project. Edit it, then: pk tree apply " + DRAWING_FILE,
            "#",
            "#   move a part     put its line under another folder, or rename its folder",
            "#   leave one out   delete its line (only lines marked optional)",
            "#   a part is a line ending in <name>; every other line is only a picture",
            "#",
            "# A broken drawing changes nothing: 'pk tree apply' checks it first, and",
            "# 'pk tree reset' redraws the tree that works now.",
            "",
            f"{name}/",
        ]
        footer = []
        if omitted:
            footer = ["", "# left out (a new project can have them: pk new NAME --tree=...):"]
            width = max(len(part.default) for part in omitted)
            tags = max(len(part.key) for part in omitted) + 2
            footer += [f"#   {part.default:<{width}}  {'<' + part.key + '>':<{tags}}  {part.about}"
                       for part in omitted]
        return "\n".join(header + lines + footer) + "\n"


# -- reading ------------------------------------------------------------------

def is_drawing(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if _TAG.search(line) or stripped[0] in _GLYPHS.replace(" ", "").replace("-", ""):
            return True
    return False


def parse_conf(text: str, origin: str = "tree.conf") -> Tree:
    paths: Dict[str, str] = {}
    omit: Set[str] = set()
    problems = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.split(" #", 1)[0].split("\t#", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        match = _CONF_LINE.fullmatch(line)
        if not match:
            problems.append(f"line {number}: expected 'part = path', got: {line}")
            continue
        key, value = _key(match.group(1)), match.group(2).strip().strip("\"'")
        if key == "omit":
            for word in value.replace(",", " ").split():
                part = omit_key(word)
                if part is None:
                    problems.append(f"line {number}: omit: '{word}' is not a part "
                                    f"({', '.join(p.key for p in PARTS if p.optional)} can be left out)")
                else:
                    omit.add(part)
        elif key in BY_KEY:
            if key in paths:
                problems.append(f"line {number}: '{key}' is set twice")
            paths[key] = _clean(value)
        else:
            problems.append(f"line {number}: '{key}' is not a part (parts: {', '.join(BY_KEY)}, omit)")
    if problems:
        raise TreeError(f"{origin}:\n  " + "\n  ".join(problems))
    return Tree(paths, omit, origin).check()


def parse_drawing(text: str, origin: str = "drawing") -> Tree:
    paths: Dict[str, str] = {}
    lines_of: Dict[str, int] = {}
    problems = []
    # (column of the name, path) of every open folder; the project itself is
    # the sentinel at column -1, which nothing pops.
    stack: List[Tuple[int, str]] = [(-1, "")]
    first = True
    for number, raw in enumerate(text.expandtabs(4).splitlines(), 1):
        line = raw.split(" #", 1)[0].rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        column = 0
        while column < len(line) and line[column] in _GLYPHS:
            column += 1
        body = line[column:]
        if not body.strip():
            continue  # a spacer line, glyphs only
        name = body.split()[0]
        if first:
            first = False
            if column == 0 and name.endswith("/") and not _TAG.search(body):
                continue  # the project folder itself
        clean = name.strip("/")
        if not clean:
            problems.append(f"line {number}: a tree line with no name")
            continue
        while stack[-1][0] >= column:
            stack.pop()
        parent = stack[-1][1]
        path = f"{parent}/{clean}" if parent else clean
        if name.endswith("/"):
            stack.append((column, path))
        for tag in _TAG.findall(body):
            key = _key(tag)
            if key not in BY_KEY:
                problems.append(f"line {number}: <{tag}> is not a part (parts: {', '.join(BY_KEY)})")
            elif key in paths:
                problems.append(f"line {number}: <{key}> is already on line {lines_of[key]}")
            else:
                paths[key] = path
                lines_of[key] = number
    omit = set()
    for part in PARTS:
        if part.key not in paths:
            if part.optional:
                omit.add(part.key)
            else:
                problems.append(f"<{part.key}> is missing: every project needs {part.about.split(',')[0]}")
    if problems:
        raise TreeError(f"{origin}:\n  " + "\n  ".join(problems))
    return Tree(paths, omit, origin).check()


def parse(text: str, origin: str) -> Tree:
    return parse_drawing(text, origin) if is_drawing(text) else parse_conf(text, origin)


def load(root: str) -> Tree:
    """The tree of the project at root: classic when it has no tree.conf."""
    path = os.path.join(root, *TREE_FILE.split("/"))
    try:
        with open(path, encoding="utf-8") as file:
            text = file.read()
    except FileNotFoundError:
        return Tree()
    except OSError as error:
        raise TreeError(f"{TREE_FILE}: {error}")
    return parse_conf(text, TREE_FILE)


def user_trees_dir() -> str:
    return os.path.join(os.environ.get("PK_HOME") or os.path.join(os.path.expanduser("~"), ".pk"), "trees")


def preset_names() -> List[str]:
    names = set()
    for folder in (PRESETS_DIR, user_trees_dir()):
        if os.path.isdir(folder):
            names.update(os.path.splitext(n)[0] for n in os.listdir(folder) if n.endswith((".conf", ".tree", ".txt")))
    return sorted(names)


def resolve(spec: str) -> Tree:
    """A tree from a file path, a tree of ~/.pk/trees or a built-in one
    (classic, minimal)."""
    candidates = [spec]
    if not os.path.splitext(spec)[1] and os.sep not in spec and "/" not in spec:
        for folder in (user_trees_dir(), PRESETS_DIR):
            candidates += [os.path.join(folder, spec + ext) for ext in (".conf", ".tree", ".txt")]
    for candidate in candidates:
        if os.path.isfile(candidate):
            with open(candidate, encoding="utf-8") as file:
                return parse(file.read(), candidate if candidate == spec else spec)
    raise TreeError(f"no tree '{spec}': not a file, and not one of: {', '.join(preset_names()) or 'none'}")


# -- what the rest of the kit asks ---------------------------------------------

def sync_map(tree: Tree) -> List[Tuple[str, str]]:
    """(QCDX path, path here) of every synced kit path this project has. QCDX
    itself always has the classic tree."""
    pairs = [("cmake/projectkit", tree.rel("kit"))]
    pairs += [(f"scripts/{name}", tree.rel("scripts", name)) for name in SCRIPT_NAMES]
    if tree.has("verify-ci") or tree.has("release-ci"):
        pairs.append((PK_SETUP, PK_SETUP))
    return pairs


def find_root(start: str) -> Optional[str]:
    """The project above start: the folder with CMakeLists.txt and
    CMakePresets.json (only the root has a CMakePresets.json)."""
    directory = os.path.abspath(start)
    while True:
        if os.path.isfile(os.path.join(directory, "CMakePresets.json")) and \
           os.path.isfile(os.path.join(directory, "CMakeLists.txt")):
            return directory
        parent = os.path.dirname(directory)
        if parent == directory:
            return None
        directory = parent


def load_or_exit(root: str) -> Tree:
    """load(), or a clear message and exit code 2 for a broken tree.conf."""
    try:
        return load(root)
    except TreeError as error:
        import sys

        sys.stderr.write(f"pk: the project tree ({TREE_FILE}) is broken: {error}\n"
                         "  'pk tree check' explains it; 'pk tree reset' goes back to the last tree that worked\n")
        raise SystemExit(2)


def profile(root: str, name: str) -> str:
    """A profile's absolute path: <profiles>/<name>."""
    return load_or_exit(root).path(root, "profiles", name)


def helper(root: str, relative: str) -> str:
    """A settings file inside the helpers part, relative to the root."""
    return load_or_exit(root).rel("helpers", relative)
