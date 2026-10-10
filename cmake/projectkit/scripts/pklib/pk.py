"""pk: one CLI for every day-to-day projectkit workflow.

Conan and CMake are still what does the work: every command pk runs is
printed before it runs, nothing is hidden; every command invocation and
output can be easily seen, copied, and parsed.

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
from typing import List, Optional, Tuple

from . import targets
from .common import (BUILD_TYPES, SCRIPTS_DIR, C, capture, confirm, entry, err, exit_code, flush, has_file,
                     have, host_arch, host_platform, lines, load_conf, native_path, out, output, remove,
                     repo_root, run, script_env, setup_output, shown, walk_files)
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
    ("project and shell", "sync", "", "upgrade", "update cmake/projectkit from the QCDX template"),
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
    "clean": ["type", "cross", "variant", "all", "deps", "yes", "dry"],
    "full-clean": ["cache", "yes", "dry"],
    "format": ["check", "dry"],
    "doctor": ["fix"],
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
    "all": "--all", "deps": "--deps", "check": "--check", "fix": "--fix", "consumer": "--no-consumer",
    "cache": "--cache", "yes": "-y, --yes", "from": "--from=URL|PATH", "branch": "--branch=NAME",
    "base": "--base=COMMIT", "nocommit": "--no-commit",
}
SWITCHES = {
    "--update": ("update", "update", True), "-n": ("dry", "dry_run", True),
    "--dry-run": ("dry", "dry_run", True), "-v": ("verbose", "verbose", True),
    "--verbose": ("verbose", "verbose", True), "--reset": ("reset", "reset", True),
    "--all": ("all", "clean_all", True), "--deps": ("deps", "clean_deps", True),
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
SYNC_STATE = "scripts/helpers/pk/upstream.conf"
UPSTREAM_REF = "refs/projectkit/upstream"
PRESETS_SCRIPT = os.path.join(SCRIPTS_DIR, "helpers", "pk", "presets.cmake")
DEPS_SCRIPT = os.path.join(SCRIPTS_DIR, "helpers", "pk", "deps.py")


BASH_INIT = r"""# projectkit 'pk': runs the nearest scripts/pk.py from anywhere in a project.
pk() {
  local dir="$PWD"
  while [ "$dir" != "/" ]; do
    if [ -f "$dir/scripts/pk.py" ]; then
      PK_SELF_NAME=pk "${PK_PYTHON:-@PYTHON@}" "$dir/scripts/pk.py" "$@"
      return $?
    fi
    dir="$(dirname "$dir")"
  done
  echo "pk: no scripts/pk.py in $PWD or above" >&2
  return 2
}

_pk_complete() {
  local dir="$PWD" script=""
  while [ "$dir" != "/" ]; do
    [ -f "$dir/scripts/pk.py" ] && { script="$dir/scripts/pk.py"; break; }
    dir="$(dirname "$dir")"
  done
  [ -n "$script" ] || return 0
  local cur="${COMP_WORDS[COMP_CWORD]}" command=""
  [ "$COMP_CWORD" -gt 1 ] && command="${COMP_WORDS[1]}"
  local IFS=$'\n'
  COMPREPLY=($(compgen -W "$("${PK_PYTHON:-@PYTHON@}" "$script" __words ":$command" ":$cur" 2>/dev/null | tr -d '\r')" -- "$cur"))
}
complete -o default -F _pk_complete pk"""

POWERSHELL_INIT = r"""# projectkit 'pk': runs the nearest scripts\pk.py from anywhere in a project.
function pk {
  $dir = (Get-Location).ProviderPath
  while ($dir) {
    $script = Join-Path $dir 'scripts\pk.py'
    if (Test-Path -LiteralPath $script -PathType Leaf) {
      $python = $env:PK_PYTHON
      if (-not $python) { $python = '@PYTHON@' }
      $env:PK_SELF_NAME = 'pk'
      try { & $python $script @args } finally { Remove-Item Env:\PK_SELF_NAME -ErrorAction SilentlyContinue }
      return
    }
    $dir = Split-Path -Parent $dir
  }
  Write-Error "pk: no scripts\pk.py in $PWD or above"
}

Register-ArgumentCompleter -Native -CommandName pk -ScriptBlock {
  param($wordToComplete, $commandAst, $cursorPosition)
  $dir = (Get-Location).ProviderPath
  $script = $null
  while ($dir) {
    $candidate = Join-Path $dir 'scripts\pk.py'
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { $script = $candidate; break }
    $dir = Split-Path -Parent $dir
  }
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
        conf = load_conf(root, "scripts/helpers/pk/pk.conf")
        self.self_name = os.environ.get("PK_SELF_NAME") or "./scripts/pk.py"
        self.default_type = conf.get("PK_DEFAULT_TYPE", "Debug")
        self.default_jobs = conf.get("PK_DEFAULT_JOBS")
        self.stage_dir = conf.get("PK_STAGE_DIR", "stage")
        self.native_profile = conf.get("PK_NATIVE_PROFILE", "native")
        self.format_exclude = conf.get("PK_FORMAT_EXCLUDE", "cmake/projectkit/ build/ stage/ _install/").split()
        self.upstream_url = conf.get("PK_UPSTREAM_URL", "https://github.com/cooldood155/QCDX.git")
        self.upstream_branch = conf.get("PK_UPSTREAM_BRANCH", "main")
        self.sync_paths = conf.get(
            "PK_SYNC_PATHS",
            ("cmake/projectkit scripts/pk.py scripts/verify.py scripts/package.py scripts/release.py "
             "scripts/bootstrap.py .github/actions/pk-setup")).split()

        self.cmd = ""
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

    @property
    def prefix(self) -> str:
        return self.v.prefix

    @property
    def project(self) -> str:
        return self.v.project

    def step(self, message: str) -> None:
        out(f"\n{C.green}==>{C.reset} {C.bold}{message}{C.reset}")

    def info(self, message: str) -> None:
        out(f"{C.dim}  {message}{C.reset}")

    def warn(self, message: str) -> None:
        err(f"{C.yellow}warning:{C.reset} {message}")

    def die(self, message: str) -> None:
        err(f"{C.red}error:{C.reset} {message}")
        raise SystemExit(1)

    def usage_die(self, message: str) -> None:
        err(f"{C.red}error:{C.reset} {message}")
        if self.cmd:
            err(f"run '{self.self_name} help {self.cmd}' for what it accepts")
        else:
            err(f"run '{self.self_name} help' for the command list")
        raise SystemExit(2)

    def show(self, argv: List[str]) -> None:
        out(f"{C.yellow}+{C.reset} {shown(argv)}")

    def run(self, argv: List[str], cwd: Optional[str] = None) -> int:
        self.show(argv)
        return 0 if self.dry_run else run(argv, cwd=cwd)

    def remove(self, path: str) -> None:
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

    def require_tools(self, *tools: str) -> None:
        missing = [tool for tool in tools if not have(tool)]
        if not missing:
            return
        err(f"{C.red}error:{C.reset} {self.cmd} needs: {' '.join(missing)}")
        for tool in missing:
            err(f"  install {tool}: {self.install_hint(tool)}")
        raise SystemExit(1)

    def package_tool(self, args: List[str]) -> int:
        from . import package

        try:
            return package.main(args, self.root)
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
            "cross": f"cross-compile with profiles/NAME and its presets, see '{self.self_name} list'",
            "variant": "use a separate tree build/<preset>-NAME that remembers its own options",
            "update": "re-run Conan even when the dependencies look current",
            "dry": "print every command without running anything",
            "verbose": "show full compiler and linker command lines",
            "tests": "build the test suite; off by default, 'test' turns it on",
            "apps": "build the applications under apps/",
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
            "check": "list files that need formatting, change nothing (exit 1 if any)",
            "fix": "create Conan's default profile when it is missing",
            "consumer": "skip building a consumer project against stage/",
            "cache": "also remove this package from the local Conan cache",
            "yes": "do not ask before deleting",
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
            "full-clean": "full-clean [--cache] [-y] [-n]",
            "sync": "sync [--from URL|PATH] [--branch NAME] [--base COMMIT] [--no-commit] [-n]",
            "format": "format [--check] [path...]",
            "help": "help [command]",
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
            "full-clean": [f"{s} full-clean -n", f"{s} full-clean", f"{s} full-clean --cache --yes"],
            "stage": [f"{s} stage", f"{s} stage release --lib=shared",
                      f'grep "^check|" {self.stage_dir}/pk-stage.txt'],
            "analyze": [f"{s} analyze"],
            "memcheck": [f"{s} memcheck"],
            "sanitize": [f"{s} sanitize", f"{s} sanitize --sanitize=thread"],
            "format": [f"{s} format", f"{s} format --check"],
            "doctor": [f"{s} doctor", f"{s} doctor --fix"],
            "verify": [f"{s} verify list", f"{s} verify run --native --build_type=Debug"],
            "package": [f"{s} package create", f"{s} package help"],
            "release": [f"{s} release list", f"{s} release stage linux-x86_64", f"{s} release pack linux-x86_64"],
            "rename": [f"{s} rename myproject --dry-run"],
            "shell-init": [
                f'eval "$(python3 {native_path(self.root)}/scripts/pk.py shell-init)"    # once, in ~/.bashrc',
                f"python {self.root}\\scripts\\pk.py shell-init powershell | Out-String | Invoke-Expression"
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
            "sync": [f"Brings the template's kit changes into this project: {' '.join(self.sync_paths)}.",
                     "Only the template's changes since the last sync are applied, as a 3-way",
                     "merge, so changes you made to the kit here are kept; where both sides",
                     "changed the same lines you get conflict markers to resolve. The result is",
                     f"one commit that touches only those paths plus {SYNC_STATE}, which",
                     "records the template URL, branch and commit for the next sync. The first",
                     "sync finds the template commit this kit matches by itself.",
                     "Needs: no staged changes, no uncommitted changes in those paths. Your",
                     "other uncommitted work is left alone."],
            "full-clean": [f"Removes every build tree and Conan output (build/), {self.stage_dir}/, _install/,",
                           "compile_commands.json, verify's scratch and consumer directories, the Conan",
                           "test_package build, clangd's index, other CMake build dirs (build-*,",
                           "cmake-build-*), Conan-written presets and sanitizer logs. Lists what exists",
                           "and asks first. Ignored files it does not own (.vscode/, docs/notes...) are",
                           "listed afterwards but never touched."],
            "stage": ["Like verify's install and consumer stages, for the tree you build with:",
                      f"{self.stage_dir}/ is emptied, the tree is installed into it, the package files",
                      "are checked, pkg-config reads the .pc, and a consumer project is built",
                      f"against {self.stage_dir}/ and run. Every result is written to",
                      f"{self.stage_dir}/pk-stage.txt, one 'kind|field|value' record per line:",
                      "  meta|type|Debug   file|lib/libx.a   check|<label>|pass   result|passed",
                      "Your build tree and its options are not touched."],
            "shell-init": ["Without an argument: powershell when started outside an MSYS2 shell on",
                           "Windows, bash everywhere else."],
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
        out("\nEvery command prints the Conan/CMake commands it runs; -n only prints them.")
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
            self.usage_die(f"'{self.cmd}' does not take {FLAG_SPELLING[flag]}")

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
                    self.usage_die(f"unknown flag '{arg}'")
                build_type = parse_type(arg)
                if not self.type and self.flag_ok("type") and build_type:
                    self.type = build_type
                else:
                    self.positional.append(arg)
                continue

            self.flag_allowed(flag)
            if not sep:
                if index >= len(args):
                    self.usage_die(f"{arg} needs a value")
                value = args[index]
                index += 1
            self.set_value_flag(flag, value)

    def set_value_flag(self, flag: str, value: str) -> None:
        if flag == "type":
            build_type = parse_type(value)
            if not build_type:
                self.usage_die(f"unknown build type '{value}'")
            self.type = build_type or ""
        elif flag == "cross":
            self.cross = value
        elif flag == "variant":
            if not value or "/" in value or "\\" in value or " " in value:
                self.usage_die("variant names are one word without '/'")
            self.variant = value
        elif flag == "sanitize":
            self.add_option("SANITIZE", value)
        elif flag == "lib":
            kinds = {"static": "STATIC", "shared": "SHARED", "both": "STATIC+SHARED",
                     "static+shared": "STATIC+SHARED", "none": "NONE"}
            if value.lower() not in kinds:
                self.usage_die(f"--lib takes static, shared, both or none, not '{value}'")
            self.add_option("LIBRARY_TYPE", kinds[value.lower()])
        elif flag in ("option", "define"):
            if "=" not in value:
                self.usage_die(f"{'-O' if flag == 'option' else '-D'} takes NAME=VALUE, got '{value}'")
            if flag == "option":
                name, _, option_value = value.partition("=")
                self.add_option(name, option_value)
            else:
                self.config_defs.append(value)
        elif flag == "jobs":
            if not value.isdigit():
                self.usage_die(f"--jobs takes a number, not '{value}'")
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
            if os.path.isfile(os.path.join(self.root, "profiles", name)):
                names.append(name)
        return names

    def app_names(self) -> List[str]:
        apps = os.path.join(self.root, "apps")
        if not os.path.isdir(apps):
            return []
        return sorted(name for name in os.listdir(apps) if os.path.isdir(os.path.join(apps, name)))

    def select(self) -> None:
        if not have("cmake"):
            self.die("cmake is not on PATH")
        if not self.type:
            build_type = parse_type(self.default_type)
            if not build_type:
                self.die(f"PK_DEFAULT_TYPE='{self.default_type}' is not a build type")
            self.type = build_type or ""
        self.type_lower = self.type.lower()

        if self.cross:
            if self.cross.startswith("cross-"):
                self.cross = self.cross[len("cross-"):]
            if not os.path.isfile(os.path.join(self.root, "profiles", self.cross)):
                self.usage_die(f"no profiles/{self.cross}; cross targets here: {' '.join(self.cross_names())}")
            self.preset = f"{self.cross}-{self.type_lower}"
        else:
            self.preset = f"native-{self.type_lower}"

        dirs = self.preset_dirs(self.preset)
        if dirs is None:
            self.die(f"CMakePresets.json has no configure preset '{self.preset}'")
            return
        self.tree, self.toolchain = dirs
        if self.variant:
            self.tree = f"{self.tree}-{self.variant}"
        if not self.toolchain:
            self.die(f"preset '{self.preset}' has no toolchainFile, pk needs Conan's")
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
                     f"profiles/{self.native_profile}", host_profile):
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
        host_profile = f"profiles/{cross}" if cross else ""
        label = f"cross {cross}" if cross else "native"
        want_tests = want_tests and not cross

        current, why = self.deps_current(conan_dir, toolchain, host_profile, want_tests)
        if current and not self.update:
            self.info(f"deps {build_type} ({label}): up to date")
            return
        if self.update:
            why = "--update given"
        self.step(f"deps {build_type} ({label}): {why}")

        args = [f"--build_type={build_type}"]
        if os.path.isfile(os.path.join("profiles", self.native_profile)):
            args.append(f"--profile={self.native_profile}")
        if cross:
            args.append(f"--host-profile={cross}")
        skip = "False" if want_tests else "True"
        args += ["--", "-c", f"tools.build:skip_test={skip}", "-c", f"tools.graph:skip_test={skip}"]
        if self.cmd == "deps":
            args += self.extra

        if self.dry_run:
            self.package_tool(["install", "--dry-run", *args])
            self.deps_changed = True
            return
        if self.package_tool(["install", *args]) != 0:
            self.die(f"conan install failed for {build_type} ({label})")
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
            self.die(f"no native-{self.type_lower} preset for host tools")
            return
        tools_tree, native_toolchain = tools[0], native[1]

        saved = self.deps_changed
        self.deps_changed = False
        self.ensure_deps(self.type, "", os.path.dirname(os.path.dirname(native_toolchain)),
                         native_toolchain, False)
        native_changed = self.deps_changed
        self.deps_changed = saved

        if cache_get(tools_tree, "CMAKE_BUILD_TYPE") != self.type or native_changed:
            self.step(f"host tools {self.type}")
            self.remove(tools_tree)
            if self.run(["cmake", "--preset", "host-tools", f"-DCMAKE_BUILD_TYPE={self.type}",
                         f"-DCMAKE_TOOLCHAIN_FILE={native_path(os.path.join(self.root, native_toolchain))}"]):
                self.die("host-tools configure failed")
        if self.run(["cmake", "--build", tools_tree]):
            self.die("host-tools build failed")

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
                self.die(f"'{self.cmd}' runs binaries, a cross build cannot")
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
        self.step(f"configure {self.preset}{variant}: {reason}")
        args = ["cmake", "--preset", self.preset]
        if self.variant:
            args += ["-B", self.tree]
        if fresh:
            args.append("--fresh")
        args += [f"-D{definition}" for definition in defs]
        if self.cmd == "configure":
            args += self.extra
        if self.run(args):
            self.die("configure failed")

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
        self.step(f"build {self.tree}")
        if self.run(args):
            self.die("build failed")

    def ctest(self) -> int:
        args = ["ctest", "--test-dir", self.tree, "--output-on-failure"]
        if self.jobs:
            args += ["-j", self.jobs]
        if self.filter:
            args += ["-R", self.filter]
        if self.label:
            args += ["-L", self.label]
        args += self.extra
        self.step(f"test {self.tree}")
        return self.run(args)

    def no_positionals(self) -> None:
        if self.positional:
            self.usage_die(f"unexpected argument '{self.positional[0]}'")

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
        self.prepare(True, False)
        self.build()
        return self.ctest()

    def cmd_install(self) -> int:
        self.no_positionals()
        self.prepare(False, False)
        self.build()
        prefix = self.prefix_dir or self.stage_dir
        self.step(f"install into {prefix}")
        if self.run(["cmake", "--install", self.tree, "--prefix", native_path(prefix)]):
            self.die("install failed")
        return 0

    def cmd_run(self) -> int:
        if len(self.positional) > 1:
            self.usage_die(f"run takes one APP, got: {' '.join(self.positional)} (app args go after --)")
        app = self.positional[0] if self.positional else ""
        if not app:
            apps = self.app_names()
            if len(apps) == 1:
                app = apps[0]
            elif not apps:
                self.die("no apps/ directories found, name the executable: run NAME")
            else:
                self.usage_die(f"several apps, pick one: {' '.join(apps)}")
        if self.cross:
            self.die("cannot run a cross-compiled binary on this machine")
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
            self.die(f"no {exe}; executables in {self.tree}/bin: {' '.join(found) or 'none'}")

        generators = os.path.join(self.conan_dir, "generators")
        names = ("conanrun.bat", "conanrun.sh") if os.name == "nt" else ("conanrun.sh",)
        run_script = next((os.path.join(generators, n) for n in names
                           if os.path.isfile(os.path.join(generators, n))), "")

        self.step(f"run {app}")
        exe_path = os.path.normpath(os.path.join(self.root, exe))
        command = [exe_path, *self.extra]
        env = None
        if run_script:
            self.info(f"with the Conan run environment {run_script.replace(os.sep, '/')}")
            if not self.dry_run:
                env = script_env(run_script)
                if env is None:
                    self.warn(f"could not read {run_script}, running without it")
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
            self.die("memcheck needs Valgrind, which pk only supports on Linux")
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

    def full_clean_paths(self) -> List[str]:
        root = self.root
        candidates = self.v.clean_paths() + [
            os.path.join(root, self.stage_dir),
            os.path.join(root, "cmake", "projectkit", "test_package", "build"),
            os.path.join(root, ".cache", "clangd"),
            os.path.join(root, "CMakeUserPresets.json"),
            os.path.join(root, "ConanPresets.json"),
            os.path.join(root, ".ninja_deps"),
            os.path.join(root, ".ninja_log"),
        ]
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
            self.die("not asking on a non-interactive input: pass --yes to delete")
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
            self.die(f"PK_STAGE_DIR='{self.stage_dir}' must be a directory inside the project")
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

    def state_get(self, key: str) -> str:
        try:
            with open(SYNC_STATE, encoding="utf-8") as file:
                for line in file:
                    if line.startswith(f"{key}="):
                        return line.rstrip("\r\n")[len(key) + 1:]
        except OSError:
            pass
        return ""

    def state_write(self, url: str, branch: str, commit: str) -> None:
        os.makedirs(os.path.dirname(SYNC_STATE), exist_ok=True)
        with open(SYNC_STATE, "w", encoding="utf-8", newline="\n") as file:
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
        for commit in lines(["git", "rev-list", "--max-count=500", tip, "--", *self.sync_paths]):
            changed = 0
            for row in lines(["git", "diff", "--numstat", commit, "HEAD", "--", *self.sync_paths]):
                fields = row.split("\t")
                if len(fields) >= 2 and fields[0] != "-":
                    changed += int(fields[0]) + int(fields[1])
            if best is None or changed < best[1]:
                best = (commit, changed)
            if changed == 0:
                break
        return best

    def short_log(self, commit: str) -> str:
        return output(["git", "log", "-1", "--format=%h %s", commit])

    def sync_run(self, patch: str) -> int:
        paths = self.sync_paths
        if not self.git_ok("rev-parse", "--verify", "-q", "HEAD"):
            self.die("sync needs at least one commit in this repository")
        if self.git_ok("rev-parse", "--verify", "-q", "MERGE_HEAD"):
            self.die("finish the merge in progress first")
        if not self.git_ok("diff", "--cached", "--quiet"):
            self.die("you have staged changes: commit or unstage them first, so the sync commit holds only the kit")
        dirty = lines(["git", "status", "--porcelain", "--", *paths, SYNC_STATE])
        if dirty:
            for line in dirty:
                err(f"  {line}")
            self.die("uncommitted changes in synced paths (above): commit or stash them first")

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
            self.die(f"could not fetch branch '{branch}' of {url}")

        tip = output(["git", "rev-parse", f"{UPSTREAM_REF}^{{commit}}"])
        if self.git_ok("merge-base", "--is-ancestor", "HEAD", tip):
            self.info(f"HEAD is already part of {name}'s history: this is the template or an unchanged copy of it")
            return 0

        state_commit = self.state_get("commit")
        if self.sync_base:
            base = output(["git", "rev-parse", "--verify", "-q", f"{self.sync_base}^{{commit}}"])
            if not base:
                self.die(f"--base {self.sync_base} is not a commit in {name}")
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
                self.die(f"no commit in {name} touches: {' '.join(paths)}")
                return 1
            base, changed = found
            self.info(f"base: {self.short_log(base)}")
            if changed > 0:
                self.info(f"{changed} lines of the kit here differ from it and are kept, in:")
                for path in lines(["git", "diff", "--name-only", base, "HEAD", "--", *paths]):
                    out(f"    {path}")
                self.info(f"if that base is wrong, pass --base with the right {name} commit")

        short = output(["git", "rev-parse", "--short", tip])
        remembered = self.remembered_url(url, state_url)

        if self.git_ok("diff", "--quiet", base, tip, "--", *paths):
            self.info(f"kit is up to date with {name} {short}")
            if state_commit and not self.git_ok("merge-base", "--is-ancestor", state_commit, tip):
                self.info(f"{SYNC_STATE} keeps {state_commit[:7]}, which is newer than {url} {branch}")
                return 0
            if state_commit != tip or state_url != remembered:
                if self.dry_run:
                    self.info(f"dry run: would record {name} {short} in {SYNC_STATE}")
                    return 0
                self.state_write(remembered, branch, tip)
                run(["git", "add", SYNC_STATE])
                if not self.no_commit:
                    if self.run(["git", "commit", "-q", "-m", f"Record projectkit upstream {name} {short}"]):
                        self.die("commit failed; the change is staged, commit it yourself")
                    self.info(f"recorded {name} {short} in {SYNC_STATE}")
                else:
                    self.info(f"staged {SYNC_STATE}; commit it when ready")
            return 0

        self.step(f"{name} changes since {output(['git', 'rev-parse', '--short', base])}")
        run(["git", "log", "--format=  %h %s", f"{base}..{tip}", "--", *paths])
        flush()
        with open(patch, "wb") as file:
            subprocess.run(["git", "diff", "--full-index", "--binary", base, tip, "--", *paths], stdout=file)
        for line in capture(["git", "apply", "--stat", patch])[1].splitlines():
            out(f" {line}")

        if self.dry_run:
            self.info("dry run: nothing changed")
            return 0

        self.step("apply as a 3-way merge")
        self.info("git apply --3way with the changes listed above")
        apply_failed = run(["git", "apply", "--3way", "--whitespace=nowarn", patch]) != 0

        self.state_write(remembered, branch, tip)
        run(["git", "add", SYNC_STATE])
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
            self.die(f'commit failed; the sync is staged, commit it yourself: git commit -m "{message}"')
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
            if self.run(["clang-format", "-i", path]):
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
            if os.path.isfile(os.path.join("profiles", self.native_profile)):
                out(f"  {C.green}OK{C.reset}    profiles/{self.native_profile}")
            else:
                out(f"  {C.yellow}--{C.reset}    no profiles/{self.native_profile}, the default profile is used")

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
            self.usage_die(f"shell-init takes bash or powershell, not '{args[0]}'")
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
        elif resolved not in ("format", "status", "doctor", "list", "rename", "full-clean", "sync"):
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
    pk = Pk(root)
    os.chdir(root)

    if not argv or argv[0] in ("-h", "--help"):
        return pk.help_overview()
    word, args = argv[0], argv[1:]
    if word == "__words":
        return pk.cmd_words(args)

    resolved, problem = resolve_command(word)
    if not resolved:
        if problem.startswith("ambiguous: "):
            pk.usage_die(f"'{word}' could be: {problem[len('ambiguous: '):]}")
        first = word[:1]
        suggestions = [name for name in NAMES if word in name or (first and name.startswith(first))]
        if suggestions:
            pk.usage_die(f"unknown command '{word}', did you mean: {' '.join(suggestions)}?")
        pk.usage_die(f"unknown command '{word}'")
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
    if resolved == "help":
        if not args:
            return pk.help_overview()
        topic, _ = resolve_command(args[0])
        if not topic:
            pk.usage_die(f"no command '{args[0]}'")
        if topic == "dep":
            return pk.deps_tool(["help", *args[1:]])
        pk.cmd = topic
        return pk.help_command(topic)
    if resolved == "shell-init":
        return pk.cmd_shell_init(args)

    pk.parse_args(args)
    started = time.monotonic()
    handler = getattr(pk, "cmd_" + resolved.replace("-", "_"))
    status = handler()

    if resolved in ("build", "test", "configure", "deps", "install", "stage", "rebuild", "analyze",
                    "memcheck", "sanitize"):
        seconds = int(time.monotonic() - started)
        if status == 0:
            out(f"\n{C.green}done{C.reset} in {seconds}s")
        else:
            out(f"\n{C.red}failed{C.reset} after {seconds}s")
    return status
