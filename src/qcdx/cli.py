"""The global 'pk' command.

Outside a project it creates one ('pk new'). Inside a project every command
runs that project's own scripts/pk.py, so the kit version the project
vendored decides what 'pk build' does, never the installed QCDX version.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from . import new, resources

HELP = """\
pk - QCDX {version}: create and build C and C++ projects with CMake and Conan

usage:
  pk new NAME [DIR] [flag...]   create a project ('pk new --help')
  pk cmake-dir                  print the QCDX CMake package directory, for
                                -DQCDX_DIR=... or CMAKE_PREFIX_PATH
  pk --version                  QCDX version, and the kit version of this project

Inside a project every other command (build, run, test, sync, ...) runs the
project's own scripts/pk.py; 'pk help' there lists them all.{where}"""


def find_project(start: Path) -> Optional[Path]:
    for directory in (start, *start.parents):
        if (directory / "scripts" / "pk.py").is_file() and (directory / "CMakePresets.json").is_file():
            return directory
    return None


def project_kit_version(project: Path) -> str:
    try:
        return (project / "cmake" / "projectkit" / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown (older than 0.1.0)"


def tool_path(env: dict) -> None:
    """Append this Python's scripts folder to PATH, as a fallback.

    pipx and uv keep a package's dependencies in a private environment, so
    the conan, cmake and ninja of "qcdx[tools]" are only reachable this way.
    Appended, not prepended: tools the user installed always win.
    """
    folder = os.path.dirname(os.path.abspath(sys.executable))
    found = [name for name in ("conan", "cmake", "ninja")
             if any(os.path.isfile(os.path.join(folder, name + ext)) for ext in ("", ".exe"))]
    paths = env.get("PATH", "").split(os.pathsep)
    if found and folder not in paths:
        env["PATH"] = os.pathsep.join([*paths, folder])


def delegate(project: Path, argv: List[str]) -> int:
    env = dict(os.environ, PK_SELF_NAME="pk")
    tool_path(env)
    script = str(project / "scripts" / "pk.py")
    try:
        return subprocess.call([sys.executable, script, *argv], env=env)
    except KeyboardInterrupt:
        return 130


def main(argv: Optional[List[str]] = None) -> int:
    try:
        return run(list(sys.argv[1:] if argv is None else argv))
    except BrokenPipeError:  # 'pk ... | head'
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 141
    except KeyboardInterrupt:
        return 130


def run(argv: List[str]) -> int:
    project = find_project(Path.cwd())
    command = argv[0] if argv else ""

    if command == "new":
        return new.main(argv[1:])
    if command in ("--version", "-V", "version"):
        print(f"QCDX {resources.version()}")
        if project is not None:
            print(f"kit {project_kit_version(project)} in {project}")
        return 0
    if command == "cmake-dir":
        print(resources.cmake_dir())
        return 0
    if project is not None:
        return delegate(project, argv)
    if command in ("", "help", "-h", "--help"):
        print(HELP.format(version=resources.version(), where="\n\n(no project here)"))
        return 0
    sys.stderr.write(f"pk: '{command}' needs a project, and there is none in {Path.cwd()} or above.\n"
                     "     'pk new NAME' creates one.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
