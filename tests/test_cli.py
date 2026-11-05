from conftest import requires_cmake

from qcdx import __version__, cli


# pk --version prints the QCDX version
def test_version(pk):
    code, out = pk("--version")
    assert code == 0 and out.startswith(f"QCDX {__version__}")


# pk runs outside a project but refuses project commands like build
def test_outside_a_project(pk):
    assert pk()[0] == 0
    code, out = pk("build")
    assert code == 2 and "pk new NAME" in out


# pk hands commands to the project's own pk.py, even from a subfolder
def test_delegates_inside_a_project(pk, tmp_path):
    assert pk("new", "probe", "--no-git")[0] == 0
    code, out = pk("help", cwd=tmp_path / "probe" / "src")
    assert code == 0 and "install and ship" in out
    code, out = pk("--version", cwd=tmp_path / "probe")
    assert f"kit {__version__}" in out


# A folder only counts as a project when it has CMakePresets.json
def test_find_project_needs_presets(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "pk.py").write_text("")
    assert cli.find_project(tmp_path) is None
    (tmp_path / "CMakePresets.json").write_text("{}")
    assert cli.find_project(tmp_path / "scripts") == tmp_path


# pk cmake-dir points at a folder with the QCDX CMake package
@requires_cmake
def test_cmake_dir_is_a_package(pk):
    code, out = pk("cmake-dir")
    assert code == 0
    from pathlib import Path

    folder = Path(out.strip())
    assert (folder / "QCDXConfig.cmake").is_file()
    assert (folder / "projectkit" / "ProjectKit.cmake").is_file()
