from __future__ import annotations

import json
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
from typing import Callable, Dict, Iterator, List, Optional, Tuple

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT_DIR = os.path.dirname(SCRIPTS_DIR)
BUILD_TYPES = ("Debug", "Release", "RelWithDebInfo", "MinSizeRel")


class Colors:
    """ANSI terminal escape sequences used to format/style text output."""

    def __init__(self) -> None:
        """Initializes empty styling strings, ensuring colorless text safe
        fallbacks."""
        self.bold = self.red = self.green = self.yellow = self.dim = self.reset = ""


C = Colors()


def _console_ansi() -> bool:
    """Checks for ANSI color capabilities; force virtual terminal processing on
    32-bit Windows systems."""
    if sys.platform != "win32":
        return True

    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except (AttributeError, OSError):
        return False


def setup_output() -> None:
    """Configures stream encoding error handlers and initializes the global
    ANSI color codes if supported."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")

    if C.reset or os.environ.get("NO_COLOR") or not sys.stdout.isatty() or not _console_ansi():
        return

    C.bold, C.red, C.green, C.yellow, C.dim, C.reset = (
        "\033[1m", "\033[31m", "\033[32m", "\033[33m", "\033[2m", "\033[0m")


def out(text: str = "") -> None:
    """Custom/Extendable wrapper for standard output printing.

    Default implementation is simply:
    ```
    print(text)
    ```"""
    print(text)


def err(text: str) -> None:
    """Custom/Extendable wrapper for standard error printing.

    Default implementation is simply:
    ```
    print(text, file=sys.stderr)
    ```"""
    print(text, file=sys.stderr)


def flush() -> None:
    """Custom/Extendable wrapper for standard out/err flushing.

    Default implementation is simply:
    ```
    sys.stdout.flush()
    sys.stderr.flush()
    ```"""
    sys.stdout.flush()
    sys.stderr.flush()


def entry(function: Callable[[List[str], Optional[str]], int], argv: List[str], root: Optional[str]) -> int:
    """Custom/Extendable wrapper for executing a target function (the entry
    point to a script), catching Ctrl+C (130) and broke pipes (141) by default,
    returning the functions return code."""
    try:
        return function(argv, root)
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 141


def exit_code(stop: SystemExit) -> int:
    """Extracts an `int` exit code from a `SystemExit` exception, defaulting to
    0 for None and 1 for string or invalid statuses."""
    if stop.code is None:
        return 0
    return stop.code if isinstance(stop.code, int) else 1


_PLAIN = re.compile(r"[A-Za-z0-9_./:=,+@%\\ -]+")


def shown(argv: List[str]) -> str:
    """Formats command-line arguments in a human-readable string for display or
    logging via selective double-quoting."""
    parts = []
    for arg in argv:
        if arg == "":
            parts.append("''")
        elif not _PLAIN.fullmatch(arg):
            parts.append(shlex.quote(arg))
        elif " " in arg:
            parts.append(f'"{arg}"')
        else:
            parts.append(arg)
    return " ".join(parts)


def _resolve(argv: List[str]) -> List[str]:
    """Resolves the base command to its absolute file system path."""
    return [shutil.which(argv[0]) or argv[0], *argv[1:]]


def run(argv: List[str], cwd: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> int:
    """Executes a command directly to the terminal, returning the exit code or
    127 if the executable cannot be found."""
    flush()
    try:
        return subprocess.run(_resolve(argv), cwd=cwd, env=env).returncode
    except OSError as error:
        err(f"{argv[0]}: {error.strerror or error}")
        return 127


def capture(argv: List[str], cwd: Optional[str] = None, merge: bool = False,
            env: Optional[Dict[str, str]] = None) -> Tuple[int, str]:
    """Executes a command silently and grabs its stdout, optionally merging
    stderr (`merge` parameter) or returning 127 on execution failure."""
    flush()
    try:
        result = subprocess.run(_resolve(argv), cwd=cwd, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT if merge else subprocess.DEVNULL)
    except OSError:
        return 127, ""
    return result.returncode, result.stdout.decode("utf-8", "replace")


def output(argv: List[str], cwd: Optional[str] = None) -> str:
    """Executes a command silently and returns its stripped stdout, or an empty
    string if the execution fails."""
    code, text = capture(argv, cwd=cwd)
    return text.strip() if code == 0 else ""


def lines(argv: List[str], cwd: Optional[str] = None) -> List[str]:
    """Executes a command silently and splits its stdout into a list of the
    outputted lines (non-empty), or an empty list if the execution fails."""
    code, text = capture(argv, cwd=cwd)
    return [line for line in text.splitlines() if line] if code == 0 else []


def tee(argv: List[str], cwd: Optional[str] = None) -> Tuple[int, str]:
    """Executes a command and streams the output to the terminal in real time,
    also tracking and returning the full captured text and exit code."""
    flush()
    try:
        process = subprocess.Popen(_resolve(argv), cwd=cwd, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
    except OSError as error:
        err(f"{argv[0]}: {error.strerror or error}")
        return 127, ""

    sink = getattr(sys.stdout, "buffer", None)
    pieces: List[bytes] = []
    for line in process.stdout or ():
        pieces.append(line)
        if sink is not None:
            sink.write(line)
            sink.flush()
        else:
            sys.stdout.write(line.decode("utf-8", "replace"))
    return process.wait(), b"".join(pieces).decode("utf-8", "replace")


def have(tool: str) -> bool:
    """Checks if a cmd-line executable exists within the system env PATH."""
    return shutil.which(tool) is not None


def _retry_writable(function: Callable[[str], object], path: str, _info: object) -> None:
    """Fallback handler to force file write permissions to retry a failed
    deletion during directory tree removal."""
    os.chmod(path, stat.S_IWRITE)
    function(path)


def remove(path: str) -> bool:
    """Safely removes a file, symlink, or directory tree, overriding read-only
    permissions on failure, returning True if successful."""
    try:
        if os.path.islink(path):
            try:
                os.remove(path)
            except OSError:
                os.rmdir(path)
        elif os.path.isdir(path):
            if sys.version_info >= (3, 12):
                shutil.rmtree(path, onexc=_retry_writable)
            else:
                shutil.rmtree(path, onerror=_retry_writable)
        elif os.path.exists(path):
            os.remove(path)
        return True

    except OSError as error:
        err(f"cannot remove {path}: {error.strerror or error}")
        return False


def walk_files(top: str) -> Iterator[str]:
    """Recursively traverses a directory tree, yielding the full path of every
    file found."""
    for directory, _dirs, files in os.walk(top):
        for name in files:
            yield os.path.join(directory, name)


def host_platform() -> str:
    """Identifies the current operating system. Variations normalized to
    'linux', 'macos', 'windows', or 'unknown'."""
    system = platform.system()
    if system == "Linux":
        return "linux"
    if system == "Darwin":
        return "macos"
    if system == "Windows" or system.startswith(("MINGW", "MSYS", "CYGWIN")):
        return "windows"
    return "unknown"


def host_arch() -> str:
    """Returns the CPU architecture of the *host machine*. Variations
    normalized to 'x86_64', 'armv8', or 'unknown'."""
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    if machine in ("aarch64", "arm64") or machine.startswith("armv8"):
        return "armv8"
    return "unknown"


def tool_env(tool: str) -> str:
    """Extracts the uppercase grandparent directory (two levels up) name of a
    tool's path to get its installation environment prefix."""
    found = shutil.which(tool)
    if not found:
        return ""
    return os.path.basename(os.path.dirname(os.path.dirname(os.path.realpath(found)))).upper()


def native_path(path: str) -> str:
    """Normalizes a file path to use forward slashes on Windows and converts
    POSIX-style paths to Windows paths inside MSYS/Cygwin environments."""
    if sys.platform in ("msys", "cygwin") and have("cygpath"):
        return output(["cygpath", "-m", path]) or path
    if os.name == "nt":
        return path.replace("\\", "/")
    return path


def exe_suffix() -> str:
    """Returns '.exe' if the host is Windows; an empty string on Unix-like
    OSs."""
    return ".exe" if host_platform() == "windows" else ""


def repo_root(given: Optional[str], check: Callable[[str], bool], missing: str) -> str:
    """Discover the repo root via configuration or by traversing upward from
    the *current directory*; updates PK_REPO_ROOT on success."""
    root = os.environ.get("PK_REPO_ROOT") or given
    if not root:
        directory = os.getcwd()
        while not check(directory):
            parent = os.path.dirname(directory)
            if parent == directory:
                err(missing.format(cwd=os.getcwd()))
                raise SystemExit(2)

            directory = parent
        root = directory

    root = os.path.abspath(root)
    os.environ["PK_REPO_ROOT"] = root
    return root


def has_file(*names: str) -> Callable[[str], bool]:
    """Generates a validator function to check if a directory contains all
    specified file `names`."""
    return lambda directory: all(os.path.isfile(os.path.join(directory, n)) for n in names)


_PROJECT = re.compile(r"^[ \t]*project[ \t]*\(\s*([A-Za-z0-9_.+-]+)", re.MULTILINE)


def detect_project(root: str) -> str:
    """Grabs the project name from a root CMakeLists.txt file using a regex
    match; returns an empty string on failure."""
    try:
        with open(os.path.join(root, "CMakeLists.txt"), encoding="utf-8", errors="replace") as file:
            match = _PROJECT.search(file.read())
    except OSError:
        return ""
    return match.group(1) if match else ""


def confirm(prompt: str, accept: Tuple[str, ...] = ("y",)) -> bool:
    """Print an interactive cmd prompt and check if the user response matches
    any value in the allowed `accept` tuple. """
    try:
        answer = input(f"{prompt} [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in accept


def script_env(script: str) -> Optional[Dict[str, str]]:
    """Evaluates a batch script or shell script inside of an isolated
    subprocess to capture and export final environment variables it outputs."""
    script = os.path.abspath(script)
    try:
        if script.endswith(".bat"):
            command = f'cmd /d /u /s /c "call "{os.path.normpath(script)}" >nul 2>&1 && set"'
            raw = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
            pairs = [line.split("=", 1) for line in raw.decode("utf-16-le", "replace").splitlines()
                     if "=" in line and not line.startswith("=")]
            return {name: value for name, value in pairs}
        if not have("sh"):
            return None
        code = "import json, os; print(json.dumps(dict(os.environ)))"
        result = subprocess.run(
            ["sh", "-c", '. "$1" >/dev/null 2>&1 && exec "$2" -c "$3"', "sh", script, sys.executable, code],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        data = json.loads(result.stdout.decode("utf-8", "replace"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


_ASSIGN = re.compile(r"(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)", re.DOTALL)
_DEFAULT = re.compile(r':[ \t]+"\$\{([A-Za-z_][A-Za-z0-9_]*):=(.*)\}"', re.DOTALL)
_VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)")


class Config:
    """Light configuration parser that processes shell-like variable
    assignments, deault fallbacks, and multi-line string expansions."""

    def __init__(self, extra: Optional[Dict[str, str]] = None) -> None:
        """Initializes an empty configuration container with optional fallback
        variables."""
        self.values: Dict[str, str] = {}
        self.extra = extra or {}

    def load(self, path: str) -> "Config":
        """Parse a configuration file line-by-line, handling escaped multiline
        quotes, default definitions, and standard NAME=value assignments."""
        if not os.path.isfile(path):
            return self

        with open(path, encoding="utf-8", errors="replace") as file:
            raw_lines = file.read().splitlines()

        index = 0
        while index < len(raw_lines):
            number = index + 1
            line = raw_lines[index].strip()
            index += 1
            while (line.count('"') - line.count('\\"')) % 2 and index < len(raw_lines):
                line += "\n" + raw_lines[index]
                index += 1
            if not line or line.startswith("#"):
                continue

            match = _DEFAULT.fullmatch(line)
            if match:
                if not self.lookup(match.group(1)):
                    self.values[match.group(1)] = self.expand(match.group(2))
                continue

            match = _ASSIGN.fullmatch(line)
            if match:
                self.values[match.group(1)] = self.parse_value(match.group(2))
                continue
            err(f"{path}:{number}: ignored, only NAME=value lines are read: {line.splitlines()[0]}")
        return self

    def lookup(self, name: str) -> str:
        """Finds a variable name by checking parsed configuration values,
        explicit fallback extras, and the host environment variables."""
        if name in self.values:
            return self.values[name]
        return self.extra.get(name) or os.environ.get(name, "")

    def expand(self, text: str) -> str:
        """Expands env style variables (e.g., ${NAME} or $NAME) and handles
        standard shell fallback values (${NAME:-default})."""
        return _VARIABLE.sub(
            lambda m: self.lookup(m.group(1) or m.group(3)) or (m.group(2) or ""), text)

    def parse_value(self, text: str) -> str:
        """Parses shell style string formatting rules, keeping literal single
        quotes, expanding double quotes, and resolving unquoted spands."""
        parts = []
        index = 0
        while index < len(text):
            char = text[index]
            if char == "'":
                end = text.find("'", index + 1)
                end = len(text) if end < 0 else end
                parts.append(text[index + 1:end])
                index = end + 1
            elif char == '"':
                end = index + 1
                while end < len(text) and text[end] != '"':
                    end += 2 if text[end] == "\\" else 1
                parts.append(self.expand(text[index + 1:end].replace('\\"', '"')))
                index = end + 1
            elif char.isspace():
                break
            else:
                end = index
                while end < len(text) and text[end] not in "'\" \t":
                    end += 1
                parts.append(self.expand(text[index:end]))
                index = end
        return "".join(parts)

    def is_set(self, name: str) -> bool:
        """Checks if a variable name has been set in the parsed file values or
        in the active system environment."""
        return name in self.values or name in os.environ

    def get(self, name: str, default: str = "") -> str:
        """Gets a configuration or environment value by `name`, falling back to
        the provided `default` if empty or unset."""
        value = self.values[name] if name in self.values else os.environ.get(name, "")
        return value or default


def load_conf(root: str, relative: str) -> Config:
    """Creates a `Config` class instance bounded to a repository root path and
    loads its settings from a normalized forward-slash relative target file."""
    return Config({"PK_REPO_ROOT": root}).load(os.path.join(root, *relative.split("/")))
