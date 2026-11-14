import subprocess
import sys


def full_clean(project, *args):
    result = subprocess.run([sys.executable, str(project / "scripts" / "pk.py"), "full-clean", *args, "--yes"],
                            cwd=str(project), capture_output=True, text=True)
    return result.returncode, result.stdout + result.stderr


def fake_build(project):
    """A build tree, a Conan output folder and the files Conan writes, without building anything."""
    for folder in ("build/Debug/generators", "build/native-debug/bin", "stage"):
        (project / folder).mkdir(parents=True)
    (project / "build/Debug/generators/conan_toolchain.cmake").write_text("")
    (project / "build/Debug/pk-deps.stamp").write_text("key=x\n")
    (project / "build/native-debug/bin/rocket").write_text("")
    (project / "build/compile_commands.json").write_text("[]")
    (project / "CMakeUserPresets.json").write_text("{}")
    (project / "ConanPresets.json").write_text("{}")


# full-clean deletes all of build/, along with Conan's output
def test_full_clean_deletes_conan_output(pk, tmp_path):
    assert pk("new", "rocket", "--no-git")[0] == 0
    project = tmp_path / "rocket"
    fake_build(project)
    code, out = full_clean(project)
    assert code == 0, out
    for relative in ("build", "stage", "CMakeUserPresets.json", "ConanPresets.json"):
        assert not (project / relative).exists(), relative


# full-clean --keep-deps deletes everything else BUT keeps Conan's output and presets,
# so the next build doesn't reinstall the dependencies
def test_full_clean_keep_deps_keeps_conan_output(pk, tmp_path):
    assert pk("new", "rocket", "--no-git")[0] == 0
    project = tmp_path / "rocket"
    fake_build(project)
    code, out = full_clean(project, "--keep-deps")
    assert code == 0, out
    for relative in ("build/Debug/generators/conan_toolchain.cmake", "build/Debug/pk-deps.stamp",
                     "CMakeUserPresets.json", "ConanPresets.json"):
        assert (project / relative).is_file(), relative
    for relative in ("build/native-debug", "build/compile_commands.json", "stage"):
        assert not (project / relative).exists(), relative


# Only full-clean takes --keep-deps ('clean' already keeps Conan's output)
def test_keep_deps_is_only_for_full_clean(pk, tmp_path):
    assert pk("new", "rocket", "--no-git")[0] == 0
    project = tmp_path / "rocket"
    result = subprocess.run([sys.executable, str(project / "scripts" / "pk.py"), "build", "--keep-deps"],
                            cwd=str(project), capture_output=True, text=True)
    assert result.returncode == 2 and "--keep-deps" in result.stdout + result.stderr
