import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def pk(tmp_path, monkeypatch):
    """Run the global pk CLI from source in tmp_path; returns (code, output)."""
    monkeypatch.chdir(tmp_path)

    def run(*args, cwd=None):
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), GIT_CONFIG_GLOBAL=str(tmp_path / "gitconfig"))
        result = subprocess.run([sys.executable, "-m", "qcdx", *args], cwd=str(cwd or tmp_path), env=env,
                                capture_output=True, text=True)
        return result.returncode, result.stdout + result.stderr

    (tmp_path / "gitconfig").write_text("[user]\n\tname = Test User\n\temail = test@example.com\n"
                                        "[commit]\n\tgpgsign = false\n[init]\n\tdefaultBranch = main\n")
    return run


requires_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
requires_cmake = pytest.mark.skipif(shutil.which("cmake") is None, reason="cmake not installed")
