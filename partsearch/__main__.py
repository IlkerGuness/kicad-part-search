# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
import sys

if len(sys.argv) > 1 and sys.argv[1] in ("cli", "import", "search"):
    from .cli import main
    args = sys.argv[2:] if sys.argv[1] in ("cli", "import") else ["--search"] + sys.argv[2:]
    sys.exit(main(args))
from .gui.app import main
sys.exit(main())
