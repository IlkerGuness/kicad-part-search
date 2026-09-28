# Releasing

Checklist for a new version (Windows, KiCad 10). Every step has to pass before the tag is pushed.

1. Update `__version__` in `partsearch/__init__.py` and add the version to `CHANGELOG.md` (date, Fixed / Added /
   Changed).
2. Tests:
   - `python -m pyflakes partsearch tests tools kicad_plugin`
   - `python tests/make_fixtures.py` (once), then `python -m unittest discover -s tests` - no failures.
   - The same unit tests on Python 3.9 (the Python of KiCad 10 on macOS), e.g.
     `uv venv --python 3.9 .py39` then `.py39\Scripts\python -m unittest discover -s tests`. GitHub Actions also
     runs 3.9 and 3.11 on Windows, macOS and Linux. Do not use features newer than 3.9 (`vermin -t=3.9-` checks).
   - `"C:\Program Files\KiCad\10.0\bin\python.exe" tests/gui_escape_check.py` - "all dialogs close with Escape"
     (do not touch mouse or keyboard while it runs).
3. Build: `python tools/build_plugin.py` → `dist/partsearch-<version>.zip`, and `python tools/build_pcm.py` →
   `dist/partsearch-<version>-pcm.zip` + `dist/pcm-metadata-<version>.json`.
4. Install the build into KiCad (copy `dist/partsearch` to `Documents\KiCad\10.0\plugins\partsearch`, then in the
   Schematic Editor *Tools → Refresh Plugins*) and check by hand:
   - the toolbar button opens the window, and the title shows the new version;
   - *File → Check setup* is all OK;
   - search (local and online), preview, add a part, then find it with **A** in the Schematic Editor;
   - *Help → About* shows the version and the author.
5. Commit, tag `v<version>`, push both, and wait for the GitHub Actions run to pass.
6. Create the GitHub release from the tag: title `Part Search <version>`, notes from `CHANGELOG.md`, attach
   `partsearch-<version>.zip`, `partsearch-<version>-pcm.zip` and `SHA256SUMS.txt` (`certutil -hashfile dist\partsearch-<version>.zip SHA256`).
   - macOS (when a Mac is available): install the pcm zip with *Install from File*, then the same checks.
7. Part Search package repository (GitHub Pages, branch `gh-pages`): copy the live
   https://ilkerguness.github.io/kicad-part-search/packages.json to `dist/pcm-repo-published/packages.json` (keeps
   the older versions), run `python tools/build_pcm_repo.py`, replace the contents of the `gh-pages` branch with
   `dist/pcm-repo/` (including `.nojekyll`), push, and check in KiCad (*Plugin and Content Manager*) that the new
   version is offered.
   A package lists its platforms (`windows`, `macos`) in `tools/build_pcm.py`; KiCad offers a version only on
   the platforms listed, so add `linux` there only after it has been tested.
8. Official KiCad repository (the KiCad team declined it in September 2026; only if they agree later - the plugin uses JLCPCB / LCSC services, see
   https://dev-docs.kicad.org/en/addons/ "Commercial Services"): add the new entry of `dist/pcm-metadata-<version>.json` to
   `packages/<identifier>/metadata.json` in a merge request to https://gitlab.com/kicad/addons/metadata
   (the pcm zip must already be attached to the GitHub release, because `download_url` points there).
