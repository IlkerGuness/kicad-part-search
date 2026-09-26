# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""Start the window: python -m partsearch  (use KiCad's bundled python, it ships wxPython)."""
from __future__ import annotations

import sys
import traceback

import wx

from ..api import Session


def _install_excepthook(frame):
    """pythonw has no console: send any uncaught error to the log and a message box instead of losing it
    (that is how the 'search hangs' bug of the first version stayed invisible)."""
    def hook(t, v, tb):
        text = "".join(traceback.format_exception(t, v, tb)).rstrip()
        try:
            frame.log("ERROR", "uncaught: " + text)
        except Exception:  # noqa: BLE001
            pass
        try:
            wx.MessageBox("Unexpected error (also written to the log):\n\n%s" % text[-1500:], "Part Search",
                          wx.ICON_ERROR)
        except Exception:  # noqa: BLE001
            pass
    sys.excepthook = hook


def main() -> int:
    session = Session()
    app = wx.App(False)
    app.SetAppName("partsearch")
    from . import theme
    theme.init_native(app, session.settings.theme)      # must happen before the first window
    from .main_window import MainFrame
    frame = MainFrame(session)
    _install_excepthook(frame)
    frame.Show()
    app.MainLoop()
    return 0
