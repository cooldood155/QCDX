import subprocess
import sys


def rename(project, *args):
    result = subprocess.run([sys.executable, str(project / "scripts" / "bootstrap.py"), *args, "--yes", "--force"],
                            cwd=str(project), capture_output=True, text=True)
    return result.returncode, result.stdout + result.stderr


def snapshot(project):
    return {str(p.relative_to(project)): p.read_bytes() for p in project.rglob("*") if p.is_file()}


def test_rename_changes_project_name_only(pk, tmp_path):
    assert pk("new", "rocket", "--no-git")[0] == 0
    project = tmp_path / "rocket"
    code, out = rename(project, "falcon")
    assert code == 0, out
    for relative in ("include/falcon/core.hpp", "src/falcon/core.cpp", "apps/falcon/main.cpp",
                     "tests/falcon/tests_core.cpp", "cmake/falconConfig.cmake.in"):
        assert (project / relative).is_file(), relative
    cmake = (project / "CMakeLists.txt").read_text()
    assert "FALCON_BUILD_TESTS" in cmake and "enable_testing()" in cmake
    recipe = (project / "conanfile.py").read_text()
    assert "class FalconRecipe" in recipe
    assert '"tools.build:skip_test"' in recipe
    assert 'TEST_CASE("falcon reports' in (project / "tests/falcon/tests_core.cpp").read_text()
    assert "no occurrences of rocket remain" in out


def test_rename_ignores_longer_words(pk, tmp_path):
    assert pk("new", "cod", "--no-git")[0] == 0
    project = tmp_path / "cod"
    code, out = rename(project, "fish")
    assert code == 0, out
    assert (project / "tools/codegen.cpp").is_file()
    assert "codegen" in (project / "tools/CMakeLists.txt").read_text()


def test_rename_refuses_a_word_of_the_kit_and_changes_nothing(pk, tmp_path):
    assert pk("new", "rocket", "--no-git")[0] == 0
    project = tmp_path / "rocket"
    code, out = rename(project, "core")
    assert code == 0, out
    assert "renaming away from it later" in out
    before = snapshot(project)
    code, out = rename(project, "core_classic")
    assert code == 1, out
    assert "the kit uses 'core' as its own word" in out
    assert snapshot(project) == before


def test_rename_checks_new_name(pk, tmp_path):
    assert pk("new", "rocket", "--no-git")[0] == 0
    project = tmp_path / "rocket"
    before = snapshot(project)
    code, out = rename(project, "test")
    assert code == 1 and "CMake/CTest" in out, out
    assert snapshot(project) == before


def test_rename_to_a_name_containing_the_old_one(pk, tmp_path):
    assert pk("new", "rocket", "--no-git")[0] == 0
    project = tmp_path / "rocket"
    code, out = rename(project, "rocket_v2")
    assert code == 0, out
    assert (project / "include/rocket_v2/core.hpp").is_file()
    assert "ROCKET_V2_BUILD_TESTS" in (project / "CMakeLists.txt").read_text()
    assert "still naming" not in out
