"""Markdown fences — V3 G1."""

from __future__ import annotations

import re

from .python_scanner import scan_python_source
from .schwab_csv import SchwabCsvIndex

_FENCE = re.compile(r"^```(\w*)\n(.*?)^```", re.MULTILINE | re.DOTALL)


def scan_markdown_file(
    rel: str,
    text: str,
    idx: SchwabCsvIndex,
    syn: dict,
) -> tuple[list[RegisterRow], bool]:
    rows: list[RegisterRow] = []
    for m in _FENCE.finditer(text):
        lang = (m.group(1) or "").strip().lower()
        body = m.group(2)
        if lang in {"", "python", "py"}:
            inner = f"{rel}::fence"
            rows.extend(scan_python_source(inner, body, idx, syn))
    return rows, True
