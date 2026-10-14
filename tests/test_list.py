import json
import shutil

from qcdx import __version__


def registry(tmp_path):
    return json.loads((tmp_path / "pk-home" / "projects.json").read_text(encoding="utf-8"))["projects"]


def test_list_without_projects(pk):
    code, out = pk("list")
    assert code == 0 and "no projects yet" in out


def test_new_remembers_the_project(pk, tmp_path):
    assert pk("new", "rocket", "--no-git")[0] == 0
    code, out = pk("list")
    assert code == 0, out
    assert "rocket" in out and __version__ in out and str(tmp_path / "rocket") in out


def test_a_command_inside_a_project_remembers_it(pk, tmp_path):
    assert pk("new", "probe", "--no-git")[0] == 0
    (tmp_path / "pk-home" / "projects.json").unlink()
    assert pk("help", cwd=tmp_path / "probe" / "src")[0] == 0
    assert [entry["path"] for entry in registry(tmp_path)] == [str((tmp_path / "probe").resolve())]


def test_a_project_is_remembered_once(pk, tmp_path):
    assert pk("new", "probe", "--no-git")[0] == 0
    assert pk("help", cwd=tmp_path / "probe")[0] == 0
    assert pk("help", cwd=tmp_path / "probe" / "src")[0] == 0
    assert len(registry(tmp_path)) == 1


def test_list_inside_a_project_is_the_projects_own(pk, tmp_path):
    assert pk("new", "probe", "--no-git")[0] == 0
    code, out = pk("list", cwd=tmp_path / "probe")
    assert code == 0 and "build types" in out


def test_missing_projects_are_shown_and_pruned(pk, tmp_path):
    assert pk("new", "kept", "--no-git")[0] == 0
    assert pk("new", "gone", "--no-git")[0] == 0
    shutil.rmtree(tmp_path / "gone")
    code, out = pk("list")
    assert code == 0 and "(missing)" in out and "1 missing" in out
    code, out = pk("list", "--prune")
    assert code == 0 and "forgot" in out and "(missing)" not in out
    assert [entry["path"] for entry in registry(tmp_path)] == [str((tmp_path / "kept").resolve())]


def test_a_broken_registry_is_reported_and_left_alone(pk, tmp_path):
    home = tmp_path / "pk-home"
    home.mkdir()
    (home / "projects.json").write_text("not json", encoding="utf-8")
    code, out = pk("list")
    assert code == 1 and "cannot read" in out
    assert pk("new", "probe", "--no-git")[0] == 0
    assert (home / "projects.json").read_text(encoding="utf-8") == "not json"


def test_list_rejects_unknown_arguments(pk):
    assert pk("list", "--bogus")[0] == 2
