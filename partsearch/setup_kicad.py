# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""First-time setup that needs changes outside Part Search's own folders.

Everything here is opt-in (the setup assistant shows the plan and asks) and reversible (a backup of every file is
taken first). Nothing is ever removed from a KiCad file - entries are only added.

  register_plan / register_apply : library folder, KiCad path variable and the two global library-table entries
  install_easyeda                : easyeda2kicad (pinned version + hash) into this Python's venv or a private venv
  kicad_running                  : KiCad keeps its settings in memory - changes should be made while it is closed
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .config import (NO_WINDOW, WINDOWS, Settings, _console_python, app_venv, forget_detection, kicad_config_dir,
                     kicad_major)

# The only third-party package. Pinned to the version this program was tested with; pip refuses the download
# if it does not match these hashes (wheel and source archive as published on PyPI).
EASYEDA_REQUIREMENT = ("easyeda2kicad==1.0.1 "
                       "--hash=sha256:b5a460650c5dd0af35a70658f433f63355fdbdf2c2b9e3bc411bc11ea98d06ed "
                       "--hash=sha256:122a48fafa3b918e730185c973dd342183928b8a0dbe24436d13d58b90290e84")
DESCR = "Personal library (Part Search)"


# ============================================================================= KiCad running?
def kicad_running() -> bool | None:
    """True/False, None if it cannot be told. Any KiCad program counts (they share the settings)."""
    names = ("kicad", "eeschema", "pcbnew")
    try:
        if WINDOWS:
            out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=15,
                                 creationflags=NO_WINDOW).stdout.lower()
            procs = {line.split('","')[0].strip('"') for line in out.splitlines() if line}
            return any(n + ".exe" in procs for n in names)
        out = subprocess.run(["ps", "-A", "-o", "comm="], capture_output=True, text=True, timeout=15).stdout
        return any(Path(line.strip()).name.lower() in names for line in out.splitlines())
    except (OSError, subprocess.SubprocessError):
        return None


# ============================================================================= library registration
@dataclass
class Change:
    what: str                 # short English description (translated by the GUI)
    path: Path                # file or folder that is created / changed
    new_text: str | None      # full new file content; None = create a folder
    detail: str = ""          # the line that is added (shown to the user)


@dataclass
class Plan:
    changes: list = field(default_factory=list)
    problems: list = field(default_factory=list)      # (English format, args): blocks the automatic setup
    config_dir: Path | None = None

    @property
    def needed(self) -> bool:
        return bool(self.changes)


def _table_entries(text: str) -> dict:
    """nickname -> uri of a sym-lib-table / fp-lib-table text (any formatting)."""
    out = {}
    for chunk in re.split(r"\(lib\s", text)[1:]:
        n = re.search(r'\(name\s+"?([^")]+)"?\)', chunk)
        u = re.search(r'\(uri\s+"?([^")]+)"?\)', chunk)
        if n:
            out[n.group(1)] = u.group(1) if u else ""
    return out


def _add_table_entry(text: str, nick: str, uri: str) -> tuple[str, str]:
    """Insert one '(lib ...)' line before the table's closing parenthesis; everything else stays byte-identical."""
    line = '\t(lib (name "%s") (type "KiCad") (uri "%s") (options "") (descr "%s"))' % (nick, uri, DESCR)
    end = text.rstrip().rfind(")")
    if end < 0:
        raise ValueError("library table has no closing parenthesis")
    head = text[:end].rstrip("\n\r\t ")
    nl = "\r\n" if "\r\n" in text else "\n"
    return head + nl + line + nl + text[end:], line


def register_plan(s: Settings) -> Plan:
    """What would have to change so that KiCad finds the library written by Part Search."""
    from . import library                                  # local import: library imports config too
    cli = s.kicad_cli_path()
    plan = Plan(config_dir=kicad_config_dir(kicad_major(cli)))
    lib = s.library_path()
    ctx = library.Context.from_settings(s)
    var = s.path_variable

    # 1. folder + empty libraries, so KiCad does not report a missing library after registration
    if not lib.is_dir():
        plan.changes.append(Change("Create the library folder", lib, None))
    if not ctx.sym_lib.exists():
        plan.changes.append(Change("Create an empty symbol library", ctx.sym_lib, ctx.sym_header))
    if not ctx.fp_lib.is_dir():
        plan.changes.append(Change("Create an empty footprint library", ctx.fp_lib, None))

    cfg = plan.config_dir
    if cfg is None:
        plan.problems.append(("KiCad's settings folder was not found - start KiCad once, then try again", ()))
        return plan

    # 2. path variable (3D model paths are written as ${VAR}/...)
    common = cfg / "kicad_common.json"
    try:
        data = json.loads(common.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = None
        plan.problems.append(("%s does not exist yet - start KiCad once, then try again", (common,)))
    except (OSError, ValueError) as e:
        data = None
        plan.problems.append(("%s cannot be read (%s)", (common, e)))
    if data is not None:
        cur = ((data.get("environment") or {}).get("vars") or {}).get(var)
        want = lib.as_posix()
        if not cur:
            env = data.setdefault("environment", {})
            if not isinstance(env.get("vars"), dict):
                env["vars"] = {}
            env["vars"][var] = want
            plan.changes.append(Change("Add the path variable to KiCad", common,
                                       json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                                       "${%s} = %s" % (var, want)))
        elif Path(cur).resolve() != lib.resolve():
            plan.problems.append(("${%s} already points to %s, not to the library folder %s - change one of them "
                                  "(Preferences > Configure Paths, or Settings > Library)", (var, cur, lib)))

    # 3. library tables (only added, never changed)
    for kind, nick, target in (("sym", s.symbol_lib, "${%s}/%s.kicad_sym" % (var, s.symbol_lib)),
                               ("fp", s.footprint_lib, "${%s}/%s.pretty" % (var, s.footprint_lib))):
        f = cfg / ("%s-lib-table" % kind)
        try:
            with open(f, encoding="utf-8", newline="") as fh:     # keep the file's own line endings
                text = fh.read()
        except FileNotFoundError:
            # never create a new global table: KiCad would then skip its first-start question and the user
            # would lose the default libraries
            plan.problems.append(("%s does not exist yet - start KiCad once (and let it set up the default "
                                  "libraries), then try again", (f,)))
            continue
        entries = _table_entries(text)
        if nick in entries:
            uri = entries[nick].replace("\\", "/")
            if uri.rstrip("/") not in (target, (lib / target.split("/", 1)[1]).as_posix()):
                plan.problems.append(("'%s' is already in %s but points to %s - it was left unchanged",
                                      (nick, f.name, entries[nick])))
            continue
        new, line = _add_table_entry(text, nick, target)
        plan.changes.append(Change("Add the %s library to KiCad" % ("symbol" if kind == "sym" else "footprint"),
                                   f, new, line.strip()))
    return plan


def register_apply(plan: Plan, backup_root: Path, log=None) -> list[str]:
    """Back up every file that is changed, then write. Returns what was done (English, for the log)."""
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    bdir = backup_root / ("kicad_setup_" + stamp)
    done = []
    for c in plan.changes:
        if c.path.exists() and c.path.is_file():
            bdir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(c.path, bdir / c.path.name)
            done.append("backup %s -> %s" % (c.path, bdir / c.path.name))
    for c in plan.changes:
        if c.new_text is None:
            c.path.mkdir(parents=True, exist_ok=True)
            done.append("created folder %s" % c.path)
            continue
        c.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = c.path.with_name(c.path.name + ".partsearch_tmp")
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(c.new_text)
        os.replace(tmp, c.path)
        done.append("%s: %s%s" % (c.what, c.path, (" (" + c.detail + ")") if c.detail else ""))
    for line in done:
        if log:
            log("SETUP", line)
    return done


# ============================================================================= easyeda2kicad
def easyeda_target() -> tuple[Path, bool]:
    """(python to install into, needs_venv). Inside a virtual environment (the KiCad plugin environment) the
    package goes there; otherwise into Part Search's private venv (never into KiCad's own Python)."""
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        return Path(_console_python(sys.executable)), False
    v = app_venv()
    py = v / ("Scripts/python.exe" if WINDOWS else "bin/python")
    return py, not py.exists()


def install_easyeda(work_dir: Path, log=None) -> tuple[bool, str]:
    """pip install the pinned easyeda2kicad. Returns (ok, output tail)."""
    def say(msg):
        if log:
            log("SETUP", msg)
    py, needs_venv = easyeda_target()
    base = Path(_console_python(getattr(sys, "_base_executable", sys.executable)))
    if needs_venv:
        say("creating private environment %s with %s" % (app_venv(), base))
        r = subprocess.run([str(base), "-m", "venv", str(app_venv())], capture_output=True, text=True,
                           timeout=300, creationflags=NO_WINDOW)
        if r.returncode != 0:
            return False, (r.stdout + r.stderr)[-2000:]
    work_dir.mkdir(parents=True, exist_ok=True)
    req = work_dir / "requirements-easyeda2kicad.txt"
    req.write_text(EASYEDA_REQUIREMENT + "\n", encoding="utf-8")
    cmd = [str(py), "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--require-hashes",
           "--only-binary", ":all:", "-r", str(req)]
    say("running: %s" % " ".join(cmd))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    out = (r.stdout + r.stderr).strip()
    say("pip exit %d: %s" % (r.returncode, out.splitlines()[-1] if out else ""))
    forget_detection()
    from . import search
    search.forget_detection()
    return r.returncode == 0, out[-2000:]
