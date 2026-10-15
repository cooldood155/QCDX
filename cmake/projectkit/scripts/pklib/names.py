from __future__ import annotations

import os
import re
from typing import List

RESERVED_CMAKE_CTEST = {
    "all", "clean", "edit_cache", "help", "install", "list_install_components", "package",
    "package_source", "rebuild_cache", "test",
}
RESERVED_CXX_NAMESPACE = {
    "alignas", "alignof", "and", "and_eq", "asm", "auto", "bitand", "bitor", "bool", "break", "case",
    "catch", "char", "char8_t", "char16_t", "char32_t", "class", "compl", "concept", "const",
    "consteval", "constexpr", "constinit", "const_cast", "continue", "contract_assert", "co_await",
    "co_return", "co_yield", "decltype", "default", "delete", "do", "double", "dynamic_cast", "else",
    "enum", "explicit", "export", "extern", "false", "float", "for", "friend", "goto", "if", "inline",
    "int", "long", "mutable", "namespace", "new", "noexcept", "not", "not_eq", "nullptr", "operator",
    "or", "or_eq", "private", "protected", "public", "register", "reinterpret_cast", "requires",
    "return", "short", "signed", "sizeof", "static", "static_assert", "static_cast", "struct",
    "switch", "template", "this", "thread_local", "throw", "true", "try", "typedef", "typeid",
    "typename", "union", "unsigned", "using", "virtual", "void", "volatile", "wchar_t", "while", "xor",
    "xor_eq", "std", "posix",
}
RESERVED_MACROS = {"linux", "unix"}
RESERVED_WINDOWS = {"con", "prn", "aux", "nul"} | {f"com{n}" for n in range(10)} | {f"lpt{n}" for n in range(10)}
KIT_CODE = (".cmake", ".in", ".sh", ".py", ".conf")


def problem(name: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,100}", name):
        return f"'{name}' must match [a-z][a-z0-9_]+ (2-101 characters), it is also the C++ namespace"
    if "__" in name:
        return f"'{name}' cannot contain '__', reserved by C++"
    if name in RESERVED_CMAKE_CTEST:
        return f"'{name}' is a reserved CMake/CTest target name"
    if name in RESERVED_CXX_NAMESPACE or re.fullmatch(r"std[0-9]+", name):
        return f"'{name}' is a reserved C++ keyword or namespace name"
    if name in RESERVED_MACROS:
        return f"'{name}' is a macro GCC/Clang predefine in GNU modes"
    if name in RESERVED_WINDOWS:
        return f"'{name}' is a reserved Windows device name"
    return ""


def name_forms(name: str) -> List[str]:
    return [name.upper(), name[:1].upper() + name[1:], name]


def name_pattern(name: str) -> "re.Pattern[bytes]":
    upper, title, lower = (re.escape(form.encode()) for form in name_forms(name))
    forms = upper + rb"(?![A-Za-z0-9])|" + title + rb"(?![a-z0-9])|" + lower + rb"(?![a-z0-9])"
    return re.compile(rb"(?<![A-Za-z0-9_])(_*)(" + forms + rb")")


def kit_uses(name: str, kit: str) -> List[str]:
    pattern = name_pattern(name)
    found = []
    for directory, dirs, files in os.walk(kit):
        dirs[:] = sorted(d for d in dirs if d not in ("build", "__pycache__"))
        for file_name in sorted(files):
            path = os.path.join(directory, file_name)
            if not file_name.endswith(KIT_CODE) or os.path.islink(path):
                continue
            try:
                with open(path, "rb") as file:
                    data = file.read()
            except OSError:
                continue
            if b"\0" in data or not pattern.search(data):
                continue
            for number, line in enumerate(data.splitlines(), 1):
                if pattern.search(line):
                    text = line.decode("utf-8", "replace").strip()
                    found.append(f"{path.replace(os.sep, '/')}:{number}: {text[:100]}")
    return found
