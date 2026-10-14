"""The tree model (pklib/tree.py) and the path rewriting of 'pk tree apply'."""

import re
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "cmake" / "projectkit" / "scripts"))

from pklib import tree as T  # noqa: E402
from pklib import treecmd  # noqa: E402

MINIMAL_MOVES = {"cmake/projectkit": ".pk/projectkit", "cmake": ".pk/cmake", "scripts": ".pk/scripts",
                 "scripts/helpers": ".pk/settings", "profiles": ".pk/profiles", "cmake/toolchains": ".pk/toolchains"}


def test_cmake_and_python_defaults_agree():
    text = (ROOT / "cmake/projectkit/Layout.cmake").read_text(encoding="utf-8")
    block = re.search(r"set\(PK_TREE_DEFAULTS(.*?)\)", text, re.DOTALL).group(1)
    cmake = dict(pair.split("=", 1) for pair in re.findall(r'"([^"]+)"', block))
    python = {part.key: part.default for part in T.PARTS if part.movable}
    assert cmake == python


def test_classic_preset_is_the_default_tree():
    assert T.resolve("classic") == T.Tree()
    assert T.resolve("classic").is_classic()


def test_minimal_preset():
    tree = T.resolve("minimal")
    assert tree.moved() == {"kit": ".pk/projectkit", "scripts": ".pk/scripts", "helpers": ".pk/settings",
                            "profiles": ".pk/profiles", "toolchains": ".pk/toolchains", "cmake": ".pk/cmake"}
    assert tree.omit == {"tools", "clangd", "pre-commit"}


@pytest.mark.parametrize("name", ["classic", "minimal"])
def test_conf_and_drawing_round_trip(name):
    tree = T.resolve(name)
    assert T.parse_conf(tree.to_conf()) == tree
    drawing = tree.draw("demo")
    assert T.is_drawing(drawing)
    assert T.parse(drawing, "drawing") == tree
    assert drawing.isascii()


def test_drawing_accepts_box_characters_and_spacers():
    drawing = T.resolve("minimal").draw("demo")
    fancy = (drawing.replace("|-- ", "\u251c\u2500\u2500 ").replace("`-- ", "\u2514\u2500\u2500 ")
             .replace("|   ", "\u2502   "))
    fancy = fancy.replace("\u251c\u2500\u2500 apps/", "\u2502\n\u251c\u2500\u2500 apps/")
    assert T.parse(fancy, "fancy") == T.resolve("minimal")


def test_drawing_moves_a_part_by_its_line():
    drawing = T.Tree().draw("demo").replace("|-- profiles/                            <profiles>\n", "")
    drawing = drawing.replace("|-- scripts/", "|-- conan/\n|   `-- profiles/  <profiles>\n|-- scripts/")
    assert T.parse(drawing, "d").moved() == {"profiles": "conan/profiles"}


def test_deleting_an_optional_line_leaves_it_out():
    drawing = T.Tree().draw("demo").replace("|-- tools/                               <tools> optional\n", "")
    assert T.parse(drawing, "d").omit == {"tools"}


@pytest.mark.parametrize("edit, message", [
    (lambda d: d.replace("<kit>", "<kitt>"), "<kitt> is not a part"),
    (lambda d: d.replace("<sources>", ""), "<sources> is missing"),
    (lambda d: d.replace("<apps>", "<tests>"), "is already on line"),
    (lambda d: d.replace("|-- .clangd ", "|-- src/.clangd "), "stays at '.clangd'"),
    (lambda d: d.replace("|-- profiles/", "|-- build/"), "keeps for itself"),
])
def test_broken_drawings_say_where(edit, message):
    with pytest.raises(T.TreeError) as error:
        T.parse(edit(T.Tree().draw("demo")), "d")
    assert message in str(error.value)


def test_conf_spellings():
    tree = T.parse_conf("PK_TREE_PROFILES=.pk/profiles\nexport scripts = 'tools/scripts'  # here\n"
                        "omit = .clangd, tools/\n")
    # tools/ is left out, so the scripts may live there
    assert tree.moved() == {"profiles": ".pk/profiles", "scripts": "tools/scripts"}
    assert tree.omit == {"clangd", "tools"}


@pytest.mark.parametrize("conf, message", [
    ("profile = x", "'profile' is not a part"),
    ("profiles = ../x", "not a relative path"),
    ("profiles = /abs", "not a relative path"),
    ("profiles = build/p", "keeps for itself"),
    ("profiles = cmake/projectkit/p", "inside the kit"),
    ("kit = src/kit", "inside sources"),
    ("headers = src", "both are 'src'"),
    ("omit = kit", "cannot be left out"),
    ("clangd = x/.clangd", "stays at '.clangd'"),
    ("profiles = a\nprofiles = b", "set twice"),
])
def test_bad_confs(conf, message):
    with pytest.raises(T.TreeError) as error:
        T.parse_conf(conf)
    assert message in str(error.value)


def test_user_trees(tmp_path, monkeypatch):
    monkeypatch.setenv("PK_HOME", str(tmp_path))
    (tmp_path / "trees").mkdir()
    (tmp_path / "trees" / "mine.conf").write_text("profiles = conan\nomit = tools\n")
    assert "mine" in T.preset_names()
    assert T.resolve("mine").moved() == {"profiles": "conan"}
    with pytest.raises(T.TreeError):
        T.resolve("nope")


def test_sync_map_follows_the_tree():
    tree = T.resolve("minimal")
    pairs = dict(T.sync_map(tree))
    assert pairs["cmake/projectkit"] == ".pk/projectkit"
    assert pairs["scripts/pk.py"] == ".pk/scripts/pk.py"
    assert pairs[T.PK_SETUP] == T.PK_SETUP
    no_ci = T.Tree(tree.paths, tree.omit | {"verify-ci", "release-ci"})
    assert T.PK_SETUP not in dict(T.sync_map(no_ci))


@pytest.mark.parametrize("before, after", [
    ('"${CMAKE_CURRENT_LIST_DIR}/cmake/projectkit"', '"${CMAKE_CURRENT_LIST_DIR}/.pk/projectkit"'),
    ('"${CMAKE_CURRENT_LIST_DIR}/cmake")', '"${CMAKE_CURRENT_LIST_DIR}/.pk/cmake")'),
    ("-pr:a profiles/native", "-pr:a .pk/profiles/native"),
    ("python3 scripts/release.py plan", "python3 .pk/scripts/release.py plan"),
    ("./scripts/pk.py dep check", "./.pk/scripts/pk.py dep check"),
    ("`python scripts\\pk.py ...`", "`python .pk\\scripts\\pk.py ...`"),
    ("!scripts/helpers/release/", "!.pk/settings/release/"),
    ('"${PK_REPO_ROOT}/scripts/helpers/verify/consumer.cpp"', '"${PK_REPO_ROOT}/.pk/settings/verify/consumer.cpp"'),
    ("what cmake/toolchains/x.cmake says", "what .pk/toolchains/x.cmake says"),
    ('KIT = "cmake/projectkit"', 'KIT = ".pk/projectkit"'),
    ("cmake_minimum_required(VERSION 3.30) and cmake --preset", "cmake_minimum_required(VERSION 3.30) and cmake "
                                                                "--preset"),
    ("../profiles/x and myscripts/x and the_cmake/x", "../profiles/x and myscripts/x and the_cmake/x"),
])
def test_rewrite_references(before, after):
    assert treecmd.rewrite_references(before, MINIMAL_MOVES) == after


def test_rewrite_references_escapes_regexes():
    before = r"exclude: ^(cmake/projectkit/|scripts/(pk|verify)\.py$)"
    assert treecmd.rewrite_references(before, MINIMAL_MOVES, escape=True) == \
        r"exclude: ^(\.pk/projectkit/|\.pk/scripts/(pk|verify)\.py$)"


def test_profile_toolchain_path_is_recomputed():
    line = 'user_toolchain=["{{ os.path.join(profile_dir, "..", "cmake", "toolchains", "x.cmake") }}"]'
    tree = T.Tree({"profiles": "conan/profiles", "toolchains": ".pk/toolchains"})
    assert treecmd.rewrite_profile_toolchains(line, tree) == \
        'user_toolchain=["{{ os.path.join(profile_dir, "..", "..", ".pk", "toolchains", "x.cmake") }}"]'
    assert treecmd.rewrite_profile_toolchains(line, T.Tree()) == line
