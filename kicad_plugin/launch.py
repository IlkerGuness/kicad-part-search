# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""KiCad toolbar button (IPC plugin action): start the Part Search window as its own process and return.

KiCad runs this file with the plugin's own virtual environment. That environment is created by KiCad with access
to KiCad's bundled packages (wxPython) and gets easyeda2kicad from requirements.txt, so the window is started
with the same environment - as pythonw on Windows, so no console window appears.

Where the program is: environment variable PARTSEARCH_HOME, else this folder (the normal, installed case), else
the path written in location.txt next to this file (development).
"""
import datetime
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WINDOWS = sys.platform == "win32"


def _home():
    cands = [os.environ.get("PARTSEARCH_HOME"), str(HERE)]
    loc = HERE / "location.txt"
    if loc.exists():
        cands.append(loc.read_text(encoding="utf-8").strip())
    for c in cands:
        if c and (Path(c) / "partsearch.pyw").exists():
            return Path(c)
    return None


def _venv_sees_kicad_packages() -> bool:
    """True if this is a virtual environment created with --system-site-packages (KiCad does that), i.e. it can
    import KiCad's wxPython."""
    if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
        return False
    try:
        cfg = (Path(sys.prefix) / "pyvenv.cfg").read_text(encoding="utf-8").lower()
    except OSError:
        return False
    return any(line.replace(" ", "") == "include-system-site-packages=true" for line in cfg.splitlines())


def _gui_python() -> Path:
    exe = Path(sys.executable)
    if _venv_sees_kicad_packages():
        if WINDOWS and exe.with_name("pythonw.exe").exists():
            return exe.with_name("pythonw.exe")
        return exe
    # fallback: KiCad's own interpreter (has wxPython; easyeda2kicad is then looked for elsewhere)
    base = Path(getattr(sys, "_base_executable", sys.executable))
    for c in (base.with_name("pythonw.exe"), Path(sys.base_prefix) / "pythonw.exe",
              Path(sys.base_prefix) / "bin" / "pythonw.exe", base):
        if c.exists():
            return c
    return exe


def _note(home, msg):
    """One line in the log, so a click that 'does nothing' still leaves a trace."""
    try:
        sys.path.insert(0, str(home))
        from partsearch.config import Settings
        log = Settings.load().work_path() / "partsearch.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write("%s [%-9s] %s\n" % (datetime.datetime.now().isoformat(timespec="seconds"), "LAUNCH", msg))
    except Exception:  # noqa: BLE001 - logging must never stop the launch
        pass


def main() -> int:
    home = _home()
    if home is None:
        sys.stderr.write("Part Search not found (set PARTSEARCH_HOME or location.txt)\n")
        return 1
    if sys.version_info < (3, 9):            # keep in step with partsearch.MIN_PYTHON
        _note(home, "Python %d.%d is too old (%s) - Part Search needs 3.9 or newer (KiCad 10)"
              % (sys.version_info[0], sys.version_info[1], sys.executable))
        sys.stderr.write("Part Search needs Python 3.9 or newer (KiCad 10)\n")
        return 1
    py = _gui_python()
    _note(home, "toolbar button: plugin python %s -> window python %s, API socket %s"
          % (sys.executable, py, "set" if os.environ.get("KICAD_API_SOCKET") else "not set"))
    kw = {}
    if WINDOWS:
        flags = 0
        for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
            flags |= getattr(subprocess, name, 0)
        kw["creationflags"] = flags
    else:
        kw["start_new_session"] = True
    env = {k: v for k, v in os.environ.items() if not k.startswith("KICAD_API_")}
    try:
        proc = subprocess.Popen([str(py), str(home / "partsearch.pyw")], cwd=str(home), env=env, close_fds=True,
                                **kw)
    except OSError as e:
        _note(home, "FAILED to start %s: %s" % (py, e))
        return 1
    _note(home, "spawned Part Search window pid %d" % proc.pid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
