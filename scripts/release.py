#!/usr/bin/env python3
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "cmake", "projectkit", "scripts"))

from pklib import release

sys.exit(release.main(sys.argv[1:], ROOT))
