# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""Setup assistant: the three things a new user may be missing, each with its status and a way to fix it.
Opened automatically on the very first start, later from File > Setup assistant or the notice bar."""
from __future__ import annotations

import threading
import webbrowser
from pathlib import Path

import wx

from .. import search, setup_kicad
from ..i18n import T
from . import theme
from .dialogs import _themed

JLCPCB_TOOLS_URL = "https://github.com/Bouni/kicad-jlcpcb-tools"


class SetupDialog(wx.Dialog):
    def __init__(self, parent, ses, on_change=None):
        super().__init__(parent, title=T("Setup assistant"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
                         size=(820, 700))
        self.ses = ses
        self.on_change = on_change or (lambda: None)
        self.pal = getattr(parent, "pal", None) or theme.palette("system")
        self.plan = None
        outer = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(self, label=T("Part Search needs three things. Everything below can also be done by "
                                            "hand - nothing is changed without your click, and every KiCad file "
                                            "is backed up before it is changed."))
        intro.Wrap(760)
        outer.Add(intro, 0, wx.ALL, 12)

        # 1 --- easyeda2kicad
        box, self.st_easy = self._section(outer, T("1. Downloading parts (easyeda2kicad)"))
        p = box.GetStaticBox()
        self.tx_easy = self._text(box)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.b_install = wx.Button(p, label=T("Install easyeda2kicad"))
        self.b_install.Bind(wx.EVT_BUTTON, self._install)
        row.Add(self.b_install, 0)
        box.Add(row, 0, wx.TOP, 6)

        # 2 --- library in KiCad
        box, self.st_lib = self._section(outer, T("2. Your library in KiCad"))
        p = box.GetStaticBox()
        self.tx_lib = self._text(box)
        self.plan_box = wx.TextCtrl(p, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(-1, 110))
        self.plan_box.SetFont(wx.Font(9, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        box.Add(self.plan_box, 0, wx.EXPAND | wx.TOP, 6)
        self.tx_running = wx.StaticText(p, label="")
        self.tx_running.SetForegroundColour(self.pal["warn"])
        self.tx_running._keep_colours = True
        box.Add(self.tx_running, 0, wx.TOP, 6)
        row = wx.BoxSizer(wx.HORIZONTAL)
        self.b_apply = wx.Button(p, label=T("Set up in KiCad"))
        self.b_apply.Bind(wx.EVT_BUTTON, self._apply)
        self.b_manual = wx.Button(p, label=T("Show manual steps"))
        self.b_manual.Bind(wx.EVT_BUTTON, self._manual)
        row.Add(self.b_apply, 0, wx.RIGHT, 6)
        row.Add(self.b_manual, 0)
        box.Add(row, 0, wx.TOP, 6)

        # 3 --- local DB
        box, self.st_db = self._section(outer, T("3. Offline search (optional)"))
        p = box.GetStaticBox()
        self.tx_db = self._text(box)
        row = wx.BoxSizer(wx.HORIZONTAL)
        b = wx.Button(p, label=T("Choose database file..."))
        b.Bind(wx.EVT_BUTTON, self._choose_db)
        row.Add(b, 0, wx.RIGHT, 6)
        b = wx.Button(p, label=T("JLCPCB Tools web page"))
        b.Bind(wx.EVT_BUTTON, lambda e: webbrowser.open(JLCPCB_TOOLS_URL))
        row.Add(b, 0)
        box.Add(row, 0, wx.TOP, 6)

        # bottom
        self.gauge = wx.Gauge(self, range=100, size=(-1, 6))
        self.gauge.Hide()
        outer.Add(self.gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        bs = wx.BoxSizer(wx.HORIZONTAL)
        self.b_recheck = wx.Button(self, label=T("Check again"))
        self.b_recheck.Bind(wx.EVT_BUTTON, lambda e: self.refresh())
        bs.Add(self.b_recheck, 0)
        bs.AddStretchSpacer()
        close = wx.Button(self, wx.ID_CANCEL, T("Close"))
        bs.Add(close, 0)
        outer.Add(bs, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizer(outer)
        _themed(self, parent)
        self.CentreOnParent()
        self._busy = False
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.refresh()

    # ---------------------------------------------------------------- layout helpers
    def _section(self, outer, title):
        sb = wx.StaticBoxSizer(wx.VERTICAL, self, title)     # its controls are children of the box (wx 3.3)
        head = wx.BoxSizer(wx.HORIZONTAL)
        st = wx.StaticText(sb.GetStaticBox(), label="")
        f = st.GetFont()
        f.SetWeight(wx.FONTWEIGHT_BOLD)
        st.SetFont(f)
        st._keep_colours = True
        head.Add(st, 0)
        sb.Add(head, 0, wx.BOTTOM, 4)
        outer.Add(sb, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        return sb, st

    def _text(self, box):
        t = wx.StaticText(box.GetStaticBox(), label="")
        box.Add(t, 0, wx.EXPAND)
        return t

    def _status(self, st, ok, text):
        st.SetLabel(text)
        st.SetForegroundColour(self.pal["ok"] if ok is True else (self.pal["warn"] if ok is False else self.pal["note"]))

    def _set(self, t, text):
        t._raw = text
        t.SetLabel(text)

    def _wrap(self, fit=True):
        """Wrap the long texts to the dialog width; with fit, make the dialog exactly as tall as its content."""
        w = max(300, self.GetClientSize().width - 60)
        self._wrapped_at = self.GetClientSize().width
        for t in (self.tx_easy, self.tx_lib, self.tx_db, self.tx_running):
            t.SetLabel(getattr(t, "_raw", t.GetLabel()))
            t.Wrap(w)
            t.InvalidateBestSize()
        self.Layout()
        if fit:
            need = self.GetSizer().GetMinSize().height
            disp = wx.Display(max(0, wx.Display.GetFromWindow(self))).GetClientArea().height
            self.SetClientSize((self.GetClientSize().width, min(need, disp - 80)))
            self.Layout()

    def _on_size(self, e):
        e.Skip()
        if getattr(self, "_wrapped_at", None) not in (None, self.GetClientSize().width):
            wx.CallAfter(lambda: self and self._wrap(fit=False))

    # ---------------------------------------------------------------- state
    def refresh(self):
        """Re-detect everything (in a thread: kicad-cli and the Python checks take a moment)."""
        if self._busy:
            return
        self._set_busy(True)
        s = self.ses.settings

        def work():
            from .. import config
            config.forget_detection()
            search.forget_detection()
            py = s.easyeda_python_path()
            target, needs_venv = setup_kicad.easyeda_target()
            try:
                plan = setup_kicad.register_plan(s)
            except Exception as e:  # noqa: BLE001
                plan = setup_kicad.Plan(problems=[("%s", (e,))])
            return dict(py=py, target=target, needs_venv=needs_venv, plan=plan, db=search.db_info(s.jlcpcb_db_path()),
                        running=setup_kicad.kicad_running())

        def done(r):
            if not self:
                return
            self._set_busy(False)
            self._show(r)
        threading.Thread(target=lambda: wx.CallAfter(done, work()), daemon=True).start()

    def _show(self, r):
        # 1
        if r["py"]:
            self._status(self.st_easy, True, T("Installed"))
            self._set(self.tx_easy, T("Found in %s") % r["py"])
            self.b_install.Hide()
        else:
            self._status(self.st_easy, False, T("Missing - needed for online search and for adding parts"))
            self._set(self.tx_easy, T("'Install' downloads easyeda2kicad %s from PyPI with pip (version and checksum "
                                    "are fixed) into:\n%s%s") % ("1.0.1", Path(r["target"]).parent.parent,
                                                                  T("  (a new private environment)") if r["needs_venv"]
                                                                  else ""))
            self.b_install.Show()
        # 2
        self.plan = plan = r["plan"]
        if not plan.needed and not plan.problems:
            self._status(self.st_lib, True, T("Set up"))
            self._set(self.tx_lib, T("KiCad knows the library folder %s.") % self.ses.settings.library_path())
            self.plan_box.SetValue("")
            self.plan_box.Hide()
            self.b_apply.Hide()
        else:
            self._status(self.st_lib, False if plan.needed else None,
                         T("Not set up yet") if plan.needed else T("Needs your attention"))
            lines = []
            for c in plan.changes:
                lines.append("+ %s: %s" % (T(c.what), c.path) + (("\n      " + c.detail) if c.detail else ""))
            for fmt, args in plan.problems:
                lines.append("! " + T(fmt) % args)
            self.plan_box.SetValue("\n".join(lines))
            self.plan_box.Show()
            self._set(self.tx_lib, T("Library folder: %s\n'Set up in KiCad' makes these changes (a backup of every "
                                   "changed KiCad file is kept in the library's .history folder):")
                                 % self.ses.settings.library_path())
            self.b_apply.Show(plan.needed)
        self._set(self.tx_running, T("KiCad is running. Close every KiCad window first (Part Search stays open), then "
                                   "press 'Set up in KiCad' - KiCad keeps its settings in memory and could otherwise "
                                   "overwrite the change when it closes.") if r["running"] and plan.needed else "")
        self.tx_running.Show(bool(self.tx_running._raw))
        # 3
        d = r["db"]
        if d["ok"]:
            self._status(self.st_db, True, T("Found"))
            self._set(self.tx_db, T("%s parts, downloaded %s\n%s") % (f"{d['parts']:,}", d["date"], d["path"]))
        else:
            self._status(self.st_db, None, T("Not installed - search uses JLCPCB online"))
            self._set(self.tx_db, T(
                "Offline search uses the parts database of the free 'JLCPCB Tools' plugin (by Bouni). To get it: "
                "KiCad > Plugin and Content Manager > Plugins > 'JLCPCB Tools' > Install. Then open JLCPCB Tools "
                "in the PCB Editor once and let it download its parts database (about 1 GB). Part Search finds the "
                "file by itself - no need to restart it."))
        self._wrap()

    def _set_busy(self, busy):
        self._busy = busy
        for b in (self.b_install, self.b_apply, self.b_recheck):
            b.Enable(not busy)
        self.gauge.Show(busy)
        if busy:
            self.gauge.Pulse()
            self._pulse = wx.CallLater(150, self._keep_pulsing)
        self.Layout()

    def _keep_pulsing(self):
        if self and self._busy:
            self.gauge.Pulse()
            self._pulse = wx.CallLater(150, self._keep_pulsing)

    # ---------------------------------------------------------------- actions
    def _install(self, _e):
        if wx.MessageBox(T("Download and install easyeda2kicad 1.0.1 from PyPI now?\n\nIt is the open-source "
                           "converter (AGPL-3.0) that turns EasyEDA/LCSC parts into KiCad files. Needs internet; "
                           "takes about half a minute."), T("Setup assistant"), wx.YES_NO | wx.ICON_QUESTION,
                         self) != wx.YES:
            return
        self._set_busy(True)
        log = self.GetParent().log if hasattr(self.GetParent(), "log") else None

        def work():
            try:
                return setup_kicad.install_easyeda(self.ses.settings.work_path(), log)
            except Exception as e:  # noqa: BLE001
                return False, str(e)

        def done(res):
            if not self:
                return
            ok, out = res
            self._set_busy(False)
            if ok:
                self.ses.reload(self.ses.settings)
                self.on_change()
                wx.MessageBox(T("easyeda2kicad is installed."), T("Setup assistant"), wx.ICON_INFORMATION, self)
            else:
                wx.MessageBox(T("The installation failed. Check the internet connection and try again.\n\n%s")
                              % out[-800:], T("Setup assistant"), wx.ICON_ERROR, self)
            self.refresh()
        threading.Thread(target=lambda: wx.CallAfter(done, work()), daemon=True).start()

    def _apply(self, _e):
        if not self.plan or not self.plan.needed:
            return
        running = setup_kicad.kicad_running()
        if running and wx.MessageBox(T("KiCad is still running. The library entries are kept, but KiCad may overwrite the "
                                       "path variable if it saves its own settings when it closes. Part Search checks "
                                       "this at its next start and offers the setup again.\n\nContinue anyway?"), T("Setup assistant"),
                                     wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self) != wx.YES:
            return
        log = self.GetParent().log if hasattr(self.GetParent(), "log") else None
        try:
            done = setup_kicad.register_apply(self.plan, self.ses.settings.library_path() / ".history", log)
        except OSError as e:
            wx.MessageBox(T("The setup could not be written: %s") % e, T("Setup assistant"), wx.ICON_ERROR, self)
            return
        self.ses.reload(self.ses.settings)
        self.on_change()
        wx.MessageBox(T("Done (%d change(s)). Start KiCad again so that it reads the new settings.")
                      % len([d for d in done if not d.startswith("backup")]), T("Setup assistant"),
                      wx.ICON_INFORMATION, self)
        self.refresh()

    def _manual(self, _e):
        s = self.ses.settings
        lib = s.library_path().as_posix()
        text = T("In KiCad's main window:\n\n"
                 "1. Preferences > Configure Paths: add the variable %s with the path\n   %s\n\n"
                 "2. Preferences > Manage Symbol Libraries > Global Libraries: add\n   nickname %s, path "
                 "${%s}/%s.kicad_sym\n\n"
                 "3. Preferences > Manage Footprint Libraries > Global Libraries: add\n   nickname %s, path "
                 "${%s}/%s.pretty\n\n"
                 "Part Search creates the files on the first 'Add to library'. If you want the libraries to exist "
                 "before that, use 'Set up in KiCad' instead.") % (s.path_variable, lib, s.symbol_lib,
                                                                  s.path_variable, s.symbol_lib, s.footprint_lib,
                                                                  s.path_variable, s.footprint_lib)
        dlg = wx.Dialog(self, title=T("Manual steps"), size=(640, 380), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        t = wx.TextCtrl(dlg, value=text, style=wx.TE_MULTILINE | wx.TE_READONLY)
        v = wx.BoxSizer(wx.VERTICAL)
        v.Add(t, 1, wx.EXPAND | wx.ALL, 10)
        v.Add(wx.Button(dlg, wx.ID_CANCEL, T("Close")), 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        dlg.SetSizer(v)
        _themed(dlg, self)
        dlg.CentreOnParent()
        dlg.ShowModal()
        dlg.Destroy()

    def _choose_db(self, _e):
        dlg = wx.FileDialog(self, T("JLCPCB database (local search)"), wildcard="*.db|*.db",
                            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            info = search.db_info(Path(path))
            if not info["ok"] or info.get("detail"):
                wx.MessageBox(T("This file is not a JLCPCB Tools parts database."), T("Setup assistant"),
                              wx.ICON_WARNING, self)
            else:
                self.ses.settings.jlcpcb_db = path
                self.ses.reload(self.ses.settings)
                self.on_change()
                self.refresh()
        dlg.Destroy()
