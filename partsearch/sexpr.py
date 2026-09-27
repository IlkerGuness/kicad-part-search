# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 İlker Güneş (Zogolder)
"""Minimal helpers for KiCad s-expression text (symbol libraries and footprints).

Only what the importer needs: balance check, top-level child spans, symbol blocks and property values.
Strings are skipped correctly, so parentheses inside quoted text never confuse the parser.
"""
from __future__ import annotations

import re

SYM_RE = re.compile(r'^\(symbol\s+"((?:[^"\\]|\\.)*)"')


def _skip_string(s: str, i: int) -> int:
    """i points at an opening quote; return the index after the closing quote."""
    i += 1
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == '"':
            return i + 1
        i += 1
    raise ValueError("unterminated string")


def balanced(s: str) -> bool:
    depth, i, n = 0, 0, len(s)
    while i < n:
        c = s[i]
        if c == '"':
            i = _skip_string(s, i)
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0


def top_level_children(s: str) -> list[tuple[int, int]]:
    """(start, end) spans of the direct children of the root list."""
    spans, depth, i, start, n = [], 0, 0, None, len(s)
    while i < n:
        c = s[i]
        if c == '"':
            i = _skip_string(s, i)
            continue
        if c == "(":
            depth += 1
            if depth == 2:
                start = i
        elif c == ")":
            if depth == 2 and start is not None:
                spans.append((start, i + 1))
                start = None
            depth -= 1
        i += 1
    return spans


def symbol_blocks(text: str) -> dict[str, str]:
    """Top-level symbols of a .kicad_sym file: name -> full block text."""
    out = {}
    for a, b in top_level_children(text):
        m = SYM_RE.match(text[a:b])
        if m:
            out[m.group(1)] = text[a:b]
    return out


def replace_or_append_symbol(lib_text: str, name: str, block: str) -> str:
    for a, b in top_level_children(lib_text):
        m = SYM_RE.match(lib_text[a:b])
        if m and m.group(1) == name:
            return lib_text[:a] + block + lib_text[b:]
    end = lib_text.rstrip().rfind(")")
    return lib_text[:end].rstrip() + "\n\t" + block.strip() + "\n)\n"


def prop_value(block: str, key: str) -> str:
    m = re.search(r'\(property\s+"%s"\s+"((?:[^"\\]|\\.)*)"' % re.escape(key), block)
    return m.group(1) if m else ""


def count_pins(block: str) -> int:
    return len(re.findall(r"\(pin\s+\w+\s+\w+", block))


def count_pads(fp_text: str) -> int:
    return len(re.findall(r'\(pad\s+"?[^\s"]*"?\s+(?:smd|thru_hole|np_thru_hole|connect)', fp_text))
