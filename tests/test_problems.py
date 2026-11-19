"""The error catalog (pklib/problems.py), the readers that explain each
tool's output and pick what quiet steps print (pklib/readers/), and 'pk fix'
/ 'pk explain'."""

import json
import re
import sys

import pytest

from conftest import ROOT, requires_git

sys.path.insert(0, str(ROOT / "cmake" / "projectkit" / "scripts"))

from pklib import problems as P  # noqa: E402
from pklib import readers  # noqa: E402

KIT_DOCS = ROOT / "cmake" / "projectkit" / "docs"

CONAN_CSTD = """\
detect_api: Found cc=gcc-13.3.0
ERROR: Error while processing 'profile.py' plugin, line 14
\t_check_correct_cstd(settings)
while calling '_check_correct_cstd', line 45
\tConanException: The provided compiler.cstd=23 is not supported by gcc 13. Supported values are: ['99', 'gnu99', \
'11', 'gnu11', '17', 'gnu17']
"""

CMAKE_FIND_PACKAGE = """\
-- demo: library 'demo' detected as COMPILED
CMake Error at CMakeLists.txt:54 (find_package):
  By not providing "FindFooBarLib.cmake" in CMAKE_MODULE_PATH this project
  has asked CMake to find a package configuration file provided by
  "FooBarLib", but CMake did not find one.

  Could not find a package configuration file provided by "FooBarLib" with
  any of the following names:


-- Configuring incomplete, errors occurred!
"""

NINJA_COMPILE = """\
[0/2] Re-checking globbed directories...
[1/4] Building CXX object src/CMakeFiles/demo.dir/demo/other.cpp.o
src/demo/other.cpp:3:9: warning: unused variable 'z' [-Wunused-variable]
[2/4] Building CXX object src/CMakeFiles/demo.dir/demo/core.cpp.o
FAILED: [code=1] src/CMakeFiles/demo.dir/demo/core.cpp.o
/usr/bin/c++ -DDEMO -I/demo/include -std=c++23 -o src/CMakeFiles/demo.dir/demo/core.cpp.o -c /demo/src/demo/core.cpp
/demo/src/demo/core.cpp: In function 'int broken()':
/demo/src/demo/core.cpp:16:23: error: 'undefined_thing' was not declared in this scope
   16 | int broken() { return undefined_thing; }
      |                       ^~~~~~~~~~~~~~~
ninja: build stopped: subcommand failed.
"""

NINJA_LINK = """\
[4/5] Linking CXX executable bin/demo
FAILED: [code=1] bin/demo
: && /usr/bin/c++ -m64 -g apps/main.cpp.o -o bin/demo lib/libdemo.a && :
/usr/bin/ld: lib/libdemo.a(core.cpp.o): in function `user()':
/demo/src/demo/core.cpp:17:(.text._Z4userv+0x9): undefined reference to `missing_def()'
collect2: error: ld returned 1 exit status
ninja: build stopped: subcommand failed.
"""

CTEST = """\
Test project /demo/build/native-debug
    Start 1: core_works
1/2 Test #1: core_works .......................   Passed    0.01 sec
    Start 2: core_breaks
2/2 Test #2: core_breaks ......................***Failed    0.02 sec
tests_core.cpp:12: FAILED:
  REQUIRE( demo::answer() == 42 )

50% tests passed, 1 tests failed out of 2

Total Test time (real) =   0.03 sec

The following tests FAILED:
\t  2 - core_breaks (Failed)
Errors while running CTest
"""


# Evan's MinGW link of an app without main(), on Windows
MINGW_NO_MAIN = """\
[1/2] Linking CXX executable bin\\incremental.exe
FAILED: [code=1] bin/incremental.exe
C:\\WINDOWS\\system32\\cmd.exe /C "cd . && C:\\msys64\\ucrt64\\bin\\x86_64-w64-mingw32-g++.exe -m64 -g \
apps/CMakeFiles/incremental_app.dir/incremental/main.cpp.obj \
apps/CMakeFiles/incremental_app.dir/__/generated/incremental/app_paths.cpp.obj \
-o bin\\incremental.exe lib/libincremental.a"
C:/msys64/ucrt64/bin/../lib/gcc/x86_64-w64-mingw32/16.2.0/../../../../x86_64-w64-mingw32/bin/ld.exe: \
C:/msys64/ucrt64/lib/libmingw32.a(lib64_libmingw32_a-crtexewin.o): in function `main':
D:/W/B/src/mingw-w64/mingw-w64-crt/crt/crtexewin.c:62:(.text.startup+0xc6): undefined reference to `WinMain'
collect2.exe: error: ld returned 1 exit status
ninja: build stopped: subcommand failed.
"""

# ... and the build after deleting the library's only source file
CMAKE_RERUN_NO_SOURCES = """\
[0/2] Re-checking globbed directories...
-- GLOB mismatch!
The following files were removed:
  -K:/Projects/incremental/src/incremental/core.cpp

[1/2] Re-running CMake...
-- incremental: Private headers are not required for library target 'incremental'.
CMake Error at cmake/projectkit/LibraryCreator.cmake:413 (message):
  'pk_create_library' (func): Sources are required when the 'REQUIRE_SOURCES'
  option is provided, yet no 'SOURCES' were provided.
Call Stack (most recent call first):
  src/CMakeLists.txt:1 (pk_create_library)


-- Configuring incomplete, errors occurred!

FAILED: [code=1] build.ninja K:/Projects/incremental/build/native-debug/cmake_install.cmake
C:\\msys64\\ucrt64\\bin\\cmake.exe --regenerate-during-build -SK:\\Projects\\incremental
ninja: error: rebuilding 'build.ninja': subcommand failed
"""


def kept(tool, text):
    keep_filter = readers.filter_for(tool)
    return [line for line in text.splitlines() if keep_filter.feed(line)[0]], keep_filter.warnings


def slug(heading):
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


# Every code has a title, an explanation and at least one place to read more
@pytest.mark.parametrize("code", sorted(P.CATALOG))
def test_every_code_is_complete(code):
    entry = P.CATALOG[code]
    assert re.fullmatch(r"PK[1-9]\d\d", code)
    assert entry.title and entry.explain.strip() and entry.docs


# Every kit document an error points at exists, and so does its #anchor
def test_kit_docs_and_anchors_exist():
    for entry in P.CATALOG.values():
        for doc in entry.docs:
            if not doc.startswith("kit:"):
                assert doc.startswith("https://")
                continue
            name, _, anchor = doc[len("kit:"):].partition("#")
            path = KIT_DOCS / name
            assert path.is_file(), doc
            if anchor:
                headings = re.findall(r"^#+ (.+)$", path.read_text(encoding="utf-8"), re.MULTILINE)
                assert anchor in [slug(heading) for heading in headings], doc


# Conan's cstd refusal is read, with the highest standard the compiler takes as the fix
def test_conan_standard_refusal(tmp_path):
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "native").write_text("[settings]\ncompiler.cppstd=23\ncompiler.cstd=23\n")
    code, why, fixes, details, docs = P.diagnose("deps", "conan", CONAN_CSTD,
                                                 {"profiles": ["profiles/native"], "root": str(tmp_path)})
    assert code == "PK401" and "compiler.cstd=23" in why and "gcc 13" in why
    assert any("profile_plugin" in doc for doc in docs)
    assert fixes[0]["edit"][0] == "profiles/native" and "compiler.cstd=17" in fixes[0]["say"]
    assert any("ConanException" in line for line in details)
    assert not any("_check_correct_cstd" in line for line in details)


# A missing find_package is named, with where it was asked for
def test_cmake_find_package():
    code, why, fixes, details, _docs = P.diagnose("configure", "cmake", CMAKE_FIND_PACKAGE)
    assert code == "PK503" and "FooBarLib" in why and "CMakeLists.txt:54" in why
    assert details[0].startswith("CMake Error at") and "Could not find" not in "\n".join(details)


# A compile error points at the first error's file and line, without the command line
def test_compile_error():
    code, why, fixes, details, _docs = P.diagnose("build", "ninja", NINJA_COMPILE)
    assert code == "PK600" and "core.cpp:16" in why and "undefined_thing" in why
    assert not any(line.startswith("/usr/bin/c++") for line in details)
    verbose = P.diagnose("build", "ninja", NINJA_COMPILE, {"verbose": True})[3]
    assert any(line.startswith("/usr/bin/c++") for line in verbose)


# Windows paths (K:/...) are read like any other
def test_compile_error_with_a_windows_path():
    text = NINJA_COMPILE.replace("/demo/src", "K:/Projects/demo/src")
    code, why, _fixes, _details, _docs = P.diagnose("build", "ninja", text)
    assert code == "PK600" and why.startswith("K:/Projects/demo/src/demo/core.cpp:16:")


# An app without main() says so, also when MinGW asks for WinMain, and names the file
def test_no_main():
    code, why, fixes, details, _docs = P.diagnose("build", "ninja", MINGW_NO_MAIN)
    assert code == "PK606" and "bin/incremental.exe has no main()" in why and "WinMain" in why
    assert "apps/incremental/main.cpp" in fixes[0]["say"]
    assert not any("cmd.exe" in line for line in details)


# A kit error points at the line of the project that called the kit, and says what changed
def test_kit_error_points_at_the_project():
    code, why, fixes, _details, _docs = P.diagnose("build", "ninja", CMAKE_RERUN_NO_SOURCES)
    assert code == "PK506"
    assert "pk_create_library at src/CMakeLists.txt:1 needs source files" in why
    assert "LibraryCreator" not in why and "removed: K:/Projects/incremental/src/incremental/core.cpp" in why
    assert "git restore" in fixes[0]["say"]
    lines, _ = kept("ninja", CMAKE_RERUN_NO_SOURCES)
    assert lines == []


# A link error names the missing symbol and where it is used
def test_link_error():
    code, why, _fixes, _details, _docs = P.diagnose("build", "ninja", NINJA_LINK)
    assert code == "PK601" and "missing_def()" in why and "user()" in why


# The failed tests are named, and the fix reruns only them
def test_failed_tests():
    code, why, fixes, _details, _docs = P.diagnose("test", "ctest", CTEST)
    assert code == "PK700" and "core_breaks" in why
    assert fixes[0]["run"] == ["pk", "test", "--", "--rerun-failed"]


# Quiet output: no progress, no command lines; warnings, failing tests and summaries stay
def test_quiet_filters():
    lines, warnings = kept("ninja", NINJA_COMPILE)
    assert lines == ["src/demo/other.cpp:3:9: warning: unused variable 'z' [-Wunused-variable]"]
    assert warnings == 1
    lines, _ = kept("cmake", "-- The CXX compiler identification is GNU 13\nCMake Warning at x.cmake:1 (message):\n"
                             "  careful\n\nhello from the project\n-- Configuring done\n" + CMAKE_FIND_PACKAGE)
    assert lines == ["CMake Warning at x.cmake:1 (message):", "  careful", "", "hello from the project"]
    lines, _ = kept("ctest", CTEST)
    assert "2/2 Test #2: core_breaks ......................***Failed    0.02 sec" in lines
    assert "  REQUIRE( demo::answer() == 42 )" in lines
    assert not any("Passed" in line or "Start" in line or "Test project" in line for line in lines)
    assert "50% tests passed, 1 tests failed out of 2" in lines
    assert kept("conan", "======== Installing packages ========\nWARN: deprecated\n")[0] == []


# Conan Center's wxwidgets on MinGW: MinGW names (an option) and a Release wxWidgets, in one fix
def test_wxwidgets_mingw_debug(tmp_path):
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "native").write_text("include(default)\n\n[settings]\ncompiler.cppstd=23\n\n[conf]\n")
    (tmp_path / "deps.json").write_text('{"packages": {"wxwidgets": {"ref": "wxwidgets/[>=3.3 <3.4]"}}}')
    text = ("CMake Error at build/Debug/generators/cmakedeps_macros.cmake:81 (message):\n"
            "  Library 'wx_mswud_xrc-3.3' not found in package.  If 'wx_mswud_xrc-3.3' is\n"
            "  a system library, declare it with 'cpp_info.system_libs' property\n")
    context = {"root": str(tmp_path), "profiles": ["profiles/native"]}
    for step, tool in (("configure", "cmake"), ("build", "ninja")):
        code, why, fixes, _details, _docs = P.diagnose(step, tool, text, context)
        assert code == "PK408" and "no 'd' for Debug" in why
        steps = fixes[0]["steps"]
        assert steps[0]["run"] == ["pk", "dep", "set", "wxwidgets", "--option",
                                   "custom_disables=wxBUILD_WIN32_MSVC_NAMING", "--option", "stc=False"]
        assert steps[1]["edit"][0] == "profiles/native"

    (tmp_path / "deps.json").write_text('{"options": {"custom_disables": "wxBUILD_WIN32_MSVC_NAMING", "stc": "False"}}')
    _code, _why, fixes, _details, _docs = P.diagnose("configure", "cmake", text, context)
    assert "edit" in fixes[0] and fixes[0]["rerun"]
    P.record(str(tmp_path), P.Problem("PK408", "configure failed", fixes=fixes), [])
    assert P.apply_fix(str(tmp_path), [sys.executable], assume_yes=True, dry_run=False) == 0
    assert "[settings]\nwxwidgets/*:build_type=Release\ncompiler.cppstd=23" in \
        (tmp_path / "profiles" / "native").read_text()

    _code, _why, fixes, _details, _docs = P.diagnose("configure", "cmake", text, context)
    assert "conan-center-index" in fixes[0]["say"]

    text = text.replace("wx_mswud_xrc-3.3", "wxlexilla")
    code, why, fixes, _details, _docs = P.diagnose("configure", "cmake", text, context)
    assert code == "PK408" and "wxlexilla-3.3" in why
    assert fixes[0]["run"] == ["pk", "dep", "set", "wxwidgets", "--option", "stc=False"]


# A package that uses GDI+ without linking it (wxwidgets on MinGW) says what to link and where
def test_package_missing_system_library():
    text = ("[3/3] Linking CXX executable bin\\incremental.exe\n"
            "FAILED: [code=1] bin/incremental.exe\n"
            "C:\\msys64\\ucrt64\\bin\\c++.exe -o bin\\incremental.exe\n"
            "C:/msys64/ucrt64/bin/ld.exe: K:/Conan-Cache/p/b/wxwide5daf50330ab6/p/lib/libwx_mswu_core-3.3.a"
            "(graphics.cpp.obj):graphics.cpp:(.text+0xf0): undefined reference to `GdipDeletePath'\n"
            "collect2.exe: error: ld returned 1 exit status\n")
    code, why, fixes, _details, _docs = P.diagnose("build", "ninja", text)
    assert code == "PK409" and "libwx_mswu_core-3.3 uses GDI+" in why
    assert "target_link_libraries(wxWidgets::wxWidgets INTERFACE gdiplus)" in fixes[0]["say"]


# A tool no reader knows still fails readably: the step's code, its last lines, all output printed
def test_unknown_tool():
    code, why, _fixes, details, _docs = P.diagnose("build", "some-new-tool", "compiling\nit broke here\n")
    assert code == "PK604" and details == ["compiling", "it broke here"]
    assert kept("some-new-tool", "a\nb")[0] == ["a", "b"]


# A project's own readers are loaded after the kit's and come first with a lower order
def test_project_readers(tmp_path):
    (tmp_path / "mine.py").write_text(
        "from pklib.problems import fix_hint\n"
        "from pklib.readers import Diagnosis, reader\n\n"
        "@reader('configure', order=1)\n"
        "def assets(text, context):\n"
        "    if 'assets/ is missing' in text:\n"
        "        return Diagnosis('PK500', 'the assets were not downloaded', [fix_hint('./get-assets.sh')])\n")
    readers.load([str(tmp_path)])
    code, why, fixes, _details, _docs = P.diagnose("configure", "cmake", "CMake Error at a.cmake:1 (message):\n"
                                                   "  assets/ is missing\n")
    assert code == "PK500" and why == "the assets were not downloaded" and fixes[0]["say"] == "./get-assets.sh"


# The error always has the same rows, with 'pk explain CODE' last
def test_render_shape():
    problem = P.Problem("PK601", "build failed", "nothing defines f()", [P.fix_run(["pk", "configure"], "x"),
                                                                        P.fix_hint("or link it")], log="b/x.log")
    text = "\n".join(P.render(problem))
    assert text.startswith("error[PK601]: build failed")
    for row in ("   why  nothing defines f()", "   fix  pk configure", "    or  link it", "   log  b/x.log",
                "  docs  "):
        assert row in text
    assert text.endswith("pk explain PK601")


# 'pk fix' applies an edit, forgets the error and runs nothing else when the command was not recorded
def test_apply_fix_edits_the_file(tmp_path, capsys):
    (tmp_path / "profiles").mkdir()
    (tmp_path / "profiles" / "native").write_text("[settings]\ncompiler.cstd=23\n")
    _code, why, fixes, _details, _docs = P.diagnose("deps", "conan", CONAN_CSTD,
                                                    {"profiles": ["profiles/native"], "root": str(tmp_path)})
    P.record(str(tmp_path), P.Problem("PK401", "conan install failed", why, fixes), [])
    assert P.apply_fix(str(tmp_path), [sys.executable], assume_yes=False, dry_run=True) == 0
    assert "compiler.cstd=23" in (tmp_path / "profiles" / "native").read_text()
    assert P.apply_fix(str(tmp_path), [sys.executable], assume_yes=True, dry_run=False) == 0
    assert (tmp_path / "profiles" / "native").read_text() == "[settings]\ncompiler.cstd=17\n"
    assert P.last(str(tmp_path)) is None
    assert P.apply_fix(str(tmp_path), [sys.executable], assume_yes=True, dry_run=False) == 0
    assert "nothing to fix" in capsys.readouterr().out


# A typo in a project command records the command it meant, for 'pk fix'
@requires_git
def test_typos_are_recorded_for_pk_fix(pk, tmp_path):
    assert pk("new", "probe", "--no-git")[0] == 0
    project = tmp_path / "probe"
    code, out = pk("biuld", cwd=project)
    assert code == 2 and "error[PK100]: unknown command 'biuld'" in out and "pk build" in out
    data = json.loads((project / "build" / "pk-last-error.json").read_text())
    assert data["fixes"][0]["run"] == ["pk", "build"]
    code, out = pk("build", "--wererror", cwd=project)
    assert code == 2 and "pk build --werror" in out
    code, out = pk("fix", "-n", cwd=project)
    assert code == 0 and "pk build --werror" in out
    code, out = pk("explain", cwd=project)
    assert code == 0 and "PK102" in out and "last time" in out


# The global pk explains codes outside a project and lists them all
def test_global_explain(pk):
    code, out = pk("explain", "401")
    assert code == 0 and out.startswith("PK401") and "docs.conan.io" in out
    code, out = pk("explain", "--list")
    assert code == 0 and all(code in out for code in P.CATALOG)
    code, out = pk("explain", "PK999")
    assert code == 2 and "no error code" in out
