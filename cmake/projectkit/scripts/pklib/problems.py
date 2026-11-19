"""Every error pk reports: a code, what went wrong, why, how to fix it and
where to read more, in one shape wherever the error comes from:

  error[PK401]: conan install failed for Debug (native)
     why  Conan's profile plugin rejects compiler.cstd=23 for gcc 13
     fix  set compiler.cstd=17 in profiles/native
          'pk fix' does it for you, then runs 'pk build' again
     log  build/pk-logs/native-debug.deps.log
    docs  https://docs.conan.io/2/reference/extensions/profile_plugin.html
          pk explain PK401

The tool's own error lines (Conan's ERROR block, CMake's 'CMake Error'
block, the compiler's first error) are printed above it, nothing else.

Nothing here knows any tool: the codes are about steps (deps, configure,
build, test), and what a tool printed is read by pklib/readers/, one module
per tool, which a project can add to.

The last error is kept in build/pk-last-error.json: 'pk fix' runs its fix
(after asking), 'pk explain' without a code explains it. Any command that
works afterwards forgets it.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import sys
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

from . import readers
from .common import KIT_DIR, C, confirm, err, flush, link, out, run, shown

LAST_ERROR = "build/pk-last-error.json"
REPO_URL = "https://github.com/cooldood155/QCDX"


class Entry(NamedTuple):
    title: str
    explain: str
    docs: Tuple[str, ...]


# 'kit:FILE#anchor' is a document of this kit (cmake/projectkit/docs/FILE);
# everything else is a URL.
CMAKE = "https://cmake.org/cmake/help/latest"

CATALOG: Dict[str, Entry] = {
    # usage: what was typed
    "PK100": Entry("unknown command", """\
pk has no command by that name. Every unambiguous prefix of a command works
('pk san' is sanitize), and so do the short names in 'pk help'. When the word
is close to a command, 'pk fix' runs the command it most likely meant.""",
                   ("kit:PK.md#commands",)),
    "PK101": Entry("ambiguous command", """\
The word is the start of more than one command, so pk will not guess. Type a
few more letters; 'pk help' lists every command with its short name.""",
                   ("kit:PK.md#commands",)),
    "PK102": Entry("unknown flag", """\
The command has no flag by that name. 'pk help COMMAND' lists every flag the
command takes. When the flag is close to one of them (a typo), 'pk fix' runs
the command again with the right one. Arguments for Conan, CMake, the build
tool, ctest or your app go after '--', where pk does not read them.""",
                   ("kit:PK.md#flags",)),
    "PK103": Entry("flag not taken by this command", """\
The flag exists, but this command does not use it ('clean' has no --jobs, for
example). 'pk help COMMAND' lists the flags each command takes.""",
                   ("kit:PK.md#flags",)),
    "PK104": Entry("flag needs a value", """\
The flag takes a value, written '--flag=VALUE' or '--flag VALUE', and none
followed it.""",
                   ("kit:PK.md#flags",)),
    "PK105": Entry("flag value not understood", """\
The value given to a flag is not one pk accepts: a build type it does not
know, a --lib kind, a --jobs count that is not a number, -O/-D without
NAME=VALUE, or a variant name with '/' or spaces. When the value is close to
a valid one, 'pk fix' runs the command again with it.""",
                   ("kit:PK.md#flags",)),
    "PK106": Entry("unexpected argument", """\
The command takes no word in that position. Arguments meant for another tool
go after '--': 'pk build -- -k 0', 'pk test -- --repeat until-fail:5',
'pk run -- --help'.""",
                   ("kit:PK.md#flags",)),
    "PK107": Entry("pick one", """\
More than one thing matches and the command works on one: name it, as the
message lists them.""",
                   ("kit:PK.md#commands",)),

    # the project and its tree
    "PK200": Entry("no project here", """\
pk works on the project it is run in: the nearest directory, from here
upwards, with a CMakeLists.txt and a CMakePresets.json. Run it inside the
project, set PK_REPO_ROOT, or create one with 'pk new NAME'.""",
                   ("kit:PK.md",)),
    "PK201": Entry("project tree broken", """\
.pk/tree.conf says where each part of the project lives, and it no longer
matches the files (a part was moved or deleted by hand, or the file was
edited into something pk cannot read). 'pk tree check' says exactly what is
wrong; 'pk tree reset' goes back to the last tree that matched, which is what
'pk fix' runs.""",
                   ("kit:TREE.md",)),
    "PK202": Entry("bad setting", """\
A setting in the project's pk.conf (scripts/helpers/pk/pk.conf in the classic
tree) or the environment has a value pk cannot use. Fix the value or delete
the line to get the default.""",
                   ("kit:PK.md#configuration",)),
    "PK203": Entry("no such cross target", """\
A cross target is a profile under profiles/ plus its CMake presets.
'pk list' shows the targets this project has; a new one needs both the
profile and its presets.""",
                   ("kit:PK.md#flags",)),
    "PK204": Entry("preset missing or incomplete", """\
pk builds through the configure presets in CMakePresets.json (native-debug,
native-release, ..., one per cross target and build type), and each must name
the toolchain the deps step writes as its toolchainFile. The preset pk needs is missing or has
no toolchainFile; compare CMakePresets.json with the template's.""",
                   (f"{CMAKE}/manual/cmake-presets.7.html",)),
    "PK205": Entry("part left out of the tree", """\
This project's tree leaves out the part the command needs (the tests, for
example). 'pk tree' shows the tree; 'pk tree apply' can bring the part
back.""",
                   ("kit:TREE.md",)),

    # tools and the machine
    "PK300": Entry("tool missing", """\
A program the command runs is not on PATH. The fix line is the usual way to
install it on this system; 'pk doctor' checks every tool pk uses at once.
When QCDX was installed with pipx, 'pipx install "qcdx[tools]"' brings Conan,
CMake and Ninja along (a compiler is still needed).""",
                   ("kit:PK.md#commands",)),
    "PK301": Entry("not available on this system", """\
The command needs something this operating system does not have (Valgrind
only runs on Linux, a cross-compiled binary does not run here).""",
                   ("kit:PK.md#limits",)),
    "PK302": Entry("needs an answer", """\
The command changes or deletes files and asks first, but there is no terminal
to ask on (CI, a pipe). Pass --yes when that is really wanted.""",
                   ("kit:PK.md#flags",)),

    # dependencies: the package manager
    "PK400": Entry("installing the dependencies failed", """\
The package manager could not install the dependencies. Its own error lines
are printed above the error; the whole output is in the log. Common causes:
no network for a package not in its cache, a version range nothing matches,
a profile the compiler does not fit, or a package that failed to build from
source.""",
                   ("kit:PK_DEP.md",)),
    "PK401": Entry("C or C++ standard not supported by the compiler", """\
The package manager checks the profile's C and C++ standards against the
compiler, and the profile asks for one this compiler does not have (for
Conan, gcc 13 has no compiler.cstd=23, gcc 14 does). Either lower the
standard in the profile, which 'pk fix' does, or use a newer compiler. The
project's own standard (pk_project_setup) is not affected: the profile only
says how the dependencies are built.""",
                   ("kit:PK_DEP.md",)),
    "PK402": Entry("package remote not reachable", """\
The package manager could not reach a remote (a server it downloads packages
from) to look up or download a package. Check the network or proxy, and its
list of remotes. When every package is already in its cache, it can install
without asking any remote.""",
                   ("kit:PK_DEP.md",)),
    "PK403": Entry("package or version not found", """\
No remote has a package matching the name and version (range) in deps.json,
or the lockfile pins a version the remotes do not have any more. Check the
name and versions there are, and change the requirement with 'pk dep set'.""",
                   ("kit:PK_DEP.md",)),
    "PK404": Entry("lockfile out of date", """\
The lockfile (conan.lock) pins the exact version of every dependency, and a
requirement is not in it (deps.json changed without 'pk dep lock'). 'pk dep
lock' writes it again, which is what 'pk fix' runs.""",
                   ("kit:PK_DEP.md",)),
    "PK405": Entry("no default package profile", """\
The package manager needs a profile describing this machine, made once (for
Conan: 'conan profile detect'). 'pk fix' (and 'pk doctor --fix') creates it.""",
                   ("kit:PK.md#commands",)),
    "PK406": Entry("package manager does not know this compiler", """\
The package manager lists the compiler versions it knows, and this compiler
is newer. Upgrading the package manager brings a newer list.""",
                   ("kit:PK_DEP.md",)),
    "PK407": Entry("a dependency failed to build", """\
No prebuilt binary matched this configuration, so the package was built from
source, and that build failed. Its output is in the log. Often another
version of the package, or a compiler setting closer to the prebuilt
binaries, avoids building it at all.""",
                   ("kit:PK_DEP.md",)),
    "PK408": Entry("a package's libraries are not where its recipe says", """\
The package was built and installed, but its library files are not named
what the package's recipe tells the build to link, so finding the package
fails. It is a bug in the package or its recipe, usually for one platform or
compiler. A known one has a fix line (often an option for the package, which
rebuilds it once); otherwise report it to the package's recipe, with the log.""",
                   ("kit:PK_DEP.md",)),
    "PK409": Entry("a package does not link a system library it needs", """\
Linking stops on functions of a system library (GDI+, Winsock, ...) that a
package uses: the package's recipe does not list that library, so nothing
links it. Link it to the package's CMake target yourself, which puts it
after the package's own libraries (MinGW's linker needs that order).""",
                   ("kit:PK_DEP.md", "https://cmake.org/cmake/help/latest/command/target_link_libraries.html")),
    "PK410": Entry("pk dep failed", """\
'pk dep' manages deps.json and conan.lock; the message says what it refused
or what failed. 'pk dep help' lists its commands.""",
                   ("kit:PK_DEP.md",)),
    "PK411": Entry("pk package failed", """\
'pk package' runs the package manager's packaging commands; the message says
what is missing.""",
                   ("kit:PACKAGE.md",)),

    # configure (CMake)
    "PK500": Entry("configure failed", """\
CMake stopped while configuring. Its 'CMake Error' block above says where
(file and line) and why; the whole output is in the log. 'pk configure
--verbose' shows everything CMake prints.""",
                   (f"{CMAKE}/manual/cmake.1.html",)),
    "PK501": Entry("no compiler found", """\
CMake found no working C or C++ compiler. Install one (the fix line has the
usual way here) and make sure it is on PATH in this shell; 'pk doctor' checks
it. After installing, the old tree must forget its failed search: 'pk fix'
reconfigures from scratch.""",
                   (f"{CMAKE}/variable/CMAKE_LANG_COMPILER.html",)),
    "PK502": Entry("CMake too old", """\
The project needs a newer CMake than the one on PATH. pip and pipx install
current releases on every system.""",
                   ("https://cmake.org/download/",)),
    "PK503": Entry("package not found by find_package", """\
CMake was asked for a package (find_package) that nothing provides. Packages
come from the package manager: 'pk dep add' puts one in deps.json, and 'pk
dep why NAME' shows what a dependency provides. When the package is meant to
come from the system, install its development files.""",
                   ("kit:PK_DEP.md", f"{CMAKE}/command/find_package.html")),
    "PK504": Entry("build tree made by something else", """\
The build tree's CMakeCache.txt was written for another source directory or
another generator (the project moved, or the tree was configured by hand). A
fresh configure fixes it, which 'pk fix' runs ('pk configure --reset').""",
                   (f"{CMAKE}/manual/cmake.1.html#cmdoption-cmake-fresh",)),
    "PK506": Entry("a target has none of its files", """\
pk_create_library (or another pk_create_*) was told the target needs source
files or public headers (REQUIRE_SOURCES, REQUIRE_PUBLIC_HEADERS) and found
none: the files were deleted or moved, or the directory it looks in is empty.
Put a file back, or drop the REQUIRE_ option when the target really has none
(a header-only library has no sources).""",
                   ("kit:PK.md#output-and-errors",)),
    "PK505": Entry("toolchain file missing", """\
The preset's toolchain file is written by the deps step, and it is gone
(build/ was cleaned by hand). 'pk fix' installs the dependencies again.""",
                   ("kit:PK.md#what-pk-decides-for-you",)),

    # build
    "PK600": Entry("compile error", """\
The compiler stopped on an error in the source. The first error is shown
with its file and line; fix that one first, later errors often follow from
it. 'pk build --verbose' shows the full compiler command lines.""",
                   ("kit:PK.md#output-and-errors",)),
    "PK601": Entry("link error", """\
Everything compiled but the linker found no definition for a function or
variable that is used. Usually the definition is missing, its source file is
not in the target, or the library that has it is not linked
(target_link_libraries, or a deps.json package with its CMake target).""",
                   ("kit:PK_DEP.md", f"{CMAKE}/command/target_link_libraries.html")),
    "PK602": Entry("header not found", """\
A #include names a header the compiler cannot find: a typo, a header of a
dependency that is not in deps.json, or an include directory not given to
the target.""",
                   ("kit:PK_DEP.md", f"{CMAKE}/command/target_include_directories.html")),
    "PK603": Entry("build files broken", """\
The build tool could not load or regenerate its build files. A fresh
configure fixes it, which 'pk fix' runs.""",
                   (f"{CMAKE}/manual/cmake.1.html#cmdoption-cmake-fresh",)),
    "PK604": Entry("build failed", """\
The build stopped. The failing step's output is printed above; the whole
output is in the log.""",
                   ("kit:PK.md#output-and-errors", f"{CMAKE}/manual/cmake.1.html#build-a-project")),
    "PK606": Entry("no main function", """\
An executable was linked without a main(). Usually the file that has it is
not in the target, main is inside a namespace, or it is misspelled. When it
is in a static library (or wxWidgets' wxIMPLEMENT_APP is), the linker never
takes it out of the library: it only takes a library's files that something
already linked uses, and nothing calls main. Keep it in the app's sources. MinGW
then reports a missing WinMain, MSVC a missing main or WinMain referenced in
invoke_main, Linux an undefined main in _start: all the same cause.""",
                   ("kit:PK.md#output-and-errors", "https://en.cppreference.com/w/cpp/language/main_function")),
    "PK605": Entry("install failed", """\
'cmake --install' stopped: the destination is not writable, or the tree was
not built. The log has the whole output.""",
                   (f"{CMAKE}/manual/cmake.1.html#install-a-project",)),

    # run and test
    "PK700": Entry("tests failed", """\
One or more tests failed; their output is printed above. 'pk fix' runs only
the failed ones again. 'pk test -R NAME' runs the tests matching NAME.""",
                   (f"{CMAKE}/manual/ctest.1.html",)),
    "PK701": Entry("nothing to run", """\
pk did not find the executable to run: no app directories, or the build made
no executable by that name. The message lists what the build did make.""",
                   ("kit:PK.md#commands",)),

    # sync and git
    "PK800": Entry("repository not ready for sync", """\
'pk sync' makes one commit that holds only the kit update, so the repository
must be in a state where that is possible: at least one commit, no merge in
progress, nothing staged, and no uncommitted changes in the kit paths.""",
                   ("kit:PK.md#sync-kit-updates-from-the-template", "https://git-scm.com/docs/git-stash")),
    "PK801": Entry("template not reachable", """\
pk could not fetch the template (QCDX) to sync from. Check the network, or
sync from a local clone: 'pk sync --from /path/to/QCDX'.""",
                   ("kit:PK.md#sync-kit-updates-from-the-template",)),
    "PK802": Entry("template history does not match", """\
pk could not find the template commit this kit was synced from. Give it
with --base COMMIT (the QCDX commit the kit currently matches).""",
                   ("kit:PK.md#sync-kit-updates-from-the-template",)),
    "PK803": Entry("commit failed", """\
git refused the commit (a hook, signing, no user.name). The change is staged:
commit it yourself once git is happy.""",
                   ("https://git-scm.com/docs/git-commit",)),

    # the other pk tools
    "PK900": Entry("pk tree failed", "'pk tree help' lists what it does; the message says what went wrong.",
                   ("kit:TREE.md",)),
    "PK901": Entry("pk rename failed", "The message says what 'pk rename' refused.", ("kit:PK.md#commands",)),
    "PK902": Entry("pk release failed", "The message says which release step failed.", ("kit:RELEASE.md",)),
    "PK903": Entry("pk verify failed", "The message says what 'pk verify' could not do.", ("kit:VERIFY.md",)),
    "PK904": Entry("pk new failed", "The message says what 'pk new' refused.", (f"{REPO_URL}#readme",)),
    "PK905": Entry("project registry unreadable", """\
The list of known projects (in ~/.pk) could not be read. Delete the file the
message names; running pk inside a project adds it again.""",
                   (f"{REPO_URL}#readme",)),
}


def fix_run(argv: Sequence[str], say: str = "", rerun: bool = True) -> Dict[str, object]:
    """A fix 'pk fix' runs: a command line ("pk" first means this project's
    pk); `rerun` runs the failed command again afterwards."""
    return {"run": list(argv), "say": say, "rerun": rerun}


def fix_edit(path: str, old: str, new: str, say: str, rerun: bool = True) -> Dict[str, object]:
    """A fix 'pk fix' applies: replace the regex `old` with `new` in `path`
    (relative to the project)."""
    return {"edit": [path, old, new], "say": say, "rerun": rerun}


def fix_steps(steps: Sequence[Dict[str, object]], say: str, rerun: bool = True) -> Dict[str, object]:
    """Several fix_run/fix_edit steps 'pk fix' applies in order, as one fix
    (when doing them one at a time would rebuild something twice)."""
    return {"steps": list(steps), "say": say, "rerun": rerun}


def fix_hint(say: str) -> Dict[str, object]:
    """A fix only you can do: shown, never run."""
    return {"say": say}


class Problem:
    """One error: `code` from CATALOG, `message` what happened, `why` the
    cause when known, `fixes` from fix_run/fix_edit/fix_hint, `details` the
    tool's own lines to show, `log` the full output, `status` the exit code."""

    def __init__(self, code: str, message: str, why: str = "", fixes: Sequence[Dict[str, object]] = (),
                 details: Sequence[str] = (), log: str = "", docs: Sequence[str] = (), status: int = 1) -> None:
        self.code = code
        self.message = message
        self.why = why
        self.fixes = list(fixes)
        self.details = list(details)
        self.log = log
        self.docs = list(docs)
        self.status = status

    def to_json(self) -> Dict[str, object]:
        return {"code": self.code, "message": self.message, "why": self.why, "fixes": self.fixes,
                "log": self.log, "docs": self.docs}

    @classmethod
    def from_json(cls, data: Dict[str, object]) -> "Problem":
        return cls(str(data.get("code", "")), str(data.get("message", "")), str(data.get("why", "")),
                   list(data.get("fixes") or []), (), str(data.get("log", "")), list(data.get("docs") or []))


def kit_version() -> str:
    try:
        with open(os.path.join(KIT_DIR, "VERSION"), encoding="utf-8") as file:
            return file.read().strip()
    except OSError:
        return ""


def doc_target(doc: str, online: bool = False) -> Tuple[str, str]:
    """(text to show, link target) of a CATALOG doc: a URL as it is, a kit
    doc as its path here (relative when below the current directory), or
    online on GitHub at this kit's tag."""
    if not doc.startswith("kit:"):
        return doc, doc
    name, _, anchor = doc[len("kit:"):].partition("#")
    path = os.path.join(KIT_DIR, "docs", name)
    if online or not os.path.isfile(path):
        version = kit_version()
        url = f"{REPO_URL}/blob/{'v' + version if version else 'main'}/cmake/projectkit/docs/{name}"
        url += f"#{anchor}" if anchor else ""
        return url, url

    shown_path = path
    try:
        relative = os.path.relpath(path)
        if not relative.startswith(".."):
            shown_path = relative
    except ValueError:
        pass
    shown_path = shown_path.replace(os.sep, "/")
    return shown_path + (f"#{anchor}" if anchor else ""), path


def runnable(fix: Dict[str, object]) -> bool:
    return "run" in fix or "edit" in fix or "steps" in fix


def fix_text(fix: Dict[str, object], self_name: str) -> str:
    if "steps" in fix:
        return " then ".join(fix_text(step, self_name) for step in fix["steps"])  # type: ignore[union-attr]
    if "run" in fix:
        argv = [str(word) for word in fix["run"]]  # type: ignore[union-attr]
        if argv and argv[0] == "pk":
            argv[0] = self_name
        return shown(argv)
    return str(fix.get("say", ""))


def render(problem: Problem, self_name: str = "pk") -> List[str]:
    entry = CATALOG.get(problem.code)
    lines = [f"{C.red}{C.bold}error{C.reset}{C.dim}[{problem.code}]{C.reset}{C.bold}: {problem.message}{C.reset}"]

    def row(label: str, first: str, *more: str) -> None:
        lines.append(f"{C.cyan}{label:>6}{C.reset}  {first}")
        lines.extend(f"        {line}" for line in more)

    if problem.why:
        import shutil
        import textwrap

        width = max(shutil.get_terminal_size((100, 20)).columns - 9, 40)
        row("why", *[part for line in problem.why.splitlines()
                     for part in (textwrap.wrap(line, width, break_on_hyphens=False) or [""])])
    told = False
    for index, item in enumerate(problem.fixes):
        text = fix_text(item, self_name)
        if index and text.startswith("or "):
            text = text[3:]
        if "run" in item:
            text = f"{C.yellow}{text}{C.reset}" + (f"    {C.dim}{item['say']}{C.reset}" if item.get("say") else "")
        elif "steps" in item:
            text = str(item.get("say", ""))
        row("fix" if index == 0 else "or", text)
        if not told and runnable(item):
            told = True
            what = "runs it" if "run" in item else "does it"
            then = ", then runs the failed command again" if item.get("rerun") else ""
            lines.append(f"        {C.dim}'{self_name} fix' {what} for you{then}{C.reset}")
    if problem.log:
        row("log", link(problem.log.replace(os.sep, "/"), problem.log))
    docs = list(problem.docs) + [doc for doc in (entry.docs if entry else ()) if doc not in problem.docs]
    shown_docs = [link(*doc_target(doc)) for doc in docs[:2]]
    shown_docs.append(f"{C.dim}{self_name} explain {problem.code}{C.reset}")
    row("docs", *shown_docs)
    return lines


def report(problem: Problem, root: Optional[str] = None, argv: Sequence[str] = (), self_name: str = "pk") -> None:
    """Prints the problem (the tool's own lines first) and, inside a project,
    records it for 'pk fix' and 'pk explain'."""
    flush()
    for line in problem.details:
        err(line)
    if problem.details:
        err("")
    for line in render(problem, self_name):
        err(line)
    if root:
        record(root, problem, argv)


def record(root: str, problem: Problem, argv: Sequence[str]) -> None:
    path = os.path.join(root, *LAST_ERROR.split("/"))
    data = problem.to_json()
    data.update(argv=list(argv), cwd=os.getcwd(), time=datetime.datetime.now().isoformat(timespec="seconds"))
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as file:
            json.dump(data, file, indent=2)
            file.write("\n")
    except OSError:
        pass


def last(root: str) -> Optional[Dict[str, object]]:
    try:
        with open(os.path.join(root, *LAST_ERROR.split("/")), encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def forget(root: str) -> None:
    try:
        os.remove(os.path.join(root, *LAST_ERROR.split("/")))
    except OSError:
        pass


def normalize_code(word: str) -> str:
    digits = re.sub(r"(?i)^pk", "", word.strip())
    return f"PK{digits}" if digits.isdigit() else word.upper()


def explain(words: Sequence[str], root: Optional[str], self_name: str = "pk") -> int:
    """'pk explain [CODE]': one code in full, the last error's code, or every
    code there is."""
    recorded = last(root) if root else None
    if words and words[0] in ("-h", "--help", "help"):
        out(f"usage: {self_name} explain [CODE]\n\nExplains an error code (PK401, 401). Without CODE: the last "
            f"error here, or the list of every code.\n'{self_name} explain --list' lists them all.")
        return 0
    if (not words and recorded is None) or (words and words[0] in ("--list", "list", "all")):
        out(f"{C.bold}error codes{C.reset} ('{self_name} explain CODE' for one)")
        group = ""
        for code, entry in CATALOG.items():
            if code[2] != group:
                group = code[2]
                out("")
            out(f"  {C.dim}{code}{C.reset}  {entry.title}")
        return 0
    code = normalize_code(words[0]) if words else str(recorded.get("code", ""))  # type: ignore[union-attr]
    entry = CATALOG.get(code)
    if entry is None:
        report(Problem("PK100", f"no error code '{words[0] if words else code}'",
                       fixes=[fix_hint(f"'{self_name} explain --list' lists every code")], status=2))
        return 2
    out(f"{C.bold}{code}{C.reset}: {entry.title}\n")
    out(entry.explain)
    if recorded and recorded.get("code") == code:
        problem = Problem.from_json(recorded)
        command = shown([self_name, *[str(word) for word in recorded.get("argv", [])]])  # type: ignore[union-attr]
        out(f"\n{C.bold}last time{C.reset} ({recorded.get('time', '?')}, '{command}')")
        for line in render(problem, self_name):
            out(f"  {line}")
    out(f"\n{C.bold}read more{C.reset}")
    readers.load()
    for doc in [*entry.docs, *[url for url in readers.DOCS.get(code, []) if url not in entry.docs]]:
        text, target = doc_target(doc)
        out(f"  {link(text, target)}")
        if doc.startswith("kit:"):
            text, target = doc_target(doc, online=True)
            out(f"  {link(text, target)}")
    return 0


def apply_fix(root: str, pk_argv: Sequence[str], assume_yes: bool, dry_run: bool, self_name: str = "pk") -> int:
    """'pk fix': applies the last error's first fix that pk can apply, after
    asking, then runs the failed command again when the fix says so.
    `pk_argv` is how to run this project's pk (python + scripts/pk.py)."""
    recorded = last(root)
    if recorded is None:
        out(f"{C.green}nothing to fix{C.reset}: no error since the last command that worked")
        return 0
    problem = Problem.from_json(recorded)
    failed = [str(word) for word in recorded.get("argv", [])]  # type: ignore[union-attr]
    chosen = next((item for item in problem.fixes if runnable(item)), None)
    out(f"{C.dim}[{problem.code}]{C.reset} {problem.message}")
    if chosen is None:
        out("pk cannot fix this one by itself; what to do:")
        for item in problem.fixes:
            out(f"  {fix_text(item, self_name)}")
        if not problem.fixes:
            out(f"  '{self_name} explain {problem.code}' says what it means")
        return 1

    steps = list(chosen["steps"]) if "steps" in chosen else [chosen]  # type: ignore[call-overload]
    plan = [f"{C.yellow}{fix_text(step, self_name)}{C.reset}" if "run" in step else fix_text(step, self_name)
            for step in steps]
    if chosen.get("rerun") and failed:
        plan.append(f"{C.yellow}{shown([self_name, *failed])}{C.reset}  {C.dim}(the command that failed){C.reset}")
    out("will:")
    for step in plan:
        out(f"  {step}")
    if dry_run:
        return 0
    if not assume_yes:
        if not sys.stdin.isatty():
            report(Problem("PK302", "not asking on a non-interactive input",
                           fixes=[fix_hint(f"'{self_name} fix --yes' applies it without asking")], status=2))
            return 2
        if not confirm("go ahead?"):
            out("nothing changed")
            return 1

    for step in steps:
        status = apply_step(root, step, pk_argv, str(recorded.get("cwd") or root), self_name)
        if status != 0:
            return status
    forget(root)
    if chosen.get("rerun") and failed:
        out(f"{C.yellow}+{C.reset} {shown([self_name, *failed])}")
        return run([*pk_argv, *failed], cwd=str(recorded.get("cwd") or root))
    return 0


def apply_step(root: str, step: Dict[str, object], pk_argv: Sequence[str], cwd: str, self_name: str) -> int:
    if "edit" in step:
        path, old, new = (str(part) for part in step["edit"])  # type: ignore[union-attr]
        full = os.path.join(root, *path.split("/"))
        try:
            with open(full, encoding="utf-8", newline="") as file:
                text = file.read()
            changed, count = re.subn(old, new, text, flags=re.MULTILINE)
            if not count:
                err(f"{C.red}error{C.reset}: {path} no longer has what the fix changes; nothing changed")
                return 1
            with open(full, "w", encoding="utf-8", newline="") as file:
                file.write(changed)
        except OSError as error:
            err(f"{C.red}error{C.reset}: cannot edit {path}: {error.strerror or error}")
            return 1
        out(f"{C.green}changed{C.reset} {path}")
        return 0
    argv = [str(word) for word in step["run"]]  # type: ignore[union-attr]
    out(f"{C.yellow}+{C.reset} {fix_text(step, self_name)}")
    argv = [*pk_argv, *argv[1:]] if argv and argv[0] == "pk" else argv
    return run(argv, cwd=cwd)


def closest(word: str, choices: Sequence[str]) -> str:
    """The choice `word` most likely meant (a typo), or ""."""
    import difflib

    found = difflib.get_close_matches(word, list(choices), n=1, cutoff=0.6)
    return found[0] if found else ""


def short_path(path: str) -> str:
    """`path` relative to the current directory when it is below it."""
    if not os.path.isabs(path):
        return path
    try:
        relative = os.path.relpath(path)
    except ValueError:
        return path

    return path if relative.startswith("..") else relative.replace(os.sep, "/")


# What a step's code is when no reader recognizes its output.
STEP_CODES = {"deps": "PK400", "configure": "PK500", "build": "PK604", "test": "PK700", "install": "PK605"}


def diagnose(step: str, tool: str, text: str, context: Optional[Dict[str, object]] = None) \
        -> Tuple[str, str, List[Dict[str, object]], List[str], List[str]]:
    """(code, why, fixes, details, docs) of a failed step's output. Only the
    readers (pklib/readers/) know what `tool` prints; without one that
    recognizes it, the step's own code and the tool's last lines."""
    found, lines = readers.read(step, tool, text, dict(context or {}))
    if found is None:
        said = next((line.strip() for line in lines if line.strip()), "")
        return STEP_CODES.get(step, "PK604"), said, [], lines, []
    details = list(lines if found.details is None else found.details)
    return found.code, found.why, list(found.fixes), details, list(found.docs)
