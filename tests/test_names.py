import sys

import pytest
from conftest import ROOT

sys.path.insert(0, str(ROOT / "cmake" / "projectkit" / "scripts"))
from pklib import names

from qcdx import new


# Valid project names are accepted
@pytest.mark.parametrize("name", ["rocket", "my_lib", "v2", "lib2_core", "qcdx"])
def test_good_names(name):
    assert names.problem(name) == ""


# Each kind of bad name is refused with the right reason
@pytest.mark.parametrize("name, why", [
    ("a", "2-101"), ("x" * 102, "2-101"), ("_foo", "[a-z]"), ("My-Project", "[a-z]"),
    ("my__lib", "'__'"), ("test", "CMake/CTest"), ("install", "CMake/CTest"),
    ("class", "C++ keyword"), ("co_await", "C++ keyword"), ("std", "namespace name"),
    ("std2", "namespace name"), ("linux", "predefine"), ("con", "Windows"), ("com1", "Windows"),
])
def test_bad_names(name, why):
    assert why in names.problem(name)


# pk new uses the kit's name rules
def test_pk_new_uses_kit_rules():
    assert new.kit_names().problem("test") == names.problem("test") != ""


# pk new refuses a reserved name before creating any files
def test_pk_new_refuses_a_reserved_name_before_creating_anything(pk, tmp_path):
    code, out = pk("new", "test", "--no-git")
    assert code == 1 and "CMake/CTest" in out, out
    assert not (tmp_path / "test").exists()


# pk new warns about a name the kit uses itself (like core)
def test_pk_new_notes_a_word_of_the_kit(pk):
    code, out = pk("new", "core", "--no-git")
    assert code == 0, out
    assert "the kit uses 'core' as its own word" in out
