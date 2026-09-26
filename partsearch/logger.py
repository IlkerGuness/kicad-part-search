# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""Stage-tagged log file shared by the command line and the window.

Every line: ISO timestamp, [STAGE], message. Stages: CHECK FETCH TRANSFORM VALIDATE PLAN PREVIEW WRITE VERIFY
SEARCH GUI LAUNCH INFO ERROR. The file is opened in append mode and flushed after every line, so a crash never
loses what happened before it.
"""
from __future__ import annotations

import datetime as dt
import threading
from pathlib import Path


class Logger:
    def __init__(self, path: Path, echo=print, callback=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._fh = open(path, "a", encoding="utf-8")
        self._echo = echo
        self._cb = callback
        self._lock = threading.Lock()          # worker threads and the GUI thread both write

    def _emit(self, line: str) -> None:
        with self._lock:
            if self._fh.closed:                # e.g. a late worker result after the window closed
                return
            self._fh.write(line + "\n")
            self._fh.flush()
        if self._echo:
            self._echo(line)
        if self._cb:
            self._cb(line)

    def __call__(self, stage: str, msg: str) -> None:
        self._emit("%s [%-9s] %s" % (dt.datetime.now().isoformat(timespec="seconds"), stage, msg))

    def banner(self, text: str) -> None:
        self._emit(text)

    def close(self) -> None:
        with self._lock:
            self._fh.close()
