"""Local projects the global 'pk' knows about; 'pk list' outside a project.

A project is remembered when 'pk new' creates it and when time the global 'pk'
runs a command inside of it. Projects made from the GitHub template show up
after their first 'pk' command too.

    ~/.pk/projects.json  # PK_HOME overrides ~/.pk

A registry that cannot be read or written will not stop a pk command,
remembering projects is the core functionality and should be performed.
"""

from __future__ import annotations

import datetime
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

FORMAT = 1


class RegistryError(Exception):
    pass


def home() -> Path:
    return Path(os.environ.get("PK_HOME") or Path.home() / ".pk")


def registry_file() -> Path:
    return home() / "projects.json"


def key(path: Path) -> str:
    """Windows paths compare case-insensitively (POSIX ones do not)."""
    return os.path.normcase(str(path))


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def load() -> List[Dict[str, str]]:
    """Every remembered project; an empty list when there is no registry yet."""
    path = registry_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as error:
        raise RegistryError(f"cannot read {path}: {error}") from error

    if not isinstance(data, dict) or not isinstance(data.get("projects"), list):
        raise RegistryError(f"{path} is not a pk project registry")
    return [entry for entry in data["projects"] if isinstance(entry, dict) and isinstance(entry.get("path"), str)]


def save(projects: List[Dict[str, str]]) -> None:
    """Write through a temporary file; crashes don't leave half a registry."""
    path = registry_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", encoding="utf-8", newline="\n") as file:
        json.dump({"format": FORMAT, "projects": projects}, file, indent=2)
        file.write("\n")
    os.replace(temporary, path)


def remember(project: Path) -> None:
    """Add the project or update when it was last used; never raises."""
    try:
        projects = load()
        project = project.resolve()
        stamp = now()
        for entry in projects:
            if key(Path(entry["path"])) == key(project):
                entry["last_used"] = stamp
                break
        else:
            projects.append({"path": str(project), "added": stamp, "last_used": stamp})
        save(projects)
    except (OSError, RegistryError):
        pass


def forget(paths: List[str]) -> List[Dict[str, str]]:
    """Remove these projects; returns removed entries."""
    keys = {key(Path(path)) for path in paths}
    projects = load()
    removed = [entry for entry in projects if key(Path(entry["path"])) in keys]
    if removed:
        save([entry for entry in projects if key(Path(entry["path"])) not in keys])
    return removed


def project_name(project: Path) -> Optional[str]:
    """The name provided by the root CMakeList.txt's project() call."""
    try:
        text = (project / "CMakeLists.txt").read_text(encoding="utf-8")
    except OSError:
        return None

    match = re.search(r"\bproject\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)", text, re.IGNORECASE)
    return match.group(1) if match else None


def exists(project: Path) -> bool:
    return (project / "scripts" / "pk.py").is_file() and (project / "CMakePresets.json").is_file()
