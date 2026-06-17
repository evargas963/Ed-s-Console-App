#!/usr/bin/env python3
"""Build governance/register_slices/stack_integrity_v1_py_1_*.csv — Layer 5 chunk-1 walk."""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS, RegisterRow

PATH = "features/stack_integrity_v1.py"
DICT_PATH = ROOT / "schwab_field_inventory" / "schwab_field_dictionary.csv"
_CITE_RE = re.compile(r"CSV row (\d+) \(canonical_field=([^)]+)\)")
TRACE = "CLAUDE Layer 5 chunk-1 disposition features/stack_integrity_v1.py"
ANCHOR = "line anchored HEAD d61e8e2; parallel-runtime degradation audit; pairs parallel_stack_schema"


def zero(symbol: str) -> str:
    return f"CSV grep zero hits for {symbol}"


def _load_csv_row_to_canonical() -> dict[int, str]:
    out: dict[int, str] = {}
    with DICT_PATH.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for line_no, row in enumerate(reader, start=2):
            out[line_no] = (row["canonical_field"] or "").strip()
    return out


def validate_slice_replaced_citations(rows: list[dict[str, str]], row_map: dict[int, str]) -> None:
    for r in rows:
        if r.get("disposition") != "REPLACED":
            continue
        cit = r.get("canonical_field_citation") or ""
        if not cit or "CSV row " not in cit:
            continue
        for m in _CITE_RE.finditer(cit):
            row_n = int(m.group(1))
            cited = m.group(2).strip()
            if row_map.get(row_n) != cited:
                raise SystemExit(
                    f"Citation mismatch register_id={r.get('register_id')}: "
                    f"row {row_n} is {row_map.get(row_n)!r}, cited {cited!r}"
                )


FORMAL_KEEP_DERIVED: list[tuple[int, str, str]] = [
    (15, "record_stack_degradation", zero("record_stack_degradation")),
    (45, "merge_stack_integrity_events", zero("merge_stack_integrity_events")),
    (55, "finalize_stack_integrity_v1", zero("finalize_stack_integrity_v1")),
]

FORMAL_LINES = {line for line, _, _ in FORMAL_KEEP_DERIVED}


def _synth_row(
    line: int,
    col: int,
    kind: str,
    surface: str,
    disposition: str,
    *,
    notes: str = "",
) -> dict[str, str]:
    note_full = f"{notes} | {ANCHOR}".strip(" |")
    return RegisterRow(
        register_id=RegisterRow.make_id(PATH, line, col, kind, "python"),
        language="python",
        path=PATH,
        line=line,
        col=col,
        pattern_kind=kind,
        surface_form=surface,
        tokens=surface[:80].replace(" ", "_"),
        csv_candidates="",
        csv_lexical_topk_note="",
        v2_trace=TRACE,
        disposition=disposition,
        canonical_field_citation="",
        governed_ref="",
        notes=note_full,
    ).as_csv_dict()


def main() -> None:
    hi = sum(1 for _ in (ROOT / PATH).open(encoding="utf-8"))
    slice_path = ROOT / "governance" / "register_slices" / f"stack_integrity_v1_py_1_{hi}.csv"
    row_map = _load_csv_row_to_canonical()

    out_by_id: dict[str, dict[str, str]] = {}
    col = 100
    for line, surf, evidence in FORMAL_KEEP_DERIVED:
        row = _synth_row(line, col, "FORMAL_KEEP_DERIVED", surf, "KEEP_DERIVED", notes=evidence)
        col += 1
        out_by_id[row["register_id"]] = row

    col = 400
    for line in range(1, hi + 1):
        if line in FORMAL_LINES:
            continue
        row = _synth_row(
            line,
            col,
            "FORMAL_NMD",
            f"L{line} orchestration",
            "NOT_MARKET_DATA",
            notes="Stack degradation / integrity audit trail (no Schwab leaves)",
        )
        col += 1
        out_by_id[row["register_id"]] = row

    out_rows = sorted(out_by_id.values(), key=lambda r: (int(r["line"]), int(r["col"])))
    validate_slice_replaced_citations(out_rows, row_map)

    slice_path.parent.mkdir(parents=True, exist_ok=True)
    with slice_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerows(out_rows)

    rep = sum(1 for r in out_rows if r["disposition"] == "REPLACED")
    kd = sum(1 for r in out_rows if r["disposition"] == "KEEP_DERIVED")
    nmd = sum(1 for r in out_rows if r["disposition"] == "NOT_MARKET_DATA")
    print(f"slice {slice_path.name} {len(out_rows)}: REPLACED={rep} KEEP_DERIVED={kd} NMD={nmd}")


if __name__ == "__main__":
    main()
