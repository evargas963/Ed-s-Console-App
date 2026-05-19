#!/usr/bin/env python3
"""Build governance/register_slices/xgb_model_input_py_1_151.csv — Layer 5 chunk-1 walk (slice-only)."""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS, RegisterRow

SLICE = ROOT / "governance" / "register_slices" / "xgb_model_input_py_1_151.csv"
DICT_PATH = ROOT / "schwab_field_inventory" / "schwab_field_dictionary.csv"
_CITE_RE = re.compile(r"CSV row (\d+) \(canonical_field=([^)]+)\)")
TRACE = "CLAUDE Layer 5 chunk-1 disposition features/xgb_model_input.py 1-151"
PATH = "features/xgb_model_input.py"
LO, HI = 1, 151
ANCHOR = (
    "line anchored HEAD 85c2117; InferenceSnapshotV1 XGB tabular path; "
    "FIND-XGB1/XGB2 disclosed slice-only pending ml_predict caller audit"
)


def zero(symbol: str) -> str:
    return f"CSV grep zero hits for {symbol}"


def _load_csv_row_to_canonical() -> dict[int, str]:
    out: dict[int, str] = {}
    with DICT_PATH.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for line_no, row in enumerate(reader, start=2):
            out[line_no] = (row["canonical_field"] or "").strip()
    return out


def validate_citation_text(text: str, row_map: dict[int, str], *, context: str) -> None:
    for m in _CITE_RE.finditer(text):
        row_n = int(m.group(1))
        cited = m.group(2).strip()
        actual = row_map.get(row_n)
        if actual != cited:
            raise SystemExit(
                f"Citation row mismatch [{context}]: CSV row {row_n} is {actual!r}, "
                f"cited canonical_field={cited!r}"
            )


def validate_formal_replaced_citations(row_map: dict[int, str]) -> None:
    for line, surf, citation, _notes in FORMAL_REPLACED:
        validate_citation_text(citation, row_map, context=f"L{line} {surf}")


def validate_slice_replaced_citations(rows: list[dict[str, str]], row_map: dict[int, str]) -> None:
    for r in rows:
        if r.get("disposition") != "REPLACED":
            continue
        cit = r.get("canonical_field_citation") or ""
        if not cit or "CSV row " not in cit:
            continue
        validate_citation_text(
            cit,
            row_map,
            context=f"slice register_id={r.get('register_id')} L{r.get('line')}",
        )


FORMAL_REPLACED: list[tuple[int, str, str, str]] = []

FORMAL_KEEP_DERIVED: list[tuple[int, str, str]] = [
    (27, "CANONICAL_TO_XGB_TABULAR canonical→legacy mapping", zero("CANONICAL_TO_XGB_TABULAR")),
    (47, "validate_inference_snapshot_v1_envelope", zero("validate_inference_snapshot_v1_envelope")),
    (73, "validate_inference_snapshot_v1_for_xgb", zero("validate_inference_snapshot_v1_for_xgb")),
    (90, "_et_from_ts_utc", zero("_et_from_ts_utc")),
    (95, "inference_snapshot_v1_to_engineering_snapshot", zero("inference_snapshot_v1_to_engineering_snapshot")),
    (119, "merge_xgb_fusion_overlay", zero("merge_xgb_fusion_overlay")),
    (137, "assert_not_raw_l1_payload boundary guard", zero("assert_not_raw_l1_payload")),
]

FORMAL_PASS_THROUGH: list[tuple[int, str, str]] = [
    (28, "price.spot → spot", "PASS_THROUGH canonical MVP feature name"),
    (29, "price.spread_pts → spread", "PASS_THROUGH canonical MVP feature name"),
    (30, "structure.zone → zone", "PASS_THROUGH canonical MVP feature name"),
    (31, "structure.nearest_above_dist", "PASS_THROUGH canonical MVP feature name"),
    (32, "structure.nearest_below_dist", "PASS_THROUGH canonical MVP feature name"),
    (33, "structure.net_gamma → net_gamma", "PASS_THROUGH canonical MVP feature name"),
    (34, "anchor.vwap_side → vwap_side", "PASS_THROUGH canonical MVP feature name"),
    (35, "anchor.vwap_dist_pts → vwap_dist_pts", "PASS_THROUGH canonical MVP feature name"),
    (36, "liquidity.absorption_score", "PASS_THROUGH canonical MVP feature name"),
    (37, "liquidity.continuation_score", "PASS_THROUGH canonical MVP feature name"),
]

FORMAL_LINES = {line for line, _, _ in FORMAL_KEEP_DERIVED} | {line for line, _, _ in FORMAL_PASS_THROUGH}


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
    row_map = _load_csv_row_to_canonical()
    validate_formal_replaced_citations(row_map)

    out_by_id: dict[str, dict[str, str]] = {}
    col = 100
    for line, surf, evidence in FORMAL_KEEP_DERIVED:
        row = _synth_row(line, col, "FORMAL_KEEP_DERIVED", surf, "KEEP_DERIVED", notes=evidence)
        col += 1
        out_by_id[row["register_id"]] = row

    col = 200
    for line, surf, evidence in FORMAL_PASS_THROUGH:
        row = _synth_row(line, col, "FORMAL_PASS_THROUGH", surf, "PASS_THROUGH", notes=evidence)
        col += 1
        out_by_id[row["register_id"]] = row

    col = 400
    for line in range(LO, HI + 1):
        if line in FORMAL_LINES:
            continue
        row = _synth_row(
            line,
            col,
            "FORMAL_NMD",
            f"L{line} orchestration",
            "NOT_MARKET_DATA",
            notes="XGB InferenceSnapshotV1 adapter (no Schwab leaves)",
        )
        col += 1
        out_by_id[row["register_id"]] = row

    out_rows = sorted(out_by_id.values(), key=lambda r: (int(r["line"]), int(r["col"])))
    validate_slice_replaced_citations(out_rows, row_map)

    SLICE.parent.mkdir(parents=True, exist_ok=True)
    with SLICE.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerows(out_rows)

    rep = sum(1 for r in out_rows if r["disposition"] == "REPLACED")
    kd = sum(1 for r in out_rows if r["disposition"] == "KEEP_DERIVED")
    pt = sum(1 for r in out_rows if r["disposition"] == "PASS_THROUGH")
    nmd = sum(1 for r in out_rows if r["disposition"] == "NOT_MARKET_DATA")
    print(f"slice {len(out_rows)}: REPLACED={rep} KEEP_DERIVED={kd} PASS_THROUGH={pt} NMD={nmd}")


if __name__ == "__main__":
    main()
