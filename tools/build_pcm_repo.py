# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""Build a KiCad PCM repository for Part Search (served with GitHub Pages).

    python tools/build_pcm.py              (first - creates dist/pcm-metadata-<version>.json)
    python tools/build_pcm_repo.py [metadata.json ...]
        -> dist/pcm-repo/repository.json   the URL users add in KiCad: Plugin and Content Manager > Manage...
        -> dist/pcm-repo/packages.json     every released version (download_* fields point to GitHub releases)
        -> dist/pcm-repo/resources.zip     <identifier>/icon.png, shown in the PCM list
        -> dist/pcm-repo/index.html        short page for people who open the URL in a browser

Without arguments all dist/pcm-metadata-*.json files are used, plus the versions already published
(dist/pcm-repo-published/packages.json, if you copied the live one there), so older versions stay available.
The contents of dist/pcm-repo/ go to the gh-pages branch (see docs/RELEASING.md).
"""
import hashlib
import json
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE_URL = "https://ilkerguness.github.io/kicad-part-search/"
REPO_NAME = "Part Search by İlker Güneş (Zogolder)"
MAINTAINER = {"name": "İlker Güneş (Zogolder)", "contact": {"github": "https://github.com/IlkerGuness"}}


def _vkey(v: dict) -> tuple:
    return tuple(int(p) if p.isdigit() else 0 for p in v["version"].split("."))


def merge(files: list) -> dict:
    package = None
    versions = {}
    for f in files:
        data = json.loads(Path(f).read_text(encoding="utf-8"))
        for pkg in data.get("packages", [data]):
            if package is None or _vkey(max(pkg["versions"], key=_vkey)) >= _vkey(max(package["versions"], key=_vkey)):
                package = dict(pkg)
            for v in pkg["versions"]:
                if "download_sha256" not in v:
                    sys.exit("%s: version %s has no download_* fields - use dist/pcm-metadata-*.json" % (f, v["version"]))
                versions[v["version"]] = v
    package.pop("$schema", None)
    package["versions"] = sorted(versions.values(), key=_vkey, reverse=True)
    return package


def resource(path: Path, now: float) -> dict:
    return {"url": BASE_URL + path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "update_timestamp": int(now), "update_time_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now))}


def main() -> None:
    dist = ROOT / "dist"
    files = sys.argv[1:] or sorted(dist.glob("pcm-metadata-*.json"))
    published = dist / "pcm-repo-published" / "packages.json"
    if not sys.argv[1:] and published.exists():
        files = [published] + list(files)
    if not files:
        sys.exit("no metadata - run tools/build_pcm.py first")
    package = merge(files)
    out = dist / "pcm-repo"
    out.mkdir(parents=True, exist_ok=True)
    now = time.time()

    packages = out / "packages.json"
    packages.write_text(json.dumps({"packages": [package]}, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8", newline="\n")
    res = out / "resources.zip"
    with zipfile.ZipFile(res, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(ROOT / "kicad_plugin" / "icon_64.png", package["identifier"] + "/icon.png")
    repo = {"$schema": "https://go.kicad.org/pcm/schemas/v1#/definitions/Repository", "name": REPO_NAME,
            "maintainer": MAINTAINER, "packages": resource(packages, now), "resources": resource(res, now)}
    (out / "repository.json").write_text(json.dumps(repo, indent=2, ensure_ascii=False) + "\n",
                                         encoding="utf-8", newline="\n")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    latest = package["versions"][0]["version"]
    (out / "index.html").write_text(INDEX % {"url": BASE_URL + "repository.json", "version": latest, "name": REPO_NAME,
                                             "home": package["resources"]["homepage"]},
                                    encoding="utf-8", newline="\n")
    print("built %s: %s, versions %s" % (out, package["identifier"], ", ".join(v["version"] for v in package["versions"])))


INDEX = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Part Search - KiCad PCM repository</title>
<style>body{font-family:system-ui,sans-serif;max-width:42rem;margin:2rem auto;padding:0 1rem;line-height:1.5}
code{background:#8882;padding:.1rem .3rem;border-radius:4px;word-break:break-all}</style></head>
<body>
<h1>Part Search - KiCad PCM repository</h1>
<p>This is a package repository for KiCad's Plugin and Content Manager. Latest version: %(version)s.</p>
<ol>
<li>In the <b>KiCad main window</b> choose <b>Tools &rarr; Plugin and Content Manager</b>.</li>
<li>Click <b>Manage...</b> next to the repository list, then the <b>+</b> button.</li>
<li>Paste this address, click <b>OK</b>, then <b>Save</b>:<br><code>%(url)s</code></li>
<li>Choose <b>%(name)s</b> in the repository list, click <b>Install</b> next to Part Search, then
<b>Apply Pending Changes</b>.</li>
<li>Enable the plugin API (<b>Preferences &rarr; Plugins</b>) and restart KiCad. The Part Search button is in the
Schematic Editor toolbar.</li>
</ol>
<p>Project page, documentation and issues: <a href="%(home)s">%(home)s</a></p>
</body>
</html>
"""

if __name__ == "__main__":
    main()
