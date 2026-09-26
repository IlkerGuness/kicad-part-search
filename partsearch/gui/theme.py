# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""Light / dark appearance.

Windows with wxWidgets 3.3 (KiCad 10's wxPython): the native dark mode is used (menus, title bar, scroll bars,
list headers all follow). It can only be switched on before the first window opens, so a theme change there
applies after restarting the window. Elsewhere our own colours are applied to the controls.
The few colours with a meaning (Basic part, out of stock, already in library, warnings) are always ours.
"""
from __future__ import annotations

import sys

import wx

LIGHT = {"bg": None, "panel": None, "fg": None, "input": None, "muted": wx.Colour(105, 105, 105),
         "basic": wx.Colour(0, 120, 40), "out": wx.Colour(150, 150, 150), "inlib": wx.Colour(226, 244, 229),
         "note": wx.Colour(170, 110, 0),
         "accent": wx.Colour(0, 95, 184), "warn": wx.Colour(176, 0, 0), "ok": wx.Colour(0, 128, 0)}
DARK = {"bg": wx.Colour(30, 31, 34), "panel": wx.Colour(43, 45, 48), "fg": wx.Colour(223, 225, 229),
        "input": wx.Colour(30, 31, 34), "muted": wx.Colour(150, 153, 158), "basic": wx.Colour(120, 210, 135),
        "out": wx.Colour(120, 123, 128), "inlib": wx.Colour(34, 58, 42), "note": wx.Colour(230, 180, 80), "accent": wx.Colour(88, 166, 255),
        "warn": wx.Colour(255, 120, 110), "ok": wx.Colour(120, 210, 135)}

_native = {"supported": False, "dark": False}      # decided once, in init_native()


def system_is_dark() -> bool:
    try:
        a = wx.SystemSettings.GetAppearance()
        return a.IsSystemDark() if hasattr(a, "IsSystemDark") else a.IsDark()
    except Exception:  # noqa: BLE001 - older wx
        return False


def init_native(app: wx.App, mode: str) -> None:
    """Call right after wx.App() and before any window. Windows + wxWidgets 3.3 only."""
    if sys.platform != "win32" or not hasattr(app, "MSWEnableDarkMode"):
        return
    _native["supported"] = True
    want = mode == "dark" or (mode == "system" and system_is_dark())
    if want:
        try:
            _native["dark"] = bool(app.MSWEnableDarkMode(1 if mode == "dark" else 0))   # 1 = always, 0 = auto
        except Exception:  # noqa: BLE001
            _native["dark"] = False


def native() -> bool:
    return _native["supported"]


def needs_restart(new_mode: str) -> bool:
    """With native dark mode the look is fixed for this process."""
    if not _native["supported"]:
        return False
    want = new_mode == "dark" or (new_mode == "system" and system_is_dark())
    return want != _native["dark"]


def palette(mode: str) -> dict:
    dark = _native["dark"] if _native["supported"] else (mode == "dark" or (mode == "system" and system_is_dark()))
    return dict(DARK if dark else LIGHT, dark=dark)


def apply(win: wx.Window, pal: dict) -> None:
    """Colour win and its children (only without native dark mode; with it Windows draws the controls)."""
    if _native["supported"]:
        win.Refresh()
        return

    def colour(w):
        if isinstance(w, wx.Button) or getattr(w, "_keep_colours", False):
            return
        if isinstance(w, (wx.TextCtrl, wx.ListCtrl, wx.ComboBox, wx.SpinCtrl, wx.Choice)):
            bg = pal["input"]
        elif isinstance(w, (wx.Frame, wx.Dialog)):
            bg = pal["bg"]
        else:
            bg = pal["panel"]
        w.SetBackgroundColour(bg if bg is not None else wx.NullColour)
        w.SetForegroundColour(pal["fg"] if pal["fg"] is not None else wx.NullColour)

    def walk(w):
        colour(w)
        for c in w.GetChildren():
            walk(c)

    walk(win)
    win.Refresh()
