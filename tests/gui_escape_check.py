# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""Manual GUI check (needs wxPython, e.g. KiCad's Python; not part of the unit tests):
opens every dialog, puts the keyboard focus on a control inside it, presses Escape with wx.UIActionSimulator and
checks that the dialog closed with wx.ID_CANCEL. Uses a throw-away settings file and work folder.

    "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" tests/gui_escape_check.py
"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

TMP = Path(tempfile.mkdtemp(prefix="ps_esc_"))
os.environ["PARTSEARCH_SETTINGS"] = str(TMP / "settings.json")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import wx  # noqa: E402

from partsearch.api import Session  # noqa: E402
from partsearch.config import Settings  # noqa: E402
from partsearch.gui import dialogs, theme  # noqa: E402
from partsearch.gui.setup_dialog import SetupDialog  # noqa: E402

SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100"><rect x="10" y="10" width="80" '
       'height="40" fill="none" stroke="black"/></svg>')


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
        ("Help", lambda: dialogs.HelpDialog(frame), None),
        ("History", lambda: dialogs.HistoryDialog(frame, ses), None),
        ("Check setup", lambda: dialogs.CheckDialog(frame, ses), None),
        ("Settings", lambda: dialogs.SettingsDialog(frame, ses), None),
        ("Setup assistant", lambda: SetupDialog(frame, ses), None),
        ("Preview (focus on buttons)", lambda: dialogs.PreviewDialog(frame, fake_prepared(), ses, confirm=True), None),
        ("Preview (focus in the pictures)", lambda: dialogs.PreviewDialog(frame, fake_prepared(), ses, confirm=True),
         "click-webview"),
    ]
    results = []
    sim = wx.UIActionSimulator()

    def press_escape(dlg, how):
        if not dlg or not dlg.IsModal():
            return
        if how == "click-webview":
            import wx.html2
            views = [w for w in dlg.GetChildren() if isinstance(w, wx.html2.WebView)]
            if views:
                r = views[0].GetScreenRect()
                sim.MouseMove(r.x + r.width // 2, r.y + r.height // 2)
                sim.MouseClick()
                wx.CallLater(800, lambda: (sim.KeyDown(wx.WXK_ESCAPE), sim.KeyUp(wx.WXK_ESCAPE)))
                return
        dlg.Raise()
        sim.KeyDown(wx.WXK_ESCAPE)
        sim.KeyUp(wx.WXK_ESCAPE)

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
