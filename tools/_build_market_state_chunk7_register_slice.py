#!/usr/bin/env python3
"""Build governance/register_slices/market_state_py_1501_1722.csv — chunk-7 (no net-new leaves)."""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS, RegisterRow

REG_V4 = ROOT / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
BASELINE = ROOT / "governance" / "register_slices" / "market_state_py_1501_1722_scanner_baseline.csv"
SLICE = ROOT / "governance" / "register_slices" / "market_state_py_1501_1722.csv"
DICT_PATH = ROOT / "schwab_field_inventory" / "schwab_field_dictionary.csv"
_CITE_RE = re.compile(r"CSV row (\d+) \(canonical_field=([^)]+)\)")
TRACE = "CLAUDE chunk-7 disposition market_state.py 1501-1722"
LO, HI = 1501, 1722
CHUNK7_MIN_LINE = 1513  # L1512 forward_confidence spillover from chunk-6 slice


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
    (1512, "ms.confidence forward_confidence fallback", zero("forward_confidence")),
    (1565, "ms.regime_confidence", zero("regime_confidence")),
    (1581, "ms.fusion_confidence", zero("fusion_confidence")),
    (1582, "ms.fusion_confidence_score", zero("fusion_confidence_score")),
    (1549, "ms.xgb_confidence", zero("xgb_confidence")),
    (1553, "ms.lstm_confidence", zero("lstm_confidence")),
    (1557, "ms.transformer_confidence", zero("transformer_confidence")),
    (1641, "stack_decision_path stage confidence", zero("stack_decision_path")),
    (1542, "ms.layer1_probs", zero("layer1_probs")),
    (1649, "ms.charm_direction_display", zero("charm_direction_display")),
    (1578, "bayesian fusion outputs block", zero("fusion_breakout")),
    (1563, "regime classification block", zero("regime_primary")),
    (1623, "stack_decision_path build", zero("stack_decision_path")),
    (1710, "entry zone derivation", zero("entry_zone")),
]

FORMAL_PASS_THROUGH: list[tuple[int, str, str]] = [
    (1503, "ms.dominant_dir forward_direction", "PASS_THROUGH from predictive engine"),
    (1511, "ms.dominant_prob", "PASS_THROUGH from _pred"),
    (1514, "samples_used model_note model_version block", "PASS_THROUGH from _pred"),
    (1523, "reversal_risk block", "PASS_THROUGH from _pred"),
    (1647, "charm parameter passthrough", "PASS_THROUGH from server.py call args"),
    (1680, "rec_strike rec_side from recommend_option_expression", "PASS_THROUGH chunk-6 OE"),
    (1689, "call_option_right from rec_side/call_signal", "PASS_THROUGH chunk-6"),
    (1697, "dte_warn dte_color from dte_style", "PASS_THROUGH chunk-6 dte_style"),
]

FORMAL_NMD_WRAPPERS: list[tuple[int, str, str]] = [
    (1682, "OE recommendation exception handler", "orchestration"),
    (1722, "return ms", "orchestration"),
]


def export_baseline() -> None:
    rows: list[dict[str, str]] = []
    for raw in csv.DictReader(REG_V4.open(encoding="utf-8", newline="")):
        if raw.get("path") != "market_state.py":
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
    if line < CHUNK7_MIN_LINE and disposition in ("REPLACED", "KEEP_DERIVED", "PASS_THROUGH"):
        if disposition != "NOT_MARKET_DATA":
            pass  # allow spillover notes only via min line filter on REPLACED
    rid = RegisterRow.make_id("market_state.py", line, col, kind, "python")
    anchor = "line anchored HEAD 7edebbb market_state.py"
    note_full = f"{notes} | {anchor}".strip(" |")
    return RegisterRow(
        register_id=rid,
        language="python",
        path="market_state.py",
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
    if not BASELINE.is_file():
        export_baseline()

    row_map = _load_csv_row_to_canonical()
    validate_formal_replaced_citations(row_map)

    out_by_id: dict[str, dict[str, str]] = {}
    for raw in csv.DictReader(BASELINE.open(encoding="utf-8", newline="")):
        line = int(raw["line"])
        if line < CHUNK7_MIN_LINE:
            continue
        row = dict(raw)
        row["disposition"] = "NOT_MARKET_DATA"
        row["governed_ref"] = ""
        row["canonical_field_citation"] = ""
        row["v2_trace"] = TRACE
        row["notes"] = row.get("notes") or "chunk-7 scanner baseline"
        out_by_id[row["register_id"]] = row

    col = 0
    for line, surf, citation, notes in FORMAL_REPLACED:
        if line < CHUNK7_MIN_LINE:
            raise ValueError(f"REPLACED L{line} below chunk-7 floor {CHUNK7_MIN_LINE}")
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

    col = 300
    for line, surf, note in FORMAL_NMD_WRAPPERS:
        row = _synth_row(line, col, "FORMAL_NMD", surf, "NOT_MARKET_DATA", notes=note)
        col += 1
        out_by_id[row["register_id"]] = row

    out_rows = list(out_by_id.values())
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
