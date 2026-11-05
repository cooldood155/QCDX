"""The kit list lives in three places; they must agree."""

import re
import sys

from conftest import ROOT

from qcdx import resources

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    tomllib = None


# The kit paths match the default PK_SYNC_PATHS in pk.py
def test_kit_paths_match_pk_sync_defaults():
    text = (ROOT / "cmake/projectkit/scripts/pklib/pk.py").read_text(encoding="utf-8")
    match = re.search(r'"PK_SYNC_PATHS",\s*\((.*?)\)\)\.split\(\)', text, re.DOTALL)
    assert match, "default PK_SYNC_PATHS not found in pk.py"
    default = "".join(re.findall(r'"([^"]*)"', match.group(1))).split()
    assert default == list(resources.KIT_PATHS)


# Every kit path exists in the repo
def test_kit_paths_exist():
    for relative in resources.KIT_PATHS:
        assert (ROOT / relative).exists(), relative


# The Python wheel includes every kit path, the template and the CMake config files
def test_wheel_ships_the_kit_and_template():
    if tomllib is None:
        return
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    mapping = config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    for relative in resources.KIT_PATHS:
        assert mapping.get(relative) == f"qcdx/data/kit/{relative}", relative
    assert mapping["template"] == "qcdx/data/template"
    for name in ("QCDXConfig.cmake", "QCDXConfigVersion.cmake"):
        assert mapping[f"cmake/{name}"] == f"qcdx/data/kit/cmake/{name}"


# VERSION is "x.y.z" and matches the Python package version
def test_one_version_everywhere():
    version = (ROOT / "cmake/projectkit/VERSION").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version)
    assert resources.version() == version


# The upstream.conf header pk new writes is the one pk sync expects
def test_state_header_matches_pk_sync():
    from qcdx.new import STATE

    text = (ROOT / "cmake/projectkit/scripts/pklib/pk.py").read_text(encoding="utf-8")
    for line in STATE.splitlines()[:2]:
        assert line in text, line


# No kit path is in the template
def test_kit_is_not_in_template():
    for relative in resources.KIT_PATHS:
        assert not (ROOT / "template" / relative).exists(), relative
