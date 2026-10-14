#!/usr/bin/env python3
"""Runs pklib.pk of the kit. The project root is the nearest folder above with a
CMakePresets.json; the kit is cmake/projectkit/, or wherever .pk/tree.conf puts it."""
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = HERE
while not os.path.isfile(os.path.join(ROOT, "CMakePresets.json")) and os.path.dirname(ROOT) != ROOT:
    ROOT = os.path.dirname(ROOT)
if not os.path.isfile(os.path.join(ROOT, "CMakePresets.json")):
    ROOT = os.path.dirname(HERE)

KIT = "cmake/projectkit"
try:
    with open(os.path.join(ROOT, ".pk", "tree.conf"), encoding="utf-8") as file:
        for line in file:
            match = re.match(r"\s*(?:PK_TREE_)?kit\s*=\s*(\S+)", line, re.IGNORECASE)
            if match:
                KIT = match.group(1).strip("\"'")
except OSError:
    pass
sys.path.insert(0, os.path.join(ROOT, *KIT.split("/"), "scripts"))

from pklib import pk  # noqa: E402

sys.exit(pk.main(sys.argv[1:], ROOT))
