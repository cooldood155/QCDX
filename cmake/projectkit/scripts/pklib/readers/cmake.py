"""CMake: what configure prints, its errors (also when CMake re-runs during a
build to regenerate the build files) and what 'cmake --install' prints."""

from __future__ import annotations

import os
import re
import sys
from typing import List, Optional, Tuple

from ..problems import fix_hint, fix_run, short_path
from . import Context, Diagnosis, LineFilter, documents, excerpt, line_filter, reader

CMAKE = "https://cmake.org/cmake/help/latest"

documents("PK500", f"{CMAKE}/manual/cmake.1.html")
documents("PK501", f"{CMAKE}/variable/CMAKE_LANG_COMPILER.html")
documents("PK502", "https://cmake.org/download/")
documents("PK503", f"{CMAKE}/command/find_package.html")
documents("PK504", f"{CMAKE}/manual/cmake.1.html#cmdoption-cmake-fresh")
documents("PK605", f"{CMAKE}/manual/cmake.1.html#install-a-project")


@line_filter("cmake")
class CMakeFilter(LineFilter):
    """Prints CMake's warnings and what the project's own message() calls say
    (meant to be read); hides the '-- ' status lines, which go to the status
    line, and the error, which is printed with the problem."""

    def line(self, text: str) -> Tuple[bool, str]:
        if text.startswith(("CMake Warning", "CMake Deprecation Warning")):
            self.block = "warning"
            return True, ""
        if text.startswith("CMake Error"):
            self.block = "error"
            return False, ""
        if self.block in ("warning", "error") and (not text.strip() or text.startswith((" ", "\t", "Call Stack"))):
            return self.block == "warning", ""
        if text.startswith(("The following files were removed", "The following files were added")):
            self.block = "glob"  # the globs noticed a change; the error says so when it matters
            return False, ""
        if self.block == "glob" and (not text.strip() or re.match(r"\s+[-+]", text)):
            return False, ""
        self.block = ""
        if text.startswith("-- "):
            return False, text[3:]
        return bool(text.strip()), ""


@line_filter("cmake-install")
class InstallFilter(LineFilter):
    def line(self, text: str) -> Tuple[bool, str]:
        if text.startswith(("-- Installing: ", "-- Up-to-date: ", "-- Set non-toolchain portion")):
            return False, text[3:]
        if text.startswith("-- Install configuration"):
            return False, ""
        return bool(text.strip()), ""


def error_blocks(text: str, limit: int = 24, first_paragraph: bool = False) -> List[str]:
    """The 'CMake Error' blocks: the heading and its indented lines (only up
    to the first blank line with `first_paragraph`)."""
    blocks: List[str] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("CMake Error"):
            inside = True
            if blocks:
                blocks.append("")
            blocks.append(line)
        elif inside and not line.strip() and first_paragraph and blocks[-1].strip():
            inside = False
        elif inside and (not line.strip() or line.startswith((" ", "\t", "Call Stack"))):
            blocks.append(line)
        else:
            inside = False
    while blocks and not blocks[-1].strip():
        blocks.pop()
    if len(blocks) > limit:
        blocks = blocks[:limit] + [f"... ({len(blocks) - limit} more lines in the log)"]
    return blocks


@excerpt("cmake")
def cmake_excerpt(text: str, context: Context) -> List[str]:
    return error_blocks(text, first_paragraph=True)


def is_kit_file(path: str) -> bool:
    return "projectkit/" in path.replace("\\", "/")


def first_error(text: str) -> Tuple[str, str]:
    """(where, what) of the first 'CMake Error'. `where` is the first place
    in the call stack outside the kit, so the line of your CMakeLists.txt
    that called the kit, not the kit's own message(); `what` is the message
    on one line, without the kit's "'pk_create_library' (func): " prefix."""
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines) if line.startswith("CMake Error")), -1)
    if start < 0:
        return "", ""
    heading = re.match(r"CMake Error(?: at (.+?):(\d+) \(([^)]*)\))?:?\s*(.*)$", lines[start])
    frames = [(heading.group(1), heading.group(2), heading.group(3))] if heading and heading.group(1) else []
    message: List[str] = [heading.group(4)] if heading and heading.group(4) else []
    in_stack = False
    for line in lines[start + 1:]:
        if line.startswith("Call Stack"):
            in_stack = True
        elif not line.strip():
            if in_stack:
                break
        elif not line.startswith((" ", "\t")):
            break
        elif in_stack:
            frame = re.match(r"\s+(.+?):(\d+) \(([^)]*)\)\s*$", line)
            if frame:
                frames.append((frame.group(1), frame.group(2), frame.group(3)))
        else:
            message.append(line.strip())
    what = re.sub(r"^'(\w+)' \(func\):\s*", r"\1: ", " ".join(message)).strip()
    own = next((frame for frame in frames if not is_kit_file(frame[0])), frames[0] if frames else None)
    where = f"{short_path(own[0])}:{own[1]} ({own[2]})" if own else ""
    return where, what


def glob_changes(text: str) -> Tuple[List[str], List[str]]:
    """The files CMake's globs found removed and added since the last
    configure (its 'GLOB mismatch!' report)."""
    removed: List[str] = []
    added: List[str] = []
    target: Optional[List[str]] = None
    for line in text.splitlines():
        if line.startswith("The following files were removed"):
            target = removed
        elif line.startswith("The following files were added"):
            target = added
        elif target is not None and re.match(r"\s+[-+]", line):
            target.append(short_path(line.strip()[1:]))
        else:
            target = None
    return removed, added


def compiler_hint() -> str:
    if sys.platform == "win32" or os.environ.get("MSYSTEM"):
        prefix = os.environ.get("MINGW_PACKAGE_PREFIX") or "mingw-w64-ucrt-x86_64"
        return f"pacman -S {prefix}-toolchain    (MSYS2; or install Visual Studio Build Tools)"
    if sys.platform == "darwin":
        return "xcode-select --install"
    return "sudo apt install build-essential    (or your distribution's compiler package)"


@reader("configure", order=50)
@reader("build", order=10)
def cmake_errors(text: str, context: Context) -> Optional[Diagnosis]:
    if "CMake Error" not in text and context.get("step") == "build":
        return None  # CMake did not re-run in this build
    details = context.get("excerpt") if context.get("tool") == "cmake" else error_blocks(text, first_paragraph=True)

    match = re.search(r"No CMAKE_(C|CXX)_COMPILER could be found", text)
    if match:
        language = "C++" if match.group(1) == "CXX" else "C"
        return Diagnosis("PK501", f"CMake found no {language} compiler", [
            fix_hint(compiler_hint()), fix_run(["pk", "configure", "--reset"], "after installing it")], details,
            (f"{CMAKE}/variable/CMAKE_LANG_COMPILER.html",))

    match = re.search(r"CMake (\d+\.\d+(?:\.\d+)?) or higher is required\.\s+You are running version (\S+)", text)
    if match:
        return Diagnosis("PK502", f"the project needs CMake {match.group(1)}, this one is {match.group(2)}",
                         [fix_hint("python -m pip install -U cmake    (or: pipx install cmake)")], details)

    match = (re.search(r'Could not find a package configuration file provided by\s+"([^"]+)"', text)
             or re.search(r'By not providing "Find([^"]+)\.cmake"', text))
    if match:
        name = match.group(1)
        where = re.search(r"CMake Error at ([^\s:]+:\d+) \(find_package\)", text)
        why = f"find_package({name}) found nothing{' at ' + where.group(1) if where else ''}"
        return Diagnosis("PK503", why, [fix_hint(f"pk dep add the package that provides {name}"),
                                        fix_hint("or install the system package with its development files")],
                         details, (f"{CMAKE}/command/find_package.html",))

    if re.search(r"does not match the source|Does not match the generator used previously"
                 r"|is different than the directory", text):
        return Diagnosis("PK504", "the build tree was configured from somewhere else", [
            fix_run(["pk", "configure", "--reset"], "configure it fresh")], details)

    match = re.search(r"Could not find toolchain file:?\s*\"?([^\s\"]+)", text)
    if match:
        return Diagnosis("PK505", f"{match.group(1)} does not exist", [
            fix_run(["pk", "deps", "--update"], "install the dependencies again, which writes it")], details)

    where, what = first_error(text)
    removed, _added = glob_changes(text)
    noticed = f"; since the last build these were removed: {', '.join(removed)}" if removed else ""

    match = re.search(r"(Sources|Public headers) are required\s+when\s+the\s+'(REQUIRE_\w+)'\s+option", text)
    if match:
        files = "source files" if match.group(1) == "Sources" else "public headers"
        command = where.rsplit("(", 1)[-1].rstrip(")") if "(" in where else "the target"
        place = where.split(" (")[0] or "?"
        fixes = [fix_hint(f"git restore {' '.join(removed)}    (when deleting them was a mistake)")] if removed else []
        fixes += [fix_hint(f"add {'a .cpp' if files == 'source files' else 'a header'} where the target looks "
                           "for its files"),
                  fix_hint(f"remove {match.group(2)} from {place} when the target really has none")]
        return Diagnosis("PK506", f"{command} at {place} needs {files} ({match.group(2)}) and found none{noticed}",
                         fixes, details)

    if "CMake Error" not in text:
        return None
    return Diagnosis("PK500", f"{where + ': ' if where else ''}{what}{noticed}",
                     [fix_hint("pk configure --reset    (when the build tree itself is the problem)")],
                     error_blocks(text))
