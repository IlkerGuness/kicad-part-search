# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""Dialogs: settings, setup check, preview/confirm, history, help, about, messages."""
from __future__ import annotations

import copy
import threading
import webbrowser
from pathlib import Path

import wx
import wx.adv

from .. import APP_NAME, AUTHOR, PROJECT_URL, __version__, checks
from ..config import Settings
from ..i18n import LANGUAGES, T
from . import theme


def _themed(dlg: wx.Dialog, parent) -> None:
    """Colours, and Escape closes the dialog - through three independent routes, because on Windows a focused
    child (multi-line text, list, web view) can swallow the key before the dialog's default handling sees it:
    the dialog's escape id, a dialog-level accelerator, and a char hook."""
    pal = getattr(parent, "pal", None) or theme.palette("system")
    theme.apply(dlg, pal)
    dlg.SetEscapeId(wx.ID_CANCEL)

    def close(_e=None):
        if not dlg:
            return
        if dlg.IsModal():
            dlg.EndModal(wx.ID_CANCEL)
        else:
            dlg.Close()

    esc_id = wx.NewIdRef()
    dlg.SetAcceleratorTable(wx.AcceleratorTable([(wx.ACCEL_NORMAL, wx.WXK_ESCAPE, esc_id)]))
    dlg.Bind(wx.EVT_MENU, close, id=esc_id)

    def hook(e):
        if e.GetKeyCode() == wx.WXK_ESCAPE:
            close()
        else:
            e.Skip()
    dlg.Bind(wx.EVT_CHAR_HOOK, hook)
    dlg._close_on_escape = close                   # used by the web view (it runs in its own process)


def show_modal(dlg: wx.Dialog) -> int:
    """ShowModal + Destroy (a dialog that is only hidden stays in memory until the program ends)."""
    try:
        return dlg.ShowModal()
    finally:
        dlg.Destroy()


def error(parent, title: str, err) -> None:
    wx.MessageBox("%s\n\n%s\n\n%s" % (title, translate_error(str(err)), T("Details are in the log (File > Open log file).")),
                  APP_NAME, wx.ICON_ERROR, parent)


def translate_error(msg: str) -> str:
    """Friendly text for the expected errors; anything else is shown as it is (English)."""
    table = [
        ("EasyEDA could not be reached", T("EasyEDA could not be reached. Check the internet connection (a "
                                           "firewall or proxy may block easyeda.com).")),
        ("EasyEDA has no CAD data for", T("EasyEDA has no symbol/footprint for this part, so it cannot be imported "
                                          "automatically. Pick another part or draw it yourself.")),
        ("easyeda2kicad was not found", T("easyeda2kicad is not installed. File > Setup assistant installs it.")),
        ("easyeda2kicad not found", T("easyeda2kicad is not installed. File > Setup assistant installs it.")),
        ("easyeda2kicad failed", T("The download failed. Check the internet connection and the LCSC number.")),
        ("kicad-cli not found", T("kicad-cli was not found. Set it in Settings > Tools.")),
        ("enter at least one search word", T("Enter at least one word with 3 or more characters.")),
        ("local JLCPCB database not found", T("The local JLCPCB database is not installed (it is optional). "
                                              "File > Setup assistant shows how to get it - or search JLCPCB "
                                              "online.")),
        ("local search stopped after", T("The local search took too long - add more words (value, package, MPN).")),
        ("online search failed", T("The online search failed (no internet, or JLCPCB did not answer).")),
        ("no answer within", T("No answer in time - try again, or add more words.")),
    ]
    for key, text in table:
        if key in msg:
            return "%s\n(%s)" % (text, msg) if _lang_is_not_en() else msg
    return msg


def _lang_is_not_en() -> bool:
    from .. import i18n
    return i18n._lang != "en"


def note_text(note: str) -> str:
    if not note:
        return ""
    out = []
    for part in note.split("; "):
        if part.startswith("more than"):
            out.append(T("Very many matches - add words (value, package, MPN) to narrow down."))
        elif part.startswith("no word match"):
            out.append(T("No whole-word match - showing partial matches."))
        elif part.startswith("online shows the first"):
            nums = [w for w in part.split() if w.isdigit()]
            out.append(T("Showing the first %s of %s online matches.") % (nums[0], part.split()[-2])
                       if nums else part)
        else:
            out.append(part)
    return "  ".join(out)


def added(parent, pp, ses) -> None:
    wx.MessageBox(T("%s was added and verified on disk.\n\nSymbol: %s   (library %s)\nFootprint: %s:%s\n\n"
                    "Next: in the Schematic Editor press A and search '%s'.") % (pp.lcsc, pp.symbol, ses.ctx.symbol_lib, ses.ctx.footprint_lib,
                                                       pp.footprint, pp.symbol),
                  T("Added"), wx.ICON_INFORMATION, parent)


def about(parent) -> None:
    info = wx.adv.AboutDialogInfo()
    info.SetName(APP_NAME)
    info.SetVersion(__version__)
    info.SetDescription(T("Find JLCPCB/LCSC parts and add symbol, footprint and 3D model to your own KiCad "
                          "library - checked by KiCad before and after writing.") + "\n\n" +
                        T("Built on easyeda2kicad (AGPL-3.0) and the parts database of the JLCPCB Tools plugin "
                          "by Bouni. Not affiliated with JLCPCB, LCSC or EasyEDA."))
    info.SetCopyright("(C) 2026 %s" % AUTHOR)
    info.AddDeveloper(AUTHOR)
    info.SetWebSite(PROJECT_URL, T("Project page"))
    info.SetLicence(T("Part Search is free software under the GNU Affero General Public License, version 3 or "
                      "later. It comes with ABSOLUTELY NO WARRANTY - check imported footprints against the "
                      "datasheet before ordering boards."))
    wx.adv.AboutBox(info, parent)


# ============================================================================= preview / confirm
class PreviewDialog(wx.Dialog):
    """Symbol + footprint pictures (kicad-cli SVG, rendered in the window) with the facts that matter.
    confirm=True: 'Add to library' / 'Cancel' - returns wx.ID_OK to add."""

    def __init__(self, parent, pp, ses, confirm: bool):
        super().__init__(parent, title=(T("Add %s to your library?") if confirm else T("Preview of %s")) % pp.lcsc,
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER, size=(1000, 760))
        self.pp = pp
        v = wx.BoxSizer(wx.VERTICAL)
        view = _web_view(self, _pictures_page(pp))
        if view is not None:
            v.Add(view, 1, wx.EXPAND | wx.ALL, 6)
        else:
            v.Add(wx.StaticText(self, label=T("No picture available - use 'Open in browser'.")), 0, wx.ALL, 12)
        g = wx.FlexGridSizer(cols=2, vgap=4, hgap=12)
        g.AddGrowableCol(1)
        rows = [(T("Symbol"), "%s : %s" % (ses.ctx.symbol_lib, pp.symbol)),
                (T("Footprint"), "%s : %s  -  %s" % (ses.ctx.footprint_lib, pp.footprint, T(pp.fp_action))),
                (T("3D model"), ", ".join(n for _, n in pp.model_files) or T("none")),
                (T("Pins / pads"), "%s / %s" % (pp.info.get("pins"), pp.info.get("pads"))),
                (T("MPN"), pp.info.get("MPN") or "-"), (T("Manufacturer"), pp.info.get("Manufacturer") or "-")]
        for a, b in rows:
            g.Add(wx.StaticText(self, label=a))
            g.Add(wx.StaticText(self, label=b), 1, wx.EXPAND)
        v.Add(g, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 14)
        pal = getattr(parent, "pal", None) or theme.palette("system")
        if pp.warnings:
            w = wx.StaticText(self, label=T("Warnings:") + "\n" + "\n".join("  ! " + x for x in pp.warnings))
            w.SetForegroundColour(pal["warn"])
            w._keep_colours = True
            v.Add(w, 0, wx.ALL, 14)
        note = wx.StaticText(self, label=T("Library only - nothing is placed in your schematic."))
        v.Add(note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 14)
        bs = wx.BoxSizer(wx.HORIZONTAL)
        b_web = wx.Button(self, label=T("Open in browser"))
        b_web.Bind(wx.EVT_BUTTON, lambda e: pp.previews and webbrowser.open(Path(pp.previews[0]).as_uri()))
        bs.Add(b_web, 0)
        bs.AddStretchSpacer()
        if confirm:
            ok = wx.Button(self, wx.ID_OK, T("Add to library"))
            ok.SetDefault()
            bs.Add(ok, 0, wx.RIGHT, 6)
            bs.Add(wx.Button(self, wx.ID_CANCEL, T("Cancel")), 0)
        else:
            bs.Add(wx.Button(self, wx.ID_CANCEL, T("Close")), 0)
        v.Add(bs, 0, wx.EXPAND | wx.ALL, 12)
        self.SetSizer(v)
        _themed(self, parent)
        self.CentreOnParent()
        # the web view takes the keyboard focus when it has loaded; give it back so Enter/Escape work
        btn = self.FindWindowById(wx.ID_OK if confirm else wx.ID_CANCEL, self)
        if btn:
            wx.CallLater(700, lambda: self and btn.SetFocus())


def _pictures_page(pp):
    """A page with just the two pictures side by side (the full preview.html is for the browser).
    kicad-cli draws each item on a whole sheet, so the SVGs are inlined and a script crops every picture to
    its drawn content before scaling it up."""
    import re
    svgs = sorted((x for x in pp.previews if str(x).endswith(".svg")),
                  key=lambda x: 0 if x.stem.startswith(pp.symbol) else 1)
    if not svgs:
        return None
    parts = []
    for x in svgs:
        t = x.read_text(encoding="utf-8", errors="replace")
        t = re.sub(r"^<\?xml[^>]*>\s*", "", t)
        t = re.sub(r"<!DOCTYPE[^>]*>\s*", "", t)
        parts.append('<div class="pic">%s</div>' % t)
    page = svgs[0].parent / "dialog_view.html"
    page.write_text(
        "<!doctype html><meta charset='utf-8'><style>html,body{margin:0;height:100%;background:#fff;overflow:hidden}"
        "body{display:flex;gap:10px;padding:8px;box-sizing:border-box}.pic{flex:1;min-width:0;height:100%}"
        ".pic svg{width:100%;height:100%}</style>" + "".join(parts) +
        "<script>for(const s of document.querySelectorAll('.pic > svg')){try{const b=s.getBBox();"
        "const m=Math.max(b.width,b.height)*0.06;s.setAttribute('viewBox',(b.x-m)+' '+(b.y-m)+' '+(b.width+2*m)+"
        "' '+(b.height+2*m));s.removeAttribute('width');s.removeAttribute('height');"
        "s.setAttribute('preserveAspectRatio','xMidYMid meet')}catch(e){}}"
        "document.addEventListener('keydown',function(e){if(e.key==='Escape'&&window.partsearch)"
        "window.partsearch.postMessage('escape')});</script>", encoding="utf-8")
    return page


def _web_view(parent, page):
    """The preview page (symbol + footprint SVG drawn by kicad-cli) inside the dialog. None if this wx build has
    no web view - the 'Open in browser' button still works then. The web view is a separate browser process that
    never passes keys to the dialog, so the page itself reports Escape back."""
    if page is None:
        return None
    try:
        import wx.html2
        view = wx.html2.WebView.New(parent)
        view.SetMinSize((820, 360))
        try:
            if view.AddScriptMessageHandler("partsearch"):
                view.Bind(wx.html2.EVT_WEBVIEW_SCRIPT_MESSAGE_RECEIVED,
                          lambda e: e.GetString() == "escape" and getattr(parent, "_close_on_escape", None)
                          and wx.CallAfter(parent._close_on_escape))
        except Exception:  # noqa: BLE001 - older web view backends: Escape then works once the focus is back
            pass
        view.LoadURL(Path(page).as_uri())
        return view
    except Exception:  # noqa: BLE001
        return None


# ============================================================================= settings
class SettingsDialog(wx.Dialog):
    PATHS = [  # key, label, kind, auto-detect function name on Settings
        ("library_dir", "Library folder", "dir", "library_path"),
        ("kicad_cli", "kicad-cli", "file", "kicad_cli_path"),
        ("easyeda_python", "Python with easyeda2kicad", "file", "easyeda_python_path"),
        ("jlcpcb_db", "JLCPCB database (local search)", "file", "jlcpcb_db_path"),
        ("work_dir", "Download and log folder", "dir", "work_path"),
    ]

    def __init__(self, parent, ses):
        super().__init__(parent, title=T("Settings"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
                         size=(760, 560))
        self.ses = ses
        self.s = copy.deepcopy(ses.settings)
        self.result = None
        nb = wx.Notebook(self)
        self.ctrls = {}
        nb.AddPage(self._page_general(nb), T("General"))
        nb.AddPage(self._page_library(nb), T("Library"))
        nb.AddPage(self._page_tools(nb), T("Tools"))
        nb.AddPage(self._page_search(nb), T("Search"))
        v = wx.BoxSizer(wx.VERTICAL)
        v.Add(nb, 1, wx.EXPAND | wx.ALL, 8)
        bs = wx.BoxSizer(wx.HORIZONTAL)
        b_def = wx.Button(self, label=T("Restore defaults"))
        b_def.Bind(wx.EVT_BUTTON, self._defaults)
        b_chk = wx.Button(self, label=T("Check setup..."))
        b_chk.Bind(wx.EVT_BUTTON, lambda e: show_modal(CheckDialog(self, self.ses, self._collect())))
        bs.Add(b_def, 0, wx.RIGHT, 6)
        bs.Add(b_chk, 0)
        bs.AddStretchSpacer()
        ok = wx.Button(self, wx.ID_OK, T("Save"))
        ok.SetDefault()
        bs.Add(ok, 0, wx.RIGHT, 6)
        bs.Add(wx.Button(self, wx.ID_CANCEL, T("Cancel")), 0)
        v.Add(bs, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(v)
        self.Bind(wx.EVT_BUTTON, self._ok, id=wx.ID_OK)
        _themed(self, parent)
        self.CentreOnParent()

    # ---------------------------------------------------------------- pages
    def _grid(self, page):
        g = wx.FlexGridSizer(cols=2, vgap=8, hgap=12)
        g.AddGrowableCol(1)
        return g

    def _finish_page(self, page, g, note=None):
        v = wx.BoxSizer(wx.VERTICAL)
        v.Add(g, 0, wx.EXPAND | wx.ALL, 12)
        if note:
            t = wx.StaticText(page, label=note)
            t.Wrap(680)
            v.Add(t, 0, wx.ALL, 12)
        page.SetSizer(v)
        return page

    def _choice(self, page, g, key, label, options):
        g.Add(wx.StaticText(page, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        c = wx.Choice(page, choices=[lab for _, lab in options])
        codes = [code for code, _ in options]
        cur = getattr(self.s, key)
        c.SetSelection(codes.index(cur) if cur in codes else 0)
        g.Add(c, 0)
        self.ctrls[key] = ("choice", c, codes)

    def _check(self, page, g, key, label):
        g.Add((0, 0))
        c = wx.CheckBox(page, label=label)
        c.SetValue(getattr(self.s, key))
        g.Add(c, 0)
        self.ctrls[key] = ("check", c)

    def _text(self, page, g, key, label, width=220):
        g.Add(wx.StaticText(page, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        t = wx.TextCtrl(page, value=str(getattr(self.s, key)), size=(width, -1))
        g.Add(t, 0)
        self.ctrls[key] = ("text", t)

    def _number(self, page, g, key, label, lo, hi):
        g.Add(wx.StaticText(page, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        sp = wx.SpinCtrl(page, min=lo, max=hi, initial=getattr(self.s, key))
        g.Add(sp, 0)
        self.ctrls[key] = ("spin", sp)

    def _path(self, page, g, key, label, kind, auto):
        g.Add(wx.StaticText(page, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
        row = wx.BoxSizer(wx.HORIZONTAL)
        t = wx.TextCtrl(page, value=getattr(self.s, key))
        try:
            detected = getattr(Settings(**{k: v for k, v in vars(self.s).items() if k != key}), auto)()
        except Exception:  # noqa: BLE001
            detected = None
        t.SetHint(T("Automatic: %s") % (detected or T("not found")))
        b = wx.Button(page, label=T("Browse..."), style=wx.BU_EXACTFIT)
        b.Bind(wx.EVT_BUTTON, lambda e: self._browse(t, kind, label))
        row.Add(t, 1, wx.RIGHT, 4)
        row.Add(b, 0)
        g.Add(row, 1, wx.EXPAND)
        self.ctrls[key] = ("text", t)

    def _browse(self, t, kind, label):
        if kind == "dir":
            dlg = wx.DirDialog(self, label, t.GetValue() or "")
        else:
            dlg = wx.FileDialog(self, label, style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            t.SetValue(dlg.GetPath())
        dlg.Destroy()

    def _page_general(self, nb):
        p = wx.Panel(nb)
        g = self._grid(p)
        self._choice(p, g, "language", T("Language"), [("", T("Follow system"))] +
                     [(c, m["name"]) for c, m in LANGUAGES.items()])
        self._choice(p, g, "theme", T("Theme"), [("system", T("Follow system")), ("light", T("Light")),
                                                 ("dark", T("Dark"))])
        self._choice(p, g, "double_click", T("Double-click on a result"),
                     [("add", T("Add to library")), ("preview", T("Preview")), ("none", T("Nothing"))])
        self._check(p, g, "confirm_add", T("Show the preview and ask before adding"))
        self._check(p, g, "show_next_steps", T("Show 'what next' after adding"))
        self._check(p, g, "show_log", T("Show the log panel"))
        return self._finish_page(p, g)

    def _page_library(self, nb):
        p = wx.Panel(nb)
        g = self._grid(p)
        self._path(p, g, "library_dir", T("Library folder"), "dir", "library_path")
        self._text(p, g, "path_variable", T("KiCad path variable"))
        self._text(p, g, "symbol_lib", T("Symbol library nickname"))
        self._text(p, g, "footprint_lib", T("Footprint library nickname"))
        self._text(p, g, "models_dir", T("3D model subfolder"))
        return self._finish_page(p, g, T(
            "The nicknames must match the entries in KiCad's symbol and footprint library tables, and the path "
            "variable must point to the library folder (Preferences > Configure Paths). 3D models are written as "
            "${VARIABLE}/<3D model subfolder>/<name>. 'Check setup' tests all of this."))

    def _page_tools(self, nb):
        p = wx.Panel(nb)
        g = self._grid(p)
        for key, label, kind, auto in self.PATHS[1:]:
            self._path(p, g, key, T(label), kind, auto)
        return self._finish_page(p, g, T("Leave a field empty to detect it automatically every time."))

    def _page_search(self, nb):
        p = wx.Panel(nb)
        g = self._grid(p)
        self._choice(p, g, "default_source", T("Search in"), [("local", T("Local database")),
                                                              ("online", T("JLCPCB online"))])
        self._check(p, g, "basic_only", T("Basic / Preferred only (default)"))
        self._check(p, g, "in_stock", T("In stock only (default)"))
        self._number(p, g, "max_results", T("Maximum results (local)"), 20, 2000)
        self._number(p, g, "online_page_size", T("Results per online search"), 10, 100)
        self._number(p, g, "local_timeout", T("Local search time limit (s)"), 2, 120)
        self._number(p, g, "online_timeout", T("Online search time limit (s)"), 5, 120)
        return self._finish_page(p, g)

    # ---------------------------------------------------------------- values
    def _collect(self) -> Settings:
        s = copy.deepcopy(self.s)
        for key, spec in self.ctrls.items():
            kind, c = spec[0], spec[1]
            if kind == "choice":
                setattr(s, key, spec[2][c.GetSelection()])
            elif kind == "check":
                setattr(s, key, c.GetValue())
            elif kind == "spin":
                setattr(s, key, int(c.GetValue()))
            else:
                setattr(s, key, c.GetValue().strip())
        return s

    def _defaults(self, _e):
        d = Settings()
        for key, spec in self.ctrls.items():
            kind, c, val = spec[0], spec[1], getattr(d, key)
            if kind == "choice":
                c.SetSelection(spec[2].index(val) if val in spec[2] else 0)
            elif kind == "check":
                c.SetValue(val)
            elif kind == "spin":
                c.SetValue(val)
            else:
                c.SetValue(str(val))

    def _ok(self, e):
        s = self._collect()
        for key in ("symbol_lib", "footprint_lib", "models_dir", "path_variable"):
            if not getattr(s, key) or any(ch in getattr(s, key) for ch in '/\\:"<>|*?${} '):
                wx.MessageBox(T("'%s' must be a plain name without spaces or special characters.") % getattr(s, key),
                              T("Settings"), wx.ICON_WARNING, self)
                return
        self.result = s
        e.Skip()


# ============================================================================= setup check
class CheckDialog(wx.Dialog):
    def __init__(self, parent, ses, settings=None):
        super().__init__(parent, title=T("Check setup"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
                         size=(900, 420))
        self.s = settings or ses.settings
        v = wx.BoxSizer(wx.VERTICAL)
        self.lc = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for i, (h, w) in enumerate(((T("Result"), 70), (T("Item"), 190), (T("Details"), 600))):
            self.lc.InsertColumn(i, h, width=w)
        v.Add(self.lc, 1, wx.EXPAND | wx.ALL, 8)
        self.summary = wx.StaticText(self, label=T("Checking ..."))
        v.Add(self.summary, 0, wx.LEFT | wx.RIGHT, 10)
        bs = wx.BoxSizer(wx.HORIZONTAL)
        b = wx.Button(self, label=T("Copy report"))
        b.Bind(wx.EVT_BUTTON, self._copy)
        bs.Add(b, 0)
        bs.AddStretchSpacer()
        bs.Add(wx.Button(self, wx.ID_CANCEL, T("Close")), 0)
        v.Add(bs, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(v)
        self.rows = []
        _themed(self, parent)
        self.CentreOnParent()
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        try:
            rows = checks.run_checks(self.s)
        except Exception as e:  # noqa: BLE001
            rows = [{"name": "check", "ok": False, "detail": str(e)}]
        wx.CallAfter(self._show, rows)

    def _show(self, rows):
        if not self:
            return
        self.rows = rows
        pal = getattr(self.GetParent(), "pal", None) or theme.palette("system")
        for r in rows:
            i = self.lc.InsertItem(self.lc.GetItemCount(), {True: T("OK"), False: T("Problem"), None: T("Note")}[r["ok"]])
            self.lc.SetItem(i, 1, T(r["name"]))
            self.lc.SetItem(i, 2, r["detail"])
            if r["ok"] is not True:
                self.lc.SetItemTextColour(i, pal["warn"] if r["ok"] is False else pal["note"])
        bad = sum(1 for r in rows if r["ok"] is False)
        self.summary.SetLabel(T("Everything needed is in place.") if not bad else
                              T("%d problem(s) - see the details above.") % bad)

    def _copy(self, _e):
        text = "\n".join("%-7s %-24s %s" % ({True: "OK", False: "PROBLEM", None: "NOTE"}[r["ok"]], r["name"],
                                            r["detail"]) for r in self.rows)
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(text))
            wx.TheClipboard.Close()


# ============================================================================= history / help
class HistoryDialog(wx.Dialog):
    def __init__(self, parent, ses):
        super().__init__(parent, title=T("Import history (newest first)"), size=(1000, 450),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        lc = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for i, (h, w) in enumerate([(T("Date"), 90), ("LCSC", 90), (T("Symbol"), 200), (T("Footprint"), 260),
                                    ("MPN", 160), (T("Source"), 300)]):
            lc.InsertColumn(i, h, width=w)
        for r in ses.history():
            i = lc.InsertItem(lc.GetItemCount(), r.get("DateFetched", ""))
            for c, k in enumerate(["LCSC", "SymbolName", "FootprintName", "MPN", "Source"], start=1):
                lc.SetItem(i, c, r.get(k, "") or "")
        s = wx.BoxSizer(wx.VERTICAL)
        s.Add(lc, 1, wx.EXPAND | wx.ALL, 6)
        s.Add(wx.Button(self, wx.ID_CANCEL, T("Close")), 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        self.SetSizer(s)
        _themed(self, parent)


class HelpDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title=T("How it works"), size=(640, 460),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        text = T(
            "1. Search. 'Local database' is the offline JLCPCB parts list of the JLCPCB Tools plugin (fast, stock "
            "as of its download date). 'JLCPCB online' asks JLCPCB directly (current stock, needs internet).\n\n"
            "2. Pick a part. Green = JLCPCB Basic part (no extra assembly fee), grey = out of stock, highlighted = "
            "already in your library.\n\n"
            "3. Add to library. The symbol, footprint and 3D model are downloaded from EasyEDA with easyeda2kicad, "
            "renamed consistently, checked by KiCad (kicad-cli), shown to you, and only then written. After "
            "writing, everything is read back from disk and loaded by KiCad again.\n\n"
            "4. Nothing is ever overwritten. Importing a part that is already there creates NAME-1, NAME-2, ... "
            "Every write keeps a backup of the symbol library in the .history folder.\n\n"
            "5. Place it: in the Schematic Editor press A and search the symbol name.\n\n"
            "Problems? File > Check setup shows what is missing. Every step is written to the log "
            "(File > Open log file).")
        t = wx.TextCtrl(self, value=text, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_NONE)
        s = wx.BoxSizer(wx.VERTICAL)
        s.Add(t, 1, wx.EXPAND | wx.ALL, 12)
        close = wx.Button(self, wx.ID_CANCEL, T("Close"))
        s.Add(close, 0, wx.ALIGN_RIGHT | wx.ALL, 8)
        self.SetSizer(s)
        _themed(self, parent)
