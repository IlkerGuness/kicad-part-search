# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""'Check setup': every external thing the tool depends on, each with a clear OK / problem line.
Pure functions (no GUI) so they can be tested and printed from the command line:
    python -m partsearch.checks
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from . import search
from .i18n import T
from .config import (NO_WINDOW, Settings, _console_python, kicad_config_dir, kicad_major, kicad_path_variable,
                     kicad_version)


def _run(cmd, timeout=30) -> tuple[int, str]:
    try:
        p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, creationflags=NO_WINDOW)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)


def _writable(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=d, prefix=".ps_write_test_"):
            pass
        return True
    except OSError:
        return False


def _lib_table_uri(kind: str, nick: str, major: int | None = None) -> str | None:
    """URI of a nickname in the global sym-lib-table / fp-lib-table of the KiCad version in use."""
    d = kicad_config_dir(major)
    for d in ([d] if d else []):
        f = d / ("%s-lib-table" % kind)
        try:
            t = f.read_text(encoding="utf-8")
        except OSError:
            continue
        for chunk in re.split(r"\(lib\s", t)[1:]:          # one chunk per library entry, any formatting
            n = re.search(r'\(name\s+"?([^")]+)"?\)', chunk)
            if n and n.group(1) == nick:
                u = re.search(r'\(uri\s+"?([^")]+)"?\)', chunk)
                return u.group(1) if u else ""
    return None


def _expand(uri: str, var: str, value: str) -> str:
    return uri.replace("${%s}" % var, value).replace("\\", "/").rstrip("/")


def run_checks(s: Settings) -> list[dict]:
    """[{"name", "ok": True/False/None(warning), "detail"}] in display order."""
    out = []

    def add(name, ok, detail):
        out.append({"name": name, "ok": ok, "detail": detail})

    cli = s.kicad_cli_path()
    if cli:
        ver = kicad_version(cli)
        major = kicad_major(cli)
        if not ver:
            add("kicad-cli", False, T("%s cannot be run") % cli)
        elif major is not None and major < 9:
            add("kicad-cli", False, T("%s  (version %s) - KiCad 9 or newer is needed") % (cli, ver))
        else:
            add("kicad-cli", True, T("%s  (version %s)") % (cli, ver))
    else:
        add("kicad-cli", False, T("not found - set it in Settings > Tools (it is in KiCad's bin folder)"))

    py = s.easyeda_python_path()
    if py:
        rc, txt = _run([_console_python(py), "-c", "import easyeda2kicad as e;print(getattr(e,'__version__','?'))"])
        add("easyeda2kicad", rc == 0, T("%s  (version %s)") % (py, txt or "?") if rc == 0 else "%s: %s" % (py, txt))
    else:
        add("easyeda2kicad", False, T("not installed - File > Setup assistant installs it (needed for online search "
                                      "and for adding parts)"))

    info = search.db_info(s.jlcpcb_db_path())
    if info["ok"]:
        add("JLCPCB database", True, T("%s parts, downloaded %s  (%s)") % (f"{info['parts']:,}", info["date"], info["path"]))
    else:
        add("JLCPCB database", None, T("not found - optional: local (offline) search uses the database of the "
                                       "'JLCPCB Tools' plugin; online search works without it (%s)") % info["path"])

    lib = s.library_path()
    add("Library folder", _writable(lib), "%s%s" % (lib, "" if _writable(lib) else T("  - not writable")))

    var_val = kicad_path_variable(s.path_variable, kicad_major(cli))
    if not var_val:
        add("KiCad path variable", False, T("${%s} is not defined in KiCad - 3D models will not be found (File > "
                                            "Setup assistant, or Preferences > Configure Paths)") % s.path_variable)
    else:
        same = Path(var_val).resolve() == lib.resolve()
        add("KiCad path variable", True if same else None,
            "${%s} = %s%s" % (s.path_variable, var_val, "" if same else T("  - differs from the library folder")))

    for kind, nick, target in (("sym", s.symbol_lib, lib / (s.symbol_lib + ".kicad_sym")),
                               ("fp", s.footprint_lib, lib / (s.footprint_lib + ".pretty"))):
        uri = _lib_table_uri(kind, nick, kicad_major(cli))
        label = "Symbol library table" if kind == "sym" else "Footprint library table"
        if uri is None:
            add(label, False, T("'%s' is not in KiCad's global %s-lib-table - File > Setup assistant adds it (or add "
                                "%s in Preferences > Manage %s Libraries)") % (nick, kind, target,
                                                                            T("Symbol") if kind == "sym" else T("Footprint")))
        else:
            ok = _expand(uri, s.path_variable, var_val or str(lib)) == target.as_posix().rstrip("/")
            add(label, True if ok else None, "%s -> %s%s" % (nick, uri, "" if ok else T("  (expected %s)") % target))

    w = s.work_path()
    add("Work folder", _writable(w), T("%s  (downloads + log)") % w)
    return out


if __name__ == "__main__":
    for r in run_checks(Settings.load()):
        print("%-5s %-24s %s" % ({True: "OK", False: "FAIL", None: "WARN"}[r["ok"]], r["name"], r["detail"]))
