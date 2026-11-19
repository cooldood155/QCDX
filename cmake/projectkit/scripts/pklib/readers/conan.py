"""Conan, the deps step: its ERROR block, and the errors it is known for.

context["profiles"] lists the profile files the install used (relative to
context["root"]), where a setting can be fixed."""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Tuple

from ..problems import fix_edit, fix_hint, fix_run, fix_steps
from . import Context, Diagnosis, LineFilter, documents, excerpt, line_filter, reader

CONAN = "https://docs.conan.io/2"

documents("PK400", f"{CONAN}/reference/commands/install.html")
documents("PK401", f"{CONAN}/reference/extensions/profile_plugin.html", f"{CONAN}/reference/config_files/profiles.html")
documents("PK402", f"{CONAN}/reference/commands/remote.html")
documents("PK403", f"{CONAN}/tutorial/versioning/version_ranges.html")
documents("PK404", f"{CONAN}/tutorial/versioning/lockfiles.html")
documents("PK405", f"{CONAN}/reference/commands/profile.html")
documents("PK406", f"{CONAN}/reference/config_files/settings.html")
documents("PK407", f"{CONAN}/reference/commands/install.html")


@line_filter("conan")
class ConanFilter(LineFilter):
    """Nothing is printed while Conan works (its WARN lines are mostly
    deprecation notes); the status line shows its stage or last line."""

    def line(self, text: str) -> Tuple[bool, str]:
        heading = re.match(r"^=+ (.+?) =+$", text)
        return False, heading.group(1) if heading else text.strip()


@excerpt("conan")
def error_block(text: str, context: Context, limit: int = 14) -> List[str]:
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines) if line.startswith("ERROR:")), -1)
    if start < 0:
        return [line for line in lines if line.strip()][-limit:]
    block = [line for line in lines[start:] if line.strip()]
    return block[:limit] + ([f"... ({len(block) - limit} more lines in the log)"] if len(block) > limit else [])


def key_lines(block: List[str]) -> List[str]:
    """The lines of the ERROR block that say what is wrong, without a
    plugin's traceback."""
    keep = [line.strip() for line in block if line.startswith("ERROR:") or "Exception:" in line]
    return keep[-2:] or block


def std_order(value: str) -> int:
    """C/C++ standards in order, '98' and '99' first."""
    try:
        number = int(value)
    except ValueError:
        return -1
    return number - 100 if number >= 90 else number


@reader(("configure", "build"), order=5)
def library_not_in_package(text: str, context: Context) -> Optional[Diagnosis]:
    """CMakeDeps: the recipe names a library the package does not have."""
    match = re.search(r"Library '([^']+)' not found in package", text)
    if not match:
        return None
    library = match.group(1)
    if re.fullmatch(r"wx(?:scintilla|lexilla)d?", library):
        # the recipe names them wxscintilla/wxlexilla on Windows, MinGW names are wxscintilla-3.3
        named = f"{library.rstrip('d')}-3.3"
        return Diagnosis("PK408", f"Conan's wxwidgets recipe looks for {library}, but MinGW builds name it {named} "
                                  "(part of wxStyledTextCtrl, the code-editor control)",
                         [fix_run(["pk", "dep", "set", "wxwidgets", "--option", "stc=False"],
                                  "build wxWidgets without wxStyledTextCtrl")],
                         docs=(f"{CONAN}/reference/tools/cmake/cmakedeps.html",))
    if not re.fullmatch(r"wx_(?:msw|base)\w*-\d+\.\d+", library):
        return Diagnosis("PK408", f"the package's recipe says it has {library}, but its files are named differently",
                         [fix_hint("report it to the package's recipe (conan-center-index), with the log")],
                         docs=(f"{CONAN}/reference/tools/cmake/cmakedeps.html",))
    return wxwidgets_mingw_names(library, context)


def wxwidgets_mingw_names(library: str, context: Context) -> Diagnosis:
    """Conan Center's wxwidgets on MinGW wants wx_mswu_core-3.3 and, for
    Debug, wx_mswud_core-3.3. wxWidgets' CMake names them wxmsw33u(d)_core
    unless told otherwise (it does whenever CMake is not MSYS2's own, like
    Conan's cmake), and with MinGW names it never adds the 'd'. So: MinGW
    names (an option) and wxWidgets built as Release, which MinGW can link
    into a Debug app; that one build then serves Debug and Release. The
    recipe also names wxStyledTextCtrl's two libraries wrong for MinGW, so
    that control is left out (stc=False), in the same rebuild."""
    root = str(context.get("root", "."))
    try:
        with open(os.path.join(root, "deps.json"), encoding="utf-8") as file:
            manifest = file.read()
    except OSError:
        manifest = ""
    options = []
    if "wxBUILD_WIN32_MSVC_NAMING" not in manifest:
        options += ["--option", "custom_disables=wxBUILD_WIN32_MSVC_NAMING"]
    if not re.search(r'"stc"\s*:', manifest):
        options += ["--option", "stc=False"]
    steps: List[Dict[str, object]] = []
    if options:
        steps.append(fix_run(["pk", "dep", "set", "wxwidgets", *options], "MinGW names"))
    debug = bool(re.match(r"wx_(?:msw|base)ud", library))
    profiles = [str(profile) for profile in context.get("profiles", [])]  # type: ignore[union-attr]
    profile = profiles[0] if profiles else ""
    if debug and profile:
        try:
            with open(os.path.join(root, profile), encoding="utf-8") as file:
                pinned = "wxwidgets/*:build_type" in file.read()
        except OSError:
            pinned = True
        if not pinned:
            steps.append(fix_edit(profile, r"^\[settings\][ \t]*(?=\r?$)", "[settings]\nwxwidgets/*:build_type=Release",
                                  f"add wxwidgets/*:build_type=Release to [settings] in {profile}"))
    why = (f"Conan's wxwidgets recipe looks for {library}, a name wxWidgets' own build never makes on MinGW"
           + (" (MinGW names have no 'd' for Debug)" if debug else ""))
    if not steps:
        fix = fix_hint("report it to conan-center-index (recipes/wxwidgets): its MinGW library names are wrong")
    elif len(steps) == 1:
        fix = dict(steps[0], rerun=True)
    else:
        fix = fix_steps(steps, "MinGW names, no wxStyledTextCtrl, and wxWidgets built as Release (one build "
                               "for Debug and Release)")
    return Diagnosis("PK408", why, [fix], docs=(f"{CONAN}/reference/tools/cmake/cmakedeps.html",))


# function prefixes of Windows system libraries that recipes have been seen to leave out
SYSTEM_LIBRARIES = (("Gdip", "gdiplus", "GDI+"),)


@reader("build", order=35)
def package_missing_system_library(text: str, context: Context) -> Optional[Diagnosis]:
    """A static package's library uses a system library its recipe does not
    list (Conan Center's wxwidgets and GDI+ on MinGW)."""
    for prefix, library, name in SYSTEM_LIBRARIES:
        found = re.search(rf"/p/lib/([^/(]+)\.(?:a|lib)\(.*undefined reference to [`']{prefix}\w*'", text)
        if found:
            package = re.search(r"/p/b/([a-z]+)", text)
            wx = package and package.group(1).startswith("wxwid")
            target = "wxWidgets::wxWidgets" if wx else "<package target>"
            why = f"{found.group(1)} uses {name}, but the package's recipe does not link {library}"
            link = f"if(MINGW) target_link_libraries({target} INTERFACE {library}) endif()"
            return Diagnosis("PK409", why, [fix_hint(f"after its pk_create_*: {link}")])
    return None


@reader("deps", "conan")
def conan_errors(text: str, context: Context) -> Optional[Diagnosis]:
    match = re.search(r"compiler\.(cstd|cppstd)=(\S+) is not supported by (\S+) (\S+)\.\s*"
                      r"Supported values are: \[([^\]]*)\]", text)
    if match:
        setting, value, compiler, version, supported = match.groups()
        values = re.findall(r"'([^']+)'", supported)
        gnu = value.startswith("gnu")
        numbers = [item for item in values if item.startswith("gnu") == gnu] or values
        best = max(numbers, key=lambda item: std_order(item.replace("gnu", ""))) if numbers else ""
        fixes: List[Dict[str, object]] = []
        pattern = rf"^([ \t]*compiler\.{setting}[ \t]*=[ \t]*){re.escape(value)}[ \t]*(?=\r?$)"
        for profile in context.get("profiles", []):  # type: ignore[union-attr]
            try:
                with open(os.path.join(str(context.get("root", ".")), profile), encoding="utf-8") as file:
                    found = re.search(pattern, file.read(), re.MULTILINE)
            except OSError:
                found = None
            if found and best:
                fixes.append(fix_edit(profile, pattern, rf"\g<1>{best}", f"set compiler.{setting}={best} in {profile}"))
                break
        if not fixes and best:
            fixes.append(fix_hint(f"set compiler.{setting}={best} in the Conan profile that sets it"))
        fixes.append(fix_hint(f"or use a newer {compiler}, one Conan allows compiler.{setting}={value} for"))
        return Diagnosis("PK401", f"Conan's profile plugin rejects compiler.{setting}={value} for {compiler} "
                                  f"{version}; it takes {', '.join(values)}", fixes,
                         key_lines(list(context.get("excerpt", []))),  # type: ignore[arg-type]
                         (f"{CONAN}/reference/extensions/profile_plugin.html",
                          f"{CONAN}/reference/config_files/profiles.html"))

    if re.search(r"Unable to connect to remote|Could not connect|ConnectionError|Max retries exceeded"
                 r"|Name or service not known|SSLError|certificate verify failed", text):
        remote = re.search(r"Unable to connect to remote (\S+?)=", text)
        return Diagnosis("PK402", f"Conan could not reach the remote{' ' + remote.group(1) if remote else ''}", [
            fix_hint("check the network or proxy, then run the command again"),
            fix_run(["pk", "deps", "--", "--no-remote"], "when every package is in the Conan cache already",
                    rerun=False),
            fix_hint("conan remote list")], docs=(f"{CONAN}/reference/commands/remote.html",))

    match = (re.search(r"Package '([^']+)' not resolved", text)
             or re.search(r"Version range '([^']*)' from requirement '([^']+)'", text)
             or re.search(r"Unable to find '([^']+)' in remotes", text))
    if match:
        wanted = match.group(match.lastindex or 1)
        name = wanted.split("/")[0]
        return Diagnosis("PK403", f"no Conan remote has a package matching '{wanted}'", [
            fix_hint(f"conan search {name} -r conancenter    (what exists)"),
            fix_hint("conan remote list    (is a remote enabled at all?)"),
            fix_hint(f"pk dep set {name} --range ...    (change the requirement in deps.json)")],
            docs=(f"{CONAN}/tutorial/versioning/version_ranges.html",))

    match = re.search(r"Requirement '([^']+)' not in lockfile", text)
    if match:
        return Diagnosis("PK404", f"{match.group(1)} is required but conan.lock does not have it", [
            fix_run(["pk", "dep", "lock"], "write conan.lock again from deps.json")],
            docs=(f"{CONAN}/tutorial/versioning/lockfiles.html",))

    if re.search(r"(?:default|build) profile .*doesn't exist|Profile not found: default", text):
        return Diagnosis("PK405", "Conan has no default profile on this machine", [
            fix_run(["conan", "profile", "detect", "--exist-ok"], "create it")],
            docs=(f"{CONAN}/reference/commands/profile.html",))

    match = re.search(r"Invalid setting '([^']+)' is not a valid 'settings\.compiler\.version' value", text)
    if match:
        return Diagnosis("PK406", f"this Conan does not know compiler version {match.group(1)}", [
            fix_hint("python -m pip install -U conan    (or: pipx upgrade conan)")],
            docs=(f"{CONAN}/reference/config_files/settings.html",))

    match = re.search(r"^ERROR: ([^\s:]+): Error in (?:build|source|package)\(\) method", text, re.MULTILINE)
    if match:
        return Diagnosis("PK407", f"building {match.group(1)} from source failed", [
            fix_hint("the log has the package's build output; another version may have a prebuilt binary")])

    first = next((line[len("ERROR:"):].strip() for line in context.get("excerpt", [])  # type: ignore[union-attr]
                  if line.startswith("ERROR:")), "")
    return Diagnosis("PK400", first, docs=(f"{CONAN}/reference/commands/install.html",)) if first else None
