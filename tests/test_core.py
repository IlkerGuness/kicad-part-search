# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""Unit tests for the parts that are new in the refactor (runs with any python >= 3.10, no wx, no network):
    python -m unittest discover -s tests -v
"""
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from partsearch import i18n, library, sexpr  # noqa: E402
from partsearch.config import Settings  # noqa: E402
from partsearch.logger import Logger  # noqa: E402


def quiet(*_a, **_k):
    pass


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="pstest_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ctx(self, **kw):
        return library.Context(lib_dir=self.tmp / "lib", work_dir=self.tmp / "work", **kw)


class SettingsTest(Tmp):
    def test_roundtrip_and_unknown_keys_kept(self):
        f = self.tmp / "s.json"
        f.write_text(json.dumps({"theme": "dark", "max_results": "150", "future_option": [1, 2], "recent": "bad"}))
        s = Settings.load(f)
        self.assertEqual((s.theme, s.max_results, s.recent), ("dark", 150, []))
        self.assertEqual(s.extra["future_option"], [1, 2])
        s.language = "tr"
        s.save(f)
        d = json.loads(f.read_text(encoding="utf-8"))
        self.assertEqual((d["language"], d["future_option"]), ("tr", [1, 2]))

    def test_corrupt_file_gives_defaults(self):
        f = self.tmp / "s.json"
        f.write_text("{not json")
        s = Settings.load(f)
        self.assertEqual(s.theme, "system")
        self.assertIn("_load_error", s.extra)
        s.save(f)                                       # the error marker is not written back
        self.assertNotIn("_load_error", json.loads(f.read_text()))

    def test_library_path_priority(self):
        s = Settings(library_dir=str(self.tmp / "x"))
        old = os.environ.pop("MYLIB_DIR", None)
        try:
            self.assertEqual(s.library_path(), self.tmp / "x")
            os.environ["MYLIB_DIR"] = str(self.tmp / "env")
            self.assertEqual(s.library_path(), self.tmp / "x")          # the setting wins over KiCad's env var
            s.library_dir = ""
            self.assertEqual(s.library_path(), self.tmp / "env")
        finally:
            os.environ.pop("MYLIB_DIR", None)
            if old:
                os.environ["MYLIB_DIR"] = old


FIXTURES = HERE / "fixtures"
NEED_FIXTURES = unittest.skipUnless((FIXTURES / "C25804").is_dir(),
                                    "tests/fixtures not present (EasyEDA data, not published) - see make_fixtures.py")


class LibraryTest(Tmp):
    @unittest.skipIf(sys.platform == "win32", "uses a shell script as fake python")
    def test_fetch_error_no_cad_data(self):
        fake = self.tmp / "fakepy"
        fake.write_text("#!/bin/sh\necho '-- easyeda2kicad.py v1.0.1 --'\n"
                        "echo '[ERROR] Failed to fetch data from EasyEDA API for part C9900276375'\nexit 1\n")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        c = self.ctx(easyeda_python=str(fake))
        log = Logger(c.log_file, echo=None)
        with self.assertRaises(library.FetchError) as cm:
            library.fetch_raw(c, "C9900276375", log)
        self.assertIn("no CAD data", str(cm.exception))
        log.close()

    @unittest.skipIf(sys.platform == "win32", "uses a shell script as fake python")
    def test_fetch_error_offline_is_not_reported_as_missing_part(self):
        fake = self.tmp / "fakepy"
        fake.write_text("#!/bin/sh\necho '[ERROR] API request failed: <urlopen error [Errno 11001] getaddrinfo "
                        "failed>'\necho '[ERROR] Failed to fetch data from EasyEDA API for part C25804'\nexit 1\n")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        c = self.ctx(easyeda_python=str(fake))
        log = Logger(c.log_file, echo=None)
        with self.assertRaises(library.FetchError) as cm:
            library.fetch_raw(c, "C25804", log)
        self.assertIn("could not be reached", str(cm.exception))
        self.assertIn("getaddrinfo", str(cm.exception))
        log.close()

    def test_no_easyeda_python(self):
        c = self.ctx(easyeda_python=None)
        log = Logger(c.log_file, echo=None)
        with self.assertRaises(library.FetchError):
            library.fetch_raw(c, "C1", log)
        log.close()

    @NEED_FIXTURES
    def test_backups_never_overwrite_and_index_cache(self):
        c = self.ctx()
        log = Logger(c.log_file, echo=None)
        for lcsc in ("C25804", "C2286", "C12340"):
            raw = self.tmp / ("raw_" + lcsc)
            shutil.copytree(HERE / "fixtures" / lcsc, raw)
            p = library.prepare(c, lcsc, "skip", log, use_cli=False, raw_dir=raw)
            library.commit(c, p, log, use_cli=False)
            self.assertIn(lcsc, library.library_index(c))     # cache refreshed after every write
        # 3 commits within ~1 s: first creates the library (no backup), the next two must leave 2 backups
        self.assertEqual(len(list(c.history_dir.glob("*.kicad_sym"))), 2)
        log.close()

    @NEED_FIXTURES
    def test_custom_names(self):
        c = self.ctx(symbol_lib="parts_sym", footprint_lib="parts_fp", models_dir="parts_3d", path_variable="PARTS")
        log = Logger(c.log_file, echo=None)
        raw = self.tmp / "raw"
        shutil.copytree(HERE / "fixtures" / "C25804", raw)
        p = library.prepare(c, "C25804", "skip", log, use_cli=False, raw_dir=raw)
        library.commit(c, p, log, use_cli=False)
        sym = (c.lib_dir / "parts_sym.kicad_sym").read_text(encoding="utf-8")
        self.assertEqual(sexpr.prop_value(sexpr.symbol_blocks(sym)["0603WAF1002T5E"], "Footprint"), "parts_fp:R0603")
        fp = (c.lib_dir / "parts_fp.pretty" / "R0603.kicad_mod").read_text(encoding="utf-8")
        self.assertIn('(model "${PARTS}/parts_3d/R0603.wrl"', fp)
        log.close()


class KiCadConfig(Tmp):
    """A fake KiCad settings folder (KICAD_CONFIG_HOME, honoured by KiCad and by Part Search)."""
    def setUp(self):
        super().setUp()
        self.cfg = self.tmp / "kicad" / "10.0"
        self.cfg.mkdir(parents=True)
        self._env = {k: os.environ.get(k) for k in ("KICAD_CONFIG_HOME", "MYLIB_DIR", "KICAD_CLI")}
        os.environ["KICAD_CONFIG_HOME"] = str(self.tmp / "kicad")
        os.environ.pop("MYLIB_DIR", None)
        os.environ["KICAD_CLI"] = str(self.tmp / "no-kicad-cli")      # not a file: version unknown -> newest dir

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        super().tearDown()


class ChecksTest(KiCadConfig):
    def test_lib_table_parsing(self):
        (self.cfg / "sym-lib-table").write_text(
            '(sym_lib_table\n  (version 7)\n  (lib (name "KiCad")(type "Table")(uri "x"))\n'
            '  (lib\n    (name "my_symbols")\n    (type "KiCad")\n'
            '    (uri "${MYLIB_DIR}/my_symbols.kicad_sym")\n  )\n)\n')
        import partsearch.checks as ch
        self.assertEqual(ch._lib_table_uri("sym", "my_symbols"), "${MYLIB_DIR}/my_symbols.kicad_sym")
        self.assertIsNone(ch._lib_table_uri("sym", "nothere"))

    def test_config_dir_follows_kicad_version(self):
        from partsearch import config
        (self.tmp / "kicad" / "9.0").mkdir()
        self.assertEqual(config.kicad_config_dir(9).name, "9.0")
        self.assertEqual(config.kicad_config_dir(None).name, "10.0")
        self.assertEqual(config.kicad_config_dir(11).name, "10.0")      # unknown version: newest


SYM_TABLE = ('(sym_lib_table\r\n\t(version 7)\r\n\t(lib (name "KiCad") (type "Table") (uri "C:/x/sym-lib-table") '
             '(options "") (descr "Türkçe açıklama"))\r\n)\r\n')
FP_TABLE = '(fp_lib_table\n\t(version 7)\n)\n'


class SetupTest(KiCadConfig):
    def settings(self):
        return Settings(library_dir=str(self.tmp / "lib"))

    def write_kicad(self, common=None):
        (self.cfg / "sym-lib-table").write_bytes(SYM_TABLE.encode("utf-8"))
        (self.cfg / "fp-lib-table").write_text(FP_TABLE, encoding="utf-8")
        (self.cfg / "kicad_common.json").write_text(json.dumps(common or {"environment": {"vars": None},
                                                                          "other": {"keep": 1}}), encoding="utf-8")

    def test_fresh_setup_plan_apply_and_idempotent(self):
        from partsearch import setup_kicad as sk
        self.write_kicad()
        plan = sk.register_plan(self.settings())
        self.assertEqual(plan.problems, [])
        self.assertEqual(len(plan.changes), 6)          # folder, symbol lib, footprint lib, variable, 2 tables
        done = sk.register_apply(plan, self.tmp / "backup")
        self.assertEqual(sum(1 for d in done if d.startswith("backup")), 3)
        sym = (self.cfg / "sym-lib-table").read_bytes().decode("utf-8")
        self.assertTrue(sym.startswith(SYM_TABLE[:-5]))                  # old content byte-identical (CRLF kept)
        self.assertIn('(name "my_symbols") (type "KiCad") (uri "${MYLIB_DIR}/my_symbols.kicad_sym")', sym)
        self.assertTrue(sym.endswith(")\r\n"))
        self.assertEqual(sym.count("\r\n"), sym.count("\n"))
        fp = (self.cfg / "fp-lib-table").read_text(encoding="utf-8")
        self.assertIn('(uri "${MYLIB_DIR}/my_footprints.pretty")', fp)
        common = json.loads((self.cfg / "kicad_common.json").read_text(encoding="utf-8"))
        self.assertEqual(common["environment"]["vars"]["MYLIB_DIR"], (self.tmp / "lib").as_posix())
        self.assertEqual(common["other"], {"keep": 1})
        lib = (self.tmp / "lib" / "my_symbols.kicad_sym").read_text(encoding="utf-8")
        self.assertTrue(sexpr.balanced(lib) and "(kicad_symbol_lib" in lib)
        self.assertTrue((self.tmp / "lib" / "my_footprints.pretty").is_dir())
        # the checks agree, and a second run has nothing left to do
        from partsearch import checks
        bad = [r for r in checks.run_checks(self.settings()) if r["name"] in
               ("KiCad path variable", "Symbol library table", "Footprint library table") and r["ok"] is not True]
        self.assertEqual(bad, [])
        again = sk.register_plan(self.settings())
        self.assertEqual((again.changes, again.problems), ([], []))

    def test_never_creates_tables_or_overrides_user_entries(self):
        from partsearch import setup_kicad as sk
        plan = sk.register_plan(self.settings())         # KiCad never started: no tables, no kicad_common.json
        self.assertFalse(any(c.path.name.endswith("lib-table") for c in plan.changes))
        self.assertEqual(len(plan.problems), 3)
        self.write_kicad({"environment": {"vars": {"MYLIB_DIR": "D:/elsewhere"}}})
        (self.cfg / "fp-lib-table").write_text('(fp_lib_table\n\t(lib (name "my_footprints")(type "KiCad")'
                                               '(uri "D:/other.pretty"))\n)\n', encoding="utf-8")
        plan = sk.register_plan(self.settings())
        names = [c.path.name for c in plan.changes]
        self.assertNotIn("kicad_common.json", names)                    # existing variable is never changed
        self.assertNotIn("fp-lib-table", names)                         # existing nickname is never changed
        self.assertIn("sym-lib-table", names)
        self.assertEqual(len(plan.problems), 2)

    def test_symbol_header_matches_kicad_version(self):
        self.assertIn("(version 20241209)", library.sym_header(9))
        self.assertIn("(version 20251024)", library.sym_header(10))
        self.assertIn('(generator_version "9.0")', library.sym_header(9))
        self.assertEqual(library.sym_header(None), library.SYM_HEADER)

    def test_pinned_requirement_is_the_same_everywhere(self):
        from partsearch import setup_kicad as sk
        req = (HERE.parent / "kicad_plugin" / "requirements.txt").read_text(encoding="utf-8")
        flat = " ".join(line.strip(" \\") for line in req.splitlines() if line and not line.startswith("#"))
        self.assertEqual(" ".join(flat.split()), " ".join(sk.EASYEDA_REQUIREMENT.split()))


class I18nTest(unittest.TestCase):
    def test_turkish_complete_and_formats_match(self):
        import ast
        import re
        keys = set()
        for f in (HERE.parent / "partsearch").rglob("*.py"):
            for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "T" and n.args \
                        and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                    keys.add(n.args[0].value)
        tr = i18n.LANGUAGES["tr"]["strings"]
        self.assertEqual(sorted(k for k in keys if k not in tr), [])
        fmt = re.compile(r"%(?:\.\d+)?[sdf]")
        self.assertEqual([k for k, v in tr.items() if fmt.findall(k) != fmt.findall(v)], [])
        i18n.set_language("tr")
        self.assertEqual(i18n.T("Search"), "Ara")
        i18n.set_language("xx")
        self.assertEqual(i18n.T("Search"), "Search")


if __name__ == "__main__":
    unittest.main()
