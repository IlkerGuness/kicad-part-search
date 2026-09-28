# Changelog

All notable changes to Part Search. Versions follow [Semantic Versioning](https://semver.org): the major number
changes when the tool is rebuilt or its way of working changes, the minor number for new features, the patch
number for fixes.

Versions before 3.0.0 were private (used on one machine only) and are listed for completeness.

## [3.0.3] - 2026-09-28

### Fixed
- macOS: adding a part failed with "write_text() got an unexpected keyword argument 'newline'". KiCad's Python on
  macOS is older than 3.10, where `Path.write_text(newline=...)` was added. The symbol library is now written with
  `open(..., newline="\n")`. Nothing was written when it failed (the library was left unchanged).
- macOS: kicad-cli is now also found when KiCad is not at `/Applications/KiCad/KiCad.app` - it is taken from the
  KiCad app whose Python runs Part Search, then `/Applications` and `~/Applications` are searched.
- macOS: if KiCad's Python finds no system certificate file, `SSL_CERT_FILE` is pointed at certifi's bundle, so
  online search and downloads do not fail with CERTIFICATE_VERIFY_FAILED.

### Changed
- Tested on macOS (KiCad 10, Intel MacBook Pro): install from the package, setup assistant, online search, preview,
  add a part and find it with **A**. The package now lists macOS as a supported platform.
- Minimum Python is stated and checked: 3.9 (KiCad 10 bundles 3.9 on macOS, 3.11 on Windows). An older Python
  stops with a clear message; *Check setup* shows the Python version and CPU type. The tests run on 3.9 and 3.11,
  on Windows, macOS and Linux.

### Added
- Own package repository for KiCad's Plugin and Content Manager on GitHub Pages
  (`https://ilkerguness.github.io/kicad-part-search/repository.json`), built with `tools/build_pcm_repo.py`, so
  Part Search can be installed and updated from inside KiCad.

## [3.0.2] - 2026-09-27

### Changed
- Licence changed from AGPL-3.0-or-later to GPL-3.0-or-later, the licence of KiCad and of most KiCad plugins, so
  the package can be listed in KiCad's Plugin and Content Manager. easyeda2kicad (AGPL-3.0) is not included and
  is installed separately; the two licences explicitly allow this combination.

### Added
- Package for KiCad's Plugin and Content Manager (`tools/build_pcm.py`, `partsearch-3.0.2-pcm.zip`): install it
  with *Plugin and Content Manager → Install from File…*.

## [3.0.1] - 2026-09-27

First public release.

### Fixed
- Escape closes every dialog. In 3.0.0 the preview did not close when its pictures had the keyboard focus (the
  embedded web view kept the key); checked with real key presses on Windows for all seven dialogs.
- Dialogs are destroyed after closing instead of staying in memory.
- Setup assistant: controls are created inside their section box (wxWidgets 3.3 warned about the layout).
- Preview: the footprint line no longer shows nested brackets.

### Changed
- Plugin identifier is now `io.github.ilkerguness.partsearch` (KiCad creates a fresh plugin environment for it and
  installs easyeda2kicad from `requirements.txt` - verified).
- About box shows the author, the project page and the licence.
- The "added" message no longer asks to reopen the Schematic Editor - the new part is found with A right away.
- The command-line summary header says "partsearch" instead of the old name "getpart".

## [3.0.0] - 2026-09-27 (private)

Complete rewrite as an installable KiCad plugin.

### Added
- Setup assistant, opened on the first start: installs easyeda2kicad (pinned version and hashes), registers the
  personal library in KiCad (backup of every changed file, only additions), explains how to get the optional
  offline parts database.
- Settings window: language (English, Turkish), theme (system, light, dark), library names and folders, tools,
  search limits, double-click action.
- "Check setup" report; notice bar when something needed is missing.
- Preview window with symbol and footprint pictures before anything is written.
- Online search is chosen automatically when the offline database is not installed.
- New symbol libraries are written in the file format of the KiCad version in use.
- Clear message when EasyEDA cannot be reached (instead of "part has no CAD data").
- Unit tests, a behaviour comparison against the previous version, `tools/build_plugin.py`.

### Changed
- One Python package (`partsearch/`) instead of loose scripts; no personal paths, everything auto-detected.
- The plugin folder is self-contained; KiCad installs the only dependency from `requirements.txt`.
- Licensed under AGPL-3.0-or-later.

## [2.0.2] - 2026-09-25 (private)

### Fixed
- The summary of a skipped part no longer claims a new footprint.

## [2.0.1] - 2026-09-25 (private)

### Fixed
- Searches never finished in the window: a wxPython cursor call raised an error inside the worker hand-off. Errors
  are now logged and shown, and a watchdog stops waiting for a search that does not answer.
- A late result could write to an already closed log.

## [2.0.0] - 2026-09-25 (private)

First version with a window: "Part Search".

### Added
- Search in the offline JLCPCB parts database (from the JLCPCB Tools plugin) and online at JLCPCB.
- Result list with Basic / Preferred / Extended, stock, price and "already in library".
- Import pipeline with named stages (check, fetch, transform, validate, plan, write, verify); symbols and
  footprints are loaded by `kicad-cli` before and after writing.
- Importing a part again creates a suffixed copy (`NAME-1`) instead of overwriting.
- SVG / HTML preview, import history, log.
- Button in the Schematic Editor toolbar (KiCad IPC plugin).

## [1.0.1] - 2026-09-25 (private)

### Fixed
- Each run uses its own staging folder, so a second import no longer fails on leftovers.
- Console output and UTF-8 text (Chinese manufacturer names) on Windows PowerShell.

## [1.0.0] - 2026-09-25 (private)

### Added
- `getpart`: command-line import of an LCSC part (symbol, footprint, 3D model) into one personal library with
  consistent names, `${MYLIB_DIR}` 3D paths, a parts registry and backups; never overwrites an existing part.

[3.0.3]: https://github.com/IlkerGuness/kicad-part-search/releases/tag/v3.0.3
[3.0.2]: https://github.com/IlkerGuness/kicad-part-search/releases/tag/v3.0.2
[3.0.1]: https://github.com/IlkerGuness/kicad-part-search/releases/tag/v3.0.1
