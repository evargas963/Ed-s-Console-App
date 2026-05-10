"""Register row schema + CSV writer — V3 (column names unchanged from V2)."""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


REGISTER_COLUMNS = [
    "register_id",
    "language",
    "path",
    "line",
    "col",
    "pattern_kind",
    "surface_form",
    "tokens",
    "csv_candidates",
    "csv_lexical_topk_note",
    "v2_trace",
    "disposition",
    "canonical_field_citation",
    "governed_ref",
    "notes",
]


@dataclass
class RegisterRow:
    register_id: str
    language: str
    path: str
    line: int
    col: int
    pattern_kind: str
    surface_form: str
    tokens: str
    csv_candidates: str
    csv_lexical_topk_note: str
    v2_trace: str
    disposition: str = "UNREVIEWED"
    canonical_field_citation: str = ""
    governed_ref: str = ""
    notes: str = ""

    @staticmethod
    def make_id(path: str, line: int, col: int, pattern_kind: str, language: str) -> str:
        h = hashlib.sha256(
            f"{language}|{path}|{line}|{col}|{pattern_kind}".encode()
        ).hexdigest()[:20]
        return h

    def as_csv_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return {k: d[k] for k in REGISTER_COLUMNS}


def write_register_csv(path: Path, rows: list[RegisterRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r.as_csv_dict())
