# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""Small facade used by the window, the command line and the tests: one Settings object -> one Context."""
from __future__ import annotations

import os
from pathlib import Path

from . import library, search
from .config import Settings
from .logger import Logger


class Session:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.load()
        self.ctx = library.Context.from_settings(self.settings)

    def reload(self, settings: Settings) -> None:
        self.settings = settings
        self.ctx = library.Context.from_settings(settings)

    def logger(self, echo=print, callback=None) -> Logger:
        return Logger(self.ctx.log_file, echo=echo, callback=callback)

    # search
    def db_path(self) -> Path:
        return self.settings.jlcpcb_db_path()

    def db_info(self) -> dict:
        return search.db_info(self.db_path())

    def search(self, where: str, query: str, basic_only: bool = False, in_stock: bool = False) -> dict:
        s = self.settings
        if where == "local":
            return search.search_local(self.db_path(), query, basic_only, in_stock, s.max_results, s.local_timeout)
        return search.search_online(query, self.ctx.easyeda_python, basic_only, in_stock, s.online_page_size)

    # library
    def prepare(self, lcsc, mode, log, use_cli=True, preview=False, raw_dir=None):
        return library.prepare(self.ctx, lcsc, mode, log, use_cli, preview, raw_dir)

    def commit(self, p, log, use_cli=True):
        return library.commit(self.ctx, p, log, use_cli)

    def lookup_existing(self, lcsc):
        return library.lookup_existing(self.ctx, lcsc)

    def library_index(self):
        return library.library_index(self.ctx)

    def history(self, limit=200):
        return library.history(self.ctx, limit)


def golden_adapter(tmp: Path) -> dict:
    """tests/golden_run.py: the same scenario as against the old tools/ code."""
    s = Settings()
    s.library_dir = os.environ["MYLIB_DIR"]
    s.work_dir = str(tmp / "work")
    ses = Session(s)
    c = ses.ctx
    return dict(prepare=ses.prepare, commit=ses.commit, lookup=ses.lookup_existing, index=ses.library_index,
                history=ses.history, search=lambda q, **kw: ses.search("local", q, **kw),
                SearchError=search.SearchError, logger=lambda: ses.logger(echo=None), sym=c.sym_lib, fp=c.fp_lib,
                models=c.models, reg=c.registry, hist=c.history_dir)
