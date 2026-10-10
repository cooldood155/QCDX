from conftest import requires_cmake

from qcdx import cli


def test_version(pk):
    code, out = pk("--version")
    assert code == 0 and out.startswith("QCDX 0.1.0")


def test_outside_a_project(pk):
    assert pk()[0] == 0
    code, out = pk("build")
    assert code == 2 and "pk new NAME" in out


def test_delegates_inside_a_project(pk, tmp_path):
    assert pk("new", "probe", "--no-git")[0] == 0
    code, out = pk("help", cwd=tmp_path / "probe" / "src")
    assert code == 0 and "install and ship" in out
    code, out = pk("--version", cwd=tmp_path / "probe")
    assert "kit 0.1.0" in out


def test_find_project_needs_presets(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "pk.py").write_text("")
    assert cli.find_project(tmp_path) is None
    (tmp_path / "CMakePresets.json").write_text("{}")
    assert cli.find_project(tmp_path / "scripts") == tmp_path


@requires_cmake
def test_cmake_dir_is_a_package(pk):
    code, out = pk("cmake-dir")
    assert code == 0
    from pathlib import Path

    folder = Path(out.strip())
    assert (folder / "QCDXConfig.cmake").is_file()
    assert (folder / "projectkit" / "ProjectKit.cmake").is_file()
