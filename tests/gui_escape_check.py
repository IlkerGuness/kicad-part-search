# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""Manual GUI check (needs wxPython, e.g. KiCad's Python; not part of the unit tests):
opens every dialog, puts the keyboard focus on a control inside it, presses a real Escape key (Windows SendInput -
KiCad's wxPython has no UIActionSimulator) and checks that the dialog closed with wx.ID_CANCEL. Uses a throw-away
settings file and work folder. Windows only; do not touch mouse or keyboard while it runs (about 20 s).

    "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" tests/gui_escape_check.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

TMP = Path(tempfile.mkdtemp(prefix="ps_esc_"))
os.environ["PARTSEARCH_SETTINGS"] = str(TMP / "settings.json")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import wx  # noqa: E402
import wx.html2  # noqa: E402,F401

from partsearch.api import Session  # noqa: E402
from partsearch.config import Settings  # noqa: E402
from partsearch.gui import dialogs, theme  # noqa: E402
from partsearch.gui.setup_dialog import SetupDialog  # noqa: E402

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><rect x="10" y="10" width="80" '
       'height="40" fill="none" stroke="black"/></svg>')


class _WinInput:
    """Real key presses / clicks through the Windows API, delivered to whatever window has the focus."""

    def __init__(self):
        import ctypes
        self.u = ctypes.windll.user32

    def focus(self, win):
        win.Raise()
        self.u.SetForegroundWindow(win.GetHandle())

    def escape(self):
        self.u.keybd_event(0x1B, 0, 0, 0)          # VK_ESCAPE down
        self.u.keybd_event(0x1B, 0, 2, 0)          # KEYEVENTF_KEYUP

    def click(self, x, y):
        self.u.SetCursorPos(int(x), int(y))
        self.u.mouse_event(0x0002, 0, 0, 0, 0)     # left down
        self.u.mouse_event(0x0004, 0, 0, 0, 0)     # left up


def fake_prepared() -> SimpleNamespace:
    d = TMP / "preview"
    d.mkdir(exist_ok=True)
    svgs = []
    for n in ("SYM", "FP"):
        f = d / (n + ".svg")
        f.write_text(SVG, encoding="utf-8")
        svgs.append(f)
    return SimpleNamespace(lcsc="C0", symbol="SYM", footprint="FP", fp_action="new", model_files=[],
                           info={"pins": 2, "pads": 2}, warnings=[], previews=svgs)


def main() -> int:
    app = wx.App(False)
    theme.init_native(app, "system")
    s = Settings(work_dir=str(TMP / "work"), library_dir=str(TMP / "lib"))
    ses = Session(s)
    frame = wx.Frame(None, title="escape check")
    frame.pal = theme.palette("system")
    frame.Show()
    cases = [
        ("Check setup", lambda: dialogs.CheckDialog(frame, ses), None),
        ("Settings", lambda: dialogs.SettingsDialog(frame, ses), None),
        ("Setup assistant", lambda: SetupDialog(frame, ses), None),
        ("Preview (focus on buttons)", lambda: dialogs.PreviewDialog(frame, fake_prepared(), ses, confirm=True), None),
        ("Preview (focus in the pictures)", lambda: dialogs.PreviewDialog(frame, fake_prepared(), ses, confirm=True),
         "click-webview"),
        ("Help", lambda: dialogs.HelpDialog(frame), None),
        ("History", lambda: dialogs.HistoryDialog(frame, ses), None),
    ]
    results = []
    sim = _WinInput()
    # a process started in the background may not take the keyboard focus at once: bring the window forward and
    # give Windows a moment before the first key press
    sim.focus(frame)
    end = time.time() + 1.5
    while time.time() < end:
        wx.Yield()

    def press_escape(dlg, how):
        if not dlg or not dlg.IsModal():
            return
        if how == "click-webview":
            views = [w for w in dlg.GetChildren() if isinstance(w, wx.html2.WebView)]
            if views:
                r = views[0].GetScreenRect()
                sim.click(r.x + r.width // 2, r.y + r.height // 2)
                wx.CallLater(800, sim.escape)
                return
        sim.focus(dlg)
        wx.CallLater(300, sim.escape)

    for name, make, how in cases:
        dlg = make()
        guard = wx.CallLater(8000, lambda d=dlg: d and d.IsModal() and d.EndModal(-1))    # never hang
        wx.CallLater(2500, press_escape, dlg, how)
        rc = dlg.ShowModal()
        guard.Stop()
        dlg.Destroy()
        results.append((name, rc == wx.ID_CANCEL))
        print("%-4s %s" % ("OK" if rc == wx.ID_CANCEL else "FAIL", name), flush=True)
    frame.Destroy()
    bad = [n for n, ok in results if not ok]
    print("all dialogs close with Escape" if not bad else "NOT closed by Escape: " + ", ".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
