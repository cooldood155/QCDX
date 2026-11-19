"""ninja, the build tool: its progress lines, which step failed, and its own
errors. What the compiler said in that step is compilers.py's."""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from ..problems import fix_run
from . import Context, Diagnosis, excerpt, line_filter, reader
from .cmake import CMakeFilter

STATUS = re.compile(r"^\[\d+/\d+\] ")


@line_filter("ninja")
class NinjaFilter(CMakeFilter):
    """Progress goes to the status line; what a step prints while it works
    (warnings) is printed; a failed step is printed with the problem. CMake's
    lines, when it re-runs to regenerate build.ninja, are read as CMake's."""

    def line(self, text: str) -> Tuple[bool, str]:
        if STATUS.match(text):
            self.block = "ok"
            return False, text
        if text.startswith("FAILED: "):
            self.block = "failed"
            return False, ""
        if text.startswith(("ninja: build stopped", "ninja: no work to do")):
            return False, ""
        if text.startswith(("CMake ", "-- ", "The following files were")) or self.block in ("warning", "error",
                                                                                            "glob"):
            return super().line(text)
        return self.block != "failed" and bool(text.strip()), ""


@excerpt("ninja")
def failed_step(text: str, context: Context, limit: int = 30) -> List[str]:
    """The output of the first failed step, without its (huge) command line
    unless verbose; its output file goes to context["target"]."""
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines) if line.startswith("FAILED: ")), -1)
    if start < 0:
        return [line for line in lines if line.strip() and not STATUS.match(line)][-limit:]
    target = re.match(r"FAILED: (?:\[code=\d+\] )?(\S+)", lines[start])
    context["target"] = target.group(1) if target else ""
    block = [lines[start]]
    skip_command = not context.get("verbose")
    for line in lines[start + 1:]:
        if STATUS.match(line) or line.startswith(("ninja: build stopped", "FAILED: ")):
            break
        if skip_command:  # the command line ninja prints after FAILED:
            skip_command = False
            continue
        block.append(line)
    if len(block) > limit:
        block = block[:limit] + [f"... ({len(block) - limit} more lines in the log)"]
    return block


@reader("build", "ninja", order=20)
def build_files(text: str, context: Context) -> Optional[Diagnosis]:
    if re.search(r"ninja: error: (?:loading 'build.ninja'|rebuilding 'build.ninja')", text):
        return Diagnosis("PK603", "ninja could not load or regenerate build.ninja", [
            fix_run(["pk", "configure", "--reset"], "configure the tree fresh")])
    return None
