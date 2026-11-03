"""Every file a Markdown document links to or names exists."""

import re

import pytest

from conftest import ROOT

PROJECT_DOCS = [
    ROOT / "template" / "README.md",
    ROOT / "dev" / "template-repo" / "README.md",
]
DOCS = sorted([
    *ROOT.glob("*.md"),
    *(ROOT / "docs").glob("*.md"),
    *(ROOT / "cmake" / "projectkit" / "docs").glob("*.md"),
])
LINK = re.compile(r"\]\(([^)\s]+)\)")
NAMED = re.compile(r"`((?:docs|cmake/projectkit/docs)/[\w.-]+\.md)`")


def name(doc):
    return doc.relative_to(ROOT).as_posix()


@pytest.mark.parametrize("doc", DOCS + PROJECT_DOCS, ids=name)
def test_doc_references_exist(doc):
    text = doc.read_text(encoding="utf-8")
    base = ROOT if doc in PROJECT_DOCS else doc.parent
    links = [link.split("#")[0] for link in LINK.findall(text)
             if not re.match(r"[a-z]+:|#", link)]
    missing = [link for link in links if not (base / link).exists()]
    missing += [path for path in NAMED.findall(text)
                if not (ROOT / path).exists()]
    assert not missing
