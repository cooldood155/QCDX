"""Where the kit and the template are, however QCDX was installed.

wheel (pip, pipx, uv)   qcdx/data/kit and qcdx/data/template, real files
zipapp (pk.pyz)         the same paths, inside the zip
source checkout         the repository root and template/ themselves
"""

from __future__ import annotations

import os
import stat
from importlib import resources
from pathlib import Path
from typing import Iterable, Optional

# What every project vendors and 'pk sync' keeps up to date. Must equal the
# default PK_SYNC_PATHS in cmake/projectkit/scripts/pklib/pk.py (a test checks).
KIT_PATHS = (
    "cmake/projectkit",
    "scripts/pk.py",
    "scripts/verify.py",
    "scripts/package.py",
    "scripts/release.py",
    "scripts/bootstrap.py",
    ".github/actions/pk-setup",
)

UPSTREAM_URL = "https://github.com/cooldood155/QCDX.git"
UPSTREAM_BRANCH = "main"

SKIP = {"__pycache__", ".pytest_cache", ".ruff_cache", "build", "stage", "compile_commands.json"}


def _data():  # -> Traversable
    return resources.files("qcdx") / "data"


def source_root() -> Optional[Path]:
    repo = Path(__file__).resolve().parents[2]
    if (repo / "template").is_dir() and (repo / "cmake" / "projectkit" / "VERSION").is_file():
        return repo
    return None


def kit_root():  # -> Traversable
    data = _data()
    if data.is_dir():
        return data / "kit"
    root = source_root()
    if root is None:
        raise RuntimeError("QCDX is incomplete: neither qcdx/data nor a source checkout was found")
    return root


def template_root():  # -> Traversable
    data = _data()
    if data.is_dir():
        return data / "template"
    root = source_root()
    if root is None:
        raise RuntimeError("QCDX is incomplete: neither qcdx/data nor a source checkout was found")
    return root / "template"


def version() -> str:
    return (kit_root() / "cmake" / "projectkit" / "VERSION").read_text(encoding="utf-8").strip()


def commit() -> str:
    """The QCDX commit this copy was built from, when known."""
    try:
        from . import _commit  # written by the release workflow

        return _commit.COMMIT
    except ImportError:
        pass
    root = source_root()
    if root is not None and (root / ".git").exists():
        import subprocess

        result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    return ""


def copy_tree(source, target: Path, skip: Iterable[str] = SKIP) -> None:
    """Copy a Traversable (directory or file) to a real path."""
    skip = set(skip)
    if source.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        data = source.read_bytes()
        target.write_bytes(data)
        if os.name == "nt":
            return
        real = Path(str(source))
        if real.is_file():  # source checkout or installed wheel: keep the mode exactly
            target.chmod(real.stat().st_mode & 0o777)
        elif data.startswith(b"#!"):  # inside pk.pyz modes are unreadable: scripts get +x
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return
    target.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        if child.name in skip or child.name.endswith((".pyc", ".pyo")):
            continue
        copy_tree(child, target / child.name, skip)


def copy_kit(target: Path) -> None:
    root = kit_root()
    for relative in KIT_PATHS:
        source = root
        for part in relative.split("/"):  # one part at a time: zip paths on 3.9 take only one
            source = source / part
        copy_tree(source, target.joinpath(*relative.split("/")))
    if os.name != "nt":
        for script in (target / "scripts").glob("*.py"):
            script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def cmake_dir() -> Path:
    """A real directory holding QCDXConfig.cmake and projectkit/.

    From a zipapp it is extracted once per version into the user cache.
    """
    source = kit_root() / "cmake"
    real = Path(str(source))
    if real.is_dir() and (real / "QCDXConfig.cmake").is_file():
        return real
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "qcdx" / "cache"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "qcdx"
    target = base / version() / "cmake"
    if not (target / "QCDXConfig.cmake").is_file():
        for name in ("QCDXConfig.cmake", "QCDXConfigVersion.cmake"):
            copy_tree(source / name, target / name)
        copy_tree(source / "projectkit", target / "projectkit")
    return target
