# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""Build the installable plugin folder (and a zip of it) from this source tree.

    python tools/build_plugin.py            ->  dist/partsearch/        (copy this folder into KiCad's plugins folder)
                                                dist/partsearch-<version>.zip

The folder is self-contained: KiCad reads plugin.json, creates the plugin's Python environment, installs
requirements.txt into it, and the toolbar button runs launch.py, which starts the window from the same folder.
"""
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from partsearch import __version__  # noqa: E402

FILES = [("kicad_plugin/plugin.json", "plugin.json"), ("kicad_plugin/launch.py", "launch.py"),
         ("kicad_plugin/requirements.txt", "requirements.txt"), ("partsearch.pyw", "partsearch.pyw"),
         ("LICENSE", "LICENSE"), ("THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.md")] + \
        [("kicad_plugin/%s" % n, n) for n in ("icon_24.png", "icon_48.png", "icon_dark_24.png", "icon_dark_48.png")]


def build(out: Path = ROOT / "dist") -> Path:
    dst = out / "partsearch"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for src, name in FILES:
        shutil.copy2(ROOT / src, dst / name)
    shutil.copytree(ROOT / "partsearch", dst / "partsearch",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    z = out / ("partsearch-%s.zip" % __version__)
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(dst.rglob("*")):
            if f.is_file():
                zf.write(f, Path("partsearch") / f.relative_to(dst))
    return dst


if __name__ == "__main__":
    d = build()
    n = sum(1 for f in d.rglob("*") if f.is_file())
    print("built %s (%d files) and %s" % (d, n, d.parent / ("partsearch-%s.zip" % __version__)))
