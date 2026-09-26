# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""Settings: one JSON file per user, every value editable in the Settings window.

Empty path values mean "detect automatically" - detection runs every time, so moving KiCad or the library does
not leave stale paths behind. Environment variables still win (handy for tests and scripts):
    PARTSEARCH_SETTINGS  settings file        MYLIB_DIR       library folder (if not set in Settings)
    PARTSEARCH_DB        local JLCPCB DB      KICAD_CLI       kicad-cli executable
    GETPART_PYTHON       python with easyeda2kicad installed
"""
from __future__ import annotations

import dataclasses
import json
import locale
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"


def _appdata(kind: str) -> Path:
    """kind 'config' (settings) or 'data' (downloads, log)."""
    if WINDOWS:
        env = "APPDATA" if kind == "config" else "LOCALAPPDATA"
        return Path(os.environ.get(env) or Path.home() / "AppData" / ("Roaming" if kind == "config" else "Local"))
    if MACOS:
        return Path.home() / "Library" / "Application Support"
    if kind == "config":
        return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


SETTINGS_FILE = Path(os.environ.get("PARTSEARCH_SETTINGS") or _appdata("config") / "partsearch" / "settings.json")


@dataclass
class Settings:
    # appearance
    language: str = ""                 # "" = follow the system (Turkish system -> tr, otherwise en)
    theme: str = "system"              # system | light | dark
    show_log: bool = False
    # library (must match the nicknames in KiCad's symbol / footprint library tables)
    library_dir: str = ""              # "" = KiCad path variable below, else <KiCad documents>/mylib
    path_variable: str = "MYLIB_DIR"   # 3D model paths are written as ${MYLIB_DIR}/my_3dmodels/...
    symbol_lib: str = "my_symbols"
    footprint_lib: str = "my_footprints"
    models_dir: str = "my_3dmodels"
    # tools
    kicad_cli: str = ""                # "" = next to this Python (KiCad's bundled one), then PATH
    easyeda_python: str = ""           # "" = a python that can import easyeda2kicad
    jlcpcb_db: str = ""                # "" = database of the "JLCPCB Tools" plugin
    work_dir: str = ""                 # downloads + log; "" = per-user app data folder
    # search
    default_source: str = "local"      # local | online
    basic_only: bool = False
    in_stock: bool = False
    max_results: int = 200
    online_page_size: int = 50
    local_timeout: int = 10
    online_timeout: int = 20
    # behaviour
    double_click: str = "add"          # add | preview | none
    confirm_add: bool = True
    show_next_steps: bool = True
    # remembered window state
    recent: list = field(default_factory=list)  # last searches (newest first)
    window: list = field(default_factory=list)  # x, y, width, height, maximized
    sash: int = 0                               # width of the results list
    extra: dict = field(default_factory=dict)   # unknown keys from newer versions are kept, not dropped

    # ------------------------------------------------------------------ load / save
    @classmethod
    def load(cls, path: Path = None) -> "Settings":
        path = path or SETTINGS_FILE
        s = cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            s.extra["_first_run"] = True           # no settings yet: the window opens the setup assistant
            return s
        except (OSError, ValueError):
            s.extra["_load_error"] = "unreadable settings file %s - defaults used" % path
            return s
        names = {f.name for f in dataclasses.fields(cls)}
        for k, v in data.items():
            if k in names and k != "extra":
                default = getattr(s, k)
                if isinstance(default, bool):
                    v = bool(v)
                elif isinstance(default, int):
                    try:
                        v = int(v)
                    except (TypeError, ValueError):
                        continue
                elif isinstance(default, str):
                    v = "" if v is None else str(v)
                elif isinstance(default, list) and not isinstance(v, list):
                    continue
                setattr(s, k, v)
            else:
                s.extra[k] = v
        return s

    def save(self, path: Path = None) -> None:
        path = path or SETTINGS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {k: v for k, v in dataclasses.asdict(self).items() if k != "extra"}
        data.update({k: v for k, v in self.extra.items() if not k.startswith("_")})
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    # ------------------------------------------------------------------ resolved values
    def lang(self) -> str:
        if self.language in ("en", "tr"):
            return self.language
        try:
            loc = (locale.getlocale()[0] or locale.getdefaultlocale()[0] or "").lower()
        except Exception:  # noqa: BLE001 - locale APIs differ between platforms
            loc = ""
        return "tr" if loc.startswith(("tr", "turkish")) else "en"

    def library_path(self) -> Path:
        # explicit setting first: KiCad passes its path variables to every program it starts, so an environment
        # variable would otherwise silently override the folder chosen in Settings
        v = self.library_dir or os.environ.get(self.path_variable) or kicad_path_variable(self.path_variable)
        return Path(v) if v else kicad_documents() / "mylib"

    def kicad_cli_path(self) -> Path | None:
        return _first_existing([os.environ.get("KICAD_CLI"), self.kicad_cli] + _kicad_cli_candidates())

    def jlcpcb_db_path(self) -> Path:
        v = os.environ.get("PARTSEARCH_DB") or self.jlcpcb_db
        if v:
            return Path(v)
        return _bouni_db() or (kicad_documents() / "10.0" / "3rdparty" / "plugins" /
                               "com_github_bouni_kicad-jlcpcb-tools" / "jlcpcb" / "current-parts-fts5.db")

    def work_path(self) -> Path:
        return Path(self.work_dir) if self.work_dir else _appdata("data") / "partsearch"

    def easyeda_python_path(self) -> str | None:
        v = os.environ.get("GETPART_PYTHON") or self.easyeda_python
        if v:
            return v
        return _find_easyeda_python()


# ---------------------------------------------------------------------- detection helpers
def _first_existing(cands) -> Path | None:
    for c in cands:
        if c and Path(c).is_file():
            return Path(c)
    return None


def kicad_documents() -> Path:
    """KiCad's documents folder (libraries, plugins, 3rd-party content) - the same rule as KiCad: the Documents
    folder (or KICAD_DOCUMENTS_HOME) + "KiCad"; on Linux the XDG data folder + "kicad"."""
    v = os.environ.get("KICAD_DOCUMENTS_HOME")
    if not WINDOWS and not MACOS:
        return (Path(v) if v else _appdata("data")) / "kicad"
    if v:
        return Path(v) / "KiCad"
    docs = None
    if WINDOWS:
        try:                                   # honours a Documents folder moved to OneDrive / another drive
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:   # CSIDL_PERSONAL
                docs = Path(buf.value)
        except Exception:  # noqa: BLE001
            docs = None
    return (docs or Path.home() / "Documents") / "KiCad"


def kicad_config_dirs() -> list[Path]:
    """KiCad's per-version configuration folders, newest first (KICAD_CONFIG_HOME is honoured like KiCad does)."""
    if os.environ.get("KICAD_CONFIG_HOME"):
        base = Path(os.environ["KICAD_CONFIG_HOME"])
    elif WINDOWS:
        base = _appdata("config") / "kicad"
    elif MACOS:
        base = Path.home() / "Library" / "Preferences" / "kicad"
    else:
        base = _appdata("config") / "kicad"
    if not base.is_dir():
        return []
    dirs = [d for d in base.iterdir() if d.is_dir() and d.name.replace(".", "").isdigit()]
    return sorted(dirs, key=lambda d: [int(x) for x in d.name.split(".")], reverse=True)


def kicad_config_dir(major: int | None = None) -> Path | None:
    """The configuration folder of the KiCad version in use (major from kicad-cli), else the newest one."""
    dirs = kicad_config_dirs()
    if major:
        for d in dirs:
            if d.name.split(".")[0] == str(major):
                return d
    return dirs[0] if dirs else None


_VERSION_CACHE: dict = {}


def kicad_version(cli) -> str:
    """'10.0.6' from 'kicad-cli version' ('' if it cannot be run). Cached per executable."""
    if not cli:
        return ""
    key = str(cli)
    if key not in _VERSION_CACHE:
        try:
            out = subprocess.run([key, "version"], capture_output=True, text=True, timeout=30,
                                 creationflags=NO_WINDOW).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            out = ""
        _VERSION_CACHE[key] = out.splitlines()[-1].strip() if out else ""
    return _VERSION_CACHE[key]


def kicad_major(cli) -> int | None:
    v = kicad_version(cli)
    try:
        return int(v.split(".")[0])
    except ValueError:
        return None


def kicad_path_variable(name: str, major: int | None = None) -> str:
    """Value of a user-defined path variable (Preferences > Configure Paths) from kicad_common.json of the KiCad
    version in use (major), or of the newest version that defines it."""
    d = kicad_config_dir(major) if major else None
    for d in ([d] if d else kicad_config_dirs()):
        try:
            data = json.loads((d / "kicad_common.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        v = ((data.get("environment") or {}).get("vars") or {}).get(name)
        if v:
            return v
    return ""


def _kicad_cli_candidates() -> list:
    exe = "kicad-cli.exe" if WINDOWS else "kicad-cli"
    c = [str(Path(sys.executable).with_name(exe)),           # we normally run on KiCad's own python ...
         str(Path(getattr(sys, "_base_executable", sys.executable)).with_name(exe))]   # ... or a venv of it
    if WINDOWS:
        pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "KiCad"
        if pf.is_dir():
            c += [str(d / "bin" / exe) for d in sorted(pf.iterdir(), reverse=True)]
    elif MACOS:
        c.append("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")
    c.append(shutil.which("kicad-cli") or "")
    return c


def _bouni_db() -> Path | None:
    base = kicad_documents()
    if not base.is_dir():
        return None
    hits = sorted(base.glob("*/3rdparty/plugins/com_github_bouni_kicad-jlcpcb-tools/jlcpcb/current-parts-fts5.db"),
                  reverse=True)
    return hits[0] if hits else None


_EASYEDA_CACHE: dict = {}


def app_venv() -> Path:
    """Private virtual environment the setup assistant can create for easyeda2kicad (when not running inside
    the KiCad plugin environment, which gets it from requirements.txt)."""
    return _appdata("data") / "partsearch" / "venv"


def forget_detection() -> None:
    """After installing easyeda2kicad: look again instead of using the cached 'not found'."""
    _EASYEDA_CACHE.clear()


def _find_easyeda_python() -> str | None:
    """A python that can run 'python -m easyeda2kicad'. Checked candidates: this python, a .venv next to the
    program folder, the app's own venv in the work folder."""
    root = Path(__file__).resolve().parent.parent
    cands = [sys.executable]
    for venv in (root / ".venv", root.parent / ".venv", app_venv()):
        cands += [venv / "Scripts" / "python.exe", venv / "bin" / "python"]
    for c in cands:
        c = str(c)
        if c in _EASYEDA_CACHE:
            if _EASYEDA_CACHE[c]:
                return c
            continue
        ok = False
        if Path(c).is_file():
            try:
                ok = subprocess.run([_console_python(c), "-c", "import easyeda2kicad"], capture_output=True,
                                    timeout=20, creationflags=NO_WINDOW).returncode == 0
            except (OSError, subprocess.SubprocessError):
                ok = False
        _EASYEDA_CACHE[c] = ok
        if ok:
            return c
    return None


def _console_python(p: str) -> str:
    """pythonw.exe cannot report through stdout; use python.exe next to it."""
    pp = Path(p)
    if pp.name.lower() == "pythonw.exe" and pp.with_name("python.exe").is_file():
        return str(pp.with_name("python.exe"))
    return p


NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)     # no console flashes from the window process
