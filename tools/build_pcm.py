# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""Build the package for KiCad's Plugin and Content Manager (PCM).

    python tools/build_pcm.py
        -> dist/partsearch-<version>-pcm.zip            install with KiCad: Plugin and Content Manager >
                                                         Install from File..., or download through the PCM
        -> dist/pcm-metadata-<version>.json              metadata.json for the kicad/addons/metadata repository
                                                         (the same as in the zip plus download_* / install_size)

Archive layout required by the PCM: plugins/ (the plugin itself, directly - no extra sub folder), resources/icon.png
(64 x 64) and metadata.json. The metadata inside the archive must not contain the download_* keys.
"""
import copy
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from partsearch import PROJECT_URL, __version__  # noqa: E402
from build_plugin import build  # noqa: E402

IDENTIFIER = json.loads((ROOT / "kicad_plugin" / "plugin.json").read_text(encoding="utf-8"))["identifier"]

METADATA = {
    "$schema": "https://go.kicad.org/pcm/schemas/v1",
    "name": "Part Search",
    "description": "Search JLCPCB/LCSC parts and add symbol, footprint and 3D model to your own library, checked by "
                   "KiCad before and after writing.",
    "description_full": (
        "Part Search finds JLCPCB / LCSC parts (offline in the JLCPCB Tools parts list, or online at JLCPCB), shows the "
        "symbol and footprint before anything is written, and adds symbol, footprint and 3D model to one personal "
        "library.\n\n"
        "- Every part is loaded by KiCad (kicad-cli) before it is written and again from your library afterwards.\n"
        "- Nothing is overwritten: importing a part again creates NAME-1, and every write keeps a backup.\n"
        "- Consistent names, 3D model paths through a path variable, a registry of what came from where.\n"
        "- Setup assistant for new users; English and Turkish interface; light and dark theme.\n\n"
        "Uses easyeda2kicad (installed automatically) for the conversion. Library only - it does not place parts in "
        "the schematic. Tested on KiCad 10 on Windows and macOS; needs KiCad 10 (Python 3.9 or newer).\n\n"
        "Not affiliated with JLCPCB, LCSC or EasyEDA."),
    "identifier": IDENTIFIER,
    "type": "plugin",
    "author": {"name": "İlker Güneş (Zogolder)", "contact": {"github": "https://github.com/IlkerGuness"}},
    "license": "GPL-3.0",
    "resources": {"homepage": PROJECT_URL, "issues": PROJECT_URL + "/issues"},
    "tags": ["jlcpcb", "lcsc", "easyeda", "library", "symbols", "footprints", "part-import"],
    "versions": [{"version": __version__, "status": "stable", "kicad_version": "10.0", "runtime": "ipc",
                  "platforms": ["windows", "macos"]}],
}


def main() -> None:
    dist = ROOT / "dist"
    plugin_dir = build(dist)
    pcm_zip = dist / ("partsearch-%s-pcm.zip" % __version__)
    install_size = 0
    with zipfile.ZipFile(pcm_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(plugin_dir.rglob("*")):
            if f.is_file():
                zf.write(f, Path("plugins") / f.relative_to(plugin_dir))
                install_size += f.stat().st_size
        icon = ROOT / "kicad_plugin" / "icon_64.png"
        zf.write(icon, "resources/icon.png")
        install_size += icon.stat().st_size
        meta = json.dumps(METADATA, indent=2, ensure_ascii=False) + "\n"
        zf.writestr("metadata.json", meta)
        install_size += len(meta.encode("utf-8"))
    data = pcm_zip.read_bytes()
    full = copy.deepcopy(METADATA)
    full["versions"][0].update({
        "download_url": "%s/releases/download/v%s/%s" % (PROJECT_URL, __version__, pcm_zip.name),
        "download_sha256": hashlib.sha256(data).hexdigest(),
        "download_size": len(data),
        "install_size": install_size,
    })
    out = dist / ("pcm-metadata-%s.json" % __version__)
    out.write_text(json.dumps(full, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("built %s (%d bytes, sha256 %s) and %s" % (pcm_zip, len(data), full["versions"][0]["download_sha256"], out))


if __name__ == "__main__":
    main()
