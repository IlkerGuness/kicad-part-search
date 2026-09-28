# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""Command line importer (same code path as the window).

    python -m partsearch.cli C25804 [C2838502 ...] [--force | --suffix] [--dry-run] [--no-kicad-cli]
    python -m partsearch.cli --search local "10k 0603"
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys

from . import search
from .api import Session


def _search(ses: Session, where: str, q: str) -> int:
    try:
        r = ses.search(where, q)
    except search.SearchError as e:
        print("ERROR:", e)
        return 1
    idx = ses.library_index()
    if not r["results"]:
        print("not found in %s" % ("local DB" if where == "local" else "online search"))
    for p in r["results"][:25]:
        print("%-10s %-9s %7d  %-16.16s %-22.22s %-8s %s" % (
            p["lcsc"], p["type"], p["stock"], p["package"], p["mfr_part"],
            "IN-LIB" if p["lcsc"].upper() in idx else "", p["description"][:60]))
    print("-- %d result(s), %d raw candidates, %.2fs %s" % (len(r["results"]), r["total_candidates"],
                                                          r["seconds"], r["note"]))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="partsearch.cli", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="*", help="LCSC part numbers, e.g. C25804")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--force", action="store_true", help="overwrite existing symbol/footprint/3D model")
    g.add_argument("--suffix", action="store_true", help="keep existing, add a new copy as NAME-1, NAME-2, ...")
    ap.add_argument("--dry-run", action="store_true", help="fetch+validate only, do not touch the library")
    ap.add_argument("--no-kicad-cli", action="store_true", help="skip kicad-cli validation (not recommended)")
    ap.add_argument("--search", nargs=2, metavar=("local|online", "QUERY"), help="search instead of importing")
    a = ap.parse_args(argv)
    from .config import ensure_ca_bundle
    ensure_ca_bundle()                    # macOS: before the first HTTPS request
    ses = Session()
    if a.search:
        return _search(ses, a.search[0], a.search[1])
    if not a.ids:
        ap.error("give at least one LCSC number or --search")
    mode = "force" if a.force else ("suffix" if a.suffix else "skip")
    from .library import process
    log = ses.logger()
    log.banner("==== partsearch %s  ids=%s mode=%s dry=%s" % (dt.datetime.now().isoformat(timespec="seconds"),
                                                         a.ids, mode, a.dry_run))
    results = []
    for raw in a.ids:
        lcsc = raw.strip().upper()
        if not re.fullmatch(r"C\d+", lcsc):
            results.append({"lcsc": raw, "status": "FAILED", "detail": "not an LCSC id (C12345)"})
            continue
        try:
            results.append(process(ses.ctx, lcsc, mode, a.dry_run, not a.no_kicad_cli, log))
        except Exception as e:  # noqa: BLE001 - report every failure, continue with the next part
            log("ERROR", "%s: %s" % (lcsc, e))
            results.append({"lcsc": lcsc, "status": "FAILED", "detail": str(e)})
    log.banner("\n==== SUMMARY")
    for r in results:
        extra = ""
        if "symbol" in r:
            extra = "  symbol=%s  footprint=%s:%s (%s)  3d=%s" % (
                r["symbol"], ses.ctx.footprint_lib, r["footprint"], r.get("fp_action"), r.get("models"))
        log.banner("  %-10s %-8s %s%s" % (r["lcsc"], r["status"], r["detail"], extra))
        for w in r.get("warnings", []):
            log.banner("  %-10s WARNING  %s" % ("", w))
    ok = all(r["status"] in ("OK", "DRY-RUN") for r in results)
    log.banner("  RESULT: %s" % ("ALL OK" if ok else "SOME PARTS NOT ADDED - see above"))
    log.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
