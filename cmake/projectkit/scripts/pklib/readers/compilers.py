"""GCC, Clang and MSVC, and their linkers (ld, lld, link.exe, Apple's ld):
the errors they print, under any build tool."""

from __future__ import annotations

import os
import re
from typing import Optional

from ..problems import fix_hint, short_path
from . import Context, Diagnosis, reader

# path:line[:column]: [fatal] error: message (GCC, Clang; Windows paths too)
# path(line[,column]): [fatal] error C1234: message (MSVC)
ERROR = re.compile(r"^(?P<file>(?:[A-Za-z]:)?[^\s:][^:]*?):(?P<line>\d+)(?::(?P<column>\d+))?: "
                   r"(?:fatal )?error: (?P<message>.*)$|"
                   r"^(?P<mfile>.+?)\((?P<mline>\d+)(?:,\d+)?\): (?:fatal )?error (?P<mmessage>\w+: .*)$")

NO_MAIN = re.compile(r"undefined reference to [`'](?:WinMain|wWinMain|main)'|unresolved external symbol "
                     r"_?w?(?:WinMain|main)\b|Undefined symbols for architecture \S+:\s*\"_main\"")


@reader("build", order=40)
def no_main(text: str, context: Context) -> Optional[Diagnosis]:
    if not NO_MAIN.search(text):
        return None
    program = str(context.get("target") or "the executable")
    # the link command: the line naming the program and its objects, which CMake
    # keeps at <dir>/CMakeFiles/<target>.dir/<source>.o(bj)
    objects = r"(\S+?)/CMakeFiles/[^/\s]+\.dir/(\S+?)\.(?:obj|o)\b"
    link = next((line for line in text.splitlines() if context.get("target") and str(context["target"]) in
                 line.replace("\\", "/") and re.search(objects, line) and not line.startswith("FAILED")), "")
    sources = sorted({f"{folder}/{source}" for folder, source in re.findall(objects, link)
                      if not source.startswith("__/")})
    mingw = " (MinGW then looks for WinMain instead)" if "WinMain" in text else ""
    where = f" in {sources[0]}" if len(sources) == 1 else ""
    details = [line for line in context.get("excerpt", []) if "crtexe" not in line or "undefined" in line]
    return Diagnosis("PK606", f"{program} has no main(){mingw}", [
        fix_hint(f"define int main(){where}, outside any namespace (with wxWidgets: wxIMPLEMENT_APP)"),
        fix_hint("when main() or wxIMPLEMENT_APP is in a static library, move it into the app's own source: "
                 "the linker skips a library's files that nothing in the program calls into"),
        fix_hint("or add the file that has main() to the app")], details)


@reader("build", order=50)
def link_error(text: str, context: Context) -> Optional[Diagnosis]:
    match = (re.search(r"undefined reference to [`'](.+?)'", text)
             or re.search(r"unresolved external symbol \"?(.+?)\"? referenced", text)
             or re.search(r"Undefined symbols for architecture \S+:\s*\"(.+?)\"", text))
    if not match:
        return None
    used = re.search(r"in function [`'](.+?)'", text)
    why = f"nothing defines {match.group(1)}" + (f" (used in {used.group(1)})" if used else "")
    return Diagnosis("PK601", why, [fix_hint("define it, add the source file that defines it to the target, or "
                                             "link the library that has it")])


@reader("build", order=60)
def missing_header(text: str, context: Context) -> Optional[Diagnosis]:
    match = (re.search(r"fatal error: ([^\s:]+): No such file or directory", text)
             or re.search(r"fatal error: '([^']+)' file not found", text)
             or re.search(r"C1083: Cannot open include file: '([^']+)'", text))
    if not match:
        return None
    where = next((found for found in map(ERROR.match, text.splitlines()) if found), None)
    at = f" ({short_path(where.group('file') or where.group('mfile'))}:{where.group('line') or where.group('mline')})" \
        if where else ""
    return Diagnosis("PK602", f"no header {match.group(1)} on the include path{at}", [
        fix_hint("when deps.json has the package, link it to the target that includes it: "
                 "pk_create_library(... DEPS_PUBLIC NAME) if a public header includes it, else DEPS_PRIVATE; "
                 "pk_create_app(... DEPS NAME)"),
        fix_hint("otherwise 'pk dep add' the package that has it, or check the spelling")])


@reader("build", order=70)
def compile_error(text: str, context: Context) -> Optional[Diagnosis]:
    for line in text.splitlines():
        found = ERROR.match(line)
        if found:
            file = found.group("file") or found.group("mfile")
            number = found.group("line") or found.group("mline")
            message = found.group("message") or found.group("mmessage")
            hint = f"start at {os.path.basename(file)} line {number}; later errors often follow from the first"
            return Diagnosis("PK600", f"{short_path(file)}:{number}: {message}", [fix_hint(hint)])
    return None
