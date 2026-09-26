# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""Double-click / launcher entry for the window (runs without a console under pythonw)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from partsearch.gui.app import main  # noqa: E402

sys.exit(main())
