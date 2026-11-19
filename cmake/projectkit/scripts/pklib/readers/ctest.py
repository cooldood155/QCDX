"""ctest, the test step: passing tests go to the status line, failing ones
are printed with their output, and the summary names them."""

from __future__ import annotations

import re
from typing import Optional, Tuple

from ..problems import fix_run
from . import Context, Diagnosis, LineFilter, line_filter, reader

RESULT = re.compile(r"^\s*\d+/\d+ Test\s+#\d+: (\S+) \.*\s*\**([^*].*?)\s+[\d.]+ sec")


@line_filter("ctest")
class CTestFilter(LineFilter):
    def line(self, text: str) -> Tuple[bool, str]:
        result = RESULT.match(text)
        if result:
            passed = result.group(2).strip() == "Passed"
            self.block = "" if passed else "failing"
            return not passed, text.strip()
        start = re.match(r"^\s*Start\s+\d+: (\S+)", text)
        if start:
            self.block = ""
            return False, f"running {start.group(1)}"
        if re.match(r"^\d+% tests passed", text) or text.startswith("The following tests"):
            self.block = "summary"
            return True, ""
        if text.startswith(("Test project ", "Total Test time", "Label Time Summary", "Errors while running")):
            self.block = "labels" if text.startswith("Label") else ""
            return False, ""
        if self.block == "labels":
            return False, ""
        return self.block in ("failing", "summary") and bool(text.strip()), ""


@reader("test", "ctest")
def failed_tests(text: str, context: Context) -> Optional[Diagnosis]:
    names = re.findall(r"^\s*\d+ - (\S+) \(([^)]*)\)", text.split("The following tests FAILED:")[-1],
                       re.MULTILINE) if "The following tests FAILED:" in text else []
    why = (f"{len(names)} failed: " + ", ".join(f"{name} ({how})" for name, how in names[:6])
           + (" ..." if len(names) > 6 else "")) if names else ""
    return Diagnosis("PK700", why, [fix_run(["pk", "test", "--", "--rerun-failed"], "run only the failed tests again",
                                            rerun=False)], [])
