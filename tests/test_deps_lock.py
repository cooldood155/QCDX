import importlib.util
import json
import types

import pytest
from conftest import ROOT

DEPS = ROOT / "cmake" / "projectkit" / "scripts" / "helpers" / "pk" / "deps.py"


@pytest.fixture
def deps():
    spec = importlib.util.spec_from_file_location("pk_deps", DEPS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Profile's dep graph
GRAPHS = {
    "native": ["wxwidgets/3.3.3#a", "zlib/1.3.2#b", "cmake/3.31.12#c"],
    "ci-linux-x86_64": ["wxwidgets/3.3.3#a", "zlib/1.3.2#b", "gtk/3.24.51#d", "cmake/3.31.12#c"],
}


def make_repo(deps, tmp_path, monkeypatch, graphs, failing=()):
    (tmp_path / "profiles").mkdir()
    for name in graphs:
        (tmp_path / "profiles" / name).write_text("[settings]\n")
    monkeypatch.setattr(deps.pktree, "load_or_exit",
                        lambda root: types.SimpleNamespace(rel=lambda *parts: "/".join(parts)))

    lock = {"version": "0.5",
            "requires": ["zlib/1.3.2#b%1", "wxwidgets/3.3.3#a%2", "gtk/3.24.51#d%3", "ctre/3.11.0#e%4"],
            "build_requires": ["cmake/3.31.12#c%5"],
            "python_requires": [], "config_requires": []}
    (tmp_path / "conan.lock").write_text(json.dumps(lock, indent=4) + "\n")

    repo = deps.Repo(str(tmp_path), [], False)

    def capture(args, check=True, quiet=False):
        profile = args[args.index("-pr:h") + 1] if "-pr:h" in args else args[args.index("-pr:a") + 1]
        profile = profile.rsplit("/", 1)[-1]
        if profile in failing:
            return types.SimpleNamespace(returncode=1, stdout="", stderr="ERROR: nope")
        nodes = {str(i): {"ref": ref} for i, ref in enumerate(["conanfile"] + graphs[profile])}
        return types.SimpleNamespace(returncode=0, stdout=json.dumps({"graph": {"nodes": nodes}}), stderr="")

    monkeypatch.setattr(repo, "capture", capture)
    return repo


def locked(tmp_path):
    lock = json.loads((tmp_path / "conan.lock").read_text())
    return lock["requires"], lock["build_requires"]


# Pruning drops what no profile uses
def test_prune_keeps_other_profiles_packages(deps, tmp_path, monkeypatch):
    repo = make_repo(deps, tmp_path, monkeypatch, GRAPHS)
    repo.lock_prune()
    requires, build_requires = locked(tmp_path)
    assert requires == ["zlib/1.3.2#b%1", "wxwidgets/3.3.3#a%2", "gtk/3.24.51#d%3"]
    assert build_requires == ["cmake/3.31.12#c%5"]


# All profiles under profiles/, native first
def test_all_profiles_reads_the_profiles_folder(deps, tmp_path, monkeypatch):
    repo = make_repo(deps, tmp_path, monkeypatch, GRAPHS)
    assert repo.all_profiles() == ["native", "ci-linux-x86_64"]


# A profile with a failing graph means nothing is pruned
def test_prune_drops_nothing_when_a_graph_fails(deps, tmp_path, monkeypatch):
    repo = make_repo(deps, tmp_path, monkeypatch, GRAPHS, failing=("ci-linux-x86_64",))
    before = (tmp_path / "conan.lock").read_text()
    repo.lock_prune()
    assert (tmp_path / "conan.lock").read_text() == before


# --dry-run writes nothing
def test_prune_dry_run_writes_nothing(deps, tmp_path, monkeypatch):
    repo = make_repo(deps, tmp_path, monkeypatch, GRAPHS)
    repo.dry_run = True
    before = (tmp_path / "conan.lock").read_text()
    repo.lock_prune()
    assert (tmp_path / "conan.lock").read_text() == before


# pk dep rm drops the listed package and keeps other profile's pins
def test_rm_keeps_other_profiles_packages(deps, tmp_path, monkeypatch):
    repo = make_repo(deps, tmp_path, monkeypatch, GRAPHS)
    (tmp_path / "deps.json").write_text(json.dumps({"schema": 1, "packages": {
        "ctre": {"ref": "ctre/3.11.0", "cmake": {"package": "ctre", "targets": ["ctre::ctre"]}},
        "wxwidgets": {"ref": "wxwidgets/[>=3.3 <3.4]", "kind": "requires",
                      "cmake": {"package": "wxWidgets", "targets": ["wxWidgets::wxWidgets"]}},
    }}))
    assert deps.cmd_rm(repo, types.SimpleNamespace(name="ctre", force=False)) == 0
    assert "ctre" not in json.loads((tmp_path / "deps.json").read_text())["packages"]
    requires, build_requires = locked(tmp_path)
    assert requires == ["zlib/1.3.2#b%1", "wxwidgets/3.3.3#a%2", "gtk/3.24.51#d%3"]
    assert build_requires == ["cmake/3.31.12#c%5"]
