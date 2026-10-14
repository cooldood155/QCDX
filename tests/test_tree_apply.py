"""'pk new --tree', 'pk tree apply', 'pk tree reset' and 'pk sync' on projects
whose parts live somewhere else than the classic tree."""

import os
import shutil
import subprocess
import sys

from conftest import ROOT, requires_git

MINIMAL_ROOT = sorted([".clang-format", ".clang-tidy", ".gitattributes", ".github", ".gitignore", ".pk",
                       "CMakeLists.txt", "CMakePresets.json", "README.md", "apps", "conan.lock", "conanfile.py",
                       "deps.json", "include", "src", "tests"])


def project_pk(project, *args, scripts="scripts", env_dir=None):
    """Run the project's own pk.py (as 'pk' does), wherever its tree puts it."""
    env = dict(os.environ, PK_SELF_NAME="pk")
    if env_dir is not None:
        env.update(GIT_CONFIG_GLOBAL=str(env_dir / "gitconfig"), PK_HOME=str(env_dir / "pk-home"))
    env.pop("PK_REPO_ROOT", None)
    result = subprocess.run([sys.executable, str(project / scripts / "pk.py"), *args], cwd=str(project), env=env,
                            capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return result.returncode, result.stdout + result.stderr


def files(root):
    found = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_file() and ".git/" not in relative + "/" and "__pycache__" not in relative:
            found[relative] = path.read_bytes()
    return found


def test_new_minimal_tree(pk, tmp_path):
    code, out = pk("new", "probe", "--no-git", "--tree=minimal")
    assert code == 0, out
    assert "still name" not in out
    project = tmp_path / "probe"
    assert sorted(os.listdir(project)) == MINIMAL_ROOT
    assert sorted(os.listdir(project / ".pk")) == ["cmake", "profiles", "projectkit", "scripts", "settings",
                                                   "toolchains", "tree.conf"]
    assert (project / ".pk/settings/pk/upstream.conf").is_file()
    cmake = (project / "CMakeLists.txt").read_text()
    assert '"${CMAKE_CURRENT_LIST_DIR}/.pk/projectkit"' in cmake
    assert "add_subdirectory(tools)" not in cmake and "pk_require_host_tools" not in cmake
    recipe = (project / "conanfile.py").read_text()
    for entry in ('".pk/tree.conf"', '".pk/projectkit/*"', '".pk/cmake/*"', '"src/*"', '"tests/*"'):
        assert entry in recipe, entry
    assert '"tools/*"' not in recipe
    profile = (project / ".pk/profiles/x86_64-mingw-w64").read_text()
    assert 'os.path.join(profile_dir, "..", "toolchains", "x86_64-mingw-w64.cmake")' in profile
    assert "next:" in out and "pk tree" in out

    code, out = project_pk(project, "tree", "check", scripts=".pk/scripts")
    assert code == 0 and "matches the files" in out, out
    code, out = pk("--version", cwd=project / "src")
    version = (ROOT / "cmake/projectkit/VERSION").read_text().strip()
    assert f"kit {version} in" in out, out


def test_new_with_only_omissions_keeps_classic_paths(pk, tmp_path):
    code, out = pk("new", "probe", "--no-git", "--omit=tools,clangd")
    assert code == 0, out
    project = tmp_path / "probe"
    assert not (project / "tools").exists() and not (project / ".clangd").exists()
    assert (project / "cmake/projectkit/VERSION").is_file()
    assert "omit         = tools clangd" in (project / ".pk/tree.conf").read_text()
    assert "add_subdirectory(tools)" not in (project / "CMakeLists.txt").read_text()


def test_new_refuses_a_broken_tree_before_creating_anything(pk, tmp_path):
    (tmp_path / "bad.tree").write_text("demo/\n|-- src/  <sources>\n")
    code, out = pk("new", "probe", "--tree=bad.tree")
    assert code == 1 and "<kit> is missing" in out
    assert not (tmp_path / "probe").exists()
    code, out = pk("new", "probe", "--omit=kit")
    assert code == 1 and ("cannot be left out" in out or "not a part" in out)
    assert not (tmp_path / "probe").exists()


def test_new_from_a_user_tree_and_a_drawing(pk, tmp_path):
    trees = tmp_path / "pk-home" / "trees"
    trees.mkdir(parents=True)
    (trees / "mine.conf").write_text("profiles = conan/profiles\nomit = pre-commit\n")
    code, out = pk("new", "one", "--no-git", "--tree=mine")
    assert code == 0, out
    assert (tmp_path / "one/conan/profiles/native").is_file()

    code, drawing = pk("tree", "minimal")
    assert code == 0 and "<kit>" in drawing
    drawing = drawing.replace("|-- src/ ", "|-- code/\n|   `-- src/ ")
    (tmp_path / "my.tree").write_text(drawing)
    code, out = pk("new", "two", "--no-git", "--tree=my.tree")
    assert code == 0, out
    assert (tmp_path / "two/code/src/two/core.cpp").is_file()
    assert "add_subdirectory(code/src)" in (tmp_path / "two/CMakeLists.txt").read_text()


def test_global_tree_lists_the_trees(pk):
    code, out = pk("tree")
    assert code == 0 and "classic" in out and "minimal" in out


@requires_git
def test_apply_is_the_same_as_new(pk, tmp_path):
    assert pk("new", "probe")[0] == 0
    project = tmp_path / "probe"
    code, out = project_pk(project, "tree", "apply", "minimal", "--yes", env_dir=tmp_path)
    assert code == 0, out
    assert "committed" in out
    assert subprocess.run(["git", "status", "--porcelain"], cwd=str(project), capture_output=True,
                          text=True).stdout == ""
    assert pk("new", "probe", "fresh", "--no-git", "--tree=minimal")[0] == 0
    applied, fresh = files(project), files(tmp_path / "fresh")
    differ = sorted(k for k in set(applied) | set(fresh) if applied.get(k) != fresh.get(k))
    assert differ == [], differ


@requires_git
def test_apply_round_trip(pk, tmp_path):
    assert pk("new", "probe")[0] == 0
    project = tmp_path / "probe"
    before = files(project)
    assert project_pk(project, "tree", "apply", "minimal", "--yes", env_dir=tmp_path)[0] == 0
    code, out = project_pk(project, "tree", "apply", "classic", "--yes", scripts=".pk/scripts", env_dir=tmp_path)
    assert code == 1 and "cannot bring its files back" in out
    code, out = project_pk(project, "tree", "apply", "classic", "--omit=tools,clangd,pre-commit", "--yes",
                           scripts=".pk/scripts", env_dir=tmp_path)
    assert code == 0, out
    after = files(project)
    gone = {k for k in before if k not in after}
    assert gone == {".clangd", ".pre-commit-config.yaml", "tools/CMakeLists.txt", "tools/codegen.cpp"}
    changed = sorted(k for k in after if before.get(k) != after[k])
    assert changed == [".pk/tree.conf", "CMakeLists.txt", "README.md", "conanfile.py"], changed


@requires_git
def test_a_broken_tree_changes_nothing_and_reset_brings_it_back(pk, tmp_path):
    assert pk("new", "probe", "--tree=minimal")[0] == 0
    project = tmp_path / "probe"
    code, out = project_pk(project, "tree", "draw", scripts=".pk/scripts", env_dir=tmp_path)
    assert code == 0, out
    drawing = project / ".pk/tree.txt"
    good = drawing.read_text()
    drawing.write_text(good.replace("<kit>", "<kitt>"))
    before = files(project)
    code, out = project_pk(project, "tree", "apply", ".pk/tree.txt", "--yes", scripts=".pk/scripts",
                           env_dir=tmp_path)
    assert code == 1 and "nothing changed" in out and "<kitt>" in out
    assert files(project) == before
    assert project_pk(project, "tree", "reset", scripts=".pk/scripts", env_dir=tmp_path)[0] == 0
    assert drawing.read_text() == good

    conf = project / ".pk/tree.conf"
    conf.write_text(conf.read_text().replace(".pk/profiles", "nowhere"))
    code, out = project_pk(project, "status", scripts=".pk/scripts", env_dir=tmp_path)
    assert code == 2 and "pk tree reset" in out
    code, out = project_pk(project, "tree", "reset", scripts=".pk/scripts", env_dir=tmp_path)
    assert code == 0 and "committed tree.conf" in out, out
    assert project_pk(project, "tree", "check", scripts=".pk/scripts", env_dir=tmp_path)[0] == 0


@requires_git
def test_sync_follows_the_tree(pk, tmp_path):
    """QCDX keeps the classic tree; a kit that lives in .pk/ still syncs."""
    upstream = tmp_path / "upstream"
    for relative in ("cmake/projectkit", "scripts", ".github/actions/pk-setup"):
        source = ROOT / relative
        target = upstream / relative
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
    env = dict(os.environ, GIT_CONFIG_GLOBAL=str(tmp_path / "gitconfig"))

    def git(*args, cwd=upstream):
        subprocess.run(["git", *args], cwd=str(cwd), env=env, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("commit", "-q", "-m", "A")
    assert pk("new", "probe", "--tree=minimal")[0] == 0
    project = tmp_path / "probe"
    # the project's kit matches A: make the scripts' modes match too
    for name in ("pk", "verify", "package", "release", "bootstrap"):
        os.chmod(upstream / "scripts" / f"{name}.py", 0o755)
    git("add", "-A")
    git("commit", "-q", "-m", "A modes")

    with open(upstream / "cmake/projectkit/Layout.cmake", "a") as file:
        file.write("# B\n")
    (upstream / "cmake/projectkit/NEW.md").write_text("B\n")
    git("add", "-A")
    git("commit", "-q", "-m", "B")
    code, out = project_pk(project, "sync", f"--from={upstream}", "--branch=main", scripts=".pk/scripts",
                           env_dir=tmp_path)
    assert code == 0, out
    assert (project / ".pk/projectkit/Layout.cmake").read_text().endswith("# B\n")
    assert (project / ".pk/projectkit/NEW.md").is_file()
    assert not (project / "cmake").exists()
