# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""The importer: fetch a part with easyeda2kicad, rename/validate it, write it into the personal library,
then re-read everything from disk to prove it is really there.

    prepare(ctx, lcsc, mode, log)  -> Prepared   CHECK FETCH TRANSFORM VALIDATE PLAN (+PREVIEW); writes nothing
    commit(ctx, prepared, log)     -> dict       WRITE + VERIFY

Modes when the part or one of its names already exists:
    skip   : write nothing, report EXISTS
    force  : overwrite symbol / footprint / 3D model (command line only)
    suffix : keep the existing part, add the new one as NAME-1 (first free -N) - symbol, footprint and 3D files
Every stage checks the file it produced instead of trusting an exit code.
"""
from __future__ import annotations

import csv
import datetime as dt
import filecmp
import html
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import sexpr
from .i18n import T
from .config import NO_WINDOW, Settings, _console_python, kicad_major

STAGE = "stage"                                          # easyeda2kicad output stem in a staging folder
# empty symbol library in the file format of each supported KiCad version (KiCad refuses files that are newer
# than itself, so a new library must be written in the format of the KiCad in use)
SYM_VERSIONS = {8: "20231120", 9: "20241209", 10: "20251024"}


def sym_header(major: int | None = None) -> str:
    major = major if major in SYM_VERSIONS else 10
    return ('(kicad_symbol_lib\n\t(version %s)\n\t(generator "kicad_symbol_editor")\n'
            '\t(generator_version "%d.0")\n)\n' % (SYM_VERSIONS[major], major))


SYM_HEADER = sym_header(10)
REGISTRY_HEADER = ["LCSC", "MPN", "Manufacturer", "Description", "SymbolName",
                   "FootprintName", "Model3D", "DateFetched", "Source"]
MIN_MODEL_BYTES = 1024                                   # smaller 3D files are almost certainly broken
LCSC_RE = re.compile(r"^C\d+$")
MODEL_RE = re.compile(r'\(model\s+"([^"]+)"')


class FetchError(RuntimeError):
    """Expected failure (part has no CAD data, network down, ...) - reported without a traceback."""


@dataclass
class Context:
    """Every path the importer touches, resolved once from the settings."""
    lib_dir: Path
    symbol_lib: str = "my_symbols"
    footprint_lib: str = "my_footprints"
    models_dir: str = "my_3dmodels"
    path_variable: str = "MYLIB_DIR"
    kicad_cli: Path | None = None
    easyeda_python: str | None = None
    work_dir: Path = Path(".")

    @classmethod
    def from_settings(cls, s: Settings) -> "Context":
        return cls(lib_dir=s.library_path(), symbol_lib=s.symbol_lib, footprint_lib=s.footprint_lib,
                   models_dir=s.models_dir, path_variable=s.path_variable, kicad_cli=s.kicad_cli_path(),
                   easyeda_python=s.easyeda_python_path(), work_dir=s.work_path())

    @property
    def sym_lib(self) -> Path:
        return self.lib_dir / (self.symbol_lib + ".kicad_sym")

    @property
    def fp_lib(self) -> Path:
        return self.lib_dir / (self.footprint_lib + ".pretty")

    @property
    def models(self) -> Path:
        return self.lib_dir / self.models_dir

    @property
    def registry(self) -> Path:
        return self.lib_dir / "parts_registry.csv"

    @property
    def history_dir(self) -> Path:
        return self.lib_dir / ".history"

    @property
    def staging(self) -> Path:
        return self.work_dir / "downloads"

    @property
    def log_file(self) -> Path:
        return self.work_dir / "partsearch.log"

    @property
    def sym_header(self) -> str:
        return sym_header(kicad_major(self.kicad_cli))

    @property
    def model_prefix(self) -> str:
        return "${%s}/%s" % (self.path_variable, self.models_dir)


# ---------------------------------------------------------------------- transforms
def fix_symbol(ctx: Context, block: str, lcsc: str, fp_name: str) -> str:
    # easyeda2kicad writes "stage:<fp>"; always point the field at the final footprint library name
    block, n = re.subn(r'(\(property\s+"Footprint"\s+")[^"]*"',
                       lambda m: m.group(1) + ctx.footprint_lib + ":" + fp_name + '"', block, count=1)
    if n != 1:
        raise ValueError("symbol has no Footprint field")
    block = re.sub(r'\(property\s+"LCSC Part"\s+"[^"]*"', '(property "LCSC Part #" "%s"' % lcsc, block)
    if '"LCSC Part #"' not in block:
        raise ValueError("symbol has no LCSC field after conversion")
    return block


def rename_symbol(text: str, old: str, new: str) -> str:
    """Rename the top-level symbol AND its unit sub-symbols (NAME_0_1 ...), nothing else."""
    if old == new:
        return text
    return re.sub(r'(\(symbol\s+")' + re.escape(old) + r'((?:_\d+_\d+)?")',
                  lambda m: m.group(1) + new + m.group(2), text)


def rename_footprint_text(text: str, old: str, new: str) -> str:
    if old == new:
        return text
    text = text.replace("easyeda2kicad:%s " % old, "easyeda2kicad:%s " % new, 1)      # legacy (module ...)
    text = re.sub(r'(\(footprint\s+")' + re.escape(old) + '"', lambda m: m.group(1) + new + '"', text, count=1)
    text = re.sub(r'(\(fp_text\s+value\s+"?)' + re.escape(old) + r'(?=["\s])', lambda m: m.group(1) + new, text, count=1)
    text = re.sub(r'(\(property\s+"Value"\s+")' + re.escape(old) + '"', lambda m: m.group(1) + new + '"', text, count=1)
    return text


def fix_footprint(ctx: Context, text: str, lcsc: str, model_map: dict[str, str]) -> tuple[str, list[str]]:
    """model_map: original model file stem -> final stem. Returns (text, final model file names)."""
    models = []

    def repl(m):
        name = Path(m.group(1).replace("\\", "/")).name
        stem, ext = os.path.splitext(name)
        final = model_map.get(stem, stem) + ext
        models.append(final)
        return '(model "%s/%s"' % (ctx.model_prefix, final)

    text = MODEL_RE.sub(repl, text)
    text = re.sub(r'\(property\s+"LCSC Part"\s+"[^"]*"', '(property "LCSC Part #" "%s"' % lcsc, text)
    return text, models


def norm_fp(text: str) -> str:
    """Footprint text for identity comparison (volatile tokens removed)."""
    text = re.sub(r'\(property\s+"LCSC Part #"\s+"[^"]*"', "", text)
    text = re.sub(r'\((?:tedit|uuid|generator_version|generator)\s+[^)]*\)', "", text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------- registry / library reading
def ensure_registry_bom(ctx: Context) -> None:
    """Older registry files were UTF-8 without BOM; add the BOM once (content unchanged)."""
    if ctx.registry.exists():
        raw = ctx.registry.read_bytes()
        if raw and not raw.startswith(b"\xef\xbb\xbf"):
            raw.decode("utf-8")                         # refuse to touch a file that is not UTF-8
            tmp = ctx.registry.with_suffix(".csv.tmp")
            tmp.write_bytes(b"\xef\xbb\xbf" + raw)
            os.replace(tmp, ctx.registry)


def read_registry(ctx: Context) -> list[dict]:
    if not ctx.registry.exists():
        return []
    with open(ctx.registry, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def history(ctx: Context, limit: int = 200) -> list[dict]:
    """Newest-first rows of parts_registry.csv (every successful import appends one row)."""
    return list(reversed(read_registry(ctx)))[:limit]


_INDEX_CACHE: dict = {}


def library_index(ctx: Context) -> dict:
    """LCSC id -> [symbol names] in the symbol library. Cached until the file changes."""
    p = ctx.sym_lib
    if not p.exists():
        return {}
    st = p.stat()
    key = (str(p), st.st_mtime_ns, st.st_size)
    if _INDEX_CACHE.get("key") != key:
        idx: dict = {}
        for name, block in sexpr.symbol_blocks(p.read_text(encoding="utf-8")).items():
            lc = sexpr.prop_value(block, "LCSC Part #").upper()
            if lc:
                idx.setdefault(lc, []).append(name)
        _INDEX_CACHE.update(key=key, idx=idx)
    return {k: list(v) for k, v in _INDEX_CACHE["idx"].items()}


def lookup_existing(ctx: Context, lcsc: str) -> list[dict]:
    """Everything the library already holds for this LCSC id (symbols are the source of truth, the registry
    adds dates)."""
    found = []
    if ctx.sym_lib.exists():
        for name, block in sexpr.symbol_blocks(ctx.sym_lib.read_text(encoding="utf-8")).items():
            if sexpr.prop_value(block, "LCSC Part #").upper() == lcsc.upper():
                found.append({"symbol": name, "footprint": sexpr.prop_value(block, "Footprint"), "date": ""})
    for row in read_registry(ctx):
        if row.get("LCSC", "").upper() == lcsc.upper():
            for f in found:
                if f["symbol"] == row.get("SymbolName"):
                    f["date"] = row.get("DateFetched", "")
    return found


# ---------------------------------------------------------------------- external programs
def run(cmd: list, log, stage: str = "INFO") -> tuple[int, str]:
    log(stage, "$ " + " ".join('"%s"' % c if " " in str(c) else str(c) for c in cmd))
    try:
        p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", creationflags=NO_WINDOW)
    except OSError as e:
        log(stage, "  could not start: %s" % e)
        return 127, str(e)
    out = p.stdout + p.stderr
    for line in out.splitlines():
        if line.strip():
            log(stage, "  " + line)
    log(stage, "  exit code %d" % p.returncode)
    return p.returncode, out


def fetch_raw(ctx: Context, lcsc: str, log) -> Path:
    """FETCH: easyeda2kicad into a fresh per-run staging folder, then check what it produced."""
    if not ctx.easyeda_python:
        raise FetchError("easyeda2kicad was not found - install it with File > Setup assistant")
    run_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    d = ctx.staging / lcsc / run_id
    d.mkdir(parents=True, exist_ok=False)
    log("FETCH", "%s staging folder %s" % (lcsc, d))
    (d / (STAGE + ".kicad_sym")).write_text(ctx.sym_header, encoding="utf-8")  # forces the current format
    rc, out = run([_console_python(ctx.easyeda_python), "-m", "easyeda2kicad", "--lcsc_id", lcsc, "--full",
                   "--overwrite", "--output", str(d / STAGE)], log, "FETCH")
    if rc != 0:
        if "API request failed" in out:            # urllib error inside easyeda2kicad: network, not the part
            detail = next((ln.split("API request failed:", 1)[1].strip() for ln in out.splitlines()
                           if "API request failed:" in ln), "")
            raise FetchError("EasyEDA could not be reached - check the internet connection (%s)" % detail)
        if "Failed to fetch data from EasyEDA API" in out:
            raise FetchError("EasyEDA has no CAD data for %s (symbol/footprint not published) - this part cannot "
                             "be imported automatically" % lcsc)
        raise FetchError("easyeda2kicad failed (exit %d) - check the internet connection and the LCSC number"
                         % rc)
    sym_text = (d / (STAGE + ".kicad_sym")).read_text(encoding="utf-8")
    blocks = sexpr.symbol_blocks(sym_text)
    if not sexpr.balanced(sym_text) or len(blocks) != 1:
        raise RuntimeError("FETCH: symbol file malformed or contains %d symbols (expected 1)" % len(blocks))
    fps = sorted((d / (STAGE + ".pretty")).glob("*.kicad_mod"))
    if len(fps) != 1 or fps[0].stat().st_size == 0 or not sexpr.balanced(fps[0].read_text(encoding="utf-8")):
        raise RuntimeError("FETCH: expected exactly 1 well-formed footprint, found %d" % len(fps))
    models = sorted((d / (STAGE + ".3dshapes")).glob("*")) if (d / (STAGE + ".3dshapes")).exists() else []
    log("FETCH", "OK symbol '%s' (%d bytes), footprint '%s' (%d bytes), 3D files: %s" % (
        next(iter(blocks)), len(sym_text), fps[0].stem, fps[0].stat().st_size,
        ", ".join("%s (%d bytes)" % (m.name, m.stat().st_size) for m in models) or "NONE"))
    return d


# ---------------------------------------------------------------------- prepare
@dataclass
class Prepared:
    lcsc: str
    raw_dir: Path
    build_dir: Path
    mode: str
    orig_symbol: str
    symbol: str
    footprint: str
    sym_block: str                    # validated symbol text (single symbol)
    fp_file: Path                     # validated footprint file
    model_files: list = field(default_factory=list)   # (src_path, final_name)
    fp_action: str = "new"
    status: str = "READY"             # READY | EXISTS
    detail: str = ""
    warnings: list = field(default_factory=list)
    previews: list = field(default_factory=list)
    info: dict = field(default_factory=dict)
    validated_by_cli: bool = True


def _raw_parts(raw: Path):
    raw_sym = (raw / (STAGE + ".kicad_sym")).read_text(encoding="utf-8")
    orig_sym, block = next(iter(sexpr.symbol_blocks(raw_sym).items()))
    raw_fp_file = next(iter(sorted((raw / (STAGE + ".pretty")).glob("*.kicad_mod"))))
    return raw_sym, orig_sym, block, raw_fp_file


def _build(ctx: Context, raw: Path, lcsc: str, sym_name: str, fp_name: str, model_map: dict, use_cli: bool,
           log, tag: str) -> tuple[Path, str, Path, list]:
    """TRANSFORM + VALIDATE into a fresh build folder with the final names."""
    b = raw / tag
    k = 1
    while b.exists():                    # raw folder reused (preview, then add): never overwrite a build
        k += 1
        b = raw / ("%s_%d" % (tag, k))
    b.mkdir()
    raw_sym, orig_sym, block, raw_fp_file = _raw_parts(raw)
    orig_fp = raw_fp_file.stem
    nb = rename_symbol(fix_symbol(ctx, block, lcsc, fp_name), orig_sym, sym_name)
    sym_text = raw_sym.replace(block, nb)
    fp_text, models = fix_footprint(ctx, raw_fp_file.read_text(encoding="utf-8"), lcsc, model_map)
    fp_text = rename_footprint_text(fp_text, orig_fp, fp_name)
    for what, t in (("symbol", sym_text), ("footprint", fp_text)):
        if not sexpr.balanced(t):
            raise RuntimeError("TRANSFORM: %s has unbalanced parentheses after transform" % what)
    (b / (STAGE + ".kicad_sym")).write_text(sym_text, encoding="utf-8")
    (b / (STAGE + ".pretty")).mkdir()
    (b / (STAGE + ".pretty") / (fp_name + ".kicad_mod")).write_text(fp_text, encoding="utf-8")
    model_files = []
    for final in models:
        stem = os.path.splitext(final)[0]
        orig_stem = next((o for o, n in model_map.items() if n == stem), stem)
        for e in (".wrl", ".step"):
            src = raw / (STAGE + ".3dshapes") / (orig_stem + e)
            if src.exists():
                model_files.append((src, stem + e))
    log("TRANSFORM", "OK symbol '%s' -> '%s', footprint '%s' -> '%s', Footprint field -> %s:%s, 3D -> %s" % (
        orig_sym, sym_name, orig_fp, fp_name, ctx.footprint_lib, fp_name,
        ", ".join(n for _, n in model_files) or "none"))

    if not use_cli:
        log("VALIDATE", "SKIPPED (--no-kicad-cli) - files are NOT checked by KiCad")
        return b, sym_text, b / (STAGE + ".pretty") / (fp_name + ".kicad_mod"), model_files
    if not ctx.kicad_cli or not Path(ctx.kicad_cli).exists():
        raise RuntimeError("VALIDATE: kicad-cli not found - set it in Settings > Tools")
    out_sym, out_fp = b / "validated.kicad_sym", b / "validated.pretty"
    if run([ctx.kicad_cli, "sym", "upgrade", "--force", "-o", out_sym, b / (STAGE + ".kicad_sym")], log, "VALIDATE")[0]:
        raise RuntimeError("VALIDATE: kicad-cli sym upgrade rejected the symbol (see log lines above)")
    if run([ctx.kicad_cli, "fp", "upgrade", "--force", "-o", out_fp, b / (STAGE + ".pretty")], log, "VALIDATE")[0]:
        raise RuntimeError("VALIDATE: kicad-cli fp upgrade rejected the footprint (see log lines above)")
    if not out_sym.exists() or out_sym.stat().st_size == 0:
        raise RuntimeError("VALIDATE: kicad-cli exit 0 but produced no symbol file")
    v_text = out_sym.read_text(encoding="utf-8")
    vb = sexpr.symbol_blocks(v_text)
    if not sexpr.balanced(v_text) or sym_name not in vb:
        raise RuntimeError("VALIDATE: upgraded symbol file malformed or symbol '%s' missing" % sym_name)
    v_fp = out_fp / (fp_name + ".kicad_mod")
    if not v_fp.exists() or v_fp.stat().st_size == 0 or not sexpr.balanced(v_fp.read_text(encoding="utf-8")):
        raise RuntimeError("VALIDATE: kicad-cli exit 0 but footprint '%s.kicad_mod' missing/malformed" % fp_name)
    log("VALIDATE", "OK kicad-cli accepted symbol '%s' (%d pins) and footprint '%s' (%d pads)" % (
        sym_name, sexpr.count_pins(vb[sym_name]), fp_name, sexpr.count_pads(v_fp.read_text(encoding="utf-8"))))
    return b, v_text, v_fp, model_files


def _free_suffix(ctx: Context, sym: str, fp: str, model_stems: list, existing_syms: set) -> int:
    n = 1
    while True:
        if ("%s-%d" % (sym, n) not in existing_syms
                and not (ctx.fp_lib / ("%s-%d.kicad_mod" % (fp, n))).exists()
                and not any((ctx.models / ("%s-%d%s" % (s, n, e))).exists()
                            for s in model_stems for e in (".wrl", ".step"))):
            return n
        n += 1


def prepare(ctx: Context, lcsc: str, mode: str, log, use_cli: bool = True, preview: bool = False,
            raw_dir: Path | None = None) -> Prepared:
    """Fetch + transform + validate. Writes nothing to the library.
    raw_dir: reuse an earlier download of this part (preview first, then add) instead of fetching again."""
    if mode not in ("skip", "force", "suffix"):
        raise ValueError("mode must be skip/force/suffix")
    existing_for_id = lookup_existing(ctx, lcsc)
    log("CHECK", "%s already in library: %s" % (lcsc, ", ".join(e["symbol"] for e in existing_for_id) or "no"))
    if raw_dir is not None:
        raw = raw_dir
        log("FETCH", "%s reusing download %s" % (lcsc, raw))
    else:
        raw = fetch_raw(ctx, lcsc, log)
    _, orig_sym, _, raw_fp_file = _raw_parts(raw)
    orig_fp = raw_fp_file.stem
    shapes = raw / (STAGE + ".3dshapes")
    model_stems = sorted({p.stem for p in shapes.glob("*")}) if shapes.exists() else []
    b, v_text, v_fp, model_files = _build(ctx, raw, lcsc, orig_sym, orig_fp, {s: s for s in model_stems},
                                          use_cli, log, "build_0")

    lib_text = ctx.sym_lib.read_text(encoding="utf-8") if ctx.sym_lib.exists() else ctx.sym_header
    existing = set(sexpr.symbol_blocks(lib_text))
    sym_clash = orig_sym in existing
    dst_fp = ctx.fp_lib / (orig_fp + ".kicad_mod")
    fp_clash = dst_fp.exists() and norm_fp(dst_fp.read_text(encoding="utf-8")) != norm_fp(v_fp.read_text(encoding="utf-8"))
    fp_same = dst_fp.exists() and not fp_clash
    model_clash = any((ctx.models / n).exists() and not filecmp.cmp(s, ctx.models / n, shallow=False)
                      for s, n in model_files)
    log("PLAN", "mode=%s symbol_exists=%s footprint_exists=%s(%s) model_differs=%s" % (
        mode, sym_clash, dst_fp.exists(), "identical" if fp_same else ("DIFFERENT" if fp_clash else "-"), model_clash))

    p = Prepared(lcsc=lcsc, raw_dir=raw, build_dir=b, mode=mode, orig_symbol=orig_sym, symbol=orig_sym,
                 footprint=orig_fp, sym_block=sexpr.symbol_blocks(v_text)[orig_sym], fp_file=v_fp,
                 model_files=model_files, validated_by_cli=use_cli)
    if mode == "skip" and (sym_clash or fp_clash or model_clash):
        p.status = "EXISTS"
        p.detail = ("symbol '%s' already in library" % orig_sym if sym_clash else
                    "a different footprint '%s' already exists" % orig_fp if fp_clash else
                    "a different 3D model with the same name already exists")
        log("PLAN", "EXISTS: %s -> nothing will be written (use --suffix / 'fetch again' or --force)" % p.detail)
        p.fp_action = "not written"
    elif mode == "suffix" and (sym_clash or fp_clash or model_clash or existing_for_id):
        n = _free_suffix(ctx, orig_sym, orig_fp, model_stems, existing)
        new_sym = "%s-%d" % (orig_sym, n)
        new_fp = "%s-%d" % (orig_fp, n) if (fp_clash or fp_same) else orig_fp
        mm = {s: ("%s-%d" % (s, n) if model_clash or any((ctx.models / (s + e)).exists() for e in (".wrl", ".step"))
                  else s) for s in model_stems}
        log("PLAN", "suffix -%d: symbol '%s', footprint '%s', 3D %s" % (n, new_sym, new_fp, list(mm.values())))
        b, v_text, v_fp, model_files = _build(ctx, raw, lcsc, new_sym, new_fp, mm, use_cli, log, "build_suffix_%d" % n)
        p.build_dir, p.symbol, p.footprint = b, new_sym, new_fp
        p.sym_block, p.fp_file, p.model_files = sexpr.symbol_blocks(v_text)[new_sym], v_fp, model_files
        p.fp_action = "new (suffixed)" if new_fp != orig_fp else "new"
    elif mode == "force":
        p.fp_action = "overwrite(--force)" if fp_clash else ("reuse-identical" if fp_same else "new")
    else:
        p.fp_action = "reuse-identical" if fp_same else "new"

    # consistency check BEFORE anything touches the library
    fp_field = sexpr.prop_value(p.sym_block, "Footprint")
    lc_field = sexpr.prop_value(p.sym_block, "LCSC Part #")
    if fp_field != "%s:%s" % (ctx.footprint_lib, p.footprint) or lc_field != lcsc:
        raise RuntimeError("TRANSFORM: built symbol fields inconsistent (Footprint=%r, LCSC=%r) - nothing written"
                           % (fp_field, lc_field))
    fp_txt = p.fp_file.read_text(encoding="utf-8")
    if sexpr.count_pads(fp_txt) == 0:
        p.warnings.append("footprint has NO pads")
    if sexpr.count_pins(p.sym_block) == 0:
        p.warnings.append("symbol has NO pins")
    names = [n for _, n in p.model_files]
    if not names:
        p.warnings.append("no 3D model downloaded")
    for src, n in p.model_files:
        if src.stat().st_size < MIN_MODEL_BYTES:
            p.warnings.append("3D file %s is only %d bytes (probably broken)" % (n, src.stat().st_size))
    if names and not any(n.endswith(".step") for n in names):
        p.warnings.append("no STEP model (STEP export for Fusion 360 will miss this part)")
    for w in p.warnings:
        log("PLAN", "WARNING: " + w)
    p.info = {"MPN": sexpr.prop_value(p.sym_block, "MPN"), "Manufacturer": sexpr.prop_value(p.sym_block, "Manufacturer"),
              "Description": sexpr.prop_value(p.sym_block, "Description"), "pins": sexpr.count_pins(p.sym_block),
              "pads": sexpr.count_pads(fp_txt)}
    if preview and use_cli:
        make_previews(ctx, p, log)
    return p


def make_previews(ctx: Context, p: Prepared, log) -> None:
    out = p.build_dir / "preview"
    out.mkdir(exist_ok=True)
    run([ctx.kicad_cli, "sym", "export", "svg", "-s", p.symbol, "-o", out, p.build_dir / "validated.kicad_sym"],
        log, "PREVIEW")
    run([ctx.kicad_cli, "fp", "export", "svg", "--fp", p.footprint, "-o", out, p.fp_file.parent], log, "PREVIEW")
    p.previews = sorted(out.glob("*.svg"))
    log("PREVIEW", "%d SVG preview(s): %s" % (len(p.previews), ", ".join(x.name for x in p.previews)))
    rows = "".join("<tr><th>%s</th><td>%s</td></tr>" % (html.escape(k), html.escape(str(v))) for k, v in (
        ("LCSC", p.lcsc), (T("Symbol name"), p.symbol), (T("Footprint"), "%s:%s" % (ctx.footprint_lib, p.footprint)),
        (T("3D files"), ", ".join("%s (%d bytes)" % (n, s.stat().st_size) for s, n in p.model_files) or T("none")),
        (T("Pins / pads"), "%s / %s" % (p.info.get("pins"), p.info.get("pads"))),
        ("MPN", p.info.get("MPN")), (T("Manufacturer"), p.info.get("Manufacturer")),
        (T("Status"), p.status + (" - " + p.detail if p.detail else ""))))
    warn = "".join("<li>%s</li>" % html.escape(w) for w in p.warnings) or "<li>%s</li>" % html.escape(T("none"))
    imgs = "".join('<figure><img src="%s"><figcaption>%s</figcaption></figure>' % (x.name, html.escape(x.name))
                   for x in p.previews) or "<p>%s</p>" % html.escape(T("No SVG preview could be generated (see the log)."))
    page = out / "preview.html"
    page.write_text(
        "<!doctype html><meta charset='utf-8'><title>%s</title><style>body{font-family:sans-serif;"
        "margin:20px}table{border-collapse:collapse}th,td{border:1px solid #ccc;padding:4px 8px;text-align:left}"
        "figure{display:inline-block;margin:10px;border:1px solid #ccc;background:#fff}img{max-width:560px;"
        "max-height:560px}.w{color:#b00}</style><h2>%s</h2><table>%s</table>"
        "<h3 class='w'>%s</h3><ul>%s</ul>%s" % (html.escape(T("Preview of %s") % p.lcsc),
                                              html.escape(T("%s - preview (NOT yet in your library)") % p.lcsc),
                                              rows, html.escape(T("Warnings")), warn, imgs), encoding="utf-8")
    p.previews.insert(0, page)


# ---------------------------------------------------------------------- commit
def commit(ctx: Context, p: Prepared, log, use_cli: bool = True) -> dict:
    """WRITE + VERIFY. Raises on any verification failure (the log says which artifact)."""
    if p.status != "READY":
        raise RuntimeError("WRITE: refusing to commit a part in state %s" % p.status)
    lib_text = ctx.sym_lib.read_text(encoding="utf-8") if ctx.sym_lib.exists() else ctx.sym_header
    if p.mode != "force" and p.symbol in sexpr.symbol_blocks(lib_text):
        raise RuntimeError("WRITE: symbol '%s' appeared in the library meanwhile - aborted" % p.symbol)
    ctx.lib_dir.mkdir(parents=True, exist_ok=True)
    ctx.history_dir.mkdir(parents=True, exist_ok=True)
    if ctx.sym_lib.exists():
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        bk = ctx.history_dir / ("%s_%s_before_%s.kicad_sym" % (ctx.symbol_lib, stamp, p.lcsc))
        k = 1
        while bk.exists():               # two imports in the same second must not overwrite a backup
            k += 1
            bk = ctx.history_dir / ("%s_%s_%d_before_%s.kicad_sym" % (ctx.symbol_lib, stamp, k, p.lcsc))
        shutil.copy2(ctx.sym_lib, bk)
        log("WRITE", "library backup %s" % bk.name)
    new_lib = sexpr.replace_or_append_symbol(lib_text, p.symbol, p.sym_block.strip())
    if not sexpr.balanced(new_lib):
        raise RuntimeError("WRITE: merged symbol library would be unbalanced - aborted, nothing written")
    tmp = ctx.sym_lib.with_suffix(".kicad_sym.tmp")
    tmp.write_text(new_lib, encoding="utf-8", newline="\n")
    os.replace(tmp, ctx.sym_lib)
    log("WRITE", "symbol '%s' -> %s" % (p.symbol, ctx.sym_lib))
    ctx.fp_lib.mkdir(parents=True, exist_ok=True)
    dst_fp = ctx.fp_lib / (p.footprint + ".kicad_mod")
    if p.fp_action != "reuse-identical":
        shutil.copyfile(p.fp_file, dst_fp)
        log("WRITE", "footprint -> %s (%s)" % (dst_fp, p.fp_action))
    else:
        log("WRITE", "footprint %s already present and identical - reused" % dst_fp.name)
    ctx.models.mkdir(parents=True, exist_ok=True)
    for src, name in p.model_files:
        dst = ctx.models / name
        if dst.exists() and filecmp.cmp(src, dst, shallow=False):
            log("WRITE", "3D %s identical - reused" % name)
            continue
        shutil.copyfile(src, dst)
        log("WRITE", "3D -> %s (%d bytes)" % (dst, dst.stat().st_size))
    new_file = not ctx.registry.exists()
    ensure_registry_bom(ctx)
    src_note = "easyeda2kicad (EasyEDA/LCSC API)"
    if p.symbol != p.orig_symbol:
        src_note += " re-fetch copy of %s" % p.orig_symbol
    if not p.validated_by_cli:
        src_note += " [not kicad-cli validated]"
    # utf-8-sig: BOM so Excel and Windows PowerShell 5.1 detect UTF-8 (Chinese vendor names, Ohm, +-).
    # In append mode Python writes the BOM only when the file is empty.
    with open(ctx.registry, "a", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        if new_file:
            w.writerow(REGISTRY_HEADER)
        w.writerow([p.lcsc, p.info.get("MPN", ""), p.info.get("Manufacturer", ""), p.info.get("Description", ""),
                    p.symbol, "%s:%s" % (ctx.footprint_lib, p.footprint), ";".join(n for _, n in p.model_files),
                    dt.date.today().isoformat(), src_note])
    log("WRITE", "registry row appended")
    verify_commit(ctx, p, log, use_cli)
    return {"lcsc": p.lcsc, "status": "OK", "detail": "added", "symbol": p.symbol, "footprint": p.footprint,
            "fp_action": p.fp_action, "models": [n for _, n in p.model_files], "warnings": p.warnings}


def verify_commit(ctx: Context, p: Prepared, log, use_cli: bool) -> None:
    """VERIFY: re-read every artifact from disk; do not trust the write calls."""
    problems = []
    lib = ctx.sym_lib.read_text(encoding="utf-8")
    blocks = sexpr.symbol_blocks(lib)
    if not sexpr.balanced(lib):
        problems.append("%s is not balanced after write" % ctx.sym_lib.name)
    blk = blocks.get(p.symbol)
    if blk is None:
        problems.append("symbol '%s' not found when re-reading %s" % (p.symbol, ctx.sym_lib.name))
    else:
        if sexpr.prop_value(blk, "LCSC Part #") != p.lcsc:
            problems.append("symbol LCSC Part # is '%s', expected %s" % (sexpr.prop_value(blk, "LCSC Part #"), p.lcsc))
        if sexpr.prop_value(blk, "Footprint") != "%s:%s" % (ctx.footprint_lib, p.footprint):
            problems.append("symbol Footprint field is '%s'" % sexpr.prop_value(blk, "Footprint"))
    fpf = ctx.fp_lib / (p.footprint + ".kicad_mod")
    if not fpf.exists() or fpf.stat().st_size == 0:
        problems.append("footprint file %s missing/empty" % fpf.name)
    else:
        t = fpf.read_text(encoding="utf-8")
        head = re.match(r'\((?:footprint\s+"([^"]+)"|module\s+(?:easyeda2kicad:)?("?)([^\s"]+)\2)', t)
        name_in = (head.group(1) or head.group(3)) if head else None
        if not sexpr.balanced(t) or name_in != p.footprint:
            problems.append("footprint file %s malformed or wrong name inside" % fpf.name)
        for m in MODEL_RE.findall(t):
            if not m.startswith(ctx.model_prefix + "/"):
                problems.append("3D path not under ${%s}: %s" % (ctx.path_variable, m))
            elif not (ctx.models / m.split("/")[-1]).exists():
                problems.append("3D file referenced by footprint is missing: %s" % m)
    for src, name in p.model_files:
        dst = ctx.models / name
        if not dst.exists() or dst.stat().st_size != src.stat().st_size:
            problems.append("3D file %s missing or size differs" % name)
    if not any(r.get("LCSC") == p.lcsc and r.get("SymbolName") == p.symbol for r in read_registry(ctx)):
        problems.append("registry row for %s/%s not found when re-reading parts_registry.csv" % (p.lcsc, p.symbol))
    if use_cli and not problems:
        out = p.build_dir / "verify"
        out.mkdir(exist_ok=True)
        rc1 = run([ctx.kicad_cli, "sym", "export", "svg", "-s", p.symbol, "-o", out, ctx.sym_lib], log, "VERIFY")[0]
        rc2 = run([ctx.kicad_cli, "fp", "export", "svg", "--fp", p.footprint, "-o", out, ctx.fp_lib], log, "VERIFY")[0]
        svgs = list(out.glob("*.svg"))
        if rc1 or rc2 or len(svgs) < 2 or any(s.stat().st_size == 0 for s in svgs):
            problems.append("KiCad could not load the new symbol/footprint FROM THE LIBRARY (kicad-cli export "
                            "exit %d/%d, %d svg files)" % (rc1, rc2, len(svgs)))
        else:
            log("VERIFY", "kicad-cli loaded '%s' from %s and '%s' from %s" % (
                p.symbol, ctx.symbol_lib, p.footprint, ctx.footprint_lib))
    if problems:
        for pr in problems:
            log("VERIFY", "FAILED: " + pr)
        raise RuntimeError("VERIFY: " + "; ".join(problems) + " | files WERE written; the previous symbol library "
                           "is in %s" % ctx.history_dir)
    log("VERIFY", "OK %s: symbol, footprint, %d 3D file(s) and registry row confirmed on disk" % (
        p.lcsc, len(p.model_files)))


def process(ctx: Context, lcsc: str, mode: str, dry: bool, use_cli: bool, log) -> dict:
    """One part for the command line: prepare, then commit unless skipped or dry-run."""
    p = prepare(ctx, lcsc, mode, log, use_cli)
    base = {"lcsc": lcsc, "symbol": p.symbol, "footprint": p.footprint, "fp_action": p.fp_action,
            "models": [n for _, n in p.model_files], "warnings": p.warnings}
    if p.status == "EXISTS":
        return dict(base, status="SKIPPED", detail=p.detail + " (use --suffix to add a copy, --force to overwrite)")
    if dry:
        return dict(base, status="DRY-RUN", detail="nothing written")
    return commit(ctx, p, log, use_cli)
