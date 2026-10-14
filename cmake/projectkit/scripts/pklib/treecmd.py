"""pk tree: show, check, draw and change where each part of a project lives.

'pk tree apply' moves a project from its tree to another one: the parts'
files move, the files that name those paths (CMakeLists.txt, presets, the
recipe, CI, profiles, settings, .gitignore, pre-commit, README) are updated,
parts the new tree leaves out are deleted, and .pk/tree.conf is written. All
of it or nothing: a failure on the way puts every file back.

'pk new --tree=...' is the same 'apply', run on a fresh copy of the template.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import tree as pktree
from .common import C, capture, confirm, err, lines, out, run, setup_output
from .tree import BY_KEY, PARTS, Tree, TreeError

USAGE = """\
usage: {self} [show]                    the tree of this project, drawn
       {self} check [FILE]              check FILE, or this project's tree against its files
       {self} draw [--out=FILE]         write the drawing to edit (default {drawing})
       {self} apply FILE|NAME [flag...] move this project to that tree
       {self} reset [FILE]              go back to the last tree that worked
       {self} list                      the trees NAME can be

A tree is a .conf file ('part = path' lines, 'omit = part ...'), a drawing
('pk tree draw'), or a NAME: classic, minimal, or one of your own in
{user}/NAME.conf (PK_HOME moves ~/.pk).

apply flags:
  --omit=PART,...     also leave these parts out
  --dry-run           show what would move and change, touch nothing
  --yes, -y           do not ask before moving or deleting
  --no-commit         stage the change but do not commit it

parts (optional ones can be left out):
{parts}"""

# Files that name the parts' paths and are updated by 'apply'. Everything else
# is only searched afterwards, and reported when it still names an old path.
REWRITE_ROOT = ("CMakeLists.txt", "CMakePresets.json", "conanfile.py", ".gitignore", ".pre-commit-config.yaml",
                "README.md")
REWRITE_PARTS = {"profiles": None, "helpers": (".conf", ".md", ".txt"), "cmake": (".cmake", ".in")}
SKIP_DIRS = {".git", "build", "stage", "_install", "__pycache__", ".cache", ".conan-cache"}
CODE_SUBDIRS = ("sources", "apps", "tests", "tools")

_PREFIXES = ("${CMAKE_CURRENT_LIST_DIR}/", "${CMAKE_CURRENT_SOURCE_DIR}/", "${PROJECT_SOURCE_DIR}/",
             "${CMAKE_SOURCE_DIR}/", "${sourceDir}/", "${PK_REPO_ROOT}/")


class ApplyError(Exception):
    pass


# -- references ---------------------------------------------------------------

def reference_regex(olds: Sequence[str]) -> "re.Pattern[str]":
    """Old part paths where they are used as paths. A one-word path ('src',
    'cmake') only when a path continues after it ('src/x') or right after
    ${VAR}/; a longer one ('cmake/projectkit') also on its own. Never inside
    a longer word, never after '../'."""
    def alternatives(paths: Sequence[str]) -> str:
        # '/' or '\\' between the names: README and docs show Windows paths too
        return "|".join(r"[/\\]".join(re.escape(s) for s in p.split("/"))
                        for p in sorted(paths, key=len, reverse=True)) or "(?!)"

    longer = alternatives([old for old in olds if "/" in old])
    names = alternatives(olds)
    after_var = "|".join(f"(?<={re.escape(prefix)})" for prefix in _PREFIXES)
    start = r"(?:(?<=\./)(?<!\.\./)|(?<![\w.\-/$}\\]))"
    return re.compile(
        rf"(?:{after_var})(?P<whole>{names})(?![\w.\-])"
        rf"|{start}(?P<longer>{longer})(?![\w.\-])"
        rf"|{start}(?P<inner>{names})(?=[/\\])")


def rewrite_references(text: str, moves: Dict[str, str], escape: bool = False) -> str:
    if not moves:
        return text
    pattern = reference_regex(list(moves))

    def replace(match: "re.Match[str]") -> str:
        found = match.group("whole") or match.group("longer") or match.group("inner")
        new = moves[found.replace("\\", "/")]
        end = match.end()
        if "\\" in found or (end < len(text) and text[end] == "\\"):
            new = new.replace("/", "\\")
        return re.escape(new) if escape else new

    return pattern.sub(replace, text)


def rewrite_profile_toolchains(text: str, new: Tree) -> str:
    """os.path.join(profile_dir, "..", "cmake", "toolchains", "x.cmake") in a
    profile: the path from the profiles to the toolchains, recomputed."""
    relative = os.path.relpath(new.rel("toolchains"), new.rel("profiles")).replace(os.sep, "/")
    parts = ", ".join(f'"{part}"' for part in relative.split("/"))
    return re.sub(r'os\.path\.join\(profile_dir((?:,\s*"[^"]*")*?),\s*"([^"/\\]+\.cmake)"\)',
                  lambda m: f'os.path.join(profile_dir, {parts}, "{m.group(2)}")', text)


def rewrite_cmakelists(text: str, old: Tree, new: Tree) -> str:
    for key in CODE_SUBDIRS:
        if not new.has(key):
            if not old.has(key):
                continue
            folder = re.escape(old.rel(key))
            text, count = re.subn(rf"^if\([^\n]*\)\n[ \t]*add_subdirectory\(\s*{folder}\s*\)\n[ \t]*endif\(\)\n\n?",
                                  "", text, flags=re.MULTILINE)
            if not count:
                text = re.sub(rf"^[ \t]*add_subdirectory\(\s*{folder}\s*\)\n", "", text, flags=re.MULTILINE)
            if key == "tools":
                text = re.sub(r"^[ \t]*pk_require_host_tools\(\)\n", "", text, flags=re.MULTILINE)
        elif old.rel(key) != new.rel(key):
            text = re.sub(rf"(add_subdirectory\(\s*){re.escape(old.rel(key))}(\s*\))",
                          lambda m: m.group(1) + new.rel(key) + m.group(2), text)
    return text


def rewrite_exports(text: str, old: Tree, new: Tree, moves: Dict[str, str]) -> str:
    """The recipe's exports_sources: what 'conan create' needs to build is the
    kit, the cmake files, the code and (for a tree that is not classic) the
    tree itself."""
    match = re.search(r"^([ \t]*)exports_sources[ \t]*=[ \t]*\(([^)]*)\)", text, re.MULTILINE)
    if not match:
        return text
    indent = match.group(1)
    entries = re.findall(r'"([^"]*)"', match.group(2))

    def covered(path: str, kept: List[str]) -> bool:
        return any(entry.endswith("/*") and (path + "/").startswith(entry[:-1]) for entry in kept) or \
            path in kept

    kept: List[str] = []
    for entry in entries:
        entry = rewrite_references(entry, moves)
        folder = entry[:-2] if entry.endswith("/*") else entry
        if any(not new.has(key) and BY_KEY[key].folder and folder == old.rel(key) for key in BY_KEY):
            continue
        if entry == pktree.TREE_FILE and new.is_classic():
            continue
        kept.append(entry)
    kept = [entry for index, entry in enumerate(kept)
            if entry not in kept[:index] and not covered(entry[:-2] if entry.endswith("/*") else entry,
                                                         [other for other in kept if other != entry])]
    for key in ("kit", "cmake", "toolchains", "headers", "sources", "apps", "tools", "tests"):
        if new.has(key) and not covered(new.rel(key), kept):
            kept.append(new.rel(key) + "/*")
    if not new.is_classic() and pktree.TREE_FILE not in kept:
        kept.insert(2 if len(kept) >= 2 else len(kept), pktree.TREE_FILE)
    body = ",\n".join(f'{indent}  "{entry}"' for entry in kept)
    replacement = f"{indent}exports_sources = (\n{body})"
    return text[:match.start()] + replacement + text[match.end():]


def drop_readme_rows(text: str, old: Tree, new: Tree) -> str:
    for part in PARTS:
        if part.folder and old.has(part.key) and not new.has(part.key):
            text = re.sub(rf"^\|[ \t]*`{re.escape(old.rel(part.key))}/`[^\n]*\n", "", text, flags=re.MULTILINE)
    return text


# -- planning -----------------------------------------------------------------

def walk(root: str, top: str) -> List[str]:
    """Every file below root/top, relative to root, with '/'."""
    found = []
    base = os.path.join(root, *top.split("/"))
    if os.path.isfile(base):
        return [top]
    for directory, dirs, files in os.walk(base):
        dirs[:] = sorted(dirs)
        for name in sorted(files):
            found.append(os.path.relpath(os.path.join(directory, name), root).replace(os.sep, "/"))
    return found


def owner(path: str, tree: Tree) -> Optional[str]:
    """The deepest movable part a file belongs to in a tree."""
    best = None
    for part in PARTS:
        if not part.movable or not tree.has(part.key):
            continue
        folder = tree.rel(part.key)
        if path.startswith(folder + "/") and (best is None or len(folder) > len(tree.rel(best))):
            best = part.key
    return best


class Plan:
    def __init__(self, root: str, old: Tree, new: Tree) -> None:
        self.root = root
        self.old = old
        self.new = new
        self.moves: List[Tuple[str, str]] = []      # (from, to), files
        self.deletes: List[str] = []                # files and folders, relative
        self.part_moves = {old.rel(key): new.rel(key) for key in BY_KEY
                           if BY_KEY[key].movable and old.has(key) and new.has(key) and old.rel(key) != new.rel(key)}
        self.problems: List[str] = []
        self.build()

    def build(self) -> None:
        old, new = self.old, self.new
        back = [key for key in old.omit if key not in new.omit]
        for key in sorted(back):
            self.problems.append(
                f"{key}: this project left it out, and pk cannot bring its files back here; make a new "
                f"project with it ('pk new tmp --tree=...') and copy {BY_KEY[key].default} from there")
        for missing in old.missing(self.root):
            self.problems.append(f"the current tree does not match the files ({missing}): "
                                 "'pk tree reset' or fix that first")

        for part in PARTS:
            if old.has(part.key) and not new.has(part.key):
                path = old.rel(part.key)
                if os.path.lexists(os.path.join(self.root, *path.split("/"))):
                    self.deletes.append(path)
        if old.has("verify-ci") or old.has("release-ci"):
            if not new.has("verify-ci") and not new.has("release-ci") and \
               os.path.isdir(os.path.join(self.root, *pktree.PK_SETUP.split("/"))):
                self.deletes.append(pktree.PK_SETUP)

        moving = [key for key in BY_KEY if BY_KEY[key].movable and old.has(key) and new.has(key)]
        sources = set()
        for key in moving:
            for path in walk(self.root, old.rel(key)):
                if owner(path, old) != key or path in sources:
                    continue
                sources.add(path)
                target = new.rel(key) + path[len(old.rel(key)):]
                if target != path:
                    self.moves.append((path, target))
        leaving = {path for path, _ in self.moves}
        for path in self.deletes:
            leaving.update(walk(self.root, path))
        targets = set()
        for source, target in self.moves:
            if target.lower() in targets:
                self.problems.append(f"two files would both move to {target}")
            targets.add(target.lower())
            if os.path.lexists(os.path.join(self.root, *target.split("/"))) and target not in leaving:
                self.problems.append(f"{target} is already there (moving {source})")

    def rewrite_files(self) -> List[str]:
        """Files to update, at their place in the new tree."""
        new = self.new
        found = [name for name in REWRITE_ROOT if os.path.isfile(os.path.join(self.root, name))]
        workflows = os.path.join(self.root, ".github", "workflows")
        if os.path.isdir(workflows):
            found += [f".github/workflows/{n}" for n in sorted(os.listdir(workflows)) if n.endswith((".yml", ".yaml"))]
        for key, suffixes in REWRITE_PARTS.items():
            for path in walk(self.root, new.rel(key)):
                if suffixes is None or path.endswith(suffixes):
                    found.append(path)
        return found


# -- doing --------------------------------------------------------------------

class Journal:
    """Every change, so a failure can put every file back."""

    def __init__(self, root: str) -> None:
        self.root = root
        self.backup = tempfile.mkdtemp(prefix="pk-tree.")
        self.steps: List[Tuple[str, str, str]] = []

    def full(self, path: str) -> str:
        return os.path.join(self.root, *path.split("/"))

    def move(self, source: str, target: str) -> None:
        os.makedirs(os.path.dirname(self.full(target)), exist_ok=True)
        os.replace(self.full(source), self.full(target))
        self.steps.append(("move", source, target))

    def write(self, path: str, data: bytes) -> None:
        saved = os.path.join(self.backup, str(len(self.steps)))
        shutil.copy2(self.full(path), saved)
        with open(self.full(path), "wb") as file:
            file.write(data)
        self.steps.append(("write", path, saved))

    def delete(self, path: str) -> None:
        saved = os.path.join(self.backup, str(len(self.steps)))
        source = self.full(path)
        if os.path.isdir(source) and not os.path.islink(source):
            shutil.copytree(source, saved, symlinks=True)
            shutil.rmtree(source)
        else:
            shutil.copy2(source, saved, follow_symlinks=False)
            os.remove(source)
        self.steps.append(("delete", path, saved))

    def create(self, path: str, data: bytes) -> None:
        existed = os.path.exists(self.full(path))
        if existed:
            self.write(path, data)
            return
        os.makedirs(os.path.dirname(self.full(path)), exist_ok=True)
        with open(self.full(path), "wb") as file:
            file.write(data)
        self.steps.append(("create", path, ""))

    def undo(self) -> None:
        for kind, first, second in reversed(self.steps):
            try:
                if kind == "move":
                    os.makedirs(os.path.dirname(self.full(first)), exist_ok=True)
                    os.replace(self.full(second), self.full(first))
                elif kind == "write":
                    shutil.copy2(second, self.full(first))
                elif kind == "delete":
                    if os.path.isdir(second):
                        shutil.copytree(second, self.full(first), symlinks=True)
                    else:
                        os.makedirs(os.path.dirname(self.full(first)), exist_ok=True)
                        shutil.copy2(second, self.full(first), follow_symlinks=False)
                elif kind == "create":
                    os.remove(self.full(first))
            except OSError as error:
                err(f"  could not undo {kind} {first}: {error}")
        self.done()

    def done(self) -> None:
        shutil.rmtree(self.backup, ignore_errors=True)


def remove_empty_dirs(root: str, folders: Sequence[str]) -> None:
    for folder in sorted(set(folders), key=lambda f: -f.count("/")):
        path = os.path.join(root, *folder.split("/"))
        while os.path.isdir(path) and os.path.abspath(path) != os.path.abspath(root):
            try:
                os.rmdir(path)
            except OSError:
                break
            path = os.path.dirname(path)


def perform(plan: Plan) -> List[str]:
    """Carry out a checked plan; every file is put back if anything fails.
    Returns the files that still name an old path (left alone)."""
    root, old, new = plan.root, plan.old, plan.new
    journal = Journal(root)
    try:
        for path in plan.deletes:
            journal.delete(path)
        for source, target in plan.moves:
            journal.move(source, target)
        remove_empty_dirs(root, [os.path.dirname(s) for s, _ in plan.moves] +
                          [os.path.dirname(p) for p in plan.deletes if "/" in p])

        for path in plan.rewrite_files():
            with open(journal.full(path), "rb") as file:
                data = file.read()
            if b"\0" in data:
                continue
            text = data.decode("utf-8", errors="surrogateescape")
            name = path.rsplit("/", 1)[-1]
            updated = rewrite_references(text, plan.part_moves, escape=(name == ".pre-commit-config.yaml"))
            if path == "CMakeLists.txt":
                updated = rewrite_cmakelists(updated, old, new)
            elif path == "conanfile.py":
                updated = rewrite_exports(updated, old, new, plan.part_moves)
            elif path == "README.md":
                updated = drop_readme_rows(updated, old, new)
            elif path.startswith(new.rel("profiles") + "/"):
                updated = rewrite_profile_toolchains(updated, new)
            if updated != text:
                journal.write(path, updated.encode("utf-8", errors="surrogateescape"))

        conf = journal.full(pktree.TREE_FILE)
        if new.is_classic():
            if os.path.exists(conf):
                journal.delete(pktree.TREE_FILE)
                remove_empty_dirs(root, [".pk"])
        else:
            journal.create(pktree.TREE_FILE, new.to_conf().encode())
        drawing = journal.full(pktree.DRAWING_FILE)
        if os.path.isfile(drawing):
            journal.write(pktree.DRAWING_FILE, new.draw(project_name(root)).encode())

        problems = new.missing(root)
        if problems:
            raise ApplyError("after moving, the tree does not match the files:\n  " + "\n  ".join(problems))
        parsed = pktree.load(root)
        if parsed != new:
            raise ApplyError(f"{pktree.TREE_FILE} does not read back as the tree that was applied")
    except BaseException:
        journal.undo()
        raise
    journal.done()
    return stale_references(root, new, plan.part_moves)


def stale_references(root: str, new: Tree, moves: Dict[str, str]) -> List[str]:
    """file:line of text files (outside the kit) that still name a moved path."""
    if not moves:
        return []
    pattern = reference_regex(list(moves))
    # 'pk sync' owns these, they keep QCDX's paths
    synced = {new.rel("kit"), pktree.PK_SETUP} | {new.rel("scripts", name) for name in pktree.SCRIPT_NAMES}
    synced |= {pktree.TREE_FILE, pktree.DRAWING_FILE}
    found = []
    for directory, dirs, files in os.walk(root):
        relative = os.path.relpath(directory, root).replace(os.sep, "/")
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and
                         (d if relative == "." else f"{relative}/{d}") not in synced)
        for name in sorted(files):
            path = os.path.join(directory, name)
            if (name if relative == "." else f"{relative}/{name}") in synced:
                continue
            try:
                with open(path, "rb") as file:
                    data = file.read(2_000_000)
            except OSError:
                continue
            if b"\0" in data or name in ("deps.json", "conan.lock"):
                continue
            for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
                if pattern.search(line):
                    found.append(f"{os.path.relpath(path, root).replace(os.sep, '/')}:{number}: {line.strip()}")
    return found


def project_name(root: str) -> str:
    from .common import detect_project

    return detect_project(root) or os.path.basename(root)


# -- the command --------------------------------------------------------------

def git_ok(root: str, *args: str) -> bool:
    return capture(["git", *args], cwd=root)[0] == 0


def in_git(root: str) -> bool:
    return git_ok(root, "rev-parse", "--verify", "-q", "HEAD")


def describe(tree: Tree) -> str:
    if tree.is_classic():
        return "classic (no .pk/tree.conf)"
    return pktree.TREE_FILE


def read_tree(spec: str, omit: Sequence[str] = ()) -> Tree:
    tree = pktree.resolve(spec)
    if omit:
        extra = set()
        for word in omit:
            key = pktree.omit_key(word)
            if key is None:
                raise TreeError(f"--omit: '{word}' is not a part")
            extra.add(key)
        tree = Tree(tree.paths, tree.omit | extra, tree.origin).check()
    return tree


def show_plan(plan: Plan) -> None:
    moved = sorted(plan.part_moves.items())
    if moved:
        out(f"{C.bold}move{C.reset}")
        for old, new in moved:
            out(f"  {old + '/':<28} -> {new}/")
    if plan.deletes:
        out(f"{C.bold}leave out (delete){C.reset}")
        for path in plan.deletes:
            count = len(walk(plan.root, path))
            out(f"  {path}" + ("/" if os.path.isdir(os.path.join(plan.root, *path.split("/"))) else "")
                + (f"  ({count} files)" if count > 1 else ""))
    out(f"{C.bold}update{C.reset}  files that name those paths, and {pktree.TREE_FILE}")


def cmd_apply(root: str, self_name: str, args: List[str]) -> int:
    spec = ""
    omit: List[str] = []
    dry_run = assume_yes = no_commit = False
    for arg in args:
        key, sep, value = arg.partition("=")
        if arg in ("--dry-run", "-n"):
            dry_run = True
        elif arg in ("--yes", "-y"):
            assume_yes = True
        elif arg == "--no-commit":
            no_commit = True
        elif sep and key == "--omit":
            omit += [word for word in re.split(r"[,\s]+", value) if word]
        elif arg.startswith("-"):
            err(f"{self_name} apply: unknown flag {arg}")
            return 2
        elif not spec:
            spec = arg
        else:
            err(f"{self_name} apply: one tree at a time ({spec}, {arg})")
            return 2
    if not spec:
        err(f"usage: {self_name} apply FILE|NAME [--omit=PART,...] [--dry-run] [--yes] [--no-commit]")
        return 2

    try:
        old = pktree.load(root)
    except TreeError as error:
        err(f"{C.red}error{C.reset}: the current tree is broken, nothing changed:\n  {error}\n"
            f"  '{self_name} reset' goes back to the last tree that worked")
        return 1
    try:
        new = read_tree(spec, omit)
    except TreeError as error:
        err(f"{C.red}error{C.reset}: {spec} is not a tree pk can use, nothing changed:\n  {error}")
        return 1

    if new == old:
        out(f"the project already has this tree ({describe(old)})")
        return 0
    plan = Plan(root, old, new)
    show_plan(plan)
    if plan.problems:
        err(f"\n{C.red}error{C.reset}: nothing changed:\n  " + "\n  ".join(plan.problems))
        return 1

    git = in_git(root)
    touched = sorted({p.split("/")[0] for s, t in plan.moves for p in (s, t)} | set(plan.deletes) |
                     set(REWRITE_ROOT) | {".pk", ".github"})
    if git and not dry_run:
        own = {pktree.DRAWING_FILE}
        try:
            own.add(os.path.relpath(os.path.abspath(spec), root).replace(os.sep, "/"))
        except ValueError:  # another drive (Windows): not in the project anyway
            pass
        dirty = [line for line in lines(["git", "status", "--porcelain", "--", *[t for t in touched if os.path.lexists(
            os.path.join(root, *t.split("/")))]], cwd=root) if line[3:].strip('"') not in own]
        if dirty:
            for line in dirty:
                err(f"  {line}")
            err(f"{C.red}error{C.reset}: uncommitted changes where files move (above): commit or stash them "
                "first, nothing changed")
            return 1
    if dry_run:
        out("\ndry run: nothing changed")
        return 0
    if plan.deletes and not assume_yes and not confirm("delete what is left out, and move the rest?"):
        out("nothing changed")
        return 0
    if not plan.deletes and not assume_yes and not confirm("move the files?"):
        out("nothing changed")
        return 0

    try:
        stale = perform(plan)
    except (ApplyError, OSError, TreeError) as error:
        err(f"{C.red}error{C.reset}: {error}\nevery file is back where it was")
        return 1

    out(f"{C.green}done{C.reset}: the project has the new tree ({describe(new)})")
    if stale:
        out(f"{C.yellow}check{C.reset}: these lines still name an old path (pk left them alone):")
        for line in stale[:40]:
            out(f"  {line}")
        if len(stale) > 40:
            out(f"  ... and {len(stale) - 40} more")
    if git:
        folders = {plan.old.rel(k) for k in BY_KEY if BY_KEY[k].movable and plan.old.has(k)} | \
                  {plan.new.rel(k) for k in BY_KEY if BY_KEY[k].movable and plan.new.has(k)}
        candidates = sorted(folders | set(plan.deletes) | set(plan.rewrite_files()) | {pktree.TREE_FILE})
        tracked = set(lines(["git", "ls-files", "--", *candidates], cwd=root))
        paths = [p for p in candidates if os.path.lexists(os.path.join(root, *p.split("/")))
                 or p in tracked or any(t.startswith(p + "/") for t in tracked)]
        if run(["git", "add", "-A", "--", *paths], cwd=root) != 0:
            err("git add failed; the files moved, stage them yourself")
            return 1
        if no_commit:
            out("staged; review with 'git diff --cached --stat', then commit")
        elif run(["git", "commit", "-q", "-m", f"pk tree: {new.origin}"], cwd=root) != 0:
            err("the commit failed; the change is staged, commit it yourself")
            return 1
        else:
            out(f"committed: pk tree: {new.origin}")
    out("build trees remember old paths: run 'pk rebuild' (or 'pk full-clean') before the next build")
    return 0


def cmd_check(root: str, self_name: str, args: List[str]) -> int:
    if args:
        try:
            tree = pktree.resolve(args[0])
        except TreeError as error:
            err(f"{C.red}broken{C.reset}: {error}")
            return 1
        out(f"{C.green}ok{C.reset}: {args[0]} is a tree pk can use")
        old = pktree.load_or_exit(root)
        plan = Plan(root, old, tree)
        if plan.problems:
            out(f"{C.yellow}but{C.reset} applying it here would stop at:\n  " + "\n  ".join(plan.problems))
            return 1
        return 0
    try:
        tree = pktree.load(root)
    except TreeError as error:
        err(f"{C.red}broken{C.reset}: {error}\n  '{self_name} reset' goes back to the last tree that worked")
        return 1
    missing = tree.missing(root)
    if missing:
        err(f"{C.red}does not match the files{C.reset} ({describe(tree)}):\n  " + "\n  ".join(missing))
        err(f"  '{self_name} reset' finds the last tree that matches, or put those files back")
        return 1
    out(f"{C.green}ok{C.reset}: {describe(tree)} matches the files")
    return 0


def last_working(root: str) -> Tuple[Optional[Tree], str]:
    """The tree to go back to: .pk/tree.conf when it reads and matches the
    files, else the committed one, else the classic tree."""
    candidates: List[Tuple[str, Callable[[], Tree]]] = [("this project's tree.conf", lambda: pktree.load(root))]
    if in_git(root):
        code, text = capture(["git", "show", f"HEAD:{pktree.TREE_FILE}"], cwd=root)
        if code == 0:
            candidates.append(("the committed tree.conf", lambda: pktree.parse_conf(text, "HEAD:" + pktree.TREE_FILE)))
    candidates.append(("the classic tree", lambda: Tree()))
    for label, make in candidates:
        try:
            tree = make()
        except TreeError:
            continue
        if not tree.missing(root):
            return tree, label
    return None, ""


def cmd_reset(root: str, self_name: str, args: List[str]) -> int:
    target = args[0] if args else pktree.DRAWING_FILE
    tree, label = last_working(root)
    if tree is None:
        err(f"{C.red}error{C.reset}: no tree matches the files any more (tree.conf, the committed one and the "
            f"classic one all miss a part); '{self_name} check' lists what is missing")
        return 1
    conf = os.path.join(root, *pktree.TREE_FILE.split("/"))
    current = None
    try:
        current = pktree.load(root)
    except TreeError:
        pass
    if current != tree:
        if tree.is_classic():
            if os.path.exists(conf):
                os.remove(conf)
        else:
            os.makedirs(os.path.dirname(conf), exist_ok=True)
            with open(conf, "w", encoding="utf-8", newline="\n") as file:
                file.write(tree.to_conf())
        out(f"restored {label}" + (f" to {pktree.TREE_FILE}" if not tree.is_classic() else ""))
    path = target if os.path.isabs(target) else os.path.join(root, *target.replace("\\", "/").split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as file:
        file.write(tree.draw(project_name(root)))
    out(f"{C.green}ok{C.reset}: {os.path.relpath(path, root)} is the tree that works now ({label})")
    return 0


def cmd_draw(root: str, self_name: str, args: List[str]) -> int:
    target = ""
    for arg in args:
        if arg.startswith("--out="):
            target = arg[len("--out="):]
        else:
            err(f"{self_name} draw: unknown argument {arg}")
            return 2
    tree = pktree.load_or_exit(root)
    target = target or pktree.DRAWING_FILE
    path = target if os.path.isabs(target) else os.path.join(root, *target.replace("\\", "/").split("/"))
    if target == "-":
        out(tree.draw(project_name(root)).rstrip())
        return 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as file:
        file.write(tree.draw(project_name(root)))
    out(f"wrote {os.path.relpath(path, root)}: edit it, then '{self_name} apply {os.path.relpath(path, root)}'")
    return 0


def cmd_list() -> int:
    out("trees for 'pk tree apply NAME' and 'pk new --tree=NAME':")
    for name in pktree.preset_names():
        tree = pktree.resolve(name)
        moved = ", ".join(f"{k}={v}" for k, v in sorted(tree.moved().items())) or "everything in its classic place"
        omitted = " ".join(sorted(tree.omit))
        out(f"  {name:<12} {moved}" + (f"; leaves out {omitted}" if omitted else ""))
    out(f"your own: {pktree.user_trees_dir()}/NAME.conf (or a drawing, NAME.tree)")
    return 0


def usage(self_name: str) -> str:
    rows = [f"  {part.key:<13}{part.default:<30}{part.about}" + (" (optional)" if part.optional else "")
            for part in PARTS]
    return USAGE.format(self=self_name, drawing=pktree.DRAWING_FILE, user=pktree.user_trees_dir(),
                        parts="\n".join(rows))


def main(args: List[str], root: str, self_name: str = "pk tree") -> int:
    setup_output()
    command = args[0] if args else "show"
    rest = args[1:]
    if command in ("-h", "--help", "help"):
        out(usage(self_name))
        return 0
    if command == "show":
        tree = pktree.load_or_exit(root)
        out(f"# {describe(tree)}")
        out(tree.draw(project_name(root)).rstrip())
        missing = tree.missing(root)
        if missing:
            out(f"\n{C.yellow}does not match the files{C.reset}: " + "; ".join(missing))
        return 0
    if command == "check":
        return cmd_check(root, self_name, rest)
    if command == "draw":
        return cmd_draw(root, self_name, rest)
    if command == "apply":
        return cmd_apply(root, self_name, rest)
    if command == "reset":
        return cmd_reset(root, self_name, rest)
    if command == "list":
        return cmd_list()
    err(f"{self_name}: unknown command '{command}'\n")
    err(usage(self_name))
    return 2
