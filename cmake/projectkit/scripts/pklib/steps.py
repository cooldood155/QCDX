"""How pk runs Conan, CMake, the build tool and ctest: quiet by default,
everything with --verbose.

Quiet: a step is one line ('==> configure native-debug: new tree  1.6s').
The tool's output goes to a log in build/pk-logs/ and only what needs
reading is printed: warnings when they happen, failing tests, and the error
when the step fails. On a terminal the step's line shows what the tool is
doing right now, and is rewritten with the time once it is done.

On GitHub Actions a failed step also prints its whole output, folded in a
group, since the log stays on the runner.

Verbose: the command line and every line the tool prints, live, with the
tools asked for their most detailed output (pk adds Conan -vvv, CMake
--log-level=TRACE, 'cmake --build -v', ctest -VV). The log is written either
way, so a failure is explained the same in both.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from typing import Dict, List, NamedTuple, Optional

from . import readers
from .common import C, flush, out, shown

LOG_DIR = "build/pk-logs"

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


class Result(NamedTuple):
    status: int
    text: str
    log: str
    warnings: int


class Runner:
    def __init__(self, root: str, verbose: bool, dry_run: bool) -> None:
        self.root = root
        self.verbose = verbose
        self.dry_run = dry_run
        self.live = bool(C.reset) and sys.stdout.isatty()

    def log_path(self, name: str) -> str:
        return f"{LOG_DIR}/{name}.log"

    def env(self, env: Optional[Dict[str, str]]) -> Dict[str, str]:
        result = dict(os.environ if env is None else env)
        result.setdefault("PYTHONUNBUFFERED", "1")  # Conan's lines as they happen
        if C.reset and "NO_COLOR" not in result:
            result.setdefault("CLICOLOR_FORCE", "1")  # keep colors through the pipe
        return result

    def run(self, argv: List[str], heading: str, tool: str, log: str, cwd: Optional[str] = None,
            env: Optional[Dict[str, str]] = None) -> Result:
        """Runs one step: `heading` is its line, `tool` picks what the quiet
        output prints (readers.filter_for; a tool no reader knows prints
        everything), `log` names the log file."""
        header = f"{C.green}==>{C.reset} {C.bold}{heading}{C.reset}"
        log_file = self.log_path(log)
        if self.verbose or self.dry_run:
            out(f"\n{header}")
            out(f"{C.yellow}+{C.reset} {shown(argv)}")
            if self.dry_run:
                return Result(0, "", "", 0)
        elif not self.live:
            out(header)

        full_log = os.path.join(self.root, *log_file.split("/"))
        os.makedirs(os.path.dirname(full_log), exist_ok=True)
        flush()
        started = time.monotonic()
        try:
            process = subprocess.Popen([shutil.which(argv[0]) or argv[0], *argv[1:]], cwd=cwd,
                                       env=self.env(env), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except OSError as error:
            text = f"{argv[0]}: {error.strerror or error}"
            with open(full_log, "w", encoding="utf-8") as file:
                file.write(f"$ {shown(argv)}\n{text}\n")
            if self.live and not self.verbose:
                out(header)
            return Result(127, text, log_file, 0)

        keep_filter = readers.filter_for(tool)
        pieces: List[str] = []
        last_draw = 0.0
        sink = getattr(sys.stdout, "buffer", None)
        try:
            with open(full_log, "w", encoding="utf-8", newline="\n") as file:
                file.write(f"$ {shown(argv)}\n")
                for raw in iter(process.stdout.readline, b""):  # type: ignore[union-attr]
                    line = raw.decode("utf-8", "replace")
                    pieces.append(line)
                    file.write(_ANSI.sub("", line))
                    if self.verbose:
                        if sink is not None:
                            sink.write(raw)
                            sink.flush()
                        else:
                            sys.stdout.write(line)
                        keep_filter.feed(_ANSI.sub("", line.rstrip("\r\n")))
                        continue
                    keep, activity = keep_filter.feed(_ANSI.sub("", line.rstrip("\r\n")))
                    if keep:
                        self.clear()
                        out(line.rstrip("\r\n"))
                        last_draw = 0.0
                    if self.live and (keep or (activity and time.monotonic() - last_draw > 0.08)):
                        self.draw(header, activity)
                        last_draw = time.monotonic()
            status = process.wait()
        except KeyboardInterrupt:
            self.clear()
            process.wait()
            raise
        seconds = time.monotonic() - started
        if not self.verbose:
            self.finish(header, status, seconds, keep_filter.warnings)
            if status and os.environ.get("GITHUB_ACTIONS") == "true":
                # the log stays on the runner: the whole output goes in a folded group
                out(f"::group::{heading}: the whole output ({log_file})")
                out(_ANSI.sub("", "".join(pieces)).rstrip("\n"))
                out("::endgroup::")
        return Result(status, "".join(pieces), log_file, keep_filter.warnings)

    def draw(self, header: str, activity: str) -> None:
        width = shutil.get_terminal_size((100, 20)).columns
        room = width - len(_ANSI.sub("", header)) - 4
        activity = activity.replace("\t", " ").strip()
        if len(activity) > room:
            activity = activity[:max(room - 3, 0)] + "..." if room > 3 else ""
        sys.stdout.write(f"\r\033[K{header}  {C.dim}{activity}{C.reset}")
        sys.stdout.flush()

    def clear(self) -> None:
        if self.live:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()

    def finish(self, header: str, status: int, seconds: float, warnings: int) -> None:
        notes = f"{seconds:.1f}s"
        if warnings:
            notes += f", {warnings} warning{'s' if warnings != 1 else ''}"
        mark = f"{C.red}failed{C.reset} " if status else ""
        if self.live:
            self.clear()
            out(f"{header}  {mark}{C.dim}{notes}{C.reset}")
        elif status:
            out(f"    {mark}{C.dim}{notes}{C.reset}")
