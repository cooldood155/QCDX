"""CHANGELOG.md agrees with VERSION and with itself."""

import re

from conftest import ROOT

REPO = "https://github.com/cooldood155/QCDX"


def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


VERSION = read("cmake/projectkit/VERSION").strip()
TEXT = re.sub(r"<!--.*?-->", "", read("CHANGELOG.md"), flags=re.DOTALL)
SECTIONS = re.findall(r"^## \[([^\]]+)\](?: - (\S+))?\s*$", TEXT, re.MULTILINE)
LINKS = dict(re.findall(r"^\[([^\]]+)\]: (\S+)\s*$", TEXT, re.MULTILINE))
RELEASES = [name for name, _ in SECTIONS if name != "Unreleased"]


def version_key(name):
    return tuple(int(part) for part in name.split("."))


# Current VERSION has a dated section in CHANGELOG.md
def test_version_has_a_dated_section():
    dates = dict(SECTIONS)
    assert VERSION in dates, f"no '## [{VERSION}] - YYYY-MM-DD' section"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", dates[VERSION]), VERSION


# Each section appears once, Unreleased comes first and releases go newest to oldest
def test_sections_are_unique_and_newest_first():
    names = [name for name, _ in SECTIONS]
    assert len(names) == len(set(names)), names
    if "Unreleased" in names:
        assert names[0] == "Unreleased"
    for name in RELEASES:
        assert re.fullmatch(r"\d+\.\d+\.\d+", name), name
    assert RELEASES == sorted(RELEASES, key=version_key, reverse=True)


# Every release has its tag link and Unreleased compares against the current version
def test_every_section_has_its_link():
    for name in RELEASES:
        assert LINKS.get(name) == f"{REPO}/releases/tag/v{name}", name
    assert LINKS.get("Unreleased") == f"{REPO}/compare/v{VERSION}...HEAD"


# Every release section lists at least one change
def test_releases_list_changes():
    parts = re.split(r"^## \[([^\]]+)\].*$", TEXT, flags=re.MULTILINE)
    for name, body in zip(parts[1::2], parts[2::2]):
        if name != "Unreleased":
            assert re.search(r"^- ", body, re.MULTILINE), name
