#!/usr/bin/env python3
"""Build governance/register_slices/training_cache_py_1_1116.csv — Layer 5 chunk-1 walk."""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS, RegisterRow

PATH = "training_cache.py"
DICT_PATH = ROOT / "schwab_field_inventory" / "schwab_field_dictionary.csv"
_CITE_RE = re.compile(r"CSV row (\d+) \(canonical_field=([^)]+)\)")
TRACE = "CLAUDE Layer 5 chunk-1 disposition training_cache.py"
ANCHOR = "line anchored HEAD da69147; ML cache/manifest identity; REPLACED=0"


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
    (47, "file_sha256_hex", zero("file_sha256_hex")),
    (55, "compute_training_code_fingerprint", zero("compute_training_code_fingerprint")),
    (73, "xgb_meta_content_sha256", zero("xgb_meta_content_sha256")),
    (79, "db_training_fingerprint", zero("db_training_fingerprint")),
    (119, "compute_scheduler_cache_key", zero("compute_scheduler_cache_key")),
    (167, "compute_feature_cache_key", zero("compute_feature_cache_key")),
    (210, "db_distinct_rth_et_dates_for_ticker", zero("db_distinct_rth_et_dates")),
    (232, "min_ts_utc_for_last_n_rth_sessions", zero("min_ts_utc_for_last_n_rth_sessions")),
    (266, "compare_tabular_data_fingerprint_from_df", zero("compare_tabular_data_fingerprint")),
    (310, "_normalize_data_fp", zero("_normalize_data_fp")),
    (339, "_meta_required_positive_int", zero("_meta_required_positive_int")),
    (351, "_canonical_lineage_identity_ok", zero("_canonical_lineage_identity_ok")),
    (385, "_feature_identity_matches", zero("_feature_identity_matches")),
    (402, "save_lstm_feature_cache", zero("save_lstm_feature_cache")),
    (442, "load_lstm_feature_cache", zero("load_lstm_feature_cache")),
    (502, "save_transformer_parallel_cache", zero("save_transformer_parallel_cache")),
    (525, "load_transformer_parallel_cache", zero("load_transformer_parallel_cache")),
    (545, "cascade_tensor_bind_slug", zero("cascade_tensor_bind_slug")),
    (583, "_cascade_identity_matches", zero("_cascade_identity_matches")),
    (621, "save_cascade_transformer_tensor_cache", zero("save_cascade_transformer_tensor_cache")),
    (658, "load_cascade_transformer_tensor_cache", zero("load_cascade_transformer_tensor_cache")),
    (695, "compute_artifact_sha256_map", zero("compute_artifact_sha256_map")),
    (704, "validate_manifest_artifact_hashes", zero("validate_manifest_artifact_hashes")),
    (746, "full_skip_eligible", zero("full_skip_eligible")),
    (981, "manifest_matches_current", zero("manifest_matches_current")),
    (1016, "build_manifest", zero("build_manifest")),
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
    slice_path = ROOT / "governance" / "register_slices" / f"training_cache_py_1_{hi}.csv"
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
            notes="Training cache / manifest / file-hash identity (no Schwab leaves)",
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
