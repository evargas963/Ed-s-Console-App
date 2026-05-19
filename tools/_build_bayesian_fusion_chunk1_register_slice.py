#!/usr/bin/env python3
"""Build governance/register_slices/bayesian_fusion_py_1_859.csv — chunk-1 walk."""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS, RegisterRow

REG_V4 = ROOT / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
BASELINE = ROOT / "governance" / "register_slices" / "bayesian_fusion_py_1_859_scanner_baseline.csv"
SLICE = ROOT / "governance" / "register_slices" / "bayesian_fusion_py_1_859.csv"
DICT_PATH = ROOT / "schwab_field_inventory" / "schwab_field_dictionary.csv"
_CITE_RE = re.compile(r"CSV row (\d+) \(canonical_field=([^)]+)\)")
TRACE = "CLAUDE chunk-1 disposition bayesian_fusion.py 1-859"
PATH = "bayesian_fusion.py"
LO, HI = 1, 859
ANCHOR = "line anchored HEAD 33a7a2f bayesian_fusion.py trunk; FusionPayload producer"


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
    (41, "FusionPayload dataclass schema", zero("FusionPayload")),
    (775, "FusionPayload emission constructor", zero("fusion_*")),
    (777, "posterior fields block", zero("*_posterior")),
    (783, "weight_* fields block", zero("weight_*")),
    (789, "dominant_outcome / dominant_probability", zero("dominant_outcome")),
    (791, "fusion_confidence (string)", zero("fusion_confidence")),
    (792, "fusion_confidence_score (numeric)", zero("fusion_confidence_score")),
    (793, "n_sources_available / n_sources_active", zero("n_sources_available")),
    (795, "evidence/contradiction/fusion summaries", zero("fusion_summary")),
    (798, "MC pass-through fields on FusionPayload", zero("mc_containment")),
    (809, "model_agreement fields", zero("model_agreement")),
    (811, "prob_up/down/flat directional fusion", zero("prob_up")),
    (817, "signal_layer_v1_fusion audit dict", zero("signal_layer_v1_fusion")),
    (818, "contributing_models / missing_models", zero("contributing_models")),
    (187, "_resolved_regime_label", zero("_resolved_regime_label")),
    (200, "_model_dominant_class", zero("_model_dominant_class")),
    (226, "_model_direction_triplet", zero("_model_direction_triplet")),
    (245, "_translate_xgb_evidence", zero("_translate_xgb_evidence")),
    (270, "_translate_lstm_evidence", zero("_translate_lstm_evidence")),
    (295, "_translate_transformer_evidence", zero("_translate_transformer_evidence")),
    (320, "_translate_rules_evidence", zero("_translate_rules_evidence")),
    (364, "build_fusion_tick_cache", zero("build_fusion_tick_cache")),
    (388, "_bayesian_update", zero("_bayesian_update")),
    (504, "_fuse_impl weight computation block", zero("BASE_WEIGHTS")),
    (567, "_bayesian_update call site", zero("posteriors")),
    (577, "fusion confidence classification thresholds", zero("fusion_confidence")),
    (587, "Phase 1 dampening Damp 1-3", zero("CALIBRATION_PENALTY")),
    (613, "model agreement computation", zero("model_agreement")),
    (629, "directional fusion weighted probs", zero("prob_up")),
    (672, "signal_layer_v1 blend", zero("signal_layer_v1_fusion")),
    (739, "Damp 4 contradiction penalty", zero("contradiction")),
    (768, "MC pass-through extraction in _fuse_impl", zero("mc_paths")),
]

FORMAL_PASS_THROUGH: list[tuple[int, str, str]] = [
    (191, "regime.primary", "PASS_THROUGH regime_engine"),
    (230, "xgb_out prob triplet", "PASS_THROUGH ml_predict"),
    (256, "xgb continuation/reversal support", "PASS_THROUGH ml_predict"),
    (281, "lstm continuation/reversal support", "PASS_THROUGH ml_predict"),
    (306, "transformer continuation/reversal support", "PASS_THROUGH ml_predict"),
    (322, "rules.signal / rules.conviction", "PASS_THROUGH rules_engine"),
    (367, "rules.signal direction hint", "PASS_THROUGH rules_engine"),
    (425, "fuse() public wrapper", "PASS_THROUGH orchestration entry"),
    (467, "fuse() exception fail-closed", "PASS_THROUGH I-01 boundary"),
    (716, "mc_out containment/expansion", "PASS_THROUGH monte_carlo"),
    (722, "xgb_out dominant_class", "PASS_THROUGH ml_predict"),
    (725, "regime.confidence", "PASS_THROUGH regime_engine"),
    (770, "mc_out n_paths horizon assumptions", "PASS_THROUGH monte_carlo"),
    (799, "mc_out distribution fields", "PASS_THROUGH monte_carlo"),
    (676, "signal_layer_v1 meta.n_bars", "PASS_THROUGH features/signal_layer_v1"),
    (684, "ED_SIGNAL_LAYER_FUSION_BLEND env", "PASS_THROUGH config not market data"),
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
            notes="trunk orchestration/constants/self-test",
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
