import os
import subprocess

from conftest import requires_git


def test_pk_new_explains_a_missing_name_and_a_spaced_value(pk):
    code, out = pk("new")
    assert code == 2 and out.startswith("pk new: missing NAME")
    code, out = pk("new", "probe", "--tree", "minimal")
    assert code == 2 and "--tree needs a value, written --tree=VALUE" in out


@requires_git
def test_pk_new_says_when_the_first_commit_fails(pk, tmp_path):
    (tmp_path / "gitconfig").write_text("[user]\n\tname = Test User\n\temail = test@example.com\n"
                                        "\tsigningkey = " + str(tmp_path / "missing-key") + "\n"
                                        "[gpg]\n\tformat = ssh\n[commit]\n\tgpgsign = true\n"
                                        "[init]\n\tdefaultBranch = main\n")
    code, out = pk("new", "probe")
    assert code == 0, out
    assert "the first commit failed" in out
    env = dict(os.environ, GIT_CONFIG_GLOBAL=str(tmp_path / "gitconfig"))
    staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=tmp_path / "probe",
                            capture_output=True, text=True, env=env)
    assert "CMakeLists.txt" in staged.stdout.split()
