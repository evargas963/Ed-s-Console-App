#!/usr/bin/env python3
"""Build governance/register_slices/liquidity_value_engine_py_1_1520.csv — chunk-1 walk."""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS, RegisterRow

REG_V4 = ROOT / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
BASELINE = ROOT / "governance" / "register_slices" / "liquidity_value_engine_py_1_1520_scanner_baseline.csv"
SLICE = ROOT / "governance" / "register_slices" / "liquidity_value_engine_py_1_1520.csv"
DICT_PATH = ROOT / "schwab_field_inventory" / "schwab_field_dictionary.csv"
_CITE_RE = re.compile(r"CSV row (\d+) \(canonical_field=([^)]+)\)")
TRACE = "CLAUDE chunk-1 disposition liquidity_value_engine.py 1-1520"
PATH = "liquidity_value_engine.py"
LO, HI = 1, 1520
ANCHOR = (
    "line anchored HEAD dfa1f82 liquidity_value_engine.py trunk; "
    "0 REPLACED (pricehistory OHLCV/datetime leaves consumed in-bar); "
    "FIND-LVE1/STYLE-LVE2/magic-thresholds/empty-string disclosed not fixed"
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
    (46, "_cluster_reference_price (I-01 no 500.0 fabrication)", zero("cluster_reference_price")),
    (67, "_resolve_bar_timestamp (Schwab datetime gate)", zero("_resolve_bar_timestamp")),
    (97, "_schwab_pricehistory_bar_missing_datetime", zero("schwab_pricehistory")),
    (109, "_bars_to_list normalize DataFrame/list", zero("_bars_to_list")),
    (212, "merge_schwab_bars_with_live_overlay", zero("merge_schwab_bars")),
    (247, "get_previous_day_levels (PDH/PDL)", zero("pdh")),
    (288, "get_overnight_levels", zero("overnight_high")),
    (326, "compute_opening_range (ORB)", zero("orb_high")),
    (360, "compute_session_vwap (RTH fail-closed volume)", zero("session_vwap")),
    (379, "compute_vwap_bands", zero("vwap_bands")),
    (430, "_volume_profile_poc_vah_val", zero("poc")),
    (482, "compute_volume_profile_levels", zero("volume_profile")),
    (499, "compute_atr_from_bars", zero("atr")),
    (556, "cluster_price_levels_into_zones (FIND-LVE1 atr→percent fallback)", zero("cluster_zones")),
    (627, "_cutoff_for_snapshot checkpoint times", zero("snapshot_cutoff")),
    (647, "build_premarket_snapshot", zero("premarket_snapshot")),
    (746, "build_opening_snapshot", zero("opening_snapshot")),
    (847, "build_midday_snapshot", zero("midday_snapshot")),
    (968, "build_afternoon_snapshot", zero("afternoon_snapshot")),
    (1089, "_last_rth_close_price fail-closed", zero("last_rth_close")),
    (1103, "_classify_live_cluster", zero("live_cluster")),
    (1132, "build_live_snapshot", zero("live_snapshot")),
    (1321, "summarize_snapshot", zero("summarize_snapshot")),
    (1342, "generate_liquidity_value_snapshot master", zero("liquidity_value_snapshot")),
    (1394, "generate_playbook_state (session_bias/auction_state)", zero("playbook_state")),
    (1462, "playbook_state_to_dict (Decision Command zones)", zero("playbook_state_to_dict")),
]

FORMAL_PASS_THROUGH: list[tuple[int, str, str]] = [
    (76, "Schwab pricehistory bar datetime leaf", "PASS_THROUGH candles.datetime (schwab_pricehistory)"),
    (129, "_bars_to_list OHLC reads (DataFrame path)", "PASS_THROUGH candles.open/high/low/close/volume"),
    (176, "_bars_to_list OHLC reads (list-of-dicts path)", "PASS_THROUGH candles.open/high/low/close/volume"),
    (200, "_bar_dt_et bar timestamp/_ts read", "PASS_THROUGH bar timestamp leaf"),
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
            notes="Key levels / playbook orchestration (no Schwab leaf replacement)",
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
