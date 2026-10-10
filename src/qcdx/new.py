"""pk new: a ready-to-build project from the template and the kit.

The template's sample project is called 'qcdx'; the project's own
scripts/bootstrap.py (the same code as 'pk rename') gives it the new name, so
creating and renaming a project can never disagree.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from . import resources

TEMPLATE_NAME = "qcdx"
TEMPLATE_DESCRIPTION = "Template project built on ProjectKit"

USAGE = """\
usage: pk new NAME [DIR] [flag...]

Creates DIR (default ./NAME) with a library, an application, tests and a
build-time tool, all named NAME, that configures and builds right away.

  NAME                  [a-z][a-z0-9_]*, it is also the C++ namespace
  --description=TEXT    project(DESCRIPTION) and the Conan recipe
  --version=X.Y.Z       first version, default 0.1.0
  --author=TEXT         recipe author, default from 'git config user.name/email'
  --url=URL             recipe url, e.g. the repository's address
  --license=SPDX        recipe license, e.g. MIT (add the LICENSE file yourself)
  --no-git              do not create a git repository and first commit
  --force               allow a DIR that exists and is not empty
  -h, --help            this message"""

# Same header pk.py's state_write() uses, so 'pk new' and 'pk sync' agree.
STATE = """\
# Written by "pk sync": the template cmake/projectkit comes from and
# the template commit it was last synced to. Keep it committed.
url={url}
branch={branch}
commit={commit}
"""

README_FOOTER = """
---

Created with [QCDX](https://github.com/cooldood155/QCDX) {version} (`pk new`).
Supported platforms and toolchains:
[BUILDING.md](https://github.com/cooldood155/QCDX/blob/v{version}/docs/BUILDING.md).
"""


class NewError(Exception):
    pass


def write_lf(path: Path, text: str) -> None:
    """Write with LF endings everywhere, like the template (.gitattributes eol=lf).

    Not Path.write_text(newline=...): that argument needs Python 3.10.
    """
    with open(path, "w", encoding="utf-8", newline="\n") as file:
        file.write(text)


def git(args: List[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


def git_identity() -> str:
    try:
        name = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True).stdout.strip()
        email = subprocess.run(["git", "config", "user.email"], capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""
    if name and email:
        return f"{name} <{email}>"
    return name


def set_recipe_field(text: str, field: str, value: str) -> str:
    """Set (or add, after description) a class attribute of the recipe;
    an empty value removes it, so nothing of the template's recipe is kept."""
    line = f'  {field} = "{value}"'
    pattern = re.compile(rf"^[ \t]*{field}[ \t]*=.*$", re.MULTILINE)
    if not value:
        return re.sub(rf"^[ \t]*{field}[ \t]*=.*\n", "", text, count=1, flags=re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(lambda _m: line, text, count=1)
    anchor = re.compile(r"^([ \t]*description[ \t]*=.*)$", re.MULTILINE)
    return anchor.sub(lambda m: f"{m.group(1)}\n{line}", text, count=1)


def create(name: str, directory: Optional[str], description: str, version: str, author: str, url: str,
           license_id: str, use_git: bool, force: bool) -> Path:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise NewError(f"'{name}' must match [a-z][a-z0-9_]*, it is also the C++ namespace")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise NewError("--version must be X.Y.Z")
    for label, value in (("description", description), ("author", author), ("url", url),
                         ("license", license_id)):
        if '"' in value or "\n" in value:
            raise NewError(f"--{label} cannot contain quotes or newlines")

    target = Path(directory or name).resolve()
    if target.exists() and (not target.is_dir() or any(target.iterdir())) and not force:
        raise NewError(f"{target} exists and is not empty (--force to use it anyway)")

    print(f"pk new: {name} in {target} (QCDX {resources.version()})")
    resources.copy_tree(resources.template_root(), target)
    resources.copy_kit(target)

    if name != TEMPLATE_NAME:
        bootstrap = [sys.executable, str(target / "scripts" / "bootstrap.py"), name, f"--from={TEMPLATE_NAME}",
                     "--yes", "--force"]
        env = dict(os.environ, PK_REPO_ROOT=str(target), PK_SELF_NAME="pk rename")
        result = subprocess.run(bootstrap, cwd=str(target), env=env, capture_output=True, text=True)
        if result.returncode != 0:
            sys.stderr.write(result.stdout + result.stderr)
            raise NewError("renaming the template failed (output above)")

    # Description and version are set here, not by the rename, which is
    # skipped when NAME is the template's own name.
    cmake = target / "CMakeLists.txt"
    text = cmake.read_text(encoding="utf-8")
    text = re.sub(r'(DESCRIPTION\s*)"[^"]*"', lambda m: f'{m.group(1)}"{description or name}"', text, count=1)
    text = re.sub(r"(project\s*\([^)]*?VERSION\s+)[0-9]+\.[0-9]+\.[0-9]+", lambda m: m.group(1) + version, text,
                  count=1, flags=re.IGNORECASE)
    write_lf(cmake, text)

    recipe = target / "conanfile.py"
    text = set_recipe_field(recipe.read_text(encoding="utf-8"), "description", description or name)
    # The template's recipe names its own author, url and license; a new
    # project gets the given values (author: the git identity) or none.
    for field, value in (("license", license_id), ("author", author or git_identity()), ("url", url)):
        text = set_recipe_field(text, field, value)
    write_lf(recipe, text)

    readme = target / "README.md"
    if readme.is_file():
        text = readme.read_text(encoding="utf-8").replace(TEMPLATE_DESCRIPTION, description or name, 1)
        write_lf(readme, text + README_FOOTER.format(version=resources.version()))

    state = target / "scripts" / "helpers" / "pk" / "upstream.conf"
    state.parent.mkdir(parents=True, exist_ok=True)
    write_lf(state, STATE.format(url=resources.UPSTREAM_URL, branch=resources.UPSTREAM_BRANCH,
                                 commit=resources.commit()))

    if use_git:
        init_git(target, name)
    return target


def init_git(target: Path, name: str) -> None:
    try:
        inside = git(["rev-parse", "--show-toplevel"], target)
    except OSError:
        print("  git not found, skipped the repository (run 'git init' later)")
        return
    if inside.returncode == 0 and Path(inside.stdout.strip()).resolve() != target:
        print(f"  inside the git repository {inside.stdout.strip()}, no new repository created")
        return
    if inside.returncode != 0:
        if git(["init", "-q", "-b", "main"], target).returncode != 0 and git(["init", "-q"], target).returncode != 0:
            print("  'git init' failed, skipped the repository")
            return
    git(["add", "-A"], target)
    message = f"Create {name} with QCDX {resources.version()}"
    # Inherit the terminal so a commit signing passphrase can be asked for.
    committed = subprocess.run(["git", "commit", "-q", "-m", message], cwd=str(target)).returncode == 0
    if committed:
        print(f"  git: first commit '{message}'")
    else:
        print("  git: files are staged, the first commit failed (set user.name/user.email and commit)")


def main(argv: List[str]) -> int:
    name = ""
    directory: Optional[str] = None
    options = {"description": "", "version": "0.1.0", "author": "", "url": "", "license": ""}
    use_git, force = True, False
    for arg in argv:
        key, sep, value = arg.partition("=")
        if arg in ("-h", "--help"):
            print(USAGE)
            return 0
        if sep and key[2:] in options and key.startswith("--"):
            options[key[2:]] = value
        elif arg == "--no-git":
            use_git = False
        elif arg == "--force":
            force = True
        elif arg.startswith("-"):
            sys.stderr.write(f"pk new: unknown option {arg}\n\n{USAGE}\n")
            return 2
        elif not name:
            name = arg
        elif directory is None:
            directory = arg
        else:
            sys.stderr.write(f"pk new: unexpected argument {arg}\n\n{USAGE}\n")
            return 2
    if not name:
        sys.stderr.write(USAGE + "\n")
        return 2
    try:
        target = create(name, directory, options["description"], options["version"], options["author"],
                        options["url"], options["license"], use_git, force)
    except NewError as error:
        sys.stderr.write(f"pk new: {error}\n")
        return 1
    shown = os.path.relpath(target) if not os.path.relpath(target).startswith("..") else str(target)
    print(f"""
next:
  cd {shown}
  pk doctor        check the tools
  pk build         install dependencies, configure and build
  pk run           run the {name} application
  pk test          build and run the tests
""")
    if not options["license"]:
        print("  Choose a license: add a LICENSE file (releases attach it) and pass --license next time.")
    return 0
