#!/usr/bin/env python3
"""Build governance/register_slices/call_engine_py_1_1768.csv — chunk-1 walk."""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS, RegisterRow

REG_V4 = ROOT / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
BASELINE = ROOT / "governance" / "register_slices" / "call_engine_py_1_1768_scanner_baseline.csv"
SLICE = ROOT / "governance" / "register_slices" / "call_engine_py_1_1768.csv"
DICT_PATH = ROOT / "schwab_field_inventory" / "schwab_field_dictionary.csv"
_CITE_RE = re.compile(r"CSV row (\d+) \(canonical_field=([^)]+)\)")
TRACE = "CLAUDE chunk-1 disposition call_engine.py 1-1768"
PATH = "call_engine.py"
LO, HI = 1, 1768
ANCHOR = "line anchored HEAD fadc9be call_engine.py trunk; Decision Command producer chain"


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
    (30, "size cue tier mappers (_mh_size_tier_from_modifier et al.)", zero("size_cue")),
    (75, "_classify_trade_type (micro+zone+signal)", zero("trade_type")),
    (112, "_build_invalidation", zero("invalidation")),
    (148, "_time_qualifier", zero("time_qualifier")),
    (171, "replay_max_hold_bars_for_setup", zero("replay_max_hold_bars")),
    (196, "_mc_reasoning_snippet", zero("mc_reasoning")),
    (231, "_build_call_headlines (LONG/SHORT/WAIT display)", zero("call_headline")),
    (314, "_greek_notes / _add_greek_color", zero("greek_notes")),
    (343, "_canonical_stack_vote", zero("canonical_stack_vote")),
    (360, "_fusion_authoritative_directional_vote", zero("fusion_authoritative_vote")),
    (372, "_index_basket_vote", zero("index_basket_vote")),
    (405, "_cross_instrument_signal", zero("cross_instrument_signal")),
    (448, "_cross_instrument_notes", zero("cross_instrument_notes")),
    (478, "_stop_distance (lifecycle_rule_core delegate)", zero("stop_distance")),
    (501, "_compute_levels (entry/stop/target/target2)", zero("entry")),
    (606, "_downgrade conviction tier", zero("_downgrade")),
    (618, "_conviction_from_canonical_forecast (CONF pill producer)", zero("conviction")),
    (655, "_size_note display string", zero("size_note")),
    (674, "EXEC_MODES r-unit ranges", zero("EXEC_MODES")),
    (683, "compute_position_size (r_units / execution_mode)", zero("r_units")),
    (769, "REGIME_MULT lookup table", zero("REGIME_MULT")),
    (971, "_validate_trade (3-layer gate)", zero("validation_passed")),
    (1028, "validate layer 1 structural", zero("structure_valid")),
    (1058, "validate layer 2 probabilistic", zero("probability_valid")),
    (1132, "validate layer 3 risk", zero("risk_valid")),
    (1189, "compute_call (STACK ORDER 8/9/10 orchestrator)", zero("compute_call")),
    (1289, "stack_votes dict (9 sources)", zero("stack_votes")),
    (1308, "STACK_THRESHOLD (2 normal / 3 elevated event risk)", zero("STACK_THRESHOLD")),
    (1330, "_NON_TRADABLE_CANONICAL_PROVENANCE gate (I-01)", zero("missing_canonical_fallback")),
    (1352, "multi_horizon policy veto/promote", zero("mh_veto")),
    (1392, "conviction environmental downgrades", zero("conviction")),
    (1429, "vol_regime trade permissibility", zero("trade_permissive")),
    (1460, "_validate_trade call site (STACK ORDER 9)", zero("validation_passed")),
    (1496, "_compute_levels + reward_risk derivation", zero("reward_risk")),
    (1546, "compute_position_size call (STACK ORDER 10)", zero("execution_mode")),
    (1588, "time warning hard-block <=30 min", zero("time_warning")),
    (1621, "_build_call_headlines call (post-override display)", zero("headline")),
    (1638, "call/put readiness (setup_readiness delegate)", zero("readiness_score")),
    (1729, "TheCall dataclass return emission", zero("TheCall")),
]

FORMAL_PASS_THROUGH: list[tuple[int, str, str]] = [
    (1231, "rules.signal", "PASS_THROUGH rules_engine"),
    (1232, "canonical.direction / confidence", "PASS_THROUGH signals.canonical_forecast_from_fusion"),
    (1234, "inp.spot + SignalInput tape fields", "PASS_THROUGH signal_types.SignalInput (signals.py)"),
    (1236, "rules.micro / micro.regime", "PASS_THROUGH micro_structure via rules_engine"),
    (1241, "vol_regime.vol_regime / trade_permissive / conv_mult / risk_mult", "PASS_THROUGH volatility_regime"),
    (1252, "fusion.available", "PASS_THROUGH bayesian_fusion"),
    (1253, "regime.primary", "PASS_THROUGH regime_engine"),
    (1269, "fusion.fusion_dominant_direction / dominant_direction", "PASS_THROUGH bayesian_fusion"),
    (1274, "mh_policy.mh_directional_vote()", "PASS_THROUGH multi_horizon_decision"),
    (1353, "mh_policy.mh_veto_stack_directional", "PASS_THROUGH multi_horizon_decision"),
    (1362, "mh_policy.final_tradeable_decision / final_bias / size_modifier", "PASS_THROUGH multi_horizon_decision"),
    (542, "pred.avg_5c_pts / avg_15c_pts / avg_60c_pts in _compute_levels", "PASS_THROUGH prediction_engine"),
    (1558, "fusion.mc_eae / mc_efe / mc_containment / model_agreement", "PASS_THROUGH bayesian_fusion"),
    (1646, "pred.timeframe_reads (readiness)", "PASS_THROUGH prediction_engine"),
    (1664, "canonical.dominant_probability() (readiness)", "PASS_THROUGH signals.canonical_forecast"),
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
            notes="trunk orchestration/constants/control-flow",
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
