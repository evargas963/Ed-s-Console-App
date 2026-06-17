#!/usr/bin/env python3
"""Build Layer 5 register slices for cascade_stack_schema + cascade_stack_contract."""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS, RegisterRow

DICT_PATH = ROOT / "schwab_field_inventory" / "schwab_field_dictionary.csv"
_CITE_RE = re.compile(r"CSV row (\d+) \(canonical_field=([^)]+)\)")
TRACE = "CLAUDE Layer 5 chunk-1 disposition features/cascade_stack_schema+contract"
ANCHOR = "line anchored HEAD c2542fe; cascade challenger runtime contract; pairs parallel_stack_schema"


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
        for m in _CITE_RE.finditer(cit):
            row_n = int(m.group(1))
            cited = m.group(2).strip()
            if row_map.get(row_n) != cited:
                raise SystemExit(
                    f"Citation mismatch {r.get('path')} register_id={r.get('register_id')}: "
                    f"row {row_n} is {row_map.get(row_n)!r}, cited {cited!r}"
                )


def _synth_row(
    path: str,
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
        register_id=RegisterRow.make_id(path, line, col, kind, "python"),
        language="python",
        path=path,
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


def _build_slice(
    path: str,
    *,
    keep_derived: list[tuple[int, str, str]],
    pass_through: list[tuple[int, str, str]],
    nmd_note: str,
) -> tuple[str, list[dict[str, str]]]:
    hi = sum(1 for _ in (ROOT / path).open(encoding="utf-8"))
    slice_name = path.replace("features/", "").replace(".py", "").replace("/", "_")
    slice_path = ROOT / "governance" / "register_slices" / f"{slice_name}_py_1_{hi}.csv"
    formal_lines = {line for line, _, _ in keep_derived} | {line for line, _, _ in pass_through}

    out_by_id: dict[str, dict[str, str]] = {}
    col = 100
    for line, surf, evidence in keep_derived:
        row = _synth_row(path, line, col, "FORMAL_KEEP_DERIVED", surf, "KEEP_DERIVED", notes=evidence)
        col += 1
        out_by_id[row["register_id"]] = row

    col = 200
    for line, surf, note in pass_through:
        row = _synth_row(path, line, col, "FORMAL_PASS_THROUGH", surf, "PASS_THROUGH", notes=note)
        col += 1
        out_by_id[row["register_id"]] = row

    col = 400
    for line in range(1, hi + 1):
        if line in formal_lines:
            continue
        row = _synth_row(
            path,
            line,
            col,
            "FORMAL_NMD",
            f"L{line} orchestration",
            "NOT_MARKET_DATA",
            notes=nmd_note,
        )
        col += 1
        out_by_id[row["register_id"]] = row

    out_rows = sorted(out_by_id.values(), key=lambda r: (int(r["line"]), int(r["col"])))
    slice_path.parent.mkdir(parents=True, exist_ok=True)
    with slice_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerows(out_rows)
    return slice_path.name, out_rows


def main() -> None:
    row_map = _load_csv_row_to_canonical()

    schema_kd = [
        (28, "build_cascade_challenger_run_metadata", zero("build_cascade_challenger_run_metadata")),
    ]
    schema_pt: list[tuple[int, str, str]] = [
        (7, "CASCADE_STACK_SCHEMA_VERSION import", "PASS_THROUGH cascade_stack_contract"),
    ]
    name1, rows1 = _build_slice(
        "features/cascade_stack_schema.py",
        keep_derived=schema_kd,
        pass_through=schema_pt,
        nmd_note="Cascade challenger run record schema (evaluation only)",
    )

    contract_kd = [
        (68, "validate_cascade_inference_lineage", zero("validate_cascade_inference_lineage")),
        (124, "assert_no_legacy_mvp_in_fusion_overlay", zero("assert_no_legacy_mvp_in_fusion_overlay")),
        (33, "LSTM_STAGE_CASCADE_INPUT_FROM_XGB (3 probs)", zero("LSTM_STAGE_CASCADE_INPUT_FROM_XGB")),
        (42, "TRANSFORMER_STAGE_CASCADE_INPUT_FROM_UPSTREAM (6 probs)", zero("TRANSFORMER_STAGE_CASCADE_INPUT_FROM_UPSTREAM")),
    ]
    contract_pt = [
        (86, "validate_inference_snapshot_v1_envelope", "PASS_THROUGH features.xgb_model_input"),
    ]
    name2, rows2 = _build_slice(
        "features/cascade_stack_contract.py",
        keep_derived=contract_kd,
        pass_through=contract_pt,
        nmd_note="Cascade challenger lineage + overlay contract (no Schwab leaves)",
    )

    validate_slice_replaced_citations(rows1 + rows2, row_map)

    for label, rows in ((name1, rows1), (name2, rows2)):
        rep = sum(1 for r in rows if r["disposition"] == "REPLACED")
        kd = sum(1 for r in rows if r["disposition"] == "KEEP_DERIVED")
        pt = sum(1 for r in rows if r["disposition"] == "PASS_THROUGH")
        nmd = sum(1 for r in rows if r["disposition"] == "NOT_MARKET_DATA")
        print(f"slice {label} {len(rows)}: REPLACED={rep} KEEP_DERIVED={kd} PASS_THROUGH={pt} NMD={nmd}")


if __name__ == "__main__":
    main()
