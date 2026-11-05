"""The kit's creators, called directly from a small C-only project."""

import re
import shutil
import subprocess
import sys

import pytest

from conftest import ROOT, requires_cmake

pytestmark = requires_cmake

KIT = (ROOT / "cmake" / "projectkit").as_posix()

HEADER = f"""cmake_minimum_required(VERSION 3.25)
project(kitprobe VERSION 1.2.3 LANGUAGES C)
list(APPEND CMAKE_MODULE_PATH "{KIT}")
include(ProjectKit)
pk_project_setup(C_STANDARD 11)
"""

MAIN = "int main(void) { return 0; }\n"

PROJECT = """
set(host_tools "${PROJECT_BINARY_DIR}/kitprobeHostToolsConfig.cmake")
pk_create_tool(NAME kitprobe_gen EXPORT_FILE "${host_tools}" SOURCES tool.c)
pk_create_tool(NAME kitprobe_pack EXPORT_FILE "${host_tools}" SOURCES tool.c)
pk_create_tool(NAME extra_one SOURCES tool.c)
pk_create_tool(NAME extra_two SOURCES tool.c)
pk_create_tool(NAME solo VERBATIM EXPORT_NAME solo
  EXPORT_FILE "${PROJECT_BINARY_DIR}/soloTargets.cmake" SOURCES tool.c)

if(WIN32)
  enable_language(RC)
endif()
pk_create_app(NAME demo SOURCE_DIR apps/demo
  GUI RC_FILE demo.rc OWN_MANIFEST STATIC_RUNTIME)
pk_create_app(NAME plain SOURCE_DIR apps/plain NO_APP_PATHS)

set(probe "WIN32=${WIN32}\\nMINGW=${MINGW}\\n")
foreach(target IN ITEMS demo_app plain_app)
  foreach(property IN ITEMS WIN32_EXECUTABLE SOURCES LINK_OPTIONS)
    get_target_property(value ${target} ${property})
    string(APPEND probe "${target}.${property}=${value}\\n")
  endforeach()
endforeach()
file(WRITE "${PROJECT_BINARY_DIR}/probe.txt" "${probe}")
"""

NO_COMPILER = re.compile(
    r"No CMAKE_C_COMPILER could be found"
    r"|could not find any instance of Visual Studio")


def configure(path, body, files):
    for relative, text in {"CMakeLists.txt": HEADER + body, **files}.items():
        (path / relative).parent.mkdir(parents=True, exist_ok=True)
        (path / relative).write_text(text, encoding="utf-8")
    command = ["cmake", "-S", str(path), "-B", str(path / "build")]
    if sys.platform != "win32" and shutil.which("ninja"):
        command += ["-G", "Ninja"]
    result = subprocess.run(command, capture_output=True, text=True)
    return result.returncode, result.stdout + result.stderr


def read(path):
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def build(tmp_path_factory):
    path = tmp_path_factory.mktemp("kitprobe")
    files = {"tool.c": MAIN, "apps/demo/main.c": MAIN,
             "apps/plain/main.c": MAIN, "demo.rc": ""}
    code, out = configure(path, PROJECT, files)
    if code and NO_COMPILER.search(out):
        pytest.skip("no C compiler")
    assert code == 0, out
    return path / "build"


@pytest.fixture(scope="module")
def probe(build):
    lines = read(build / "probe.txt").splitlines()
    return dict(line.split("=", 1) for line in lines)


# Tools given the same export file all end up in it
def test_tools_share_export_files(build):
    host_tools = read(build / "kitprobeHostToolsConfig.cmake")
    assert "add_executable(kitprobe::gen IMPORTED)" in host_tools
    assert "add_executable(kitprobe::pack IMPORTED)" in host_tools

    extra = read(build / "extraTargets.cmake")
    assert "add_executable(extra::one IMPORTED)" in extra
    assert "add_executable(extra::two IMPORTED)" in extra

    solo = read(build / "soloTargets.cmake")
    assert "add_executable(solo IMPORTED)" in solo


# Windows-only app options (.rc file, static runtime, own manifest) are only used on Windows
def test_app_windows_options(probe):
    windows = probe["WIN32"] not in ("", "0")
    mingw = probe["MINGW"] not in ("", "0")
    links = probe["demo_app.LINK_OPTIONS"].split(";")
    own_manifest = [link for link in links
                    if link.startswith("-B")
                    and link.endswith("_no_default_manifest/")]

    assert probe["demo_app.WIN32_EXECUTABLE"] == "TRUE"
    assert ("demo.rc" in probe["demo_app.SOURCES"]) == windows
    assert ("-static" in links) == mingw
    assert bool(own_manifest) == mingw

    assert probe["plain_app.WIN32_EXECUTABLE"] == "value-NOTFOUND"
    assert probe["plain_app.LINK_OPTIONS"] == "value-NOTFOUND"


# C files get generated, except for NO_APP_PATHS apps
def test_app_paths(build):
    assert (build / "generated" / "demo" / "app_paths.h").is_file()
    assert (build / "generated" / "demo" / "app_paths.c").is_file()
    assert not (build / "generated" / "plain").exists()


# A missing RC_FILE stops the configuration with a CLEAR error
def test_app_rc_file_must_exist(build, tmp_path):
    body = "pk_create_app(NAME demo SOURCE_DIR apps/demo RC_FILE x.rc)\n"
    code, out = configure(tmp_path, body, {"apps/demo/main.c": MAIN})
    assert code != 0
    assert "'RC_FILE' for 'demo' does not exist" in " ".join(out.split())
