"""Registry of every target the ProjectKit verify script knows how to verify.

Record fields: name, kind, os, arch, env, probe, description
  os     host OS family required: linux, macos, windows, any
  arch   host arch required: x86_64, armv8, any
  env    MSYS2 environment required (MSYSTEM value), or "-"
  probe  executable that must be on PATH, or "-"

A target is only reported as runnable when every field it names is satisfied,
an environment you don't have installed shows up as such rather than being
attempted and failing. The "possible" mode checks only os and arch.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple, Union

from .common import have, host_arch, host_platform, tool_env

RECORDS = (
    ("linux-x86_64", "native", "linux", "x86_64", "-", "-", "Linux x86_64, native toolchain"),
    ("linux-armv8", "native", "linux", "armv8", "-", "-", "Linux armv8, native toolchain"),
    ("macos-x86_64", "native", "macos", "x86_64", "-", "-", "macOS x86_64, Apple Clang"),
    ("macos-armv8", "native", "macos", "armv8", "-", "-", "macOS armv8, Apple Clang"),
    ("windows-ucrt64", "native", "windows", "x86_64", "UCRT64", "gcc",
     "Windows x86_64, MSYS2 UCRT64 (GCC, UCRT)"),
    ("windows-clang64", "native", "windows", "x86_64", "CLANG64", "clang",
     "Windows x86_64, MSYS2 CLANG64 (Clang, libc++)"),
    ("windows-clangarm64", "native", "windows", "armv8", "CLANGARM64", "clang",
     "Windows armv8, MSYS2 CLANGARM64 (Clang, libc++)"),
    ("cross-x86_64-linux-gnu", "cross", "any", "any", "-", "x86_64-linux-gnu-gcc",
     "Cross to Linux x86_64 via x86_64-linux-gnu"),
    ("cross-aarch64-linux-gnu", "cross", "any", "any", "-", "aarch64-linux-gnu-gcc",
     "Cross to Linux armv8 via aarch64-linux-gnu"),
    ("cross-x86_64-mingw-w64", "cross", "any", "any", "-", "x86_64-w64-mingw32-gcc",
     "Cross to Windows x86_64 via MinGW-w64 GCC"),
    ("cross-aarch64-mingw-llvm-w64", "cross", "any", "any", "-", "aarch64-w64-mingw32-clang",
     "Cross to Windows armv8 via llvm-mingw"),
)

DEFAULT_TYPE_STAGES = ["workflow", "library_matrix", "auto_discovery", "install", "consumer",
                       "cpack", "host_tools"]


def record(name: str) -> Optional[Tuple[str, ...]]:
    for entry in RECORDS:
        if entry[0] == name:
            return entry
    return None


def availability(name: str, root: str, mode: str = "strict") -> Optional[Tuple[bool, str]]:
    entry = record(name)
    if entry is None:
        return None
    _, kind, want_os, want_arch, want_env, probe, _ = entry

    if want_os != "any" and want_os != host_platform():
        return False, f"needs {want_os} host, this is {host_platform()}"
    if want_arch != "any" and want_arch != host_arch():
        return False, f"needs {want_arch} host, this is {host_arch()}"

    # os and arch are the only properties of the machine itself: everything below
    # is something you could install or a terminal you could open.
    if mode == "possible":
        return True, ""

    # PATH decides which MSYS2 environment builds: an MSYS2 launcher puts its own
    # bin first, and outside one (PowerShell, cmd, Git Bash) it is whichever bin
    # the user added. MSYSTEM alone proves nothing: Git Bash sets MINGW64.
    if want_env != "-" and tool_env(probe) != want_env:
        active = os.environ.get("MSYSTEM")
        shell = f", this shell is {active}" if active else ""
        return False, f"needs {want_env}'s {probe} first on PATH{shell}"

    if probe != "-" and not have(probe):
        return False, f"{probe} not on PATH"

    if kind == "cross":
        triple = name[len("cross-"):]
        if not os.path.isfile(os.path.join(root, "profiles", triple)):
            return False, f"no profiles/{triple}"

    return True, ""


def runnable(name: str, root: str, mode: str = "strict") -> bool:
    result = availability(name, root, mode)
    return bool(result and result[0])


def configure(name: str, root: str) -> Optional[Dict[str, Union[str, List[str]]]]:
    entry = record(name)
    if entry is None and not name.startswith("cross-"):
        return None
    settings: Dict[str, Union[str, List[str]]] = {
        "platform_label": entry[6] if entry else "",
        "build_profile": os.path.join(root, "profiles", "native"),
        "host_profile": "",
        "preset_prefix": "native",
        "library_types": ["STATIC", "SHARED", "STATIC+SHARED"],
        "required_tools": ["conan", "cmake", "ctest", "ninja", "git"],
        "setup_stages": ["environment", "clean_slate"],
        "type_stages": list(DEFAULT_TYPE_STAGES),
        "final_stages": ["reset"],
    }
    if name.startswith("cross-"):
        triple = name[len("cross-"):]
        settings.update({
            "host_profile": os.path.join(root, "profiles", triple),
            "preset_prefix": triple,
            "library_types": ["STATIC", "SHARED"],
            "required_tools": ["conan", "cmake", "ninja", "git"],
            "type_stages": ["host_tools_for_cross", "cross_build", "library_matrix"],
        })
    return settings
