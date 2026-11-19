"""pk: one CLI for every day-to-day projectkit workflow.

Conan and CMake are still what does the work, and nothing is hidden: each
step prints one line and keeps the tool's whole output in build/pk-logs/,
--verbose prints every command and every line live, and -n prints the
commands without running them (steps.py). When something fails, pk says why,
how to fix it and where to read more (problems.py); 'pk fix' applies the fix.

pk only decides *which* commands are needed:

  deps       re-run only when conanfile.py or a profile changed, or when the
             tests now need Catch2 and the last install skipped it
  configure  re-run only when the tree is new, the deps changed, or a flag
             asks for a value the tree does not yet have defined
  options    are remembered per build tree, like the CMake cache they live
             in, until changed again or reset with the --reset flag
"""

from __future__ import annotations

import datetime
import glob
import os
import re
import subprocess
import sys
import tempfile
import time
import zlib
from functools import lru_cache
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import problems, readers, targets
from . import tree as pktree
from .common import (BUILD_TYPES, SCRIPTS_DIR, C, capture, confirm, entry, err, exit_code, flush, has_file,
                     have, host_arch, host_platform, lines, load_conf, native_path, out, output, remove,
                     repo_root, run, script_env, setup_output, shown, walk_files)
from .problems import Problem, fix_hint, fix_run
from .steps import Result, Runner
from .verify_base import Verify

COMMANDS = (
    ("build and run", "configure", "c", "cfg conf", "install deps and (re)configure the build tree, no build"),
    ("build and run", "build", "b", "", "install deps, configure and build what is needed"),
    ("build and run", "rebuild", "", "", "delete the build tree, then build from scratch"),
    ("build and run", "run", "r", "", "build one app and run it, forwarding args after --"),
    ("build and run", "test", "t", "", "build with tests turned on, then run them with ctest"),
    ("dependencies", "deps", "", "", "install Conan deps for a build type (profiles/native)"),
    ("dependencies", "dep", "", "", "manage deps.json/conan.lock (add, rm, update, lock, ...)"),
    ("install and ship", "install", "i", "", "build, then install into stage/ (or --prefix), no checks"),
    ("install and ship", "stage", "", "", "fresh install into stage/, checked, with a report"),
    ("install and ship", "verify", "", "check", "full verification matrix (scripts/verify.py)"),
    ("install and ship", "package", "", "", "Conan packaging: create, upload, ... (scripts/package.py)"),
    ("install and ship", "release", "", "", "release archives how the CI makes them (scripts/release.py)"),
    ("code quality", "analyze", "", "", "build with clang-tidy and cppcheck (own tree)"),
    ("code quality", "sanitize", "", "", "build and test with sanitizers (own tree)"),
    ("code quality", "memcheck", "", "", "run the tests under Valgrind (own tree)"),
    ("code quality", "format", "fmt", "", "clang-format every C and C++ file (or --check)"),
    ("cleanup", "clean", "", "", "delete one build tree (--deps: its Conan output too)"),
    ("cleanup", "full-clean", "", "purge distclean", "delete everything generated, stage/ included"),
    ("inspect", "status", "st", "", "show build trees, their options and dependency state"),
    ("inspect", "list", "ls", "", "list build types, apps, cross targets and presets"),
    ("inspect", "doctor", "", "", "check tools and environment (--fix to repair)"),
    ("when something fails", "fix", "", "", "apply the last error's fix, then run the failed command again"),
    ("when something fails", "explain", "", "why", "explain an error code (the last error without one)"),
    ("project and shell", "sync", "", "upgrade", "update the kit (projectkit, scripts) from the QCDX template"),
    ("project and shell", "tree", "", "layout", "show, check, draw or change where each part of the project lives"),
    ("project and shell", "rename", "", "bootstrap", "rename a project made from the template"),
    ("project and shell", "help", "", "", "show help ('help <command>' for one command)"),
    ("project and shell", "shell-init", "", "", "print a 'pk' function + completion for bash or PowerShell"),
)
NAMES = [row[1] for row in COMMANDS]

CONFIG_FLAGS = ["tests", "apps", "lib", "werror", "lto", "sanitize", "coverage", "analyze", "option",
                "define", "reset"]
TREE_FLAGS = ["type", "cross", "variant", "update", "dry", "verbose"]
COMMAND_FLAGS = {
    "deps": ["type", "cross", "update", "dry", "verbose"],
    "configure": TREE_FLAGS + CONFIG_FLAGS,
    "build": TREE_FLAGS + CONFIG_FLAGS + ["jobs", "target"],
    "rebuild": TREE_FLAGS + CONFIG_FLAGS + ["jobs", "target"],
    "analyze": TREE_FLAGS + CONFIG_FLAGS + ["jobs", "target"],
    "run": TREE_FLAGS + CONFIG_FLAGS + ["jobs"],
    "test": TREE_FLAGS + CONFIG_FLAGS + ["jobs", "filter", "label"],
    "memcheck": TREE_FLAGS + CONFIG_FLAGS + ["jobs", "filter", "label"],
    "sanitize": TREE_FLAGS + CONFIG_FLAGS + ["jobs", "filter", "label"],
    "install": TREE_FLAGS + CONFIG_FLAGS + ["jobs", "prefix"],
    "stage": TREE_FLAGS + CONFIG_FLAGS + ["jobs", "consumer"],
    "clean": ["type", "cross", "variant", "all", "deps", "yes", "dry", "verbose"],
    "full-clean": ["keepdeps", "cache", "yes", "dry", "verbose"],
    "format": ["check", "dry", "verbose"],
    "doctor": ["fix"],
    "fix": ["yes", "dry"],
    "sync": ["from", "branch", "base", "nocommit", "dry"],
}
FLAG_SPELLING = {
    "type": "-t, --type=TYPE", "cross": "-x, --cross=NAME", "variant": "--variant=NAME",
    "update": "--update", "dry": "-n, --dry-run", "verbose": "-v, --verbose",
    "tests": "--tests, --no-tests", "apps": "--apps, --no-apps", "lib": "--lib=KIND",
    "werror": "--werror, --no-werror", "lto": "--lto, --no-lto",
    "sanitize": "--sanitize=LIST, --no-sanitize", "coverage": "--coverage, --no-coverage",
    "analyze": "--analyze, --no-analyze", "option": "-O, --option NAME=VALUE",
    "define": "-D NAME=VALUE", "reset": "--reset", "jobs": "-j, --jobs=N", "target": "--target=NAME",
    "filter": "-R, --filter=REGEX", "label": "-L, --label=REGEX", "prefix": "--prefix=DIR",
    "all": "--all", "deps": "--deps", "keepdeps": "--keep-deps", "check": "--check", "fix": "--fix",
    "consumer": "--no-consumer",
    "cache": "--cache", "yes": "-y, --yes", "from": "--from=URL|PATH", "branch": "--branch=NAME",
    "base": "--base=COMMIT", "nocommit": "--no-commit",
}
SWITCHES = {
    "--update": ("update", "update", True), "-n": ("dry", "dry_run", True),
    "--dry-run": ("dry", "dry_run", True), "-v": ("verbose", "verbose", True),
    "--verbose": ("verbose", "verbose", True), "--reset": ("reset", "reset", True),
    "--all": ("all", "clean_all", True), "--deps": ("deps", "clean_deps", True),
    "--keep-deps": ("keepdeps", "keep_deps", True),
    "--check": ("check", "check", True), "-y": ("yes", "assume_yes", True),
    "--yes": ("yes", "assume_yes", True), "--cache": ("cache", "clean_cache", True),
    "--no-consumer": ("consumer", "no_consumer", True), "--no-commit": ("nocommit", "no_commit", True),
    "--fix": ("fix", "fix", True), "--tests": ("tests", "tests", "ON"), "--no-tests": ("tests", "tests", "OFF"),
}
OPTION_SWITCHES = {
    "--apps": ("apps", "BUILD_APPS", "ON"), "--no-apps": ("apps", "BUILD_APPS", "OFF"),
    "--werror": ("werror", "WERROR", "ON"), "--no-werror": ("werror", "WERROR", "OFF"),
    "--lto": ("lto", "LTO", "ON"), "--no-lto": ("lto", "LTO", "OFF"),
    "--coverage": ("coverage", "COVERAGE", "ON"), "--no-coverage": ("coverage", "COVERAGE", "OFF"),
    "--analyze": ("analyze", "SA_ALL", "ON"), "--no-analyze": ("analyze", "SA_ALL", "OFF"),
    "--no-sanitize": ("sanitize", "SANITIZE", ""),
}
VALUE_FLAGS = {
    "-t": "type", "--type": "type", "-x": "cross", "--cross": "cross", "--variant": "variant",
    "--sanitize": "sanitize", "--lib": "lib", "-O": "option", "--option": "option", "-D": "define",
    "-j": "jobs", "--jobs": "jobs", "--target": "target", "-R": "filter", "--filter": "filter",
    "-L": "label", "--label": "label", "--prefix": "prefix", "--from": "from", "--branch": "branch",
    "--base": "base",
}
STATUS_OPTIONS = ("BUILD_TESTS", "BUILD_APPS", "LIBRARY_TYPE", "WERROR", "SANITIZE", "SA_ALL", "LTO",
                  "COVERAGE", "VALGRIND")
STAMP_NAME = "pk-deps.stamp"
SYNC_STATE = "scripts/helpers/pk/upstream.conf"  # in the classic tree; Pk.sync_state follows the tree
UPSTREAM_REF = "refs/projectkit/upstream"
PRESETS_SCRIPT = os.path.join(SCRIPTS_DIR, "helpers", "pk", "presets.cmake")
DEPS_SCRIPT = os.path.join(SCRIPTS_DIR, "helpers", "pk", "deps.py")


BASH_INIT = r"""# projectkit 'pk': runs the nearest project's pk.py from anywhere in a project.
# The scripts folder is scripts/, or wherever .pk/tree.conf puts it.
__pk_script() {
  local dir="$PWD" scripts
  while [ "$dir" != "/" ]; do
    scripts=scripts
    if [ -f "$dir/.pk/tree.conf" ]; then
      scripts="$(awk -F= 'tolower($1) ~ /^[ \t]*(pk_tree_)?scripts[ \t]*$/ { v = $2 }
        END { gsub(/["\r]/, "", v); gsub(/^[ \t]+|[ \t]+$/, "", v); print v }' "$dir/.pk/tree.conf")"
    fi
    if [ -n "$scripts" ] && [ -f "$dir/$scripts/pk.py" ]; then
      printf '%s\n' "$dir/$scripts/pk.py"
      return 0
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

pk() {
  local script
  if script="$(__pk_script)"; then
    PK_SELF_NAME=pk "${PK_PYTHON:-@PYTHON@}" "$script" "$@"
    return $?
  fi
  echo "pk: no project (scripts/pk.py) in $PWD or above" >&2
  return 2
}

_pk_complete() {
  local script
  script="$(__pk_script)" || return 0
  local cur="${COMP_WORDS[COMP_CWORD]}" command=""
  [ "$COMP_CWORD" -gt 1 ] && command="${COMP_WORDS[1]}"
  local IFS=$'\n'
  COMPREPLY=($(compgen -W "$("${PK_PYTHON:-@PYTHON@}" "$script" __words ":$command" ":$cur" 2>/dev/null | tr -d '\r')" -- "$cur"))
}
complete -o default -F _pk_complete pk"""

POWERSHELL_INIT = r"""# projectkit 'pk': runs the nearest project's pk.py from anywhere in a project.
# The scripts folder is scripts\, or wherever .pk\tree.conf puts it.
function __pk_script {
  $dir = (Get-Location).ProviderPath
  while ($dir) {
    $scripts = 'scripts'
    $conf = Join-Path $dir '.pk\tree.conf'
    if (Test-Path -LiteralPath $conf -PathType Leaf) {
      foreach ($line in Get-Content -LiteralPath $conf) {
        if ($line -match '^\s*(PK_TREE_)?scripts\s*=\s*(.*?)\s*$') { $scripts = $Matches[2].Trim('"') }
      }
    }
    $script = Join-Path $dir (Join-Path $scripts 'pk.py')
    if ($scripts -and (Test-Path -LiteralPath $script -PathType Leaf)) { return $script }
    $dir = Split-Path -Parent $dir
  }
  return $null
}

function pk {
  $script = __pk_script
  if ($script) {
    $python = $env:PK_PYTHON
    if (-not $python) { $python = '@PYTHON@' }
    $env:PK_SELF_NAME = 'pk'
    try { & $python $script @args } finally { Remove-Item Env:\PK_SELF_NAME -ErrorAction SilentlyContinue }
    return
  }
  Write-Error "pk: no project (scripts\pk.py) in $PWD or above"
}

Register-ArgumentCompleter -Native -CommandName pk -ScriptBlock {
  param($wordToComplete, $commandAst, $cursorPosition)
  $script = __pk_script
  if (-not $script) { return }
  $python = $env:PK_PYTHON
  if (-not $python) { $python = '@PYTHON@' }
  $words = @($commandAst.CommandElements | ForEach-Object { $_.ToString() })
  $index = $words.Count
  if ($wordToComplete) { $index = $words.Count - 1 }
  $command = ''
  if ($index -gt 1) { $command = $words[1] }
  & $python $script __words ":$command" ":$wordToComplete" 2>$null |
    Where-Object { $_ -like "$wordToComplete*" } |
    ForEach-Object { [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_) }
}"""


def die_tree(error: Exception, root: str) -> None:
    problems.report(Problem("PK201", "the project tree (.pk/tree.conf) is broken", str(error),
                            [fix_run(["pk", "tree", "reset"], "go back to the last tree that worked"),
                             fix_hint("pk tree check    (what exactly is wrong)")], status=2),
                    root, sys.argv[1:])
    raise SystemExit(2)


def parse_type(word: str) -> Optional[str]:
    return {"d": "Debug", "debug": "Debug", "r": "Release", "rel": "Release", "release": "Release",
            "rwd": "RelWithDebInfo", "relwithdebinfo": "RelWithDebInfo", "msr": "MinSizeRel",
            "minsizerel": "MinSizeRel"}.get(word.lower())


def normalize_value(value: Optional[str]) -> str:
    upper = (value or "").upper()
    if upper in ("ON", "TRUE", "YES", "Y", "1"):
        return "ON"
    if upper in ("OFF", "FALSE", "NO", "N", "0", ""):
        return "OFF"
    return value or ""


def resolve_command(word: str) -> Tuple[str, str]:
    if word in NAMES:
        return word, ""
    for _group, name, short, also, _summary in COMMANDS:
        if word and word in short.split() + also.split():
            return name, ""
    matches = [name for name in NAMES if name.startswith(word)]
    if len(matches) == 1:
        return matches[0], ""
    return "", ("ambiguous: " + " ".join(matches)) if matches else "unknown"


def cache_get(tree: str, key: str) -> Optional[str]:
    try:
        with open(os.path.join(tree, "CMakeCache.txt"), encoding="utf-8", errors="replace") as file:
            for line in file:
                match = re.match(rf"{re.escape(key)}:[A-Z_]*=(.*)", line.rstrip("\r\n"))
                if match:
                    return match.group(1)
    except OSError:
        return None
    return ""


def stamp_get(conan_dir: str, key: str) -> Optional[str]:
    try:
        with open(os.path.join(conan_dir, STAMP_NAME), encoding="utf-8") as file:
            for line in file:
                if line.startswith(f"{key}="):
                    return line.rstrip("\r\n")[len(key) + 1:]
    except OSError:
        return None
    return None


@lru_cache(maxsize=None)
def preset_query(query: str, preset: str = "") -> Tuple[str, ...]:
    code, text = capture(["cmake", f"-DPK_QUERY={query}", f"-DPK_PRESET={preset}",
                          "-DPK_PRESETS_FILE=CMakePresets.json", "-P", PRESETS_SCRIPT])
    return tuple(line[len("-- pk|"):] for line in text.splitlines() if line.startswith("-- pk|"))


class Pk:
    def __init__(self, root: str) -> None:
        self.root = root
        self.orig_pwd = os.getcwd()
        self.v = Verify(root)
        try:
            self.layout = pktree.load(root)
        except pktree.TreeError as error:
            die_tree(error, root)
        missing = self.layout.missing(root, required_only=True)
        if missing:
            die_tree(pktree.TreeError("it does not match the files:\n" + "\n".join(missing)), root)
        conf = load_conf(root, self.layout.rel("helpers", "pk/pk.conf"))
        self.self_name = os.environ.get("PK_SELF_NAME") or "./" + self.layout.rel("scripts", "pk.py")
        self.default_type = conf.get("PK_DEFAULT_TYPE", "Debug")
        self.default_jobs = conf.get("PK_DEFAULT_JOBS")
        self.stage_dir = conf.get("PK_STAGE_DIR", "stage")
        self.native_profile = conf.get("PK_NATIVE_PROFILE", "native")
        self.format_exclude = conf.get("PK_FORMAT_EXCLUDE",
                                       f"{self.layout.rel('kit')}/ build/ stage/ _install/").split()
        self.upstream_url = conf.get("PK_UPSTREAM_URL", "https://github.com/cooldood155/QCDX.git")
        self.verbose_default = conf.get("PK_VERBOSE", "0").lower() in ("1", "on", "yes", "true")
        self.upstream_branch = conf.get("PK_UPSTREAM_BRANCH", "main")
        # QCDX paths of the kit; sync_pairs maps each to where it is here.
        self.sync_paths = conf.get(
            "PK_SYNC_PATHS",
            ("cmake/projectkit scripts/pk.py scripts/verify.py scripts/package.py scripts/release.py "
             "scripts/bootstrap.py .github/actions/pk-setup")).split()
        self.sync_pairs = self.map_sync_paths(self.sync_paths)
        self.sync_state = self.layout.rel("helpers", "pk/upstream.conf")

        self.cmd = ""
        self.argv: List[str] = []
        self.type = ""
        self.cross = ""
        self.variant = ""
        self.dry_run = False
        self.verbose = False
        self.update = False
        self.reset = False
        self.jobs = self.default_jobs
        self.filter = ""
        self.label = ""
        self.prefix_dir = ""
        self.clean_all = False
        self.clean_deps = False
        self.keep_deps = False
        self.check = False
        self.fix = False
        self.assume_yes = False
        self.clean_cache = False
        self.no_consumer = False
        self.sync_from = ""
        self.sync_branch = ""
        self.sync_base = ""
        self.no_commit = False
        self.tests = ""
        self.config_defs: List[str] = []
        self.targets: List[str] = []
        self.positional: List[str] = []
        self.extra: List[str] = []

        self.type_lower = ""
        self.preset = ""
        self.tree = ""
        self.toolchain = ""
        self.conan_dir = ""
        self.platform_label = ""
        self.want_tests = "OFF"
        self.deps_changed = False
        self.report_lines: List[str] = []
        self._runner: Optional[Runner] = None

    @property
    def prefix(self) -> str:
        return self.v.prefix

    @property
    def project(self) -> str:
        return self.v.project

    @property
    def loud(self) -> bool:
        """Print every command pk runs (--verbose or --dry-run)."""
        return self.verbose or self.dry_run

    @property
    def runner(self) -> Runner:
        if self._runner is None:
            # the project's own readers (see pklib/readers/__init__.py) come after the kit's
            readers.load([self.layout.path(self.root, "helpers", "pk/readers")])
            self._runner = Runner(self.root, self.verbose, self.dry_run)
        return self._runner

    def step(self, message: str) -> None:
        gap = "\n" if self.loud else ""  # quiet steps are one line each, no blank line between
        out(f"{gap}{C.green}==>{C.reset} {C.bold}{message}{C.reset}")

    def info(self, message: str) -> None:
        out(f"{C.dim}  {message}{C.reset}")

    def warn(self, message: str) -> None:
        err(f"{C.yellow}warning:{C.reset} {message}")

    def die(self, message: str, code: str = "PK604", why: str = "", fixes: Sequence[Dict[str, object]] = (),
            details: Sequence[str] = (), log: str = "", status: int = 1, docs: Sequence[str] = ()) -> None:
        """Reports the error (see problems.py), records it for 'pk fix' and
        'pk explain', and exits with `status`."""
        problems.report(Problem(code, message, why, fixes, details, log, docs, status), self.root, self.argv,
                        self.self_name)
        raise SystemExit(status)

    def step_failed(self, step: str, tool: str, result: "Result", message: str, **context: object) -> None:
        """Explains a failed step from its output (the readers know the
        tool) and exits."""
        context.setdefault("profiles", [self.layout.rel("profiles", self.native_profile)]
                           + ([self.layout.rel("profiles", self.cross)] if self.cross else []))
        context.update(root=self.root, verbose=self.verbose)
        code, why, fixes, details, docs = problems.diagnose(step, tool, result.text, context)
        self.die(message, code, why, fixes, details, result.log, docs=docs)

    def build_tool(self, tree: str) -> str:
        """The tool 'cmake --build' runs in `tree`, from its generator."""
        generator = (cache_get(tree, "CMAKE_GENERATOR") or "").lower()
        for word, tool in (("ninja", "ninja"), ("makefiles", "make"), ("visual studio", "msbuild"),
                           ("xcode", "xcodebuild")):
            if word in generator:
                return tool
        return generator or "ninja"

    def usage_die(self, message: str, code: str = "PK106", fixes: Sequence[Dict[str, object]] = ()) -> None:
        topic = f"{self.self_name} help {self.cmd}" if self.cmd else f"{self.self_name} help"
        self.die(message, code, fixes=[*fixes, fix_hint(f"'{topic}' lists what {self.cmd or 'pk'} takes")],
                 status=2)

    def corrected(self, wrong: str, right: str) -> List[str]:
        """The command line that failed with `wrong` replaced by `right`, as a
        word, a --flag=VALUE value or a -xVALUE value."""
        def fixed(word: str) -> str:
            if word == wrong:
                return right
            if word.endswith("=" + wrong) or (len(word) == len(wrong) + 2 and word[0] == "-" and word.endswith(wrong)):
                return word[:len(word) - len(wrong)] + right
            return word
        return ["pk", *[fixed(word) for word in self.argv]]

    def show(self, argv: List[str]) -> None:
        out(f"{C.yellow}+{C.reset} {shown(argv)}")

    def run(self, argv: List[str], cwd: Optional[str] = None) -> int:
        self.show(argv)
        return 0 if self.dry_run else run(argv, cwd=cwd)

    def remove(self, path: str) -> None:
        if self.loud:
            self.show(["rm", "-rf", path])
        if not self.dry_run:
            remove(os.path.join(self.root, path))

    def install_hint(self, tool: str) -> str:
        system = host_platform()
        clang_tool = tool in ("clang-tidy", "clang-format")
        if system == "windows":
            prefix = os.environ.get("MINGW_PACKAGE_PREFIX") or "mingw-w64-ucrt-x86_64"
            return f"pacman -S {prefix}-clang-tools-extra" if clang_tool else f"pacman -S {prefix}-{tool}"
        if system == "macos":
            return "brew install llvm" if clang_tool else f"brew install {tool}"
        return f"sudo apt install {tool}   (or your distribution's package)"

    def install_fix(self, tool: str) -> Dict[str, object]:
        hint = self.install_hint(tool)
        if hint.startswith(("pacman ", "brew ")):  # no sudo, nothing to guess: pk fix may run it
            return fix_run(hint.split(), f"install {tool}")
        return fix_hint(hint)

    def require_tools(self, *tools: str) -> None:
        missing = [tool for tool in tools if not have(tool)]
        if not missing:
            return
        self.die(f"{self.cmd} needs {' and '.join(missing)}, which {'is' if len(missing) == 1 else 'are'} not on PATH",
                 "PK300", fixes=[self.install_fix(tool) for tool in missing])

    def package_tool(self, args: List[str], runner: Optional[Callable[[List[str]], int]] = None) -> int:
        from . import package

        try:
            return package.main(args, self.root, runner)
        except SystemExit as stop:
            return exit_code(stop)

    def deps_tool(self, args: List[str]) -> int:
        python = os.environ.get("PK_PYTHON") or sys.executable
        env = dict(os.environ, PK_CONAN=os.environ.get("PK_CONAN") or "conan",
                   PK_NATIVE_PROFILE=self.native_profile)
        return run([python, DEPS_SCRIPT, *args], env=env)

    def flag_meaning(self, flag: str) -> str:
        return {
            "type": "Debug (default), Release, RelWithDebInfo or MinSizeRel; a bare word works too: "
                    "'build release', 'test rwd'",
            "cross": f"cross-compile with {self.layout.rel('profiles')}/NAME and its presets, "
                     f"see '{self.self_name} list'",
            "variant": "use a separate tree build/<preset>-NAME that remembers its own options",
            "update": "re-run Conan even when the dependencies look current",
            "dry": "print every command without running anything",
            "verbose": "every command and all of its output, live, the tools at their most detailed",
            "tests": "build the test suite; off by default, 'test' turns it on",
            "apps": f"build the applications under {self.layout.rel('apps')}/",
            "lib": "library artifacts: static, shared, both or none",
            "werror": "treat compiler warnings as errors",
            "lto": "link-time optimization",
            "sanitize": "sanitizers, comma separated: address,undefined,thread,leak",
            "coverage": "instrument for coverage",
            "analyze": "run clang-tidy and cppcheck while compiling",
            "option": f"set project option {self.prefix}_NAME, e.g. -O VALGRIND=ON",
            "define": "pass any CMake cache variable through unchanged",
            "reset": "forget remembered options and reconfigure from scratch",
            "jobs": "parallel compile jobs (default: the build tool's own choice)",
            "target": "build only this CMake target; repeatable",
            "filter": "run only tests whose name matches REGEX",
            "label": "run only tests whose label matches REGEX",
            "prefix": f"install location, default {self.stage_dir}/",
            "all": f"same as '{self.self_name} full-clean'",
            "deps": "also delete the Conan output for this build type",
            "keepdeps": "keep the Conan output in build/, so nothing reinstalls",
            "check": "list files that need formatting, change nothing (exit 1 if any)",
            "fix": "create Conan's default profile when it is missing",
            "consumer": "skip building a consumer project against stage/",
            "cache": "also remove this package from the local Conan cache",
            "yes": "do not ask first",
            "from": "template to sync from: a URL (remembered) or a local clone (this sync only)",
            "branch": f"template branch, default {self.upstream_branch} (remembered)",
            "base": "template commit the kit currently matches, if pk guesses wrong",
            "nocommit": "stage the update for review instead of committing it",
        }.get(flag, "")

    def usage_line(self, command: str) -> str:
        if command in ("build", "rebuild", "install", "analyze"):
            return f"{command} [TYPE] [flag...] [-- build-tool args]"
        if command in ("test", "memcheck", "sanitize"):
            return f"{command} [TYPE] [flag...] [-- ctest args]"
        if command in ("verify", "package", "release", "rename"):
            return f"{command} [args...]   (everything is passed to the script)"
        return {
            "configure": "configure [TYPE] [flag...] [-- cmake args]",
            "deps": "deps [TYPE] [flag...] [-- conan args]",
            "run": "run [APP] [TYPE] [flag...] [-- app args]",
            "clean": "clean [TYPE] [flag...]",
            "stage": "stage [TYPE] [flag...]",
            "full-clean": "full-clean [--keep-deps] [--cache] [-y] [-n]",
            "sync": "sync [--from URL|PATH] [--branch NAME] [--base COMMIT] [--no-commit] [-n]",
            "format": "format [--check] [path...]",
            "help": "help [command]",
            "fix": "fix [--yes] [-n]",
            "explain": "explain [CODE]",
            "shell-init": "shell-init [bash|powershell]",
        }.get(command, command)

    def examples(self, command: str) -> List[str]:
        s, p = self.self_name, self.project
        table = {
            "build": [f"{s} build", f"{s} build release --werror", f"{s} build --lib=shared --target={p}",
                      f"{s} build -x x86_64-mingw-w64"],
            "run": [f"{s} run", f"{s} run {p} release -- --help"],
            "test": [f"{s} test", f"{s} test release -R core", f"{s} test -- --repeat until-fail:5"],
            "configure": [f"{s} configure --tests --werror",
                          f"{s} configure -O LTO=ON -D CMAKE_VERBOSE_MAKEFILE=ON", f"{s} configure --reset"],
            "deps": [f"{s} deps", f"{s} deps release --update"],
            "install": [f"{s} install release", f"{s} install --prefix=/tmp/{p}"],
            "clean": [f"{s} clean", f"{s} clean release --deps"],
            "sync": [f"{s} sync -n", f"{s} sync", f"{s} sync --from /path/to/QCDX"],
            "full-clean": [f"{s} full-clean -n", f"{s} full-clean", f"{s} full-clean --keep-deps",
                           f"{s} full-clean --cache --yes"],
            "stage": [f"{s} stage", f"{s} stage release --lib=shared",
                      f'grep "^check|" {self.stage_dir}/pk-stage.txt'],
            "analyze": [f"{s} analyze"],
            "memcheck": [f"{s} memcheck"],
            "sanitize": [f"{s} sanitize", f"{s} sanitize --sanitize=thread"],
            "format": [f"{s} format", f"{s} format --check"],
            "fix": [f"{s} fix", f"{s} fix -n", f"{s} fix --yes"],
            "explain": [f"{s} explain", f"{s} explain PK401", f"{s} explain --list"],
            "doctor": [f"{s} doctor", f"{s} doctor --fix"],
            "verify": [f"{s} verify list", f"{s} verify run --native --build_type=Debug"],
            "package": [f"{s} package create", f"{s} package help"],
            "release": [f"{s} release list", f"{s} release stage linux-x86_64", f"{s} release pack linux-x86_64"],
            "rename": [f"{s} rename myproject --dry-run"],
            "shell-init": [
                f'eval "$(python3 {native_path(self.root)}/{self.layout.rel("scripts", "pk.py")} shell-init)"'
                "    # once, in ~/.bashrc",
                f"python {self.root}\\{self.layout.rel('scripts', 'pk.py').replace('/', chr(92))} shell-init powershell"
                " | Out-String | Invoke-Expression"
                "    # once, in $PROFILE"],
        }
        return table.get(command, [])

    def notes(self, command: str) -> List[str]:
        table = {
            "run": ["APP defaults to the only app when there is one. Runs from the directory you",
                    "called pk from. Not available for cross builds."],
            "test": ["Turns tests on in the tree (remembered) and installs Catch2 if the last",
                     "dependency install skipped it. Not available for cross builds."],
            "analyze": ["Uses tree build/<preset>-analyze so your normal tree keeps compiling fast."],
            "memcheck": [f"Uses tree build/<preset>-memcheck with {self.prefix}_VALGRIND=ON and runs the",
                         "'valgrind' labelled tests. Linux only."],
            "sanitize": ["Uses tree build/<preset>-sanitize; default sanitizers: address,undefined."],
            "format": [f"Formats tracked and new (not ignored) files; skips {' '.join(self.format_exclude)}"],
            "clean": ["Without flags only the selected build tree goes; Conan output is kept so the",
                      "next build does not reinstall anything. For everything, use full-clean."],
            "sync": [f"Brings the template's kit changes into this project: {' '.join(p for _, p in self.sync_pairs)}.",
                     "Only the template's changes since the last sync are applied, as a 3-way",
                     "merge, so changes you made to the kit here are kept; where both sides",
                     "changed the same lines you get conflict markers to resolve. The result is",
                     f"one commit that touches only those paths plus {self.sync_state}, which",
                     "records the template URL, branch and commit for the next sync. The first",
                     "sync finds the template commit this kit matches by itself.",
                     "Needs: no staged changes, no uncommitted changes in those paths. Your",
                     "other uncommitted work is left alone."],
            "full-clean": [f"Removes every build tree and Conan output (build/), {self.stage_dir}/, _install/,",
                           "compile_commands.json, verify's scratch and consumer directories, the Conan",
                           "test_package build, clangd's index, other CMake build dirs (build-*,",
                           "cmake-build-*), Conan-written presets and sanitizer logs. Lists what exists",
                           "and asks first. Ignored files it does not own (.vscode/, docs/notes...) are",
                           "listed afterwards but never touched. --keep-deps keeps every Conan output",
                           "folder in build/ and the Conan-written presets, so the next build only",
                           "configures and compiles."],
            "stage": ["Like verify's install and consumer stages, for the tree you build with:",
                      f"{self.stage_dir}/ is emptied, the tree is installed into it, the package files",
                      "are checked, pkg-config reads the .pc, and a consumer project is built",
                      f"against {self.stage_dir}/ and run. Every result is written to",
                      f"{self.stage_dir}/pk-stage.txt, one 'kind|field|value' record per line:",
                      "  meta|type|Debug   file|lib/libx.a   check|<label>|pass   result|passed",
                      "Your build tree and its options are not touched."],
            "shell-init": ["Without an argument: powershell when started outside an MSYS2 shell on",
                           "Windows, bash everywhere else."],
            "fix": ["Every error pk reports is kept in build/pk-last-error.json with its fix. 'fix'",
                    "shows what it will do, asks, does it, then runs the command that failed again.",
                    "Errors only you can fix (a typo in your code) are shown again instead."],
            "explain": ["Every error has a code (error[PK401]). 'explain CODE' says what it means, the",
                        "usual causes and where to read more; 'explain --list' lists every code."],
        }
        return table.get(command, [])

    def print_examples(self, pairs: List[Tuple[str, str]]) -> None:
        width = max(len(command) for command, _ in pairs)
        width = width + 2 - width % 2
        for command, comment in pairs:
            out(f"  {command:<{width}}# {comment}")

    def help_overview(self) -> int:
        s = self.self_name
        out(f"{C.bold}pk{C.reset} - {self.project} project workflows without typing Conan or CMake\n")
        out(f"usage: {s} <command> [TYPE] [flag...] [-- passthrough]")
        last = ""
        for group, command, short, _also, summary in COMMANDS:
            if group != last:
                out(f"\n{C.bold}{group}{C.reset}")
                last = group
            out(f"  {command:<12}{short:<6}{summary}")
        out(f"\n{C.bold}build types{C.reset} (a bare word anywhere, or -t TYPE; default: {self.default_type})")
        out("  debug (d)  release (r)  relwithdebinfo (rwd)  minsizerel (msr)")
        out(f"\nAny unambiguous prefix also works: '{s} san' is sanitize.")
        out(f"\n{C.bold}examples{C.reset}")
        self.print_examples([
            (f"{s} build", "first run installs deps and configures"),
            (f"{s} run", "build and start the app"),
            (f"{s} test release", "Release build with tests, then ctest"),
            (f"{s} build --werror --lib=both", "options are remembered per build tree"),
            (f"{s} status", "what is configured and how"),
            (f"{s} help build", "every flag 'build' accepts"),
        ])
        out("\nEach step prints one line, its output goes to build/pk-logs/; -v (--verbose) shows every")
        out("command and all of its output, -n only prints the commands. When something fails,")
        out(f"'{s} fix' fixes it and '{s} explain' says more.")
        return 0

    def help_command(self, command: str) -> int:
        out(f"usage: {self.self_name} {self.usage_line(command)}\n")
        out(next((row[4] for row in COMMANDS if row[1] == command), ""))
        notes = self.notes(command)
        if notes:
            out("\n" + "\n".join(notes))
        flags = COMMAND_FLAGS.get(command, [])
        if flags:
            out(f"\n{C.bold}flags{C.reset}")
            for flag in flags:
                out(f"  {FLAG_SPELLING[flag]:<32} {self.flag_meaning(flag)}")
            out(f"  {'-h, --help':<32} this help")
        examples = self.examples(command)
        if examples:
            out(f"\n{C.bold}examples{C.reset}")
            for example in examples:
                out(f"  {example}")
        return 0

    def flag_ok(self, flag: str) -> bool:
        return flag in COMMAND_FLAGS.get(self.cmd, [])

    def flag_allowed(self, flag: str) -> None:
        if not self.flag_ok(flag):
            self.usage_die(f"'{self.cmd}' does not take {FLAG_SPELLING[flag]}", "PK103")

    def add_option(self, name: str, value: str) -> None:
        if not name.startswith(f"{self.prefix}_"):
            name = f"{self.prefix}_{name.upper()}"
        self.config_defs.append(f"{name}={value}")

    def parse_args(self, args: List[str]) -> None:
        index = 0
        while index < len(args):
            arg = args[index]
            index += 1
            if arg == "--":
                self.extra = args[index:]
                return
            if arg in ("-h", "--help"):
                self.help_command(self.cmd)
                raise SystemExit(0)

            if arg in SWITCHES:
                flag, attribute, value = SWITCHES[arg]
                self.flag_allowed(flag)
                setattr(self, attribute, value)
                continue
            if arg in OPTION_SWITCHES:
                flag, option, value = OPTION_SWITCHES[arg]
                self.flag_allowed(flag)
                self.add_option(option, value)
                continue

            key, sep, value = arg.partition("=") if arg.startswith("--") else (arg, "", "")
            if not sep and len(arg) > 2 and arg[:2] in ("-O", "-D", "-j"):
                key, sep, value = arg[:2], "=", arg[2:]
            flag = VALUE_FLAGS.get(key)
            if flag is None:
                if arg.startswith("-"):
                    self.unknown_flag(arg)
                build_type = parse_type(arg)
                if not self.type and self.flag_ok("type") and build_type:
                    self.type = build_type
                else:
                    self.positional.append(arg)
                continue

            self.flag_allowed(flag)
            if not sep:
                if index >= len(args):
                    self.usage_die(f"{arg} needs a value", "PK104",
                                   [fix_hint(f"{arg}=VALUE    ({FLAG_SPELLING[flag]})")])
                value = args[index]
                index += 1
            self.set_value_flag(flag, value)

    def unknown_flag(self, arg: str) -> None:
        name, sep, value = arg.partition("=")
        spelled = [part.split("=", 1)[0] for flag in COMMAND_FLAGS.get(self.cmd, [])
                   for part in FLAG_SPELLING[flag].replace(",", " ").split() if part.startswith("--")]
        right = problems.closest(name, spelled)
        fixes = [fix_run(self.corrected(arg, right + sep + value), f"{right}, not {name}", rerun=False)] \
            if right else []
        self.usage_die(f"unknown flag '{arg}'", "PK102", fixes)

    def bad_value(self, message: str, wrong: str, choices: Sequence[str]) -> None:
        right = problems.closest(wrong.lower(), choices)
        fixes = [fix_run(self.corrected(wrong, right), f"{right}, not {wrong}", rerun=False)] if right else []
        self.usage_die(message, "PK105", fixes)

    def set_value_flag(self, flag: str, value: str) -> None:
        if flag == "type":
            build_type = parse_type(value)
            if not build_type:
                self.bad_value(f"unknown build type '{value}': Debug, Release, RelWithDebInfo or MinSizeRel",
                               value, ["debug", "release", "relwithdebinfo", "minsizerel"])
            self.type = build_type or ""
        elif flag == "cross":
            self.cross = value
        elif flag == "variant":
            if not value or "/" in value or "\\" in value or " " in value:
                self.usage_die("variant names are one word without '/'", "PK105")
            self.variant = value
        elif flag == "sanitize":
            self.add_option("SANITIZE", value)
        elif flag == "lib":
            kinds = {"static": "STATIC", "shared": "SHARED", "both": "STATIC+SHARED",
                     "static+shared": "STATIC+SHARED", "none": "NONE"}
            if value.lower() not in kinds:
                self.bad_value(f"--lib takes static, shared, both or none, not '{value}'", value, list(kinds))
            self.add_option("LIBRARY_TYPE", kinds[value.lower()])
        elif flag in ("option", "define"):
            if "=" not in value:
                self.usage_die(f"{'-O' if flag == 'option' else '-D'} takes NAME=VALUE, got '{value}'", "PK105")
            if flag == "option":
                name, _, option_value = value.partition("=")
                self.add_option(name, option_value)
            else:
                self.config_defs.append(value)
        elif flag == "jobs":
            if not value.isdigit():
                self.usage_die(f"--jobs takes a number, not '{value}'", "PK105")
            self.jobs = value
        elif flag == "target":
            self.targets.append(value)
        else:
            setattr(self, {"filter": "filter", "label": "label", "prefix": "prefix_dir",
                           "from": "sync_from", "branch": "sync_branch", "base": "sync_base"}[flag], value)

    def preset_dirs(self, preset: str) -> Optional[Tuple[str, str]]:
        answer = preset_query("dirs", preset)
        if not answer or answer == ("missing",):
            return None
        binary = next((line[len("binary|"):] for line in answer if line.startswith("binary|")), "")
        toolchain = next((line[len("toolchain|"):] for line in answer if line.startswith("toolchain|")), "")
        return binary, toolchain

    def cross_names(self) -> List[str]:
        names = []
        for preset in preset_query("configure-presets"):
            if preset == "native-debug" or preset == "host-tools" or not preset.endswith("-debug"):
                continue
            name = preset[:-len("-debug")]
            if os.path.isfile(self.layout.path(self.root, "profiles", name)):
                names.append(name)
        return names

    def app_names(self) -> List[str]:
        if not self.layout.has("apps"):
            return []
        apps = self.layout.path(self.root, "apps")
        if not os.path.isdir(apps):
            return []
        return sorted(name for name in os.listdir(apps) if os.path.isdir(os.path.join(apps, name)))

    def select(self) -> None:
        if not have("cmake"):
            self.die("cmake is not on PATH", "PK300",
                     fixes=[fix_hint("python -m pip install cmake    (or: pipx install \"qcdx[tools]\")")])
        if not self.type:
            build_type = parse_type(self.default_type)
            if not build_type:
                self.die(f"PK_DEFAULT_TYPE='{self.default_type}' is not a build type", "PK202",
                         fixes=[fix_hint(f"set PK_DEFAULT_TYPE=Debug in {self.layout.rel('helpers', 'pk/pk.conf')}")])
            self.type = build_type or ""
        self.type_lower = self.type.lower()

        if self.cross:
            if self.cross.startswith("cross-"):
                self.cross = self.cross[len("cross-"):]
            if not os.path.isfile(self.layout.path(self.root, "profiles", self.cross)):
                names = self.cross_names()
                right = problems.closest(self.cross, names)
                fixes = [fix_run(self.corrected(self.cross, right), f"{right}, not {self.cross}", rerun=False)] \
                    if right else []
                self.die(f"no cross target '{self.cross}' (no {self.layout.rel('profiles', self.cross)})", "PK203",
                         f"cross targets here: {' '.join(names) or 'none'}", fixes, status=2)
            self.preset = f"{self.cross}-{self.type_lower}"
        else:
            self.preset = f"native-{self.type_lower}"

        dirs = self.preset_dirs(self.preset)
        if dirs is None:
            self.die(f"CMakePresets.json has no configure preset '{self.preset}'", "PK204")
            return
        self.tree, self.toolchain = dirs
        if self.variant:
            self.tree = f"{self.tree}-{self.variant}"
        if not self.toolchain:
            self.die(f"preset '{self.preset}' has no toolchainFile, pk needs Conan's", "PK204")
        self.conan_dir = os.path.dirname(os.path.dirname(self.toolchain))
        self.platform_label = f"cross {self.cross}" if self.cross else "native"

    def banner(self) -> None:
        tests_now = cache_get(self.tree, f"{self.prefix}_BUILD_TESTS")
        line = (f"{C.bold}{self.project}{C.reset}  {self.cmd}  {C.bold}{self.type}{C.reset}  "
                f"{self.platform_label}  tree {self.tree}")
        if tests_now:
            line += f"  (tests {normalize_value(tests_now)})"
        out(line)

    def deps_key(self, host_profile: str) -> str:
        checksum = 0
        for name in ("conanfile.py", "conanfile.txt", "deps.json", "conan.lock",
                     self.layout.rel("profiles", self.native_profile), host_profile):
            if name and os.path.isfile(name):
                with open(name, "rb") as file:
                    checksum = zlib.crc32(file.read(), checksum)
        return str(checksum)

    def deps_current(self, conan_dir: str, toolchain: str, host_profile: str,
                     want_tests: bool) -> Tuple[bool, str]:
        if not os.path.isfile(toolchain):
            return False, "not installed yet"
        key = stamp_get(conan_dir, "key")
        if key is None:
            return False, "installed outside pk, reinstalling once"
        if key != self.deps_key(host_profile):
            return False, "conanfile.py, deps.json, conan.lock or a profile changed"
        if want_tests and stamp_get(conan_dir, "tests") != "1":
            return False, "tests need Catch2, the last install skipped it"
        return True, "up to date"

    def ensure_deps(self, build_type: str, cross: str, conan_dir: str, toolchain: str,
                    want_tests: bool) -> None:
        host_profile = self.layout.rel("profiles", cross) if cross else ""
        label = f"cross {cross}" if cross else "native"
        want_tests = want_tests and not cross

        current, why = self.deps_current(conan_dir, toolchain, host_profile, want_tests)
        if current and not self.update:
            self.info(f"deps {build_type} ({label}): up to date")
            return
        if self.update:
            why = "--update given"
        heading = f"deps {build_type} ({label}): {why}"

        args = [f"--build_type={build_type}"]
        if os.path.isfile(self.layout.rel("profiles", self.native_profile)):
            args.append(f"--profile={self.native_profile}")
        if cross:
            args.append(f"--host-profile={cross}")
        skip = "False" if want_tests else "True"
        args += ["--", "-c", f"tools.build:skip_test={skip}", "-c", f"tools.graph:skip_test={skip}"]
        if self.verbose:
            args.append("-vvv")
        if self.cmd == "deps":
            args += self.extra

        results = []

        def conan(argv: List[str]) -> int:
            results.append(self.runner.run(argv, heading, "conan", f"{os.path.basename(self.tree)}.deps"))
            return results[-1].status

        if self.dry_run:
            self.package_tool(["install", "--dry-run", *args], conan)
            self.deps_changed = True
            return
        if self.package_tool(["install", *args], conan) != 0:
            message = f"conan install failed for {build_type} ({label})"
            if not results:
                self.die(message, "PK400")
            profiles = [self.layout.rel("profiles", self.native_profile)] + ([host_profile] if host_profile else [])
            self.step_failed("deps", "conan", results[-1], message, profiles=profiles)
        with open(os.path.join(conan_dir, STAMP_NAME), "w", newline="\n") as file:
            file.write(f"key={self.deps_key(host_profile)}\ntests={1 if want_tests else 0}\n")
        self.deps_changed = True

    def ensure_host_tools(self) -> None:
        tools = self.preset_dirs("host-tools")
        if tools is None:
            self.info("no host-tools preset, skipping host tools")
            return
        native = self.preset_dirs(f"native-{self.type_lower}")
        if native is None:
            self.die(f"no native-{self.type_lower} preset for host tools", "PK204")
            return
        tools_tree, native_toolchain = tools[0], native[1]

        saved = self.deps_changed
        self.deps_changed = False
        self.ensure_deps(self.type, "", os.path.dirname(os.path.dirname(native_toolchain)),
                         native_toolchain, False)
        native_changed = self.deps_changed
        self.deps_changed = saved

        if cache_get(tools_tree, "CMAKE_BUILD_TYPE") != self.type or native_changed:
            self.remove(tools_tree)
            self.cmake_step(["cmake", "--preset", "host-tools", f"-DCMAKE_BUILD_TYPE={self.type}",
                             f"-DCMAKE_TOOLCHAIN_FILE={native_path(os.path.join(self.root, native_toolchain))}"],
                            f"configure host tools {self.type}", "host-tools.configure", "host-tools configure failed")
        self.build_step(["cmake", "--build", tools_tree, *(["-v"] if self.verbose else [])],
                        f"build host tools {tools_tree}", "host-tools.build", "host-tools build failed", tools_tree)

    def cmake_step(self, args: List[str], heading: str, log: str, failed: str) -> None:
        """Runs a CMake configure, explaining a failure."""
        if self.verbose:
            args = [*args, "--log-level=TRACE"]
        result = self.runner.run(args, heading, "cmake", log)
        if result.status:
            self.step_failed("configure", "cmake", result, failed)

    def build_step(self, args: List[str], heading: str, log: str, failed: str, tree: str) -> None:
        """Runs a 'cmake --build', explaining a failure."""
        tool = self.build_tool(tree)
        result = self.runner.run(args, heading, tool, log)
        if result.status:
            self.step_failed("build", tool, result, failed)

    def decide_tests(self, needs: bool) -> None:
        cached = cache_get(self.tree, f"{self.prefix}_BUILD_TESTS")
        if self.tests:
            self.want_tests = self.tests
        elif needs:
            self.want_tests = "ON"
        elif cached:
            self.want_tests = normalize_value(cached)
        else:
            self.want_tests = "OFF"

        if self.cross and self.want_tests == "ON":
            if needs:
                self.die(f"'{self.cmd}' runs binaries, a cross build cannot", "PK301",
                         fixes=[fix_hint(f"{self.self_name} build -x {self.cross}    (builds, runs nothing)")],
                         status=2)
            self.warn("tests are built but not run for cross targets")

    def configure(self, force: bool) -> None:
        defs = [f"{self.prefix}_BUILD_TESTS={self.want_tests}", *self.config_defs]
        fresh = False
        reason = ""
        if not os.path.isfile(os.path.join(self.tree, "CMakeCache.txt")):
            reason = "new tree"
        elif not (os.path.isfile(os.path.join(self.tree, "build.ninja"))
                  or os.path.isfile(os.path.join(self.tree, "Makefile"))):
            reason = "last configure did not finish"
        elif self.cmd == "rebuild":
            reason = "rebuild"
        elif self.reset:
            reason, fresh = "--reset", True
        elif self.deps_changed:
            reason = "dependencies changed"
        elif force:
            reason = "requested"
        else:
            for definition in defs:
                key, _, value = definition.partition("=")
                key = key.split(":", 1)[0]
                cached = cache_get(self.tree, key) or ""
                if normalize_value(cached) != normalize_value(value):
                    reason = f"{key}: {cached or 'unset'} -> {value or 'empty'}"
                    break

        if not reason:
            self.info(f"configure {self.tree}: up to date")
            return
        variant = f" ({self.variant})" if self.variant else ""
        args = ["cmake", "--preset", self.preset]
        if self.variant:
            args += ["-B", self.tree]
        if fresh:
            args.append("--fresh")
        args += [f"-D{definition}" for definition in defs]
        if self.cmd == "configure":
            args += self.extra
        self.cmake_step(args, f"configure {self.preset}{variant}: {reason}", f"{os.path.basename(self.tree)}.configure",
                        f"configure failed for {self.preset}{variant}")

    def prepare(self, needs_tests: bool, force_configure: bool) -> None:
        self.select()
        self.decide_tests(needs_tests)
        self.banner()
        self.deps_changed = False
        if self.cross:
            self.ensure_host_tools()
        self.ensure_deps(self.type, self.cross, self.conan_dir, self.toolchain, self.want_tests == "ON")
        self.configure(force_configure)

    def build(self, *build_targets: str) -> None:
        args = ["cmake", "--build", self.tree]
        if self.jobs:
            args += ["-j", self.jobs]
        if self.verbose:
            args.append("-v")
        chosen = list(build_targets) or self.targets
        if chosen:
            args += ["--target", *chosen]
        if self.cmd in ("build", "rebuild", "install", "analyze") and self.extra:
            args += ["--", *self.extra]
        what = f" ({' '.join(chosen)})" if chosen else ""
        self.build_step(args, f"build {self.tree}{what}", f"{os.path.basename(self.tree)}.build",
                        f"build failed in {self.tree}", self.tree)

    def ctest(self) -> int:
        args = ["ctest", "--test-dir", self.tree, "--output-on-failure"]
        if self.jobs:
            args += ["-j", self.jobs]
        if self.filter:
            args += ["-R", self.filter]
        if self.label:
            args += ["-L", self.label]
        if self.verbose:
            args.append("-VV")
        args += self.extra
        result = self.runner.run(args, f"test {self.tree}", "ctest", f"{os.path.basename(self.tree)}.test")
        if result.status:
            code, why, fixes, details, docs = problems.diagnose("test", "ctest", result.text, {"root": self.root})
            problems.report(Problem(code, "tests failed", why, fixes, details, result.log, docs), self.root,
                            self.argv, self.self_name)
        return result.status

    def no_positionals(self) -> None:
        if self.positional:
            word = self.positional[0]
            right = problems.closest(word.lower(), ["debug", "release", "relwithdebinfo", "minsizerel"]) \
                if self.flag_ok("type") else ""
            fixes = [fix_run(self.corrected(word, right), f"the build type {right}", rerun=False)] if right else []
            self.usage_die(f"unexpected argument '{word}'", "PK106",
                           [*fixes, fix_hint(f"{self.self_name} {self.cmd} -- {' '.join(self.positional)}    "
                                             "(when it is meant for the tool pk runs)")])

    def cmd_deps(self) -> int:
        self.no_positionals()
        self.select()
        self.banner()
        self.deps_changed = False
        want = normalize_value(cache_get(self.tree, f"{self.prefix}_BUILD_TESTS")) == "ON"
        if self.cross:
            self.ensure_host_tools()
        self.ensure_deps(self.type, self.cross, self.conan_dir, self.toolchain, want)
        return 0

    def cmd_configure(self) -> int:
        self.no_positionals()
        self.prepare(False, True)
        return 0

    def cmd_build(self) -> int:
        self.no_positionals()
        self.prepare(False, False)
        self.build()
        return 0

    def cmd_rebuild(self) -> int:
        self.no_positionals()
        self.select()
        self.step(f"remove {self.tree}")
        self.remove(self.tree)
        self.prepare(False, False)
        self.build()
        return 0

    def cmd_test(self) -> int:
        self.no_positionals()
        if not self.layout.has("tests"):
            self.die("this project's tree leaves the tests out", "PK205",
                     fixes=[fix_hint(f"{self.self_name} tree    (shows the tree; 'tree apply' changes it)")])
        self.prepare(True, False)
        self.build()
        return self.ctest()

    def cmd_install(self) -> int:
        self.no_positionals()
        self.prepare(False, False)
        self.build()
        prefix = self.prefix_dir or self.stage_dir
        result = self.runner.run(["cmake", "--install", self.tree, "--prefix", native_path(prefix),
                                  *(["-v"] if self.verbose else [])],
                                 f"install into {prefix}", "cmake-install", f"{os.path.basename(self.tree)}.install")
        if result.status:
            self.step_failed("install", "cmake-install", result, f"install into {prefix} failed")
        return 0

    def cmd_run(self) -> int:
        if len(self.positional) > 1:
            self.usage_die(f"run takes one APP, got: {' '.join(self.positional)}", "PK106",
                           [fix_hint(f"{self.self_name} run {self.positional[0]} -- {' '.join(self.positional[1:])}"
                                     "    (app arguments go after --)")])
        app = self.positional[0] if self.positional else ""
        if not app:
            apps = self.app_names()
            if len(apps) == 1:
                app = apps[0]
            elif not apps:
                self.die(f"no {self.layout.rel('apps')}/ directories found", "PK701",
                         fixes=[fix_hint(f"{self.self_name} run NAME    (name the executable)")], status=2)
            else:
                self.usage_die(f"several apps: {' '.join(apps)}", "PK107",
                               [fix_hint(f"{self.self_name} run {app_name}") for app_name in apps[:3]])
        if self.cross:
            self.die("cannot run a cross-compiled binary on this machine", "PK301", status=2)
        self.prepare(False, False)

        target = f"{app}_app"
        if not self.dry_run:
            query = ["ninja", "-C", self.tree, "-t", "query"]
            if capture(query + [target])[0] != 0:
                target = app if capture(query + [app])[0] == 0 else ""
        if target:
            self.build(target)
        else:
            self.build()

        exe = f"{self.tree}/bin/{app}{self.v.exe_suffix}"
        if not self.dry_run and not os.path.isfile(exe):
            bin_dir = os.path.join(self.tree, "bin")
            found = sorted(n for n in os.listdir(bin_dir) if os.path.isfile(os.path.join(bin_dir, n))) \
                if os.path.isdir(bin_dir) else []
            right = problems.closest(app, [os.path.splitext(name)[0] for name in found])
            self.die(f"no {exe}", "PK701", f"executables in {self.tree}/bin: {' '.join(found) or 'none'}",
                     [fix_run(self.corrected(app, right), f"{right}, not {app}", rerun=False)] if right else [])

        generators = os.path.join(self.conan_dir, "generators")
        names = ("conanrun.bat", "conanrun.sh") if os.name == "nt" else ("conanrun.sh",)
        run_script = next((os.path.join(generators, n) for n in names
                           if os.path.isfile(os.path.join(generators, n))), "")

        self.step(f"run {app}")
        exe_path = os.path.normpath(os.path.join(self.root, exe))
        command = [exe_path, *self.extra]
        env = None
        if run_script:
            if self.loud:
                self.info(f"with the Conan run environment {run_script.replace(os.sep, '/')}")
            if not self.dry_run:
                env = script_env(run_script)
                if env is None:
                    self.warn(f"could not read {run_script}, running without it")
        if self.loud:
            self.show(command)
        if self.dry_run:
            return 0
        return run(command, cwd=self.orig_pwd, env=env)

    def variant_command(self, default_variant: str, needs_tests: bool) -> None:
        self.variant = self.variant or default_variant
        self.no_positionals()
        self.prepare(needs_tests, False)

    def cmd_analyze(self) -> int:
        self.require_tools("clang-tidy", "cppcheck")
        self.add_option("SA_ALL", "ON")
        self.variant_command("analyze", False)
        self.build()
        return 0

    def cmd_memcheck(self) -> int:
        if host_platform() != "linux":
            self.die("memcheck needs Valgrind, which pk only supports on Linux", "PK301",
                     fixes=[fix_hint(f"{self.self_name} sanitize    (address and undefined behaviour checks)")],
                     status=2)
        self.require_tools("valgrind")
        self.add_option("VALGRIND", "ON")
        self.label = self.label or "valgrind"
        self.variant_command("memcheck", True)
        self.build()
        return self.ctest()

    def cmd_sanitize(self) -> int:
        if not any(d.partition("=")[0] == f"{self.prefix}_SANITIZE" for d in self.config_defs):
            self.add_option("SANITIZE", "address,undefined")
        self.variant_command("sanitize", True)
        self.build()
        return self.ctest()

    def cmd_clean(self) -> int:
        self.no_positionals()
        if self.clean_all:
            return self.cmd_full_clean()
        self.select()
        self.step(f"remove {self.tree}")
        self.remove(self.tree)
        if self.clean_deps:
            self.step(f"remove Conan output {self.conan_dir}")
            self.remove(self.conan_dir)
        return 0

    def relative(self, path: str) -> str:
        if path.startswith(self.root + os.sep):
            return path[len(self.root) + 1:].replace(os.sep, "/")
        return path

    def conan_outputs(self) -> List[str]:
        """Every folder right under build/ that Conan has installed into (has
        Conan's toolchain), for full-clean --keep-deps."""
        build = os.path.join(self.root, "build")
        if not os.path.isdir(build):
            return []
        return sorted(os.path.join(build, name) for name in os.listdir(build)
                      if os.path.isfile(os.path.join(build, name, "generators", "conan_toolchain.cmake")))

    def full_clean_paths(self) -> List[str]:
        root = self.root
        candidates = self.v.clean_paths() + [
            os.path.join(root, self.stage_dir),
            self.layout.path(root, "kit", "test_package", "build"),
            os.path.join(root, ".cache", "clangd"),
            os.path.join(root, "CMakeUserPresets.json"),
            os.path.join(root, "ConanPresets.json"),
            os.path.join(root, ".ninja_deps"),
            os.path.join(root, ".ninja_log"),
        ]
        if self.keep_deps:
            # build/ goes folder by folder, Conan's own and the presets it wrote stay
            build = os.path.normpath(os.path.join(root, "build"))
            kept = [os.path.normpath(path) for path in self.conan_outputs()]
            kept += [os.path.normpath(os.path.join(root, name)) for name in ("CMakeUserPresets.json",
                                                                            "ConanPresets.json")]
            candidates = [path for path in candidates
                          if os.path.normpath(path) != build and os.path.normpath(path) not in kept]
            if os.path.isdir(build):
                candidates += sorted(os.path.join(build, name) for name in os.listdir(build)
                                     if os.path.join(build, name) not in kept)
        for pattern in ("build-*", "cmake-build-*", "asan.log.*", "ubsan.log.*"):
            candidates += sorted(glob.glob(os.path.join(root, pattern)))
        seen: List[str] = []
        for path in candidates:
            path = os.path.normpath(path)
            if (os.path.lexists(path)) and path not in seen:
                seen.append(path)
        return seen

    def disk_size(self, path: str) -> str:
        total = 0
        if os.path.isdir(path) and not os.path.islink(path):
            for file in walk_files(path):
                try:
                    total += os.lstat(file).st_size
                except OSError:
                    pass
        else:
            try:
                total = os.lstat(path).st_size
            except OSError:
                return "-"
        size = float(total)
        for unit in ("B", "K", "M", "G"):
            if size < 1024:
                return f"{int(size)}{unit}" if unit == "B" else f"{size:.1f}{unit}"
            size /= 1024
        return f"{size:.1f}T"

    def cmd_full_clean(self) -> int:
        self.no_positionals()
        paths = self.full_clean_paths()
        self.step(f"full clean of {self.project}")
        if not paths and not self.clean_cache:
            self.info("nothing generated is present")
        else:
            for path in paths:
                out(f"  {self.disk_size(path):<8} {self.relative(path)}")
            if self.clean_cache:
                out(f"  {'cache':<8} this package in the local Conan cache")

            if self.dry_run:
                self.info("dry run: nothing deleted")
            elif self.assume_yes or self.ask("delete the above?"):
                for path in paths:
                    if self.loud:
                        self.show(["rm", "-rf", path])
                    remove(path)
                try:
                    os.rmdir(os.path.join(self.root, ".cache"))
                except OSError:
                    pass
                if self.clean_cache and self.package_tool(["remove", "--yes"]) != 0:
                    self.warn("removing the Conan cache entry failed")
                self.info("removed")
            else:
                self.info("nothing deleted")
                return 1

        owned = [self.relative(path) for path in paths]
        leftovers = []
        for line in lines(["git", "clean", "-ndX"]):
            entry = line[len("Would remove "):] if line.startswith("Would remove ") else line
            bare = entry.rstrip("/")
            covered = any(bare == o or bare.startswith(o + "/") or o.startswith(bare + "/") for o in owned)
            if not covered:
                leftovers.append(entry)
        if leftovers:
            out(f"\n{C.bold}ignored by git but not generated by the build, left alone:{C.reset}")
            for entry in leftovers:
                out(f"  {entry}")
        return 0

    def ask(self, prompt: str) -> bool:
        if not sys.stdin.isatty():
            self.die("not asking on a non-interactive input", "PK302",
                     fixes=[fix_hint(f"{self.self_name} {self.cmd} --yes    (when deleting is really wanted)")],
                     status=2)
        return confirm(prompt, ("y", "yes"))

    def report(self, *fields: str) -> None:
        cleaned = [field.replace("|", "/").replace("\n", " ") for field in fields]
        self.report_lines.append("|".join(cleaned))

    def stage_dir_is_safe(self) -> bool:
        stage = self.stage_dir
        return not (stage in ("", ".", "./") or os.path.isabs(stage) or stage.startswith("..")
                    or "/.." in stage.replace("\\", "/"))

    def cmd_stage(self) -> int:
        self.no_positionals()
        if not self.stage_dir_is_safe():
            self.die(f"PK_STAGE_DIR='{self.stage_dir}' must be a directory inside the project", "PK202",
                     fixes=[fix_hint(f"set PK_STAGE_DIR=stage in {self.layout.rel('helpers', 'pk/pk.conf')}")])
        self.prepare(False, False)
        self.build()

        stage = self.stage_dir
        stage_abs = os.path.join(self.root, stage)
        install = ["cmake", "--install", self.tree, "--prefix", native_path(stage_abs)]
        if self.dry_run:
            self.step(f"stage into {stage}")
            self.remove(stage)
            self.run(install)
            self.info(f"then: package file checks, pkg-config, consumer project, {stage}/pk-stage.txt")
            return 0

        v = self.v
        v.on_result = lambda status, label: self.report("check", label, status)
        v.build_type = self.type
        v.pass_count = v.skip_count = 0
        v.failures = []

        for field, value in (
                ("project", self.project), ("version", cache_get(self.tree, "CMAKE_PROJECT_VERSION") or ""),
                ("type", self.type), ("platform", self.platform_label), ("preset", self.preset),
                ("tree", self.tree), ("git", output(["git", "describe", "--always", "--dirty"]) or "-"),
                ("date", datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))):
            self.report("meta", field, value)

        v.stage(f"Install into {stage}")
        remove(stage_abs)
        self.show(install)
        installed = v.attempt(f"install {self.tree}", install)
        if installed:
            for path in sorted(os.path.relpath(p, stage_abs).replace(os.sep, "/") for p in walk_files(stage_abs)):
                out(f"  {path}")
                self.report("file", path)

        v.stage("Package files")
        library_type = cache_get(self.tree, f"{self.prefix}_LIBRARY_TYPE")
        install_rules = cache_get(self.tree, f"{self.prefix}_INSTALL")
        if not installed:
            v.skip("package files (install failed)")
        elif library_type == "NONE" or normalize_value(install_rules) == "OFF":
            v.skip(f"package files ({self.prefix}_LIBRARY_TYPE=NONE or {self.prefix}_INSTALL=OFF)")
        else:
            for expected in v.expected_install_files():
                if os.path.isfile(os.path.join(stage_abs, *expected.split("/"))):
                    v.ok(f"installed {expected}")
                else:
                    v.fail(f"missing {expected}")
            pc_dir = os.path.join(stage_abs, "lib", "pkgconfig")
            if not os.path.isfile(os.path.join(pc_dir, f"{v.package}.pc")):
                v.skip(f"pkg-config (no {v.package}.pc)")
            elif have("pkg-config"):
                env = dict(os.environ, PKG_CONFIG_PATH=native_path(pc_dir))
                v.attempt(f"pkg-config reads {v.package}.pc",
                          lambda: run(["pkg-config", "--cflags", "--libs", v.package], env=env) == 0)
            else:
                v.skip("pkg-config not installed")

        if self.no_consumer or self.cross or stage != "stage":
            v.stage("Consumer project")
            if self.no_consumer:
                v.skip("consumer (--no-consumer)")
            elif self.cross:
                v.skip("consumer (a cross build cannot run here)")
            else:
                v.skip(f"consumer (verify's consumer reads stage/, PK_STAGE_DIR is {stage})")
        elif installed:
            v.stage_consumer()

        failed = sum(1 for line in self.report_lines if line.startswith("check|") and line.endswith("|fail"))
        self.report("result", "passed" if failed == 0 else "failed")

        report_path = os.path.join(stage_abs, "pk-stage.txt")
        if os.path.isdir(stage_abs):
            with open(report_path, "w", encoding="utf-8", newline="\n") as file:
                file.write('# pk stage report: one "kind|field|value" record per line\n'
                           "# kinds: meta (about the build), file (installed, relative to this\n"
                           "# directory), check (label|pass, fail or skip), result (passed/failed)\n")
                file.write("".join(f"{line}\n" for line in self.report_lines))

        out(f"\n{C.bold}---- stage {self.type} ----{C.reset}")
        out(f"passed: {v.pass_count}  skipped: {v.skip_count}  failed: {failed}")
        if os.path.isfile(report_path):
            out(f"report: {stage}/pk-stage.txt")
        return 0 if failed == 0 else 1

    def map_sync_paths(self, paths: List[str]) -> List[Tuple[str, str]]:
        """(QCDX path, path here) for each synced path. QCDX has the classic
        tree; a kit part this project left out (pk-setup without CI) is skipped."""
        known = dict(pktree.sync_map(self.layout))
        pairs = []
        for path in paths:
            path = path.strip("/")
            if path == pktree.PK_SETUP and path not in known:
                continue
            for up, here in sorted(known.items(), key=lambda pair: -len(pair[0])):
                if path == up or path.startswith(up + "/"):
                    pairs.append((path, here + path[len(up):]))
                    break
            else:
                pairs.append((path, path))
        return pairs

    def state_get(self, key: str) -> str:
        try:
            with open(self.sync_state, encoding="utf-8") as file:
                for line in file:
                    if line.startswith(f"{key}="):
                        return line.rstrip("\r\n")[len(key) + 1:]
        except OSError:
            pass
        return ""

    def state_write(self, url: str, branch: str, commit: str) -> None:
        os.makedirs(os.path.dirname(self.sync_state), exist_ok=True)
        with open(self.sync_state, "w", encoding="utf-8", newline="\n") as file:
            file.write('# Written by "pk sync": the template cmake/projectkit comes from and\n'
                       "# the template commit it was last synced to. Keep it committed.\n"
                       f"url={url}\nbranch={branch}\ncommit={commit}\n")

    @staticmethod
    def normalize_url(url: str) -> str:
        url = re.sub(r"^[a-z+]*://", "", url, count=1)
        url = re.sub(r"^[^@/]*@", "", url, count=1)
        url = url.replace(":", "/", 1)
        url = re.sub(r"\.git$", "", url)
        return url.rstrip("/").lower()

    def remembered_url(self, url: str, state_url: str) -> str:
        if "://" in url or re.search(r"@.*:", url):
            return url
        return state_url or self.upstream_url

    def git_ok(self, *args: str) -> bool:
        return capture(["git", *args])[0] == 0

    def detect_base(self, tip: str) -> Optional[Tuple[str, int]]:
        best: Optional[Tuple[str, int]] = None
        upstream = [up for up, _ in self.sync_pairs]
        for commit in lines(["git", "rev-list", "--max-count=500", tip, "--", *upstream]):
            changed = self.kit_difference(commit)
            if best is None or changed < best[1]:
                best = (commit, changed)
            if changed == 0:
                break
        return best

    def kit_difference(self, commit: str) -> int:
        """Lines that differ between the kit of a QCDX commit and the kit here
        (HEAD), path by path, so a kit that lives elsewhere still compares."""
        changed = 0
        for up, here in self.sync_pairs:
            left, right = f"{commit}:{up}", f"HEAD:{here}"
            left_ok, right_ok = self.git_ok("cat-file", "-e", left), self.git_ok("cat-file", "-e", right)
            if not left_ok or not right_ok:
                changed += 0 if left_ok == right_ok else 100000  # only on one side: never a match
                continue
            for row in lines(["git", "diff", "--numstat", left, right]):
                fields = row.split("\t")
                if len(fields) >= 2 and fields[0] != "-":
                    changed += int(fields[0]) + int(fields[1])
        return changed

    def differing_kit_files(self, commit: str) -> List[str]:
        found = []
        for up, here in self.sync_pairs:
            folder = output(["git", "cat-file", "-t", f"HEAD:{here}"]) == "tree"
            for name in lines(["git", "diff", "--name-only", f"{commit}:{up}", f"HEAD:{here}"]):
                found.append(f"{here}/{name}" if folder and name else here)
        return sorted(set(found))

    def map_patch(self, patch: str) -> None:
        """Rewrite the QCDX paths in a 'git diff' to where the kit lives here."""
        def mapped(path: str) -> str:
            for up, here in sorted(self.sync_pairs, key=lambda pair: -len(pair[0])):
                if path == up or path.startswith(up + "/"):
                    return here + path[len(up):]
            return path

        header = re.compile(rb"^(diff --git a/)(\S+)( b/)(\S+)$|^(--- a/|\+\+\+ b/)(\S+)$|"
                            rb"^(rename from |rename to |copy from |copy to )(\S+)$")
        with open(patch, "rb") as file:
            text = file.read().split(b"\n")
        result = []
        for line in text:
            match = header.match(line)
            if match is None:
                result.append(line)
            elif match.group(1):
                result.append(match.group(1) + mapped(match.group(2).decode()).encode() + match.group(3)
                              + mapped(match.group(4).decode()).encode())
            elif match.group(5):
                result.append(match.group(5) + mapped(match.group(6).decode()).encode())
            else:
                result.append(match.group(7) + mapped(match.group(8).decode()).encode())
        with open(patch, "wb") as file:
            file.write(b"\n".join(result))

    def short_log(self, commit: str) -> str:
        return output(["git", "log", "-1", "--format=%h %s", commit])

    def sync_run(self, patch: str) -> int:
        paths = [up for up, _ in self.sync_pairs]
        here = [local for _, local in self.sync_pairs]
        if not self.git_ok("rev-parse", "--verify", "-q", "HEAD"):
            self.die("sync needs at least one commit in this repository", "PK800",
                     fixes=[fix_hint('git add -A && git commit -m "First commit"')])
        if self.git_ok("rev-parse", "--verify", "-q", "MERGE_HEAD"):
            self.die("a merge is in progress", "PK800",
                     fixes=[fix_hint("finish it (git commit) or drop it (git merge --abort)")])
        if not self.git_ok("diff", "--cached", "--quiet"):
            self.die("you have staged changes", "PK800", "the sync commit must hold only the kit",
                     [fix_hint("commit them, or unstage them: git restore --staged .")])
        dirty = lines(["git", "status", "--porcelain", "--", *here, self.sync_state])
        if dirty:
            self.die("uncommitted changes in synced paths", "PK800", details=[f"  {line}" for line in dirty],
                     fixes=[fix_run(["git", "stash", "push", "--", *here, self.sync_state],
                                    "stash them ('git stash pop' brings them back)"),
                            fix_hint("or commit them")])

        state_url = self.state_get("url")
        url = self.sync_from or state_url or self.upstream_url
        branch = self.sync_branch or self.state_get("branch") or self.upstream_branch
        name = re.split(r"[/\\]", re.sub(r"\.git$", "", url).rstrip("/"))[-1] or "template"

        origin = output(["git", "remote", "get-url", "origin"])
        if origin and self.normalize_url(origin) == self.normalize_url(url):
            self.info(f"this repository is the template ({url}); there is nothing to sync from")
            return 0

        self.step(f"fetch {url} ({branch})")
        fetch = ["git", "fetch", "--no-tags", "--quiet", url, f"+refs/heads/{branch}:{UPSTREAM_REF}"]
        self.show(fetch)
        if run(fetch) != 0:
            self.die(f"could not fetch branch '{branch}' of {url}", "PK801",
                     fixes=[fix_hint(f"{self.self_name} sync --from /path/to/a/QCDX/clone")])

        tip = output(["git", "rev-parse", f"{UPSTREAM_REF}^0"])
        if self.git_ok("merge-base", "--is-ancestor", "HEAD", tip):
            self.info(f"HEAD is already part of {name}'s history: this is the template or an unchanged copy of it")
            return 0

        state_commit = self.state_get("commit")
        if self.sync_base:
            base = output(["git", "rev-parse", "--verify", "-q", f"{self.sync_base}^0"])
            if not base:
                self.die(f"--base {self.sync_base} is not a commit in {name}", "PK802", status=2)
            self.info(f"base: {self.sync_base} (--base)")
        elif state_commit and self.git_ok("merge-base", "--is-ancestor", state_commit, tip):
            base = state_commit
            self.info(f"base: {self.short_log(base)} (last sync)")
        else:
            if state_commit:
                self.warn(f"last synced commit {state_commit[:7]} is not in {url} {branch} "
                          "(not pushed yet, or history rewritten); searching instead")
            self.step(f"find the {name} commit this kit matches")
            found = self.detect_base(tip)
            if found is None:
                self.die(f"no commit in {name} touches: {' '.join(paths)}", "PK802",
                         fixes=[fix_hint(f"{self.self_name} sync --base COMMIT    (the {name} commit the kit is)")])
                return 1
            base, changed = found
            self.info(f"base: {self.short_log(base)}")
            if changed > 0:
                self.info(f"{changed} lines of the kit here differ from it and are kept, in:")
                for path in self.differing_kit_files(base):
                    out(f"    {path}")
                self.info(f"if that base is wrong, pass --base with the right {name} commit")

        short = output(["git", "rev-parse", "--short", tip])
        remembered = self.remembered_url(url, state_url)

        if self.git_ok("diff", "--quiet", base, tip, "--", *paths):
            self.info(f"kit is up to date with {name} {short}")
            if state_commit and not self.git_ok("merge-base", "--is-ancestor", state_commit, tip):
                self.info(f"{self.sync_state} keeps {state_commit[:7]}, which is newer than {url} {branch}")
                return 0
            if state_commit != tip or state_url != remembered:
                if self.dry_run:
                    self.info(f"dry run: would record {name} {short} in {self.sync_state}")
                    return 0
                self.state_write(remembered, branch, tip)
                run(["git", "add", self.sync_state])
                if not self.no_commit:
                    if self.run(["git", "commit", "-q", "-m", f"Record projectkit upstream {name} {short}"]):
                        self.die("commit failed; the change is staged, commit it yourself", "PK803")
                    self.info(f"recorded {name} {short} in {self.sync_state}")
                else:
                    self.info(f"staged {self.sync_state}; commit it when ready")
            return 0

        self.step(f"{name} changes since {output(['git', 'rev-parse', '--short', base])}")
        run(["git", "log", "--format=  %h %s", f"{base}..{tip}", "--", *paths])
        flush()
        with open(patch, "wb") as file:
            subprocess.run(["git", "diff", "--full-index", "--binary", base, tip, "--", *paths], stdout=file)
        self.map_patch(patch)
        for line in capture(["git", "apply", "--stat", patch])[1].splitlines():
            out(f" {line}")

        if self.dry_run:
            self.info("dry run: nothing changed")
            return 0

        self.step("apply as a 3-way merge")
        self.info("git apply --3way with the changes listed above")
        apply_failed = run(["git", "apply", "--3way", "--whitespace=nowarn", patch]) != 0

        self.state_write(remembered, branch, tip)
        run(["git", "add", self.sync_state])
        message = f"Sync projectkit from {name} {short}"

        conflicts = lines(["git", "diff", "--name-only", "--diff-filter=U"])
        if apply_failed or conflicts:
            out(f"\n{C.red}conflicts{C.reset}: both sides changed the same lines in:")
            for path in conflicts:
                out(f"  {path}")
            out("\nfix the <<<<<<< ======= >>>>>>> blocks in those files, then:")
            out(f"  git add {' '.join(conflicts)}")
            out(f'  git commit -m "{message}"')
            out("or undo the whole sync (your other uncommitted work is kept): git reset --merge")
            return 1

        if self.no_commit:
            self.info(f"staged: review with 'git diff --cached', then: git commit -m \"{message}\"")
            return 0

        self.step("commit")
        full_tip = output(["git", "rev-parse", tip])
        if self.run(["git", "commit", "-q", "-m", message, "-m", f"Upstream: {url} {branch} {full_tip}"]):
            self.die("commit failed; the sync is staged", "PK803",
                     fixes=[fix_hint(f'git commit -m "{message}"')])
        for line in capture(["git", "show", "--stat", "--format=  %h %s", "HEAD"])[1].splitlines():
            out(f" {line}")
        return 0

    def cmd_sync(self) -> int:
        self.no_positionals()
        handle, patch = tempfile.mkstemp(prefix="pk-sync.")
        os.close(handle)
        try:
            return self.sync_run(patch)
        finally:
            os.remove(patch)

    def cmd_format(self) -> int:
        self.require_tools("clang-format")
        if self.positional:
            files = list(self.positional)
        else:
            files = [f for f in lines(["git", "ls-files", "-co", "--exclude-standard", "--",
                                       "*.c", "*.h", "*.cc", "*.cpp", "*.cxx", "*.hh", "*.hpp", "*.hxx"])
                     if not f.startswith(tuple(self.format_exclude))]
        if not files:
            self.info("no C or C++ files to format")
            return 0

        if self.check:
            self.step(f"check formatting of {len(files)} files")
            bad = [f for f in files if capture(["clang-format", "--dry-run", "--Werror", f])[0] != 0]
            if bad:
                for path in bad:
                    out(f"  needs formatting: {path}")
                out(f"fix with: {self.self_name} format")
                return 1
            self.info(f"all {len(files)} files are formatted")
            return 0

        self.step(f"format {len(files)} files")
        for path in files:
            argv = ["clang-format", "-i", path]
            if self.run(argv) if self.loud else run(argv):
                return 1
        return 0

    def cmd_status(self) -> int:
        self.no_positionals()
        describe = output(["git", "describe", "--always", "--dirty"]) or "-"
        out(f"{C.bold}{self.project}{C.reset} {describe}  ({self.root}, prefix {self.prefix})")

        out(f"\n{C.bold}build trees{C.reset}")
        caches = sorted(glob.glob(os.path.join("build", "*", "CMakeCache.txt")))
        for cache in caches:
            tree = os.path.dirname(cache).replace(os.sep, "/")
            line = f"  {tree:<34} {cache_get(tree, 'CMAKE_BUILD_TYPE') or '-':<15}"
            for option in STATUS_OPTIONS:
                value = cache_get(tree, f"{self.prefix}_{option}") or ""
                state = normalize_value(value)
                if option == "BUILD_TESTS" and state == "ON":
                    line += " tests"
                elif option == "BUILD_APPS" and state == "OFF":
                    line += " no-apps"
                elif option == "LIBRARY_TYPE" and state != "OFF":
                    line += f" lib={value.lower()}"
                elif option == "SANITIZE" and state != "OFF":
                    line += f" sanitize={value}"
                elif state == "ON" and option in ("WERROR", "SA_ALL", "LTO", "COVERAGE", "VALGRIND"):
                    line += " " + {"WERROR": "werror", "SA_ALL": "analyze", "LTO": "lto",
                                   "COVERAGE": "coverage", "VALGRIND": "valgrind"}[option]
            out(line)
        if not caches:
            out(f"  none yet, '{self.self_name} build' creates one")

        out(f"\n{C.bold}Conan output{C.reset}")
        toolchains = sorted(glob.glob(os.path.join("build", "*", "generators", "conan_toolchain.cmake")))
        for toolchain in toolchains:
            directory = os.path.dirname(os.path.dirname(toolchain))
            if stamp_get(directory, "key") is not None:
                with_tests = stamp_get(directory, "tests") == "1"
                state = "installed by pk, " + ("with Catch2" if with_tests else "without Catch2")
            else:
                state = "installed outside pk (next pk use reinstalls once)"
            out(f"  {directory.replace(os.sep, '/'):<34} {state}")
        if not toolchains:
            out("  none")

        out(f"\n{C.bold}{self.stage_dir}/{C.reset}")
        report = os.path.join(self.stage_dir, "pk-stage.txt")
        if os.path.isfile(report):
            with open(report, encoding="utf-8") as file:
                records = [line.rstrip("\n") for line in file if not line.startswith("#")]
            meta = {r.split("|")[1]: r.split("|", 2)[2] for r in records if r.startswith("meta|") and r.count("|") >= 2}
            checks = sum(1 for r in records if r.startswith("check|"))
            result = next((r[len("result|"):] for r in records if r.startswith("result|")), "")
            out(f"  {meta.get('type', '')} from {meta.get('preset', '')}, {meta.get('date', '')}, "
                f"{checks} checks, {result}")
        elif os.path.isdir(self.stage_dir):
            out("  present, not made by stage (no pk-stage.txt)")
        else:
            out("  none")

        out(f"\n{C.bold}compile_commands.json{C.reset}")
        if os.path.islink("compile_commands.json"):
            out(f"  -> {os.readlink('compile_commands.json')}")
        elif os.path.isfile("compile_commands.json"):
            out("  copy (not a link)")
        else:
            out("  none")
        return 0

    def cmd_list(self) -> int:
        self.no_positionals()
        out(f"{C.bold}build types{C.reset}  {' '.join(BUILD_TYPES)} (default {self.default_type})")

        out(f"\n{C.bold}apps{C.reset} (pk run NAME)")
        apps = self.app_names()
        for app in apps or ["none"]:
            out(f"  {app}")

        out(f"\n{C.bold}cross targets{C.reset} (pk build -x NAME)")
        names = self.cross_names()
        for name in names:
            result = targets.availability(f"cross-{name}", self.root, "strict")
            if result is None:
                out(f"  {name}")
            elif result[0]:
                out(f"  {name:<28} {C.green}ready{C.reset}")
            else:
                out(f"  {name:<28} {result[1] or 'not available'}")
        if not names:
            out("  none")

        out(f"\n{C.bold}native presets{C.reset}")
        for preset in preset_query("configure-presets"):
            if preset.startswith("native-") or preset == "host-tools":
                out(f"  {preset}")
        return 0

    def tool_line(self, tool: str, need: str) -> bool:
        if have(tool):
            text = [line.strip() for line in capture([tool, "--version"])[1].splitlines() if line.strip()]
            version = next((line for line in text if "version" in line.lower()), text[0] if text else "")
            out(f"  {C.green}OK{C.reset}    {tool:<13} {version}")
            return True
        if need == "required":
            out(f"  {C.red}MISS{C.reset}  {tool:<13} required")
            return False
        out(f"  {C.yellow}--{C.reset}    {tool:<13} optional: {need}")
        return True

    def cmd_doctor(self) -> int:
        self.no_positionals()
        failed = False
        host = f"{C.bold}host{C.reset}     {host_platform()} {host_arch()}"
        if os.environ.get("MSYSTEM"):
            host += f" (MSYSTEM={os.environ['MSYSTEM']})"
        out(f"{host}, python {sys.version.split()[0]}")
        out(f"{C.bold}project{C.reset}  {self.project} at {self.root}\n")

        out(f"{C.bold}required{C.reset}")
        for tool in ("conan", "cmake", "ctest", "ninja", "git"):
            failed = not self.tool_line(tool, "required") or failed
        compiler = next((tool for tool in ("gcc", "clang", "cc") if have(tool)), "")
        if compiler:
            self.tool_line(compiler, "required")
        else:
            out(f"  {C.red}MISS{C.reset}  {'compiler':<13} required: gcc, clang or cc")
            failed = True

        out(f"\n{C.bold}optional{C.reset}")
        self.tool_line("clang-format", "pk format")
        self.tool_line("clang-tidy", "pk analyze")
        self.tool_line("cppcheck", "pk analyze")
        self.tool_line("ccache", "faster rebuilds (sccache works too)")
        self.tool_line("pkg-config", "verify's pkg-config check")
        if host_platform() == "linux":
            self.tool_line("valgrind", "pk memcheck")

        if have("cmake"):
            match = re.search(r"(\d+)\.(\d+)", output(["cmake", "--version"]))
            if match and (int(match.group(1)), int(match.group(2))) < (3, 30):
                out(f"\n{C.red}problem{C.reset} CMake {match.group(0)} is older than 3.30, "
                    "which the project requires")
                failed = True

        out(f"\n{C.bold}Conan{C.reset}")
        if have("conan"):
            default_profile = output(["conan", "profile", "path", "default"])
            if default_profile:
                out(f"  {C.green}OK{C.reset}    default profile {default_profile}")
            elif self.fix:
                failed = self.run(["conan", "profile", "detect", "--exist-ok"]) != 0 or failed
            else:
                out(f"  {C.red}MISS{C.reset}  no default profile: run '{self.self_name} doctor --fix'")
                failed = True
            if os.path.isfile(self.layout.rel("profiles", self.native_profile)):
                out(f"  {C.green}OK{C.reset}    {self.layout.rel('profiles', self.native_profile)}")
            else:
                out(f"  {C.yellow}--{C.reset}    no {self.layout.rel('profiles', self.native_profile)}, "
                    "the default profile is used")

        out(f"\n{C.bold}native verify targets here{C.reset}")
        for name, kind, *_rest in targets.RECORDS:
            if kind == "native" and targets.runnable(name, self.root):
                out(f"  {name}")

        out()
        if failed:
            out(f"{C.red}not ready{C.reset}: fix the MISS lines above")
            return 1
        out(f"{C.green}ready{C.reset}: try '{self.self_name} build'")
        return 0

    def cmd_fix(self) -> int:
        self.no_positionals()
        script = os.path.join(self.root, *self.layout.rel("scripts", "pk.py").split("/"))
        return problems.apply_fix(self.root, [sys.executable, script], self.assume_yes, self.dry_run, self.self_name)

    def cmd_shell_init(self, args: List[str]) -> int:
        shell = args[0].lower() if args else ""
        if not shell:
            outside_msys = os.name == "nt" and not os.environ.get("MSYSTEM")
            shell = "powershell" if outside_msys else "bash"
        python = sys.executable
        if shell in ("powershell", "pwsh", "ps"):
            out(POWERSHELL_INIT.replace("@PYTHON@", python.replace("'", "''")))
        elif shell == "bash":
            out(BASH_INIT.replace("@PYTHON@", native_path(python).replace('"', '\\"')))
        else:
            self.usage_die(f"shell-init takes bash or powershell, not '{args[0]}'", "PK105")
        return 0

    def cmd_words(self, args: List[str]) -> int:
        command = args[0][1:] if args and args[0].startswith(":") else (args[0] if args else "")
        current = args[1][1:] if len(args) > 1 and args[1].startswith(":") else (args[1] if len(args) > 1 else "")
        if not command:
            out("\n".join(NAMES))
            return 0
        resolved, _ = resolve_command(command)
        if not resolved:
            return 0

        if current.startswith("-"):
            words = []
            for flag in COMMAND_FLAGS.get(resolved, []):
                for part in FLAG_SPELLING[flag].replace(",", " ").split():
                    if part.startswith("-"):
                        words.append(part.split("=", 1)[0])
            out("\n".join(words + ["--help"]))
        elif resolved == "help":
            out("\n".join(NAMES))
        elif resolved == "verify":
            out("\n".join(["list", "list-possible", "run", "run-possible", "clean", "help"]))
        elif resolved == "release":
            out("\n".join(["plan", "stage", "pack", "finalize", "list", "help"]))
        elif resolved == "package":
            out("\n".join(["reference", "install", "create", "build", "export", "export-pkg", "list", "info",
                           "path", "editable", "remove", "upload", "cache-clean", "help"]))
        elif resolved == "dep":
            words = ["ls", "add", "set", "rm", "update", "lock", "check", "why", "tree", "help"]
            if os.path.isfile("deps.json"):
                with open("deps.json", encoding="utf-8") as file:
                    words += re.findall(r'^    "([a-z0-9_.+-]*)": \{$', file.read(), re.MULTILINE)
            out("\n".join(words))
        elif resolved == "shell-init":
            out("bash\npowershell")
        elif resolved == "tree":
            out("\n".join(["show", "check", "draw", "apply", "reset", "list", "help"] + pktree.preset_names()))
        elif resolved == "explain":
            out("\n".join(problems.CATALOG))
        elif resolved not in ("format", "status", "doctor", "list", "rename", "full-clean", "sync", "tree", "fix"):
            words = ["debug", "release", "relwithdebinfo", "minsizerel"]
            if resolved == "run":
                words += self.app_names()
            out("\n".join(words))
        return 0


def main(argv: List[str], root: Optional[str] = None) -> int:
    return entry(_main, argv, root)


def _main(argv: List[str], given_root: Optional[str]) -> int:
    root = repo_root(given_root, has_file("CMakeLists.txt", "CMakePresets.json"),
                     "pk: no CMakeLists.txt + CMakePresets.json above {cwd}: set PK_REPO_ROOT")
    setup_output()
    # 'pk tree' works on a broken tree too (that is what 'reset' is for), so
    # it runs before Pk reads the tree.
    if argv and resolve_command(argv[0])[0] == "tree":
        from . import treecmd

        name = os.environ.get("PK_SELF_NAME") or "pk"
        return treecmd.main(argv[1:], root, f"{name} tree")
    if len(argv) >= 2 and argv[0] == "help" and resolve_command(argv[1])[0] == "tree":
        from . import treecmd

        return treecmd.main(["help"], root, f"{os.environ.get('PK_SELF_NAME') or 'pk'} tree")
    pk = Pk(root)
    os.chdir(root)

    if not argv or argv[0] in ("-h", "--help"):
        return pk.help_overview()
    word, args = argv[0], argv[1:]
    if word == "__words":
        return pk.cmd_words(args)

    pk.argv = list(argv)
    resolved, problem = resolve_command(word)
    if not resolved:
        if problem.startswith("ambiguous: "):
            pk.usage_die(f"'{word}' could be: {problem[len('ambiguous: '):]}", "PK101",
                         [fix_hint(f"{pk.self_name} {name}") for name in problem[len("ambiguous: "):].split()[:4]])
        right = problems.closest(word, NAMES + [w for row in COMMANDS for w in (row[2] + " " + row[3]).split()])
        right = resolve_command(right)[0] if right else ""
        fixes = [fix_run(pk.corrected(word, right), f"{right}, not {word}", rerun=False)] if right else []
        pk.usage_die(f"unknown command '{word}'", "PK100", fixes)
    pk.cmd = resolved

    if resolved == "verify":
        from . import verify

        return verify.main(args, root)
    if resolved == "package":
        return pk.package_tool(args)
    if resolved == "release":
        from . import release

        return release.main(args, root)
    if resolved == "rename":
        from . import bootstrap

        return bootstrap.main(args, root)
    if resolved == "dep":
        return pk.deps_tool(args)
    if resolved == "explain":
        return problems.explain(args, root, pk.self_name)
    if resolved == "help":
        if not args:
            return pk.help_overview()
        topic, _ = resolve_command(args[0])
        if not topic:
            pk.usage_die(f"no command '{args[0]}'", "PK100")
        if topic == "dep":
            return pk.deps_tool(["help", *args[1:]])
        pk.cmd = topic
        return pk.help_command(topic)
    if resolved == "shell-init":
        return pk.cmd_shell_init(args)

    pk.parse_args(args)
    if not pk.verbose and pk.verbose_default:
        pk.verbose = True
    started = time.monotonic()
    handler = getattr(pk, "cmd_" + resolved.replace("-", "_"))
    status = handler()
    if status == 0 and resolved not in ("fix", "status", "list", "doctor") and not pk.dry_run:
        problems.forget(root)

    if resolved in ("build", "test", "configure", "deps", "install", "stage", "rebuild", "analyze",
                    "memcheck", "sanitize"):
        seconds = time.monotonic() - started
        gap = "\n" if pk.loud else ""
        if status == 0:
            out(f"{gap}{C.green}done{C.reset} in {seconds:.1f}s")
        else:
            out(f"{gap}{C.red}failed{C.reset} after {seconds:.1f}s")
    return status
