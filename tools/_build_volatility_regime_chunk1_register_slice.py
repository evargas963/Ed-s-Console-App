#!/usr/bin/env python3
"""Build governance/register_slices/volatility_regime_py_1_291.csv — chunk-1 walk."""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS, RegisterRow

REG_V4 = ROOT / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
BASELINE = ROOT / "governance" / "register_slices" / "volatility_regime_py_1_291_scanner_baseline.csv"
SLICE = ROOT / "governance" / "register_slices" / "volatility_regime_py_1_291.csv"
DICT_PATH = ROOT / "schwab_field_inventory" / "schwab_field_dictionary.csv"
_CITE_RE = re.compile(r"CSV row (\d+) \(canonical_field=([^)]+)\)")
TRACE = "CLAUDE chunk-1 disposition volatility_regime.py 1-291"
PATH = "volatility_regime.py"
LO, HI = 1, 291
ANCHOR = "line anchored HEAD 5b1c1f4 volatility_regime.py trunk; STACK ORDER 2 policy producer"


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
    (43, "VolRegimeThresholds dataclass (operator-tunable ladder)", zero("VolRegimeThresholds")),
    (66, "VolRegimePayload dataclass (policy outputs)", zero("VolRegimePayload")),
    (83, "_f safe float extraction (None on invalid)", zero("_f")),
    (93, "_normalize_vol_decimal (percent heuristic + log)", zero("VOL_DECIMAL_PERCENT_HEURISTIC")),
    (112, "_safe_floats (garch list coercion)", zero("garch_sigma_bars")),
    (130, "_garch_trend (rising/falling from sigma bars)", zero("garch_trend")),
    (150, "classify_volatility_regime (main producer)", zero("classify_volatility_regime")),
    (189, "extreme VIX early return -> VOL_UNSTABLE trade_permissive=False", zero("trade_permissive")),
    (200, "rapid VIX change -> VOL_UNSTABLE", zero("vol_regime")),
    (216, "conflicting IV/RV/garch -> VOL_UNSTABLE", zero("vol_regime")),
    (246, "compression_score ladder -> VOL_COMPRESSION", zero("compression")),
    (270, "expansion_score ladder -> VOL_EXPANSION", zero("expansion")),
    (282, "default VOL_UNKNOWN trade_permissive=False (I-01)", zero("unknown")),
]

FORMAL_PASS_THROUGH: list[tuple[int, str, str]] = [
    (168, "mvp_spot(mvp) canonical spot for ATR%", "PASS_THROUGH features.regime_mvp_context"),
    (174, "inp.realized_vol", "PASS_THROUGH SignalInput (signals.py)"),
    (175, "inp.atr", "PASS_THROUGH SignalInput"),
    (176, "inp.iv_level", "PASS_THROUGH SignalInput (chunk-3 _iv_tracker)"),
    (177, "inp.vix_level", "PASS_THROUGH SignalInput (market_context 03c6a8f)"),
    (178, "inp.vix_vs_prev", "PASS_THROUGH SignalInput"),
    (179, "inp.iv_direction", "PASS_THROUGH SignalInput"),
    (180, "inp.garch_sigma_bars", "PASS_THROUGH SignalInput / accumulator"),
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
            notes="constants/module doc/scoring control-flow",
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
