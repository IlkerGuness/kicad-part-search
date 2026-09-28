# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""Main window: search box, results list, part details, actions."""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback
import webbrowser

import wx

from .. import APP_NAME, __version__, library, search
from ..i18n import T, set_language
from . import dialogs, theme

LCSC_PAGE = "https://www.lcsc.com/product-detail/%s.html"
JLC_PAGE = "https://jlcpcb.com/partdetail/%s"
MAX_RECENT = 12


def open_path(path) -> None:
    """Open a file or folder with the system's default program."""
    path = str(path)
    if sys.platform == "win32":
        os.startfile(path)                                   # noqa: S606 - local file chosen by the user
    else:
        import subprocess
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])


class MainFrame(wx.Frame):
    # (key, header, width, alignment)
    COLUMNS = [("lcsc", "LCSC", 90, wx.LIST_FORMAT_LEFT), ("type", "Type", 78, wx.LIST_FORMAT_LEFT),
               ("stock", "Stock", 80, wx.LIST_FORMAT_RIGHT), ("price", "Price $", 64, wx.LIST_FORMAT_RIGHT),
               ("package", "Package", 120, wx.LIST_FORMAT_LEFT), ("mfr_part", "MFR part", 170, wx.LIST_FORMAT_LEFT),
               ("manufacturer", "Manufacturer", 130, wx.LIST_FORMAT_LEFT), ("inlib", "In library", 90, wx.LIST_FORMAT_LEFT),
               ("description", "Description", 380, wx.LIST_FORMAT_LEFT)]

    def __init__(self, session):
        super().__init__(None, title="%s %s" % (APP_NAME, __version__), size=(1320, 800))
        self.ses = session
        self.results: list[dict] = []
        self.lib: dict = {}
        self.busy = False
        self._gen = 0
        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._tick, self._timer)
        self._tick_state = None
        self._sort = (None, False)
        self.prepared_cache: dict = {}          # lcsc -> download folder of the last preview (no 2nd download)
        self.log = session.logger(echo=None, callback=lambda line: wx.CallAfter(self._append_log, line))
        set_language(self.ses.settings.lang())
        self._build()
        self._set_icon()
        self._restore_geometry()
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self._refresh_lib()
        self._update_db_status()
        self.log("GUI", "%s %s window opened (pid %d, python %s %s, %s)" % (
            APP_NAME, __version__, os.getpid(), sys.executable, sys.version.split()[0], sys.platform))
        if self.ses.settings.extra.pop("_first_run", False):
            self.log("GUI", "first start (no settings file yet) - opening the setup assistant")
            self._save_settings()                  # the next start is not a first start any more
            wx.CallAfter(self._setup_assistant)
        else:
            self._check_readiness()

    # ================================================================== layout
    def _build(self):
        s = self.ses.settings
        self._build_menu()
        self.panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)

        # --- notice bar (shown only while something needed is missing)
        self.infobar = wx.InfoBar(self.panel)
        self.infobar.AddButton(self._id_setup, T("Setup assistant..."))
        self.infobar.Bind(wx.EVT_BUTTON, lambda e: self._setup_assistant(), id=self._id_setup)
        root.Add(self.infobar, 0, wx.EXPAND)

        # --- search row
        top = wx.BoxSizer(wx.HORIZONTAL)
        self.q = wx.SearchCtrl(self.panel, style=wx.TE_PROCESS_ENTER, size=(-1, 30))
        self.q.ShowCancelButton(True)
        self.q.SetDescriptiveText(T("Part number, value or LCSC id - e.g. 10k 0603, ESP32-C3, C25804"))
        self.q.Bind(wx.EVT_TEXT_ENTER, lambda e: self._search())
        self.q.Bind(wx.EVT_SEARCH, lambda e: self._search())
        self.q.Bind(wx.EVT_SEARCH_CANCEL, lambda e: self.q.SetValue(""))
        self._update_recent_menu()
        self.rb_local = wx.RadioButton(self.panel, label=T("Local database"), style=wx.RB_GROUP)
        self.rb_online = wx.RadioButton(self.panel, label=T("JLCPCB online"))
        self._db_ok = self.ses.db_info()["ok"]
        if not self._db_ok:
            self.rb_local.SetToolTip(T("Not installed - see File > Setup assistant (optional)"))
        # without the local database the online search is the only one that works
        (self.rb_online if s.default_source == "online" or not self._db_ok else self.rb_local).SetValue(True)
        self.b_search = wx.Button(self.panel, label=T("Search"))
        self.b_search.Bind(wx.EVT_BUTTON, lambda e: self._search())
        top.Add(self.q, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        top.Add(self.rb_local, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        top.Add(self.rb_online, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        top.Add(self.b_search, 0, wx.ALIGN_CENTER_VERTICAL)
        root.Add(top, 0, wx.EXPAND | wx.ALL, 8)

        flt = wx.BoxSizer(wx.HORIZONTAL)
        self.cb_basic = wx.CheckBox(self.panel, label=T("Basic / Preferred only"))
        self.cb_stock = wx.CheckBox(self.panel, label=T("In stock only"))
        self.cb_basic.SetValue(s.basic_only)
        self.cb_stock.SetValue(s.in_stock)
        self.hint = wx.StaticText(self.panel, label=T("Adds to your library only - place it with A in the "
                                                    "Schematic Editor."))
        flt.Add(self.cb_basic, 0, wx.RIGHT, 14)
        flt.Add(self.cb_stock, 0, wx.RIGHT, 14)
        flt.AddStretchSpacer()
        flt.Add(self.hint, 0, wx.ALIGN_CENTER_VERTICAL)
        root.Add(flt, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # --- results | details
        self.split = wx.SplitterWindow(self.panel, style=wx.SP_LIVE_UPDATE | wx.SP_3DSASH)
        self.split.SetMinimumPaneSize(340)
        self.split.SetSashGravity(1.0)                   # the list grows with the window, details keep their width
        self.lc = wx.ListCtrl(self.split, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for i, (_, head, w, al) in enumerate(self.COLUMNS):
            self.lc.InsertColumn(i, T(head), al, width=w)
        self.lc.Bind(wx.EVT_LIST_ITEM_SELECTED, lambda e: self._show_detail(self._current()))
        self.lc.Bind(wx.EVT_LIST_ITEM_DESELECTED, lambda e: self._show_detail(None))
        self.lc.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_activate)
        self.lc.Bind(wx.EVT_LIST_COL_CLICK, self._on_col_click)
        self.lc.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self._on_context)
        self.detail = DetailPanel(self.split, self)
        self.split.SplitVertically(self.lc, self.detail, s.sash or -400)
        root.Add(self.split, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # --- log
        self.logbox = wx.TextCtrl(self.panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL | wx.TE_RICH2,
                                  size=(-1, 150))
        self.logbox.SetFont(wx.Font(9, wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        root.Add(self.logbox, 0, wx.EXPAND | wx.ALL, 8)
        self.logbox.Show(s.show_log)

        self.panel.SetSizer(root)
        if not self.GetStatusBar():
            self.CreateStatusBar(2)
        self.GetStatusBar().SetStatusWidths([-3, -2])
        self.SetAcceleratorTable(wx.AcceleratorTable([
            (wx.ACCEL_CTRL, ord("F"), self._id_focus), (wx.ACCEL_CTRL, ord("L"), self._id_focus),
            (wx.ACCEL_NORMAL, wx.WXK_F5, self._id_research)]))
        self.Bind(wx.EVT_MENU, lambda e: (self.q.SetFocus(), self.q.SelectAll()), id=self._id_focus)
        self.Bind(wx.EVT_MENU, lambda e: self._search(), id=self._id_research)
        self.apply_theme()
        self._show_detail(None)
        self.panel.Layout()
        self.q.SetFocus()

    _id_focus = wx.NewIdRef()
    _id_research = wx.NewIdRef()
    _id_setup = wx.NewIdRef()

    def _build_menu(self):
        mb = wx.MenuBar()
        m = wx.Menu()
        self._menu(m, T("Setup assistant..."), self._setup_assistant)
        self._menu(m, T("Settings...") + "\tCtrl+,", self._settings)
        self._menu(m, T("Check setup..."), self._check_setup)
        m.AppendSeparator()
        self._menu(m, T("Open library folder"), lambda: open_path(self.ses.ctx.lib_dir))
        self._menu(m, T("Open download folder"), lambda: self._open_dir(self.ses.ctx.staging))
        self._menu(m, T("Open log file"), self._open_log)
        self._menu(m, T("Import history..."), lambda: dialogs.show_modal(dialogs.HistoryDialog(self, self.ses)))
        m.AppendSeparator()
        self._menu(m, T("Exit") + "\tCtrl+Q", self.Close)
        mb.Append(m, T("&File"))

        m = wx.Menu()
        self.mi_log = m.AppendCheckItem(wx.ID_ANY, T("Show log panel"))
        self.mi_log.Check(self.ses.settings.show_log)
        self.Bind(wx.EVT_MENU, lambda e: self._toggle_log(), self.mi_log)
        sub = wx.Menu()
        for code, label in (("system", T("Follow system")), ("light", T("Light")), ("dark", T("Dark"))):
            it = sub.AppendRadioItem(wx.ID_ANY, label)
            it.Check(self.ses.settings.theme == code)
            self.Bind(wx.EVT_MENU, lambda e, c=code: self._set_theme(c), it)
        m.AppendSubMenu(sub, T("Theme"))
        sub = wx.Menu()
        from ..i18n import LANGUAGES
        cur = self.ses.settings.lang()
        for code, meta in LANGUAGES.items():
            it = sub.AppendRadioItem(wx.ID_ANY, meta["name"])
            it.Check(cur == code)
            self.Bind(wx.EVT_MENU, lambda e, c=code: self._set_language(c), it)
        m.AppendSubMenu(sub, T("Language"))
        mb.Append(m, T("&View"))

        m = wx.Menu()
        self._menu(m, T("How it works"), lambda: dialogs.show_modal(dialogs.HelpDialog(self)))
        self._menu(m, T("About %s") % APP_NAME, lambda: dialogs.about(self))
        mb.Append(m, T("&Help"))
        self.SetMenuBar(mb)

    def _menu(self, menu, label, fn):
        it = menu.Append(wx.ID_ANY, label)
        self.Bind(wx.EVT_MENU, lambda e: fn(), it)
        return it

    def _set_icon(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        bundle = wx.IconBundle()
        for folder in (root, os.path.join(root, "kicad_plugin")):
            for n in ("icon_24.png", "icon_48.png"):
                f = os.path.join(folder, n)
                if os.path.exists(f):
                    bundle.AddIcon(wx.Icon(f, wx.BITMAP_TYPE_PNG))
            if not bundle.IsEmpty():
                self.SetIcons(bundle)
                return

    def rebuild(self):
        """Re-create all controls (language change) and keep query, filters, results and selection."""
        state = (self.q.GetValue(), self.rb_online.GetValue(), self.cb_basic.GetValue(), self.cb_stock.GetValue(),
                 self.lc.GetFirstSelected(), self.logbox.GetValue())
        self.ses.settings.sash = self.split.GetSashPosition()
        self.Freeze()
        try:
            self.panel.Destroy()
            self._build()
            q, online, basic, stock, sel, logtext = state
            self.q.SetValue(q)
            self.rb_online.SetValue(online)
            self.rb_local.SetValue(not online)
            self.cb_basic.SetValue(basic)
            self.cb_stock.SetValue(stock)
            self.logbox.SetValue(logtext)
            self._fill()
            if 0 <= sel < self.lc.GetItemCount():
                self.lc.Select(sel)
                self.lc.EnsureVisible(sel)
            self.Layout()
        finally:
            self.Thaw()
        self.status("")
        self._update_db_status()
        self._check_readiness()

    def apply_theme(self):
        self.pal = theme.palette(self.ses.settings.theme)
        theme.apply(self, self.pal)
        self.hint.SetForegroundColour(self.pal["muted"])
        self.detail.apply_palette(self.pal)
        self._fill_colours()

    # ================================================================== small helpers
    def _append_log(self, line):
        if self:                                   # the window may already be closed
            self.logbox.AppendText(line + "\n")

    def status(self, text, field=0):
        if self:
            self.SetStatusText(text, field)

    def _refresh_lib(self):
        try:
            self.lib = self.ses.library_index()
        except Exception as e:  # noqa: BLE001
            self.lib = {}
            self.log("ERROR", "cannot read the symbol library: %s" % e)
        self._update_db_status()

    def _update_db_status(self):
        d = self.ses.db_info()
        db = (T("Local DB: %s parts (%s)") % (f"{d['parts']:,}", d["date"])) if d["ok"] else T("Local DB not found")
        self.status("%s   |   %s" % (db, T("Library: %d LCSC parts") % len(self.lib)), 1)

    def _current(self):
        i = self.lc.GetFirstSelected()
        return self.results[i] if 0 <= i < len(self.results) else None

    def _selected(self):
        p = self._current()
        if p is None:
            wx.MessageBox(T("Select a part in the list first."), APP_NAME, wx.ICON_INFORMATION, self)
        return p

    def _open_dir(self, d):
        d.mkdir(parents=True, exist_ok=True)
        open_path(d)

    def _open_log(self):
        if self.ses.ctx.log_file.exists():
            open_path(self.ses.ctx.log_file)

    def _toggle_log(self):
        s = self.ses.settings
        s.show_log = not s.show_log
        self.mi_log.Check(s.show_log)
        self.logbox.Show(s.show_log)
        self.panel.Layout()
        self._save_settings()

    def _set_theme(self, code):
        self.ses.settings.theme = code
        self._save_settings()
        if theme.needs_restart(code):
            self._offer_restart()
        else:
            self.apply_theme()

    def _offer_restart(self):
        if wx.MessageBox(T("The new theme is used after the window is restarted. Restart now?"), APP_NAME,
                         wx.YES_NO | wx.ICON_QUESTION, self) == wx.YES and not self.busy:
            import subprocess
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            argv = (["-m", "partsearch"] + sys.argv[1:]) if sys.argv[0].endswith("__main__.py") else sys.argv
            subprocess.Popen([sys.executable] + argv, cwd=root, creationflags=flags, close_fds=True)
            self.Close()

    def _set_language(self, code):
        self.ses.settings.language = code
        set_language(code)
        self._save_settings()
        self.rebuild()

    def _save_settings(self):
        try:
            self.ses.settings.save()
        except OSError as e:
            self.log("ERROR", "settings not saved: %s" % e)

    # ================================================================== background work
    def _set_busy(self, busy, msg=""):
        self.busy = busy
        for w in (self.b_search, self.q):
            w.Enable(not busy)
        self.detail.enable_actions(not busy)
        if msg:
            self.status(msg)
        try:                                         # wx.SetCursor(wx.Cursor()) froze v1 of this tool - keep this
            if busy and not wx.IsBusy():
                wx.BeginBusyCursor()
            elif not busy and wx.IsBusy():
                wx.EndBusyCursor()
        except Exception:  # noqa: BLE001 - a cosmetic cursor must never block the tool
            pass

    def _run(self, work, done, msg, timeout=None):
        """work() in a thread, then done(result, error) on the GUI thread. The status bar shows the elapsed
        seconds. With a timeout (searches only - never library writes) the window stops waiting after
        `timeout` s and ignores a late answer."""
        self._gen += 1
        gen = self._gen
        self._tick_state = (gen, time.time(), msg, timeout, done)
        self._set_busy(True, msg)
        self._timer.Start(500)

        def target():
            try:
                res, err = work(), None
            except (search.SearchError, library.FetchError) as e:       # expected: no traceback in the log
                res, err = None, e
            except Exception as e:  # noqa: BLE001
                res, err = None, e
                self.log("ERROR", "%s\n%s" % (e, traceback.format_exc().rstrip()))
            wx.CallAfter(self._finish, gen, done, res, err)
        threading.Thread(target=target, daemon=True).start()

    def _tick(self, _evt=None):
        if not self._tick_state or not self.busy:
            return
        gen, t0, msg, timeout, done = self._tick_state
        if gen != self._gen:
            return
        el = time.time() - t0
        if timeout and el > timeout:
            self._gen += 1                                # abandon: a late result is ignored
            self._timer.Stop()
            self._set_busy(False)
            self.log("ERROR", "%s gave no answer within %d s - abandoned" % (msg.rstrip(". "), timeout))
            done(None, TimeoutError(T("no answer within %d s") % timeout))
            return
        self.status("%s  %d s%s" % (msg, el, T("  (still working...)") if el >= 3 else ""))

    def _finish(self, gen, done, res, err):
        if not self:
            return
        if gen != self._gen:
            self.log("INFO", "late result ignored (the window had already stopped waiting)")
            return
        self._timer.Stop()
        self._set_busy(False)
        self.status("")
        try:
            done(res, err)
        except Exception as e:  # noqa: BLE001 - never leave the window stuck
            self.log("ERROR", "GUI update failed: %s\n%s" % (e, traceback.format_exc().rstrip()))
            self.status(T("Internal error while showing the result (details in the log): %s") % e)

    # ================================================================== search
    def _search(self):
        if self.busy:
            return
        q = self.q.GetValue().strip()
        if not q:
            return
        where = "online" if self.rb_online.GetValue() else "local"
        basic, stock = self.cb_basic.GetValue(), self.cb_stock.GetValue()
        self._remember_query(q)
        src = T("local database") if where == "local" else T("JLCPCB online")

        def done(r, err):
            if err is not None:
                self.log("SEARCH", "%s '%s' FAILED: %s" % (where, q, err))
                self.results = []
                self._fill()
                self.status(T("Search failed: %s") % dialogs.translate_error(str(err)).replace("\n", " "))
                return
            n = len(r["results"])
            self.log("SEARCH", "%s '%s' basic_only=%s in_stock=%s -> %d result(s) (%d raw, %.2fs) %s"
                     % (where, q, basic, stock, n, r["total_candidates"], r["seconds"], r["note"]))
            self.results = r["results"]
            self._sort = (None, False)
            self._fill()
            if n == 0:
                msg = (T("Nothing found in the local database (%.2f s). Check the part number, try a shorter "
                         "fragment, or search JLCPCB online.") if where == "local" else
                       T("Nothing found in the JLCPCB online search (%.2f s) - JLCPCB/LCSC may not stock it.")) % r["seconds"]
            else:
                msg = (T("%d result(s) from %s in %.2f s.") % (n, src, r["seconds"]) + "  " +
                       dialogs.note_text(r["note"])).strip()
            self.status(msg)
            if n:
                self.lc.Select(0)
                self.lc.Focus(0)
        timeout = (self.ses.settings.local_timeout if where == "local" else self.ses.settings.online_timeout) + 5
        self._run(lambda: self.ses.search(where, q, basic, stock), done,
                  T("Searching %s for '%s' ...") % (src, q), timeout=timeout)

    def _remember_query(self, q):
        r = [x for x in self.ses.settings.recent if x.lower() != q.lower()]
        self.ses.settings.recent = [q] + r[:MAX_RECENT - 1]
        self._update_recent_menu()
        self._save_settings()

    def _update_recent_menu(self):
        m = wx.Menu()
        rec = self.ses.settings.recent
        if not rec:
            m.Append(wx.ID_ANY, T("(no recent searches)")).Enable(False)
        for q in rec:
            it = m.Append(wx.ID_ANY, q)
            self.Bind(wx.EVT_MENU, lambda e, q=q: (self.q.SetValue(q), self._search()), it)
        self.q.SetMenu(m)

    # ================================================================== results list
    def _cell(self, p, key):
        if key == "stock":
            return f"{p['stock']:,}"
        if key == "inlib":
            return T("yes") if self.lib.get(p["lcsc"].upper()) else ""
        if key == "type":
            return T(p["type"]) if p["type"] in ("Basic", "Preferred", "Extended") else p["type"]
        return str(p.get(key, "") or "")

    def _fill(self):
        self._refresh_lib()
        self.lc.Freeze()
        try:
            self.lc.DeleteAllItems()
            for p in self.results:
                i = self.lc.InsertItem(self.lc.GetItemCount(), p["lcsc"])
                for c, (key, *_rest) in enumerate(self.COLUMNS[1:], start=1):
                    self.lc.SetItem(i, c, self._cell(p, key))
            self._fill_colours()
        finally:
            self.lc.Thaw()
        self._show_detail(self._current())

    def _fill_colours(self):
        pal = getattr(self, "pal", None)
        if not pal:
            return
        for i, p in enumerate(self.results[:self.lc.GetItemCount()]):
            fg = pal["out"] if p["stock"] <= 0 else (pal["basic"] if p["type"] == "Basic" else pal["fg"])
            self.lc.SetItemTextColour(i, fg if fg is not None else wx.SystemSettings.GetColour(wx.SYS_COLOUR_LISTBOXTEXT))
            inlib = bool(self.lib.get(p["lcsc"].upper()))
            bg = pal["inlib"] if inlib else pal["input"]
            self.lc.SetItemBackgroundColour(i, bg if bg is not None else wx.SystemSettings.GetColour(wx.SYS_COLOUR_LISTBOX))

    def _on_col_click(self, e):
        key = self.COLUMNS[e.GetColumn()][0]
        col, rev = self._sort
        rev = not rev if col == key else key in ("stock",)
        sel = self._current()

        def k(p):
            if key == "stock":
                return p["stock"]
            if key == "price":
                try:
                    return float(p.get("price") or 1e9)
                except ValueError:
                    return 1e9
            if key == "type":
                return search.TYPE_RANK.get(p["type"], 3)
            if key == "inlib":
                return 0 if self.lib.get(p["lcsc"].upper()) else 1
            return str(p.get(key, "")).lower()
        self.results.sort(key=k, reverse=rev)
        self._sort = (key, rev)
        self._fill()
        if sel in self.results:
            i = self.results.index(sel)
            self.lc.Select(i)
            self.lc.EnsureVisible(i)

    def _on_activate(self, _e):
        act = self.ses.settings.double_click
        if act == "add":
            self._add()
        elif act == "preview":
            self._preview()

    def _on_context(self, e):
        p = self._current()
        if not p:
            return
        m = wx.Menu()
        for entry in ((T("Add to library..."), self._add), (T("Preview"), self._preview), None,
                      (T("Copy LCSC number"), lambda: self._copy(p["lcsc"])),
                      (T("Copy part number (MPN)"), lambda: self._copy(p["mfr_part"])), None,
                      (T("Open LCSC product page"), lambda: webbrowser.open(LCSC_PAGE % p["lcsc"])),
                      (T("Open JLCPCB part page"), lambda: webbrowser.open(JLC_PAGE % p["lcsc"])),
                      (T("Open datasheet"), self._datasheet)):
            if entry is None:
                m.AppendSeparator()
                continue
            label, fn = entry
            it = m.Append(wx.ID_ANY, label)
            self.Bind(wx.EVT_MENU, lambda _e, f=fn: f(), it)
        self.lc.PopupMenu(m)
        m.Destroy()

    def _copy(self, text):
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(text))
            wx.TheClipboard.Close()
            self.status(T("Copied: %s") % text)

    def _show_detail(self, p):
        self.detail.show(p, self.lib.get(p["lcsc"].upper(), []) if p else [])

    # ================================================================== preview / add
    def _preview(self):
        p = self._selected()
        if not p or self.busy:
            return
        lcsc = p["lcsc"].upper()

        def done(pp, err):
            if err is not None:
                self._fail(T("Preview of %s failed.") % lcsc, err, "preview %s" % lcsc)
                return
            self.prepared_cache[lcsc] = pp.raw_dir
            dialogs.show_modal(dialogs.PreviewDialog(self, pp, self.ses, confirm=False))
            self.status(T("Preview of %s - nothing was written to the library.") % lcsc)
        self._run(lambda: self.ses.prepare(lcsc, "suffix", self.log, use_cli=True, preview=True,
                                           raw_dir=self.prepared_cache.get(lcsc)),
                  done, T("Downloading %s for preview (nothing is written) ...") % lcsc)

    def _add(self):
        p = self._selected()
        if not p or self.busy:
            return
        lcsc = p["lcsc"].upper()
        if not library.LCSC_RE.match(lcsc):
            wx.MessageBox(T("'%s' is not an LCSC number.") % lcsc, APP_NAME, wx.ICON_ERROR, self)
            return
        existing = self.ses.lookup_existing(lcsc)
        mode = "skip"
        if existing:
            names = "\n".join("   %s  (%s%s)" % (e["symbol"], e["footprint"], ", " + e["date"] if e["date"] else "")
                              for e in existing)
            if wx.MessageBox(T("%s is already in your library:\n\n%s\n\nImport it again as a separate copy?\n\n"
                               "The existing part is never overwritten - the new copy gets the next free suffix "
                               "(NAME-1, NAME-2, ...) for symbol, footprint and 3D model.") % (lcsc, names),
                             T("Already in library"), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self) != wx.YES:
                self.log("CHECK", "%s already in library - user chose not to import again" % lcsc)
                return
            mode = "suffix"
        self._prepare_and_confirm(lcsc, mode)

    def _prepare_and_confirm(self, lcsc, mode):
        raw = self.prepared_cache.get(lcsc)

        def done(pp, err):
            if err is not None:
                self._fail(T("%s could not be prepared - nothing was written.") % lcsc, err, "prepare %s" % lcsc)
                return
            self.prepared_cache[lcsc] = pp.raw_dir
            if pp.status == "EXISTS":
                # a DIFFERENT part already uses one of the generated names
                if wx.MessageBox(T("%s: %s.\n\nAdd it as a suffixed copy (NAME-1, ...)? Nothing existing is "
                                   "overwritten.") % (lcsc, pp.detail), T("Name already used"),
                                 wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, self) == wx.YES:
                    self._prepare_and_confirm(lcsc, "suffix")
                else:
                    self.log("PLAN", "%s name clash - user cancelled" % lcsc)
                return
            if self.ses.settings.confirm_add:
                if dialogs.show_modal(dialogs.PreviewDialog(self, pp, self.ses, confirm=True)) != wx.ID_OK:
                    self.log("PLAN", "%s: user cancelled at confirmation - nothing written" % pp.lcsc)
                    return
            self._commit(pp)
        self._run(lambda: self.ses.prepare(lcsc, mode, self.log, use_cli=True, preview=True, raw_dir=raw),
                  done, T("Downloading and checking %s ...") % lcsc)

    def _commit(self, pp):
        def done(res, err):
            self._refresh_lib()
            sel = self.lc.GetFirstSelected()
            self._fill()
            if 0 <= sel < self.lc.GetItemCount():
                self.lc.Select(sel)
            if err is not None:
                self._fail(T("Adding %s FAILED.") % pp.lcsc, err, "write %s" % pp.lcsc)
                return
            self.prepared_cache.pop(pp.lcsc, None)
            self.status(T("%s added and verified: %s") % (pp.lcsc, pp.symbol))
            if self.ses.settings.show_next_steps:
                dialogs.added(self, pp, self.ses)
        self._run(lambda: self.ses.commit(pp, self.log, use_cli=True), done, T("Writing %s ...") % pp.lcsc)

    def _fail(self, title, err, what):
        """Expected failures are logged as one line (no traceback) and shown in plain words."""
        if isinstance(err, (search.SearchError, library.FetchError, TimeoutError)):
            self.log("ERROR", "%s failed: %s" % (what, err))
        dialogs.error(self, title, err)

    def _datasheet(self):
        p = self._selected()
        if p:
            if p.get("datasheet"):
                webbrowser.open(p["datasheet"])
            else:
                wx.MessageBox(T("No datasheet link for %s.") % p["lcsc"], APP_NAME, wx.ICON_INFORMATION, self)

    def _product_page(self):
        p = self._selected()
        if p:
            webbrowser.open(p.get("url") or LCSC_PAGE % p["lcsc"])

    # ================================================================== settings / checks
    def _settings(self):
        dlg = dialogs.SettingsDialog(self, self.ses)
        if dlg.ShowModal() == wx.ID_OK:
            old_lang = self.ses.settings.lang()
            self.ses.reload(dlg.result)
            self._save_settings()
            self.log("GUI", "settings saved")
            set_language(self.ses.settings.lang())
            if self.ses.settings.lang() != old_lang:
                self.rebuild()
            else:
                if theme.needs_restart(self.ses.settings.theme):
                    wx.CallAfter(self._offer_restart)
                self.apply_theme()
                self.logbox.Show(self.ses.settings.show_log)
                self.mi_log.Check(self.ses.settings.show_log)
                self.panel.Layout()
                sel = self.lc.GetFirstSelected()
                self._fill()
                if 0 <= sel < self.lc.GetItemCount():
                    self.lc.Select(sel)
        dlg.Destroy()

    def _check_setup(self):
        dialogs.show_modal(dialogs.CheckDialog(self, self.ses))

    def _setup_assistant(self):
        from .setup_dialog import SetupDialog
        dlg = SetupDialog(self, self.ses, on_change=self._after_setup)
        dlg.ShowModal()
        dlg.Destroy()
        self._check_readiness()

    def _after_setup(self):
        self._refresh_lib()
        self._update_db_status()
        ok = self.ses.db_info()["ok"]
        if ok != getattr(self, "_db_ok", ok):
            self._db_ok = ok
            self.rb_local.SetToolTip(None if ok else T("Not installed - see File > Setup assistant (optional)"))
            if ok and self.ses.settings.default_source == "local":
                self.rb_local.SetValue(True)

    def _check_readiness(self):
        """Background look at the two things without which nothing can be added; the notice bar says what is
        missing. (The local database is optional and only shown in the status bar.)"""
        s = self.ses.settings

        def work():
            from .. import setup_kicad
            missing = []
            if not s.easyeda_python_path():
                missing.append(T("easyeda2kicad is not installed"))
            try:
                plan = setup_kicad.register_plan(s)
                if plan.problems or any(c.path.name in ("kicad_common.json", "sym-lib-table", "fp-lib-table")
                                        for c in plan.changes):
                    missing.append(T("your library is not set up in KiCad yet"))
            except Exception:  # noqa: BLE001 - the notice is a convenience, never an error
                pass
            return missing

        def done(missing):
            if not self:
                return
            if missing:
                self.log("GUI", "setup incomplete: %s" % "; ".join(missing))
                self.infobar.ShowMessage(T("Part Search is not ready yet: %s.") % ", ".join(missing),
                                         wx.ICON_INFORMATION)
            elif self.infobar.IsShown():
                self.infobar.Dismiss()
        threading.Thread(target=lambda: wx.CallAfter(done, work()), daemon=True).start()

    # ================================================================== window state
    def _restore_geometry(self):
        w = self.ses.settings.window
        if len(w) == 5:
            x, y, cw, ch, maxi = w
            rect = wx.Rect(x, y, cw, ch)
            if any(wx.Display(i).GetClientArea().Intersects(rect) for i in range(wx.Display.GetCount())):
                self.SetSize(rect)
                if maxi:
                    self.Maximize()
                return
        self.Centre()

    def _on_close(self, e):
        if self.busy and wx.MessageBox(T("A download or write is still running. Close anyway?"), APP_NAME,
                                       wx.YES_NO | wx.NO_DEFAULT, self) != wx.YES:
            e.Veto()
            return
        s = self.ses.settings
        r = self.GetRect() if not self.IsMaximized() else wx.Rect(*(s.window[:4] if len(s.window) == 5 else (0, 0, 1320, 800)))
        s.window = [r.x, r.y, r.width, r.height, self.IsMaximized()]
        s.sash = self.split.GetSashPosition()
        self._save_settings()
        self._timer.Stop()
        self.log.close()
        e.Skip()


class DetailPanel(wx.Panel):
    """Right-hand side: everything about the selected part plus the actions."""

    FIELDS = [("lcsc", "LCSC"), ("type", "Type"), ("stock", "Stock"), ("price", "Price $"), ("package", "Package"),
              ("category", "Category"), ("source", "Source"), ("inlib", "In library")]

    def __init__(self, parent, frame: MainFrame):
        super().__init__(parent)
        self.frame = frame
        v = wx.BoxSizer(wx.VERTICAL)
        self.title = wx.StaticText(self, label="", style=wx.ST_ELLIPSIZE_END | wx.ST_NO_AUTORESIZE)
        f = self.title.GetFont()
        f.SetPointSize(f.GetPointSize() + 4)
        f.SetWeight(wx.FONTWEIGHT_BOLD)
        self.title.SetFont(f)
        self.sub = wx.StaticText(self, label="", style=wx.ST_ELLIPSIZE_END | wx.ST_NO_AUTORESIZE)
        v.Add(self.title, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 12)
        v.Add(self.sub, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        g = wx.FlexGridSizer(cols=2, vgap=5, hgap=12)
        g.AddGrowableCol(1)
        self.values = {}
        self.labels = []
        for key, label in self.FIELDS:
            lab = wx.StaticText(self, label=T(label))
            val = wx.StaticText(self, label="", style=wx.ST_ELLIPSIZE_END | wx.ST_NO_AUTORESIZE)
            self.labels.append(lab)
            self.values[key] = val
            g.Add(lab, 0)
            g.Add(val, 1, wx.EXPAND)
        v.Add(g, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        self.desc = wx.StaticText(self, label="")
        v.Add(self.desc, 0, wx.EXPAND | wx.ALL, 12)
        self.b_add = wx.Button(self, label=T("Add to library..."), size=(-1, 34))
        self.b_add.SetDefault()
        self.b_prev = wx.Button(self, label=T("Preview"))
        self.b_page = wx.Button(self, label=T("Product page"))
        self.b_ds = wx.Button(self, label=T("Datasheet"))
        self.b_copy = wx.Button(self, label=T("Copy LCSC number"))
        self.b_add.Bind(wx.EVT_BUTTON, lambda e: frame._add())
        self.b_prev.Bind(wx.EVT_BUTTON, lambda e: frame._preview())
        self.b_page.Bind(wx.EVT_BUTTON, lambda e: frame._product_page())
        self.b_ds.Bind(wx.EVT_BUTTON, lambda e: frame._datasheet())
        self.b_copy.Bind(wx.EVT_BUTTON, lambda e: frame._current() and frame._copy(frame._current()["lcsc"]))
        v.Add(self.b_add, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        grid = wx.GridSizer(cols=2, vgap=6, hgap=6)
        for b in (self.b_prev, self.b_ds, self.b_page, self.b_copy):
            grid.Add(b, 0, wx.EXPAND)
        v.Add(grid, 0, wx.EXPAND | wx.ALL, 12)
        self.empty = wx.StaticText(self, label=T("Search for a part, then select it in the list."))
        v.Add(self.empty, 0, wx.ALL, 12)
        # nothing may ask for more width than the pane has: long texts are ellipsized / wrapped, buttons shrink
        for w in [self.title, self.sub] + list(self.values.values()):
            w.SetMinSize((20, -1))
        for b in (self.b_add, self.b_prev, self.b_page, self.b_ds, self.b_copy):
            b.SetMinSize((60, b.GetBestSize().height))
        self.SetSizer(v)
        self.Bind(wx.EVT_SIZE, self._on_size)

    def _on_size(self, e=None):
        w = max(160, self.GetClientSize().width - 30)
        self.desc.SetLabel(getattr(self, "_desc", ""))
        self.desc.Wrap(w)
        self.desc.InvalidateBestSize()
        self.desc.SetMinSize((20, self.desc.GetBestSize().height))
        self.Layout()
        if e:
            e.Skip()

    def apply_palette(self, pal):
        self.pal = pal
        for lab in self.labels + [self.sub, self.empty]:
            lab.SetForegroundColour(pal["muted"])

    def enable_actions(self, on):
        for b in (self.b_add, self.b_prev, self.b_page, self.b_ds, self.b_copy):
            b.Enable(on and self.frame._current() is not None)

    def show(self, p, inlib_names):
        has = p is not None
        for w in [self.title, self.sub, self.desc, self.b_add, self.b_prev, self.b_page, self.b_ds, self.b_copy] + \
                self.labels + list(self.values.values()):
            w.Show(has)
        self.empty.Show(not has)
        if has:
            self.title.SetLabel(p.get("mfr_part") or p["lcsc"])
            self.sub.SetLabel("  ·  ".join(x for x in (p.get("manufacturer"), p.get("package")) if x))
            vals = {"lcsc": p["lcsc"], "type": T(p["type"]) if p["type"] in ("Basic", "Preferred", "Extended") else p["type"],
                    "stock": f"{p['stock']:,}", "price": p.get("price") or "-", "package": p.get("package") or "-",
                    "category": p.get("category") or "-",
                    "source": T("local database") if p.get("source") == "local" else T("JLCPCB online"),
                    "inlib": ", ".join(inlib_names) if inlib_names else T("no")}
            for k, v in vals.items():
                self.values[k].SetLabel(v)
            pal = getattr(self, "pal", None)
            if pal:
                self.values["inlib"].SetForegroundColour(pal["ok"] if inlib_names else pal["fg"] or wx.NullColour)
                self.values["type"].SetForegroundColour(pal["basic"] if p["type"] == "Basic" else pal["fg"] or wx.NullColour)
            self._desc = p.get("description") or ""
            for k in ("lcsc", "category", "package"):
                self.values[k].SetToolTip(self.values[k].GetLabel())
        else:
            self._desc = ""
        self.enable_actions(not self.frame.busy)
        if has:
            self.b_ds.Enable(bool(p.get("datasheet")) and not self.frame.busy)
        self._on_size()
