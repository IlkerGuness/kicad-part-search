# Third-party software and data

Part Search itself is licensed under the GNU Affero General Public License v3.0 or later (see `LICENSE`).
It does **not** bundle any third-party code or data. It uses the following, each obtained separately by the user:

| What | Used for | Licence / terms | How it gets onto the computer |
|---|---|---|---|
| [easyeda2kicad](https://github.com/uPesy/easyeda2kicad.py) 1.0.1 | converting EasyEDA/LCSC parts to KiCad symbol, footprint and 3D model; JLCPCB online search | AGPL-3.0 | installed from PyPI by KiCad (`requirements.txt`) or by the setup assistant - version and SHA-256 pinned |
| [KiCad](https://www.kicad.org) (`kicad-cli`, bundled Python and wxPython) | validating and previewing parts, the window | KiCad: GPL-3.0-or-later; wxPython: wxWindows Library Licence | part of the user's KiCad installation |
| Parts database of [JLCPCB Tools](https://github.com/Bouni/kicad-jlcpcb-tools) by Bouni (optional) | offline search | the plugin is MIT-licensed; the database is built from JLCPCB's public parts list | downloaded by that plugin; Part Search only reads it (read-only) |
| Part data (symbols, footprints, 3D models, stock, prices) | the content that is imported | belongs to EasyEDA / LCSC / JLCPCB and the part manufacturers; subject to their terms of use | fetched on demand from their public services when the user searches or adds a part |

Nothing from these services is stored in this repository (the test fixtures are downloaded with
`tests/make_fixtures.py`).

## Trademarks and affiliation

JLCPCB, LCSC and EasyEDA are trademarks of their respective owners. KiCad is a trademark of the KiCad project.
Part Search is an independent project and is **not affiliated with, endorsed or sponsored by** any of them.
The names are used only to describe what the program works with.

## No warranty for imported parts

Converted symbols, footprints and 3D models can contain errors (this is also stated by easyeda2kicad). Part Search
checks that KiCad can load them, but always compare pads, pin numbers and dimensions with the datasheet before
ordering boards.
