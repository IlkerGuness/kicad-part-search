# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""Part Search - find JLCPCB/LCSC parts and add symbol, footprint and 3D model to a personal KiCad library."""
__version__ = "3.0.3"
APP_NAME = "Part Search"
AUTHOR = "İlker Güneş (Zogolder)"
PROJECT_URL = "https://github.com/IlkerGuness/kicad-part-search"

# Oldest Python the code runs on. KiCad 10 bundles Python 3.9 on macOS (3.11 on Windows) and easyeda2kicad 1.0.1
# needs 3.9 too. Checked here, before any other module is imported, so an older Python gives this message
# instead of a confusing error somewhere later. Keep this file free of newer syntax.
MIN_PYTHON = (3, 9)

import sys as _sys  # noqa: E402

if _sys.version_info < MIN_PYTHON:
    raise ImportError("%s needs Python %d.%d or newer (this is Python %d.%d at %s). Use KiCad 10 (its bundled "
                      "Python) or a newer Python." % ((APP_NAME,) + MIN_PYTHON + tuple(_sys.version_info[:2])
                                                     + (_sys.executable,)))
