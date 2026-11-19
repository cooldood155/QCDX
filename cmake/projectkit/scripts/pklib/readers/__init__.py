"""Readers: the only code in pk that knows what a tool prints.

pk's core knows steps (deps, configure, build, test, install), never tools:
problems.py has the error codes, the error's shape, 'pk fix' and 'pk
explain', steps.py runs a step quietly. What one tool prints is read by one
module here:

  cmake.py      CMake: configure, its errors (also when it re-runs in a build), install
  ninja.py      ninja, the build tool
  compilers.py  GCC, Clang, MSVC and their linkers, whatever the build tool
  ctest.py      ctest, the test step
  conan.py      Conan, the deps step

A module registers what it knows with three decorators:

  @reader(steps, tool="", order=50)  fn(text, context) -> Diagnosis or None
                                     the first reader (lowest order) that
                                     recognizes the output explains it
  @line_filter(tool)                 a LineFilter: what a quiet step prints
  @excerpt(tool)                     fn(text, context) -> the lines worth
                                     showing above the error
  documents(code, *urls)             the tool's own pages about a code, for
                                     'pk explain'

`tool` "" means any tool of that step (the compilers read every build).
Another tool (vcpkg, make, MSBuild, a test runner) is one more module, and a
project can add its own: every .py in <helpers>/pk/readers/ (the classic
tree: scripts/helpers/pk/readers/) is loaded after these, so it can add or
replace anything, e.g. explain an error of its own CMake code:

  from pklib.problems import fix_hint
  from pklib.readers import Diagnosis, reader

  @reader("configure", order=5)
  def no_assets(text, context):
      if "assets/ is missing" in text:
          return Diagnosis("PK500", "the assets were not downloaded", [fix_hint("./get-assets.sh")])
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import pkgutil
import re
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

Context = Dict[str, object]


class Diagnosis(NamedTuple):
    """What a reader found: a code of problems.CATALOG, the cause, fixes
    (problems.fix_run/fix_edit/fix_hint), the tool's lines to show (None: the
    tool's excerpt) and the tool's own documentation (URLs)."""
    code: str
    why: str = ""
    fixes: Sequence[Dict[str, object]] = ()
    details: Optional[Sequence[str]] = None
    docs: Sequence[str] = ()


Reader = Callable[[str, Context], Optional[Diagnosis]]

READERS: List[Tuple[int, int, str, str, Reader]] = []  # (order, registration, step, tool, reader)
FILTERS: Dict[str, type] = {}
EXCERPTS: Dict[str, Callable[[str, Context], List[str]]] = {}
DOCS: Dict[str, List[str]] = {}  # code -> a tool's own documents, for 'pk explain'

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_WARNING = re.compile(r": warning[: ]|\bwarning [A-Z]+\d+:|^CMake (?:Deprecation )?Warning")
_loaded: List[str] = []


def plain(text: str) -> str:
    """`text` without colors and links."""
    return _ANSI.sub("", text)


def reader(steps: "str | Sequence[str]", tool: str = "", order: int = 50) -> Callable[[Reader], Reader]:
    def register(function: Reader) -> Reader:
        for step in ([steps] if isinstance(steps, str) else steps):
            READERS.append((order, len(READERS), step, tool, function))
        READERS.sort(key=lambda item: (item[0], item[1]))
        return function
    return register


def documents(code: str, *urls: str) -> None:
    """A tool's own documents about an error code, which 'pk explain' lists
    after the kit's."""
    DOCS.setdefault(code, [])
    DOCS[code] += [url for url in urls if url not in DOCS[code]]


def line_filter(tool: str) -> Callable[[type], type]:
    def register(cls: type) -> type:
        FILTERS[tool] = cls
        return cls
    return register


def excerpt(tool: str) -> Callable[[Callable[[str, Context], List[str]]], Callable[[str, Context], List[str]]]:
    def register(function: Callable[[str, Context], List[str]]) -> Callable[[str, Context], List[str]]:
        EXCERPTS[tool] = function
        return function
    return register


class LineFilter:
    """What a quiet step prints. feed() takes each line (no colors, no
    newline) and returns (print it, what the step's status line says); this
    base prints everything, for tools no module knows."""

    warning = _WARNING

    def __init__(self) -> None:
        self.warnings = 0
        self.block = ""

    def feed(self, text: str) -> Tuple[bool, str]:
        if self.warning.search(text):
            self.warnings += 1
        return self.line(text)

    def line(self, text: str) -> Tuple[bool, str]:
        return True, ""


def load(extra: Sequence[str] = ()) -> None:
    """Imports every reader module here, once, then the .py files in the
    `extra` directories (a project's own readers)."""
    if "builtin" not in _loaded:
        _loaded.append("builtin")
        for module in sorted(info.name for info in pkgutil.iter_modules(__path__)):
            importlib.import_module(f"{__name__}.{module}")
    for directory in extra:
        if not directory or directory in _loaded or not os.path.isdir(directory):
            continue
        _loaded.append(directory)
        for name in sorted(os.listdir(directory)):
            if name.endswith(".py") and not name.startswith("_"):
                path = os.path.join(directory, name)
                spec = importlib.util.spec_from_file_location(f"pk_project_readers.{name[:-3]}", path)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)


def filter_for(tool: str) -> LineFilter:
    load()
    return FILTERS.get(tool, LineFilter)()


def read(step: str, tool: str, text: str, context: Context) -> Tuple[Optional[Diagnosis], List[str]]:
    """The first reader's diagnosis of a step's output (None when no reader
    knows it) and the tool's excerpt, for the details."""
    load()
    clean = plain(text)
    context = dict(context, step=step, tool=tool)
    lines = EXCERPTS[tool](clean, context) if tool in EXCERPTS else \
        [line for line in clean.splitlines() if line.strip()][-15:]
    context["excerpt"] = lines
    for _order, _index, wanted_step, wanted_tool, function in READERS:
        if wanted_step == step and wanted_tool in ("", tool):
            found = function(clean, context)
            if found is not None:
                return found, lines
    return None, lines
