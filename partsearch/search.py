# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""Part search.

local  : the JLCPCB parts database downloaded by the "JLCPCB Tools" plugin (Bouni), SQLite FTS5 trigram index,
         opened READ-ONLY. Offline and fast; as fresh as that plugin's last download.
online : JLCPCB's web search through easyeda2kicad (the same package that fetches the CAD data). Live stock.
"""
from __future__ import annotations

import importlib
import logging
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from .config import NO_WINDOW, _console_python

MAX_CANDIDATES = 3000          # rows pulled from FTS before re-ranking
TYPE_RANK = {"Basic": 0, "Preferred": 1, "Extended": 2}
LCSC_RE = re.compile(r"^C\d{1,9}$", re.I)
COLS = ('"LCSC Part","First Category","Second Category","MFR.Part","Package","Manufacturer",'
        '"Library Type","Description","Datasheet","Price","Stock"')


class SearchError(Exception):
    """A search could not run (as opposed to: it ran and found nothing)."""


def _int(v) -> int:
    try:
        return int(float(str(v).replace(",", "").strip() or 0))
    except ValueError:
        return 0


def _first_price(price: str) -> str:
    # "1-9:1.845,10-29:1.623,..." -> "1.845"
    m = re.match(r"[^:,]*:([0-9.]+)", price or "")
    return m.group(1) if m else ""


def _row(r) -> dict:
    return {"lcsc": r[0], "category": "%s / %s" % (r[1], r[2]), "mfr_part": r[3], "package": r[4],
            "manufacturer": r[5], "type": r[6] or "?", "description": r[7], "datasheet": r[8],
            "price": _first_price(r[9]), "stock": _int(r[10]), "source": "local"}


# ---------------------------------------------------------------------- local DB
def _connect(db: Path, deadline: float | None = None) -> sqlite3.Connection:
    c = sqlite3.connect("file:%s?mode=ro" % db.as_posix(), uri=True, timeout=5)
    if deadline is not None:
        # SQLite calls this every 20k VM steps; a non-zero return aborts the query ("interrupted")
        c.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 20000)
    return c


def db_info(db: Path) -> dict:
    """Existence, size and download date of the local DB (status bar, settings check)."""
    if not db.exists():
        return {"ok": False, "path": str(db), "detail": "local JLCPCB database not found"}
    info = {"ok": True, "path": str(db), "size_mb": db.stat().st_size // (1 << 20), "date": "?", "parts": 0}
    c = None
    try:
        c = _connect(db)
        m = c.execute("select * from meta").fetchone()
        if m:
            info["parts"] = _int(m[2])
            info["date"] = str(m[3])
    except sqlite3.Error as e:
        info["detail"] = "meta unreadable: %s" % e
    finally:
        if c is not None:
            c.close()
    return info


def _fts_phrase(tok: str) -> str:
    return '"%s"' % tok.replace('"', '""')


def _boundary_re(tok: str) -> re.Pattern:
    # "10k" must not match "510kΩ" or "10kV" but must match "10kΩ", "10K", "(10k)"
    return re.compile(r"(?<![0-9a-z.])%s(?![0-9a-z])" % re.escape(tok.lower()))


def _prefix_re(tok: str) -> re.Pattern:
    # word START only: "stm32" matches "STM32F103C8T6", "10k" still not "510k"
    return re.compile(r"(?<![0-9a-z.])%s" % re.escape(tok.lower()))


def search_local(db: Path, query: str, basic_only: bool = False, in_stock: bool = False, limit: int = 200,
                 timeout: int = 10) -> dict:
    """{"results": [...], "total_candidates": n, "note": str, "seconds": t}. Raises SearchError if the DB is
    missing/unreadable or the query is unusable."""
    t0 = time.time()
    q = query.strip()
    if not q:
        raise SearchError("empty search")
    if not db.exists():
        raise SearchError("local JLCPCB database not found: %s (optional - File > Setup assistant shows how to "
                          "get it; the online search works without it)" % db)
    toks = q.split()
    note = ""
    c = None
    try:
        c = _connect(db, t0 + timeout)
        if len(toks) == 1 and LCSC_RE.match(toks[0]):
            lc = toks[0].upper()
            rows = c.execute("select %s from parts where parts match ? " % COLS,
                             ('"LCSC Part" : %s' % _fts_phrase(lc),)).fetchall()
            return {"results": [_row(r) for r in rows if r[0].upper() == lc], "total_candidates": len(rows),
                    "note": "", "seconds": time.time() - t0}
        long_toks = [t for t in toks if len(t) >= 3]
        short_toks = [t for t in toks if len(t) < 3]
        if not long_toks:
            raise SearchError("enter at least one search word with 3 or more characters "
                              "(the local index is a trigram index)")
        match = " AND ".join(_fts_phrase(t) for t in long_toks)
        sql = "select %s from parts where parts match ? limit %d" % (COLS, MAX_CANDIDATES)
        rows = c.execute(sql, (match,)).fetchall()
        if len(rows) >= MAX_CANDIDATES:
            # the capped candidate set is arbitrary - make sure Basic/Preferred parts are never lost
            seen = {r[0] for r in rows}
            for lt in ("Basic", "Preferred"):
                for r in c.execute(sql, ('%s AND "Library Type" : "%s"' % (match, lt),)):
                    if r[0] not in seen:
                        seen.add(r[0])
                        rows.append(r)
    except sqlite3.OperationalError as e:
        if "interrupt" in str(e).lower():
            raise SearchError("local search stopped after %d s - add more words (value, package, MPN)"
                              % timeout) from e
        raise SearchError("local DB query failed: %s" % e) from e
    except sqlite3.Error as e:
        raise SearchError("local DB query failed: %s" % e) from e
    finally:
        if c is not None:
            c.close()
    if len(rows) >= MAX_CANDIDATES:
        note = "more than %d raw matches - add words (value, package, MPN) to narrow down" % MAX_CANDIDATES
    pats = [_boundary_re(t) for t in toks]
    ppats = [_prefix_re(t) for t in toks]
    short_low = [t.lower() for t in short_toks]
    strict, prefix, loose = [], [], []
    for r in rows:
        p = _row(r)
        if basic_only and p["type"] not in ("Basic", "Preferred"):
            continue
        if in_stock and p["stock"] <= 0:
            continue
        h = " ".join((p["lcsc"], p["mfr_part"], p["package"], p["manufacturer"], p["description"],
                      p["category"])).lower()
        if short_low and not all(s in h for s in short_low):
            continue
        if all(pt.search(h) for pt in pats):
            strict.append(p)
        elif all(pt.search(h) for pt in ppats):
            prefix.append(p)
        else:
            loose.append(p)
    # whole words, then word starts (STM32F103 for "stm32"); pure substrings (510k for "10k") only if nothing
    # better matched
    if strict or prefix:
        use = strict + prefix
    else:
        use = loose
        if loose:
            note = (note + "; " if note else "") + "no word match - showing partial (substring) matches"
    tier = {id(p): 0 for p in strict}
    # Basic (no JLCPCB feeder fee) > Preferred > Extended, then most stock
    use.sort(key=lambda p: (tier.get(id(p), 1), TYPE_RANK.get(p["type"], 3), -p["stock"]))
    return {"results": use[:limit], "total_candidates": len(rows), "note": note, "seconds": time.time() - t0}


# ---------------------------------------------------------------------- online
class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)
        self.msgs = []

    def emit(self, record):
        self.msgs.append(record.getMessage())


_SITE_CACHE: dict = {}


def forget_detection() -> None:
    _SITE_CACHE.clear()
    importlib.invalidate_caches()


def _import_easyeda(easyeda_python: str | None):
    """easyeda2kicad is pure Python: import it in-process, from the environment of the configured python if
    this python does not have it (KiCad's bundled python normally does not)."""
    try:
        from easyeda2kicad.easyeda.easyeda_api import EasyedaApi
        return EasyedaApi
    except ImportError:
        pass
    if easyeda_python:
        if easyeda_python not in _SITE_CACHE:
            try:
                out = subprocess.run([_console_python(easyeda_python), "-c",
                                      "import easyeda2kicad,os;print(os.path.dirname(os.path.dirname("
                                      "easyeda2kicad.__file__)))"],
                                     capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW)
                _SITE_CACHE[easyeda_python] = out.stdout.strip() if out.returncode == 0 else ""
            except (OSError, subprocess.SubprocessError):
                _SITE_CACHE[easyeda_python] = ""
        sp = _SITE_CACHE[easyeda_python]
        if sp and sp not in sys.path:
            sys.path.append(sp)                 # append: never shadow the host's own packages
    try:
        from easyeda2kicad.easyeda.easyeda_api import EasyedaApi
        return EasyedaApi
    except ImportError as e:
        raise SearchError("easyeda2kicad not found - install it with File > Setup assistant (%s)" % e) from e


def search_online(query: str, easyeda_python: str | None = None, basic_only: bool = False, in_stock: bool = False,
                  page_size: int = 50) -> dict:
    """JLCPCB live search. Raises SearchError when the request itself failed (so 'failed' is never shown as
    'no results')."""
    t0 = time.time()
    q = query.strip()
    if not q:
        raise SearchError("empty search")
    api = _import_easyeda(easyeda_python)
    cap = _Capture()
    root = logging.getLogger()
    root.addHandler(cap)
    try:
        data = api().search_jlcpcb_components(q, page=1, page_size=page_size,
                                              part_type="base" if basic_only else None)
    except Exception as e:  # noqa: BLE001 - timeouts etc. are not caught inside easyeda2kicad
        raise SearchError("online search failed: %s" % e) from e
    finally:
        root.removeHandler(cap)
    if cap.msgs:
        raise SearchError("online search failed: " + " | ".join(cap.msgs))
    res = []
    for it in data.get("results", []):
        p = {"lcsc": it.get("lcsc", ""), "mfr_part": it.get("model") or it.get("name", ""),
             "package": it.get("package", ""), "manufacturer": it.get("brand", ""),
             "type": it.get("type", "?"), "description": it.get("description") or it.get("name", ""),
             "category": it.get("category", ""), "datasheet": it.get("datasheet", ""),
             "price": str(it.get("price") or ""), "stock": _int(it.get("stock")), "source": "online",
             "url": it.get("url", "")}
        if in_stock and p["stock"] <= 0:
            continue
        res.append(p)
    total = _int(data.get("total"))
    return {"results": res, "total_candidates": total, "seconds": time.time() - t0,
            "note": "online shows the first %d of %s matches" % (page_size, data.get("total", "?"))
            if total > page_size else ""}
