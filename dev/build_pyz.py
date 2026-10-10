#!/usr/bin/env python3
"""Build pk.pyz, QCDX as one file that runs anywhere Python 3.9+ does:

    python dev/build_pyz.py dist/qcdx-X.Y.Z-py3-none-any.whl dist/pk.pyz
    python pk.pyz new myproject

The wheel already holds everything (the CLI, the kit and the template), so the
zipapp is the wheel's contents plus a __main__.py.
"""

import sys
import tempfile
import zipapp
import zipfile
from pathlib import Path

MAIN = "import sys\nfrom qcdx.cli import main\nsys.exit(main())\n"


def build(wheel: Path, target: Path) -> None:
    with tempfile.TemporaryDirectory() as work:
        root = Path(work)
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(root)
        (root / "__main__.py").write_text(MAIN, encoding="utf-8")
        target.parent.mkdir(parents=True, exist_ok=True)
        zipapp.create_archive(root, target, interpreter="/usr/bin/env python3", compressed=True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: build_pyz.py WHEEL OUTPUT.pyz")
    build(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"{sys.argv[2]}: {Path(sys.argv[2]).stat().st_size // 1024} KiB")
