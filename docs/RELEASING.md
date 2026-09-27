# Releasing

Checklist for a new version (Windows, KiCad 10). Every step has to pass before the tag is pushed.

1. Update `__version__` in `partsearch/__init__.py` and add the version to `CHANGELOG.md` (date, Fixed / Added /
   Changed).
2. Tests:
   - `python -m pyflakes partsearch tests tools kicad_plugin`
   - `python tests/make_fixtures.py` (once), then `python -m unittest discover -s tests` - no failures.
   - `"C:\Program Files\KiCad\10.0\bin\python.exe" tests/gui_escape_check.py` - "all dialogs close with Escape"
     (do not touch mouse or keyboard while it runs).
3. Build: `python tools/build_plugin.py` → `dist/partsearch-<version>.zip`.
4. Install the build into KiCad (copy `dist/partsearch` to `Documents\KiCad\10.0\plugins\partsearch`, then in the
   Schematic Editor *Tools → Refresh Plugins*) and check by hand:
   - the toolbar button opens the window, and the title shows the new version;
   - *File → Check setup* is all OK;
   - search (local and online), preview, add a part, then find it with **A** in the Schematic Editor;
   - *Help → About* shows the version and the author.
5. Commit, tag `v<version>`, push both, and wait for the GitHub Actions run to pass.
6. Create the GitHub release from the tag: title `Part Search <version>`, notes from `CHANGELOG.md`, attach
   `partsearch-<version>.zip` and `SHA256SUMS.txt` (`certutil -hashfile dist\partsearch-<version>.zip SHA256`).
