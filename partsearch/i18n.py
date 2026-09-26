# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""Interface languages. English text is the key; other languages map it to their translation.
Log lines stay English on purpose (they are for bug reports).
Adding a language: copy the TR dict, translate the values, register it in LANGUAGES."""
from __future__ import annotations

_lang = "en"


def set_language(code: str) -> None:
    global _lang
    _lang = code if code in LANGUAGES else "en"


def T(text: str) -> str:
    table = LANGUAGES.get(_lang, {}).get("strings")
    return table.get(text, text) if table else text


TR: dict = {}          # filled in i18n_tr.py
LANGUAGES = {"en": {"name": "English", "strings": None}, "tr": {"name": "Türkçe", "strings": TR}}

try:
    from .i18n_tr import STRINGS as _TR
    TR.update(_TR)
except ImportError:
    pass
