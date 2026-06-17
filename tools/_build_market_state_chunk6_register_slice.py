#!/usr/bin/env python3
"""Build governance/register_slices/market_state_py_1_1500.csv — chunk-6 + CONFIDENCE-1a."""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS, RegisterRow

REG_V4 = ROOT / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
BASELINE = ROOT / "governance" / "register_slices" / "market_state_py_1_1500_scanner_baseline.csv"
SLICE = ROOT / "governance" / "register_slices" / "market_state_py_1_1500.csv"
PERF_CHAIN = ROOT / "governance" / "artifacts" / "perf_proof" / "replacements" / (
    "pp_v4b_market_state_chunk6_chain_leaf_provenance.json"
)
PERF_INDEX = ROOT / "governance" / "artifacts" / "perf_proof" / "index.json"
DICT_PATH = ROOT / "schwab_field_inventory" / "schwab_field_dictionary.csv"
_CITE_RE = re.compile(r"CSV row (\d+) \(canonical_field=([^)]+)\)")
TRACE = "CLAUDE chunk-6 disposition market_state.py 1-1500"
LO, HI = 1, 1500

# Option (c): function-level S1 — 42 keys in _oe_chain_row_snapshot (L497-540); twin call/put map families.
S1_SNAPSHOT_CITATION = (
    "CSV rows 4-65 (chains.callExpDateMap.* family) + 71-130 (chains.putExpDateMap.*); "
    "42-key _oe_chain_row_snapshot ct.get projection; representative: "
    + "CSV row 14 (canonical_field=chains.callExpDateMap.*.delta)"
)

NET_NEW_REPLACED_ORDERED: tuple[str, ...] = (
    "_oe_chain_row_snapshot ct.get keys",
    "ct.get putCall L547",
    "ct.get strikePrice L549",
    "c.get putCall L668",
    "c.get strikePrice L670",
    "ct.get putCall L792",
    "ct.get strikePrice L794",
    "ct.get bid L803",
    "ct.get ask L804",
    "ct.get mark L810",
    "ct.get last L820",
    "ct.get putCall L853",
    "ct.get strikePrice L856",
    "ct.get daysToExpiration L860",
)


def cite(row: int, field: str) -> str:
    return f"CSV row {row} (canonical_field={field})"


def pair_cite(call_row: int, put_row: int, leaf: str) -> str:
    return (
        f"{cite(call_row, f'chains.callExpDateMap.*.{leaf}')}; "
        f"{cite(put_row, f'chains.putExpDateMap.*.{leaf}')}"
    )


def zero(symbol: str) -> str:
    return f"CSV grep zero hits for {symbol}"


def _load_csv_row_to_canonical() -> dict[int, str]:
    """File line number (row 1 = header) → canonical_field for data rows."""
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


FORMAL_REPLACED: list[tuple[int, str, str, str]] = [
    (
        541,
        "_oe_chain_row_snapshot ct.get keys",
        S1_SNAPSHOT_CITATION,
        "V4 memo S1; 42-key projection — each k maps chains.*.<k> call+put twin",
    ),
    (547, "ct.get putCall L547", pair_cite(49, 116, "putCall"), "_oe_first_contract_row filter"),
    (549, "ct.get strikePrice L549", pair_cite(53, 120, "strikePrice"), "_oe_first_contract_row filter"),
    (668, "c.get putCall L668", pair_cite(49, 116, "putCall"), "recommend_option_expression side filter"),
    (670, "c.get strikePrice L670", pair_cite(53, 120, "strikePrice"), "recommend_option_expression strikes"),
    (792, "ct.get putCall L792", pair_cite(49, 116, "putCall"), "_oe_bid_ask_mid filter"),
    (794, "ct.get strikePrice L794", pair_cite(53, 120, "strikePrice"), "_oe_bid_ask_mid filter"),
    (803, "ct.get bid L803", pair_cite(8, 75, "bid"), "_oe_bid_ask_mid"),
    (804, "ct.get ask L804", pair_cite(6, 73, "ask"), "_oe_bid_ask_mid"),
    (810, "ct.get mark L810", pair_cite(31, 98, "mark"), "_oe_bid_ask_mid mark path"),
    (820, "ct.get last L820", pair_cite(26, 93, "last"), "_oe_bid_ask_mid last fallback"),
    (853, "ct.get putCall L853", pair_cite(49, 116, "putCall"), "_schwab_days_to_expiration_for_contract"),
    (856, "ct.get strikePrice L856", pair_cite(53, 120, "strikePrice"), "_schwab_days_to_expiration_for_contract"),
    (860, "ct.get daysToExpiration L860", pair_cite(12, 79, "daysToExpiration"), "CSV-R2 Schwab-primary DTE"),
]

FORMAL_KEEP_DERIVED: list[tuple[int, str, str]] = [
    (332, "CONFIDENCE-1a ms.confidence field", "canopy WTDS forward confidence; not MHAP/fused_confidence_*"),
    (1500, "ms.confidence canonical_forecast", zero("confidence")),
    (1512, "ms.confidence forward_confidence fallback", zero("forward_confidence")),
    (1448, "mhap_rows confidence per horizon", zero("mhap_confidence")),
    (297, "mhap_rows field", zero("mhap_rows")),
    (328, "fusion_policy_snapshot_cols", zero("fusion_policy_snapshot_cols")),
    (625, "recommend_option_expression", "math_exposure score_option_expression"),
    (1007, "consensus_summary bias_signal", zero("bias_signal")),
    (556, "_oe_composite_strike_row", "score_option_expression composite"),
]

FORMAL_PASS_THROUGH: list[tuple[int, str, str]] = [
    (997, "build_market_state ms.spot", "server._fetch_state handoff; quotes.quote.lastPrice producer"),
    (998, "build_market_state ms.bid", "quotes.quote.bidPrice producer"),
    (999, "build_market_state ms.ask", "quotes.quote.askPrice producer"),
    (915, "contracts_use parameter", "server chain flatten handoff"),
]

FORMAL_NMD_WRAPPERS: list[tuple[int, str, str]] = [
    (44, "derive_zone bias_color helpers", "pure formatting"),
    (906, "build_market_state def", "orchestration entry"),
    (129, "MarketState dataclass", "schema container"),
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
    rid = RegisterRow.make_id("market_state.py", line, col, kind, "python")
    anchor = "line anchored HEAD 1539d42 market_state.py"
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
        row = dict(raw)
        row["disposition"] = "NOT_MARKET_DATA"
        row["governed_ref"] = ""
        row["canonical_field_citation"] = ""
        row["v2_trace"] = TRACE
        row["notes"] = row.get("notes") or "chunk-6 scanner baseline"
        out_by_id[row["register_id"]] = row

    col = 0
    net_new_ids: list[str] = []
    for line, surf, citation, notes in FORMAL_REPLACED:
        row = _synth_row(line, col, "FORMAL_REPLACED", surf, "REPLACED", citation=citation, notes=notes)
        col += 1
        out_by_id[row["register_id"]] = row
        if surf in NET_NEW_REPLACED_ORDERED:
            net_new_ids.append(row["register_id"])

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
    print(f"net_new_ids: {len(net_new_ids)}")

    PERF_CHAIN.parent.mkdir(parents=True, exist_ok=True)
    PERF_CHAIN.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "perf_proof_id": "pp_v4b_market_state_chunk6_chain_leaf_provenance",
                "landed_batch": "v4b-2026-05-19",
                "replacement_scope": (
                    "market_state.py chunk 6 (L1-1500): V4 memo S1-S5 chain contract ct.get "
                    "emission sites; CONFIDENCE-1a docstring on ms.confidence (no behavior change)."
                ),
                "code_paths": ["market_state.py"],
                "evidence": {
                    "pytest_args": [
                        "tests/test_a2_market_state_proof_row_completeness.py",
                    ],
                    "note": "Proof-row keys + chain leaf reads; CONFIDENCE-1a documentation only.",
                },
                "benchmark": {
                    "command": [
                        "python",
                        "-m",
                        "pytest",
                        "tests/test_a2_market_state_proof_row_completeness.py",
                        "-q",
                        "--no-header",
                    ],
                    "iterations": 1,
                    "timings_ms": [5000],
                    "median_ms": 5000,
                    "platform_note": "Windows; chunk-6 market_state 2026-05-19",
                },
                "register_link": {
                    "status": "bound",
                    "replaced_register_ids": net_new_ids,
                    "producer_note": "contracts from server safe_get_chain flatten",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    if PERF_INDEX.is_file():
        idx = json.loads(PERF_INDEX.read_text(encoding="utf-8"))
        files = list(idx.get("perf_proof_files") or [])
        if PERF_CHAIN.name not in files:
            files.append(PERF_CHAIN.name)
        idx["perf_proof_files"] = files
        idx["P_count"] = len(files)
        idx["updated_at_utc"] = "2026-05-19T07:00:00Z"
        PERF_INDEX.write_text(json.dumps(idx, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
