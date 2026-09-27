# Part Search - development notes

Find a JLCPCB/LCSC part, preview it, and add symbol + footprint + 3D model to a personal KiCad library -
checked by KiCad (kicad-cli) before and after writing. Library only; nothing is placed in a schematic.
Licence: GPL-3.0-or-later (`LICENSE`); third-party software and data: `THIRD_PARTY_NOTICES.md`.
All files in the repository are in English (the Turkish interface text lives in `partsearch/i18n_tr.py`).

User documentation: [README](../README.md).

## Requirements
- KiCad 9 or newer (IPC plugin API; tested: KiCad 10.0.6 on Windows 11). The window runs on KiCad's bundled
  Python + wxPython. macOS / Linux: code paths exist but are **not tested**.
- easyeda2kicad 1.0.1 - installed automatically (see below).
- Optional: the parts database of the "JLCPCB Tools" plugin (Bouni) for offline search.

## Install (user)
1. `python tools/build_plugin.py` → `dist/partsearch/` (and a zip of it).
2. Copy the `partsearch` folder into KiCad's plugins folder (`Documents\KiCad\<version>\plugins\`, see KiCad's
   *Preferences > Plugins*), restart KiCad. KiCad creates the plugin's Python environment and installs
   `requirements.txt` (easyeda2kicad, version + SHA-256 pinned) into it.
3. Schematic Editor → toolbar button *Part Search*. On the very first start the **setup assistant** opens:
   - easyeda2kicad missing → installs it (same pinned requirement) into the plugin environment, or into a private
     venv when Part Search is started outside KiCad;
   - library not known to KiCad → shows the exact changes (folder, empty libraries, path variable, two global
     library-table entries), backs up every KiCad file first, only adds entries, never creates a missing
     library table (KiCad would then skip its first-start dialog), warns if KiCad is running;
   - no local database → explains how to get it with JLCPCB Tools; online search works without it.

## Run from the source tree
- `partsearch.bat` (or `pythonw partsearch.pyw` with KiCad's Python). Command line: `python -m partsearch cli C25804`,
  `python -m partsearch search local "10k 0603"`, `python -m partsearch.checks`.
- Settings: `%APPDATA%\partsearch\settings.json` (override with `PARTSEARCH_SETTINGS`). Empty paths = auto-detect.
  Environment overrides for tests: `KICAD_CONFIG_HOME`, `KICAD_DOCUMENTS_HOME`, `PARTSEARCH_DB`, `KICAD_CLI`,
  `GETPART_PYTHON`, `MYLIB_DIR`.

## Layout
| Path | What |
|---|---|
| `partsearch/config.py` | settings + auto-detection (KiCad folders and version, kicad-cli, easyeda2kicad, DB) |
| `partsearch/library.py` | importer: fetch → transform → validate → plan → write → verify |
| `partsearch/search.py` | local (JLCPCB Tools DB, read-only FTS5) and online (easyeda2kicad) search |
| `partsearch/setup_kicad.py` | first-time setup: library registration in KiCad, easyeda2kicad install |
| `partsearch/checks.py` | "Check setup" |
| `partsearch/i18n.py`, `i18n_tr.py` | English / Turkish interface |
| `partsearch/gui/` | window, dialogs, setup assistant, theme |
| `kicad_plugin/` | plugin.json, toolbar launcher, requirements.txt, icons |
| `tools/build_plugin.py` | builds the installable plugin folder + zip |
| `tests/` | unit tests, fixture download script, GUI Escape check |

Release checklist: [RELEASING.md](RELEASING.md).

## Tests
- `python -m unittest discover -s tests -v` (no wx, no network; library tests need the fixtures).
- Fixtures (EasyEDA data, **not in the repository**): `python tests/make_fixtures.py`.
- Before 3.0.0 was released, its behaviour was compared step by step with the private 2.x code on the same parts
  (identical results). That comparison script needs the old code and is not part of the repository.
- GUI check (Windows, KiCad's Python, opens and closes each dialog with a simulated Escape key):
  `"C:\Program Files\KiCad\10.0\bin\python.exe" tests/gui_escape_check.py`
