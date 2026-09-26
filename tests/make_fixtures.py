# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""Download the test fixtures (easyeda2kicad output for a few parts) into tests/fixtures/.

They are not part of the repository: the symbols, footprints and 3D models are EasyEDA/LCSC data. Run once
before the library tests (needs internet and easyeda2kicad):
    python tests/make_fixtures.py [--python <python with easyeda2kicad>]
"""
import argparse
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from partsearch import library  # noqa: E402
from partsearch.config import Settings  # noqa: E402

PARTS = ["C25804", "C2838502", "C5145278", "C12340", "C2286", "C88224"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--python", help="python that has easyeda2kicad (default: detect)")
    a = ap.parse_args()
    py = a.python or Settings().easyeda_python_path()
    if not py:
        print("easyeda2kicad not found - pass --python")
        return 1
    tmp = Path(tempfile.mkdtemp(prefix="ps_fixtures_"))
    ctx = library.Context(lib_dir=tmp / "lib", work_dir=tmp / "work", easyeda_python=py)
    try:
        for lcsc in PARTS:
            dst = HERE / "fixtures" / lcsc
            if dst.exists():
                print("%-9s already there" % lcsc)
                continue
            raw = library.fetch_raw(ctx, lcsc, lambda stage, msg: None)
            dst.mkdir(parents=True)
            for item in raw.iterdir():
                if item.name.startswith(library.STAGE):
                    (shutil.copytree if item.is_dir() else shutil.copy2)(item, dst / item.name)
            print("%-9s downloaded" % lcsc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
