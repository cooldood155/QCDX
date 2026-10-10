import re
import subprocess

from conftest import ROOT, requires_git


def files_mentioning(root, word):
    hits = []
    for path in root.rglob("*"):
        parts = set(path.relative_to(root).parts)
        if path.is_dir() or ".git" in parts or "projectkit" in parts:
            continue
        if path.name == "upstream.conf" or path.name == "README.md":
            continue
        try:
            if word in path.read_text(encoding="utf-8").lower():
                hits.append(str(path.relative_to(root)))
        except UnicodeDecodeError:
            pass
    return hits


def test_new_project_is_renamed_and_complete(pk, tmp_path):
    code, out = pk("new", "rocket", "--no-git", "--description=Rocket sim", "--license=MIT",
                   "--author=Ada <ada@example.com>", "--url=https://example.com/rocket")
    assert code == 0, out
    project = tmp_path / "rocket"
    for relative in ("CMakeLists.txt", "CMakePresets.json", "conanfile.py", "deps.json", "conan.lock",
                     "include/rocket/core.hpp", "src/rocket/core.cpp", "apps/rocket/main.cpp",
                     "tests/rocket/tests_core.cpp",
                     "cmake/projectkit/VERSION", "scripts/pk.py", "scripts/release.py",
                     ".github/actions/pk-setup/action.yml", ".github/workflows/verify.yml",
                     ".gitignore", ".gitattributes", "README.md", "scripts/helpers/pk/upstream.conf"):
        assert (project / relative).exists(), relative
    assert files_mentioning(project, "qcdx") == []
    cmake = (project / "CMakeLists.txt").read_text()
    assert re.search(r"project\(rocket\s+VERSION\s+0\.1\.0", cmake)
    assert 'DESCRIPTION "Rocket sim"' in cmake
    recipe = (project / "conanfile.py").read_text()
    assert 'license = "MIT"' in recipe
    assert 'author = "Ada <ada@example.com>"' in recipe
    assert 'url = "https://example.com/rocket"' in recipe
    readme = (project / "README.md").read_text()
    assert readme.startswith("# rocket\n\nRocket sim\n")
    assert "Created with [QCDX]" in readme
    state = (project / "scripts/helpers/pk/upstream.conf").read_text()
    assert "url=https://github.com/cooldood155/QCDX.git" in state


def test_new_kit_is_identical_to_the_source_kit(pk, tmp_path):
    assert pk("new", "probe", "--no-git")[0] == 0
    project = tmp_path / "probe"
    for source in (ROOT / "cmake/projectkit").rglob("*"):
        if source.is_file() and "__pycache__" not in source.parts:
            copy = project / source.relative_to(ROOT)
            assert copy.read_bytes() == source.read_bytes(), str(copy)


def test_new_default_description_is_the_name(pk, tmp_path):
    assert pk("new", "probe", "--no-git")[0] == 0
    assert 'DESCRIPTION "probe"' in (tmp_path / "probe/CMakeLists.txt").read_text()


def test_new_keeps_nothing_of_the_template_recipe_identity(pk, tmp_path):
    assert pk("new", "probe", "--no-git")[0] == 0
    recipe = (tmp_path / "probe/conanfile.py").read_text()
    assert 'author = "Test User <test@example.com>"' in recipe
    assert not re.search(r"^\s*(url|license)\s*=", recipe, re.MULTILINE)
    assert "Reumann" not in recipe


@requires_git
def test_new_makes_a_first_commit(pk, tmp_path):
    code, out = pk("new", "probe")
    assert code == 0, out
    log = subprocess.run(["git", "log", "--format=%s"], cwd=tmp_path / "probe", capture_output=True, text=True)
    assert log.stdout.strip() == "Create probe with QCDX 0.1.0"


def test_new_refuses_bad_names_and_full_directories(pk, tmp_path):
    assert pk("new", "My-Project", "--no-git")[0] == 1
    (tmp_path / "taken").mkdir()
    (tmp_path / "taken" / "file.txt").write_text("x")
    assert pk("new", "probe", "taken", "--no-git")[0] == 1
    assert pk("new", "probe", "taken", "--no-git", "--force")[0] == 0
