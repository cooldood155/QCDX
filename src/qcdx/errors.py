"""Errors of the global pk, in the same shape as a project's (the kit's
pklib/problems.py has the codes, the rendering and 'pk explain').

The global pk must not import a project's kit, so it loads the kit QCDX
itself ships, from real files like resources.kit_tree(). When even that
fails, errors are still printed, plainly.
"""

from __future__ import annotations

import sys
from typing import List, Sequence

from . import resources

_loaded = None


def kit_problems():  # -> module pklib.problems, or None
    global _loaded
    if _loaded is None:
        try:
            scripts = resources.cmake_dir() / "projectkit" / "scripts"
            if not (scripts / "pklib" / "problems.py").is_file():  # extracted by an older QCDX of this version
                resources.copy_tree(resources.kit_root() / "cmake" / "projectkit", scripts.parent)
            if str(scripts) not in sys.path:
                sys.path.insert(0, str(scripts))
            from pklib import common, problems  # type: ignore[import-not-found]

            common.setup_output()
            _loaded = problems
        except Exception:  # noqa: BLE001
            _loaded = False
    return _loaded or None


def report(code: str, message: str, why: str = "", fixes: Sequence[str] = (), details: Sequence[str] = ()) -> None:
    """Prints an error; `fixes` are what to do, one line each. Outside a
    project nothing is recorded, so there is no 'pk fix' here."""
    problems = kit_problems()
    if problems is None:
        for line in details:
            sys.stderr.write(f"{line}\n")
        sys.stderr.write(f"error[{code}]: {message}\n" + (f"   why  {why}\n" if why else ""))
        for index, hint in enumerate(fixes):
            sys.stderr.write(f"   {'fix' if index == 0 else ' or'}  {hint}\n")
        sys.stderr.write(f"  docs  pk explain {code}\n")
        return
    docs = [f"{problems.REPO_URL}/blob/v{resources.version()}/docs/RUNNING_PK.md"]
    problems.report(problems.Problem(code, message, why, [problems.fix_hint(hint) for hint in fixes], details,
                                     docs=docs))


def explain(argv: List[str]) -> int:
    problems = kit_problems()
    if problems is None:
        sys.stderr.write("pk explain: the kit's error catalog could not be loaded\n")
        return 1
    return problems.explain(argv, None)


def closest(word: str, choices: Sequence[str]) -> str:
    import difflib

    found = difflib.get_close_matches(word, list(choices), n=1, cutoff=0.6)
    return found[0] if found else ""
