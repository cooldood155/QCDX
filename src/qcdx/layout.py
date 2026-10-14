"""Where the parts of a project live, for the global pk.

The project's own kit reads its tree with pklib/tree.py; the global pk only
needs two parts (scripts, to run the project's pk.py, and the kit, for its
version) and must not import a project's kit, so it reads them here.
"""

from __future__ import annotations

import re
from pathlib import Path


def tree_part(project: Path, part: str, default: str) -> Path:
    """Where a part of the project lives: its classic place, or where the
    project's .pk/tree.conf puts it."""
    value = default
    try:
        text = (project / ".pk" / "tree.conf").read_text(encoding="utf-8")
    except OSError:
        text = ""
    for line in text.splitlines():
        match = re.match(rf"\s*(?:PK_TREE_)?{re.escape(part)}\s*=\s*(\S+)", line, re.IGNORECASE)
        if match:
            value = match.group(1).strip("\"'")
    return project.joinpath(*value.split("/"))


def project_script(project: Path) -> Path:
    return tree_part(project, "scripts", "scripts") / "pk.py"
