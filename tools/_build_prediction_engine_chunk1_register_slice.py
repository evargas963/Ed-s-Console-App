#!/usr/bin/env python3
"""Build governance/register_slices/prediction_engine_py_1_1249.csv — chunk-1 walk."""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS, RegisterRow

REG_V4 = ROOT / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
BASELINE = ROOT / "governance" / "register_slices" / "prediction_engine_py_1_1249_scanner_baseline.csv"
SLICE = ROOT / "governance" / "register_slices" / "prediction_engine_py_1_1249.csv"
DICT_PATH = ROOT / "schwab_field_inventory" / "schwab_field_dictionary.csv"
_CITE_RE = re.compile(r"CSV row (\d+) \(canonical_field=([^)]+)\)")
TRACE = "CLAUDE chunk-1 disposition prediction_engine.py 1-1249"
PATH = "prediction_engine.py"
LO, HI = 1, 1249
ANCHOR = "line anchored HEAD 3a55cfe prediction_engine.py trunk; PredictiveCard / WTDS producer"


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
    (50, "PredictionEnrichmentState dataclass", zero("PredictionEnrichmentState")),
    (69, "_as_of_ts_utc_for_similarity (SQL lookahead guard)", zero("as_of_ts_utc")),
    (91, "_count_labeled", zero("_count_labeled")),
    (98, "_literal_empirical_horizon (I-01 fail-closed empirical probs)", zero("outcome_5c_prob")),
    (138, "_tri_probs", zero("_tri_probs")),
    (147, "_fusion_snap_triplet (None when fusion incomplete)", zero("_fusion_snap_triplet")),
    (159, "_norm_triplet_floats (degenerate uniform fallback)", zero("_norm_triplet_floats")),
    (167, "_overlay_multi_horizon_ml_on_product_triplets (labeled provenance per hz)", zero("fusion_ml_primary")),
    (254, "_avg_outcome_pts (None below 5 samples)", zero("avg_5c_pts")),
    (261, "_pack_horizon_row (WTDS bar row)", zero("horizon_prob_bars")),
    (293, "_build_horizon_prob_bars (1m/5m/15m/60m)", zero("horizon_prob_bars")),
    (324, "_timeframe_reads (15m/60m structure narrative)", zero("timeframe_reads")),
    (363, "_prediction_headline (legacy narrative)", zero("headline")),
    (420, "_get_all_recent (DB fallback wrapper)", zero("_get_all_recent")),
    (436, "build_fusion_model_overlay_for_stack (~60 overlay keys)", zero("build_fusion_model_overlay")),
    (578, "_empty_prediction (no_database labeled fallback)", zero("no_database")),
    (640, "compute_prediction_core (hot path PredictiveCard)", zero("compute_prediction_core")),
    (886, "compute_prediction_enrichment (cold path headline/model_note)", zero("compute_prediction_enrichment")),
    (958, "reversal_risk from 5c histogram", zero("reversal_risk")),
    (982, "reversal_shortfall + reversal_severity", zero("reversal_shortfall")),
    (1192, "compute_prediction (public API)", zero("compute_prediction")),
]

FORMAL_PASS_THROUGH: list[tuple[int, str, str]] = [
    (462, "inp.refresh_ts_utc + snapshot as_of_ts", "PASS_THROUGH signals.py / inference_snapshot"),
    (465, "db.get_similar_setups", "PASS_THROUGH db.py (not Schwab leaf)"),
    (506, "inp.flow_imbalance / bid_ask_imbalance", "PASS_THROUGH SignalInput (signals.py)"),
    (508, "rules.signal / rules.conviction", "PASS_THROUGH rules_engine (pending walk)"),
    (510, "inp.et_hour / et_minute", "PASS_THROUGH SignalInput"),
    (515, "SignalInput attribute reads for fusion overlay", "PASS_THROUGH signals.py SignalInput"),
    (611, "canonical direction/probability/confidence/provenance", "PASS_THROUGH signals.canonical_forecast_from_fusion"),
    (794, "fusion MC reads (mc_lower_50 / mc_upper_50)", "PASS_THROUGH bayesian_fusion"),
    (869, "ml_bundle movement_head_probs / fusion_policy_snapshot_cols", "PASS_THROUGH signals.py ml_bundle"),
    (920, "eval_metrics_store dashboard metrics", "PASS_THROUGH eval_metrics_store"),
    (1116, "regime/fusion/MC reads for model_note narrative", "PASS_THROUGH regime_engine / bayesian_fusion"),
]

FORMAL_LINES = {line for line, _, _ in FORMAL_KEEP_DERIVED} | {line for line, _, _ in FORMAL_PASS_THROUGH}


def export_baseline() -> None:
    if not REG_V4.is_file():
        print("REG_V4 missing; skipping baseline export")
        return
    rows: list[dict[str, str]] = []
    with REG_V4.open(encoding="utf-8", newline="") as f:
        for raw in csv.DictReader(f):
            if raw.get("path") != PATH:
                continue
            line = int(raw["line"])
            if LO <= line <= HI:
                rows.append(dict(raw))
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    with BASELINE.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"baseline {len(rows)} rows -> {BASELINE.name}")


def _synth_row(
    line: int,
    col: int,
    kind: str,
    surface: str,
    disposition: str,
    *,
    citation: str = "",
    governed_ref: str = "",
    notes: str = "",
) -> dict[str, str]:
    rid = RegisterRow.make_id(PATH, line, col, kind, "python")
    note_full = f"{notes} | {ANCHOR}".strip(" |")
    return RegisterRow(
        register_id=rid,
        language="python",
        path=PATH,
        line=line,
        col=col,
        pattern_kind=kind,
        surface_form=surface,
        tokens=surface[:80].replace(" ", "_"),
        csv_candidates=citation.split(";")[0].strip() if citation else "",
        csv_lexical_topk_note="",
        v2_trace=TRACE,
        disposition=disposition,
        canonical_field_citation=citation,
        governed_ref=governed_ref,
        notes=note_full,
    ).as_csv_dict()


def main() -> None:
    if not BASELINE.is_file() and "--export-baseline" in sys.argv:
        export_baseline()
    elif not BASELINE.is_file():
        print("no baseline (pass --export-baseline to stream from REG_V4); synth NMD for uncovered lines")

    row_map = _load_csv_row_to_canonical()
    validate_formal_replaced_citations(row_map)

    out_by_id: dict[str, dict[str, str]] = {}
    if BASELINE.is_file():
        for raw in csv.DictReader(BASELINE.open(encoding="utf-8", newline="")):
            line = int(raw["line"])
            if not (LO <= line <= HI):
                continue
            row = dict(raw)
            row["disposition"] = "NOT_MARKET_DATA"
            row["governed_ref"] = ""
            row["canonical_field_citation"] = ""
            row["v2_trace"] = TRACE
            row["notes"] = row.get("notes") or "chunk-1 scanner baseline NMD"
            out_by_id[row["register_id"]] = row

    lines_with_baseline = {int(r["line"]) for r in out_by_id.values()}

    col = 0
    for line, surf, citation, notes in FORMAL_REPLACED:
        row = _synth_row(line, col, "FORMAL_REPLACED", surf, "REPLACED", citation=citation, notes=notes)
        col += 1
        out_by_id[row["register_id"]] = row

    col = 100
    for line, surf, evidence in FORMAL_KEEP_DERIVED:
        row = _synth_row(line, col, "FORMAL_KEEP_DERIVED", surf, "KEEP_DERIVED", notes=evidence)
        col += 1
        out_by_id[row["register_id"]] = row

    col = 200
    for line, surf, note in FORMAL_PASS_THROUGH:
        row = _synth_row(line, col, "FORMAL_PASS_THROUGH", surf, "PASS_THROUGH", notes=note)
        col += 1
        out_by_id[row["register_id"]] = row

    col = 400
    for line in range(LO, HI + 1):
        if line in FORMAL_LINES:
            continue
        if line in lines_with_baseline:
            continue
        row = _synth_row(
            line,
            col,
            "FORMAL_NMD",
            f"L{line} orchestration",
            "NOT_MARKET_DATA",
            notes="trunk orchestration/constants/display formatting",
        )
        col += 1
        out_by_id[row["register_id"]] = row

    out_rows = sorted(out_by_id.values(), key=lambda r: (int(r["line"]), int(r["col"])))
    SLICE.parent.mkdir(parents=True, exist_ok=True)
    with SLICE.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerows(out_rows)
    _rt = list(csv.DictReader(SLICE.open(encoding="utf-8", newline="")))
    if len(_rt) != len(out_rows) or any(len(r) != len(REGISTER_COLUMNS) for r in _rt):
        raise SystemExit("slice CSV round-trip failed")
    validate_slice_replaced_citations(_rt, row_map)

    rep = sum(1 for r in out_rows if r["disposition"] == "REPLACED")
    kd = sum(1 for r in out_rows if r["disposition"] == "KEEP_DERIVED")
    pt = sum(1 for r in out_rows if r["disposition"] == "PASS_THROUGH")
    nmd = sum(1 for r in out_rows if r["disposition"] == "NOT_MARKET_DATA")
    print(f"slice {len(out_rows)}: REPLACED={rep} KEEP_DERIVED={kd} PASS_THROUGH={pt} NMD={nmd}")
    if out_rows:
        lines = [int(r["line"]) for r in out_rows]
        print(f"line range min={min(lines)} max={max(lines)}")


if __name__ == "__main__":
    main()
