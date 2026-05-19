#!/usr/bin/env python3
"""Build governance/register_slices/signals_py_1_1422.csv — chunk-1 walk."""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS, RegisterRow

DICT_PATH = ROOT / "schwab_field_inventory" / "schwab_field_dictionary.csv"
SLICE = ROOT / "governance/register_slices/signals_py_1_1422.csv"
_CITE_RE = re.compile(r"CSV row (\d+) \(canonical_field=([^)]+)\)")
TRACE = "CLAUDE chunk-1 disposition signals.py 1-1422"
PATH = "signals.py"
LO, HI = 1, 1422
ANCHOR = "line anchored HEAD d3f0ce8 signals.py trunk; fusion_policy sub-walk d3f0ce8+"


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
    (64, "_unavailable_model_namespace", zero("_unavailable_model_namespace")),
    (95, "canonical_forecast_from_fusion", zero("canonical_forecast")),
    (150, "_debug_canonical_override", zero("_debug_canonical_override")),
    (167, "_pred_override_allowed", zero("_pred_override_allowed")),
    (171, "_live_model_stack_horizons", zero("_live_model_stack_horizons")),
    (203, "_log_decision_bundle", zero("_log_decision_bundle")),
    (249, "_build_calibration_payload", zero("_build_calibration_payload")),
    (292, "_spot_for_mc_fusion_adjustment", zero("_spot_for_mc_fusion_adjustment")),
    (314, "_run_model_stack", zero("_run_model_stack")),
    (562, "compute_fusion_policy_flat_for_replay", zero("compute_fusion_policy_flat_for_replay")),
    (722, "_build_stack_decision_path", zero("stack_decision_path")),
    (741, "stack stage XGBoost", zero("stack_decision_path")),
    (758, "stack stage Monte Carlo", zero("stack_decision_path")),
    (832, "stack stage Fusion", zero("stack_decision_path")),
    (858, "stack stage Final Call", zero("stack_decision_path")),
    (867, "StackDecisionPath return", zero("stack_decision_path")),
    (881, "_build_snapshot_dict", zero("_build_snapshot_dict")),
    (935, "compute_signals public API", zero("compute_signals")),
    (961, "_compute_signals_impl", zero("_compute_signals_impl")),
    (1218, "ml_bundle fusion_policy_snapshot_cols", zero("fusion_policy_snapshot_cols")),
    (1233, "ml_bundle stack_integrity_events", zero("stack_integrity_events")),
    (1409, "SignalOutput emission", zero("SignalOutput")),
]

FORMAL_PASS_THROUGH: list[tuple[int, str, str]] = [
    (107, "fusion.prob_up/down/flat", "PASS_THROUGH bayesian_fusion"),
    (132, "fusion.dominant_direction", "PASS_THROUGH bayesian_fusion"),
    (136, "fusion.fusion_confidence", "PASS_THROUGH bayesian_fusion"),
    (220, "canonical fields in log payload", "PASS_THROUGH self-derived"),
    (320, "rules.signal direction_hint", "PASS_THROUGH rules_engine"),
    (348, "inp.ticker / rules.signal", "PASS_THROUGH SignalInput"),
    (480, "inp.iv_level", "PASS_THROUGH SignalInput"),
    (483, "regime.primary", "PASS_THROUGH regime_engine"),
    (486, "regime.confidence", "PASS_THROUGH regime_engine"),
    (511, "inp.em_upper / em_lower", "PASS_THROUGH SignalInput"),
    (728, "model stack stage outputs", "PASS_THROUGH ml_predict"),
    (750, "mc_out fields", "PASS_THROUGH monte_carlo"),
    (836, "fusion stage fields", "PASS_THROUGH bayesian_fusion"),
    (859, "call.signal / conviction", "PASS_THROUGH call_engine"),
    (886, "snapshot dict rules/pred/call fields", "PASS_THROUGH upstream engines"),
    (1007, "vol_regime", "PASS_THROUGH volatility_regime"),
    (1066, "build_fusion_tick_cache", "PASS_THROUGH bayesian_fusion"),
    (1262, "compute_prediction_core", "PASS_THROUGH prediction_engine"),
    (1289, "compute_multi_horizon_synthesis", "PASS_THROUGH multi_horizon_decision"),
    (1290, "compute_call", "PASS_THROUGH call_engine"),
    (1333, "finalize_multi_horizon_bundle", "PASS_THROUGH multi_horizon_decision"),
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
    for line, surf, note in FORMAL_PASS_THROUGH:
        row = _synth_row(line, col, "FORMAL_PASS_THROUGH", surf, "PASS_THROUGH", notes=note)
        col += 1
        out_by_id[row["register_id"]] = row

    col = 400
    for line in range(LO, HI + 1):
        if line in FORMAL_LINES:
            continue
        row = _synth_row(line, col, "FORMAL_NMD", f"L{line}", "NOT_MARKET_DATA", notes="orchestration")
        col += 1
        out_by_id[row["register_id"]] = row

    out_rows = sorted(out_by_id.values(), key=lambda r: (int(r["line"]), int(r["col"])))
    SLICE.parent.mkdir(parents=True, exist_ok=True)
    with SLICE.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerows(out_rows)
    _rt = list(csv.DictReader(SLICE.open(encoding="utf-8", newline="")))
    if len(_rt) != len(out_rows):
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
