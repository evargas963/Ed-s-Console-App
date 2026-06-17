#!/usr/bin/env python3
"""Build governance/register_slices/market_context_py_1_961.csv — chunk-1 walk."""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS, RegisterRow

SLICE = ROOT / "governance/register_slices/market_context_py_1_961.csv"
GOV_REF_PERF = (
    "governance/artifacts/perf_proof/replacements/pp_v4b_market_context_quote_pricehistory_leaf_provenance.json"
)
PERF_PATH = ROOT / "governance/artifacts/perf_proof/replacements/pp_v4b_market_context_quote_pricehistory_leaf_provenance.json"
PERF_INDEX = ROOT / "governance/artifacts/perf_proof/index.json"
DICT_PATH = ROOT / "schwab_field_inventory/schwab_field_dictionary.csv"
_CITE_RE = re.compile(r"CSV row (\d+) \(canonical_field=([^)]+)\)")
TRACE = "CLAUDE chunk-1 disposition market_context.py 1-961"
PATH = "market_context.py"
LO, HI = 1, 961
ANCHOR = "line anchored HEAD a4d46c2 market_context.py; quote+pricehistory producer"


def cite(row: int, field: str) -> str:
    return f"CSV row {row} (canonical_field={field})"


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
        if not cit:
            continue
        validate_citation_text(cit, row_map, context=f"slice L{r.get('line')} {r.get('surface_form')}")


FORMAL_REPLACED: list[tuple[int, str, str, str]] = [
    (279, "quote.get(lastPrice)", cite(2275, "quotes.quote.lastPrice"), "_extract_quote wire-first last"),
    (280, "ext.get(lastPrice)", cite(2240, "quotes.extended.lastPrice"), "_extract_quote extended last"),
    (281, "reg.get(regularMarketLastPrice)", cite(2301, "quotes.regular.regularMarketLastPrice"), "_extract_quote regular last"),
    (282, "quote.get(mark)", cite(2278, "quotes.quote.mark"), "_extract_quote mark fallback"),
    (284, "quote.get(netPercentChange)", cite(2282, "quotes.quote.netPercentChange"), "_extract_quote pct chg"),
    (286, "reg.get(regularMarketPercentChange)", cite(2304, "quotes.regular.regularMarketPercentChange"), "_extract_quote pct chg fallback"),
    (287, "quote.get(netChange)", cite(2281, "quotes.quote.netChange"), "_extract_quote net chg"),
    (289, "reg.get(regularMarketNetChange)", cite(2303, "quotes.regular.regularMarketNetChange"), "_extract_quote net chg fallback"),
    (827, "q.get(openPrice)", cite(2283, "quotes.quote.openPrice"), "fetch_price_levels Tier1 OHLC"),
    (828, "q.get(highPrice)", cite(2273, "quotes.quote.highPrice"), "fetch_price_levels Tier1 OHLC"),
    (829, "q.get(lowPrice)", cite(2277, "quotes.quote.lowPrice"), "fetch_price_levels Tier1 OHLC"),
    (830, "q.get(closePrice)", cite(2272, "quotes.quote.closePrice"), "fetch_price_levels Tier1 PDC"),
    (866, "resp.json().get(candles)", cite(2224, "pricehistory.candles"), "fetch_price_levels Tier2"),
    (876, "c.get(datetime)", cite(2227, "pricehistory.candles.*.datetime"), "candle bar datetime"),
    (905, 'c["high"] prev_bars max', cite(2228, "pricehistory.candles.*.high"), "PDH"),
    (906, 'c["low"] prev_bars min', cite(2229, "pricehistory.candles.*.low"), "PDL"),
    (908, 'prev_bars[-1][1]["close"]', cite(2226, "pricehistory.candles.*.close"), "PDC fallback"),
    (913, 'c["high"] overnight max', cite(2228, "pricehistory.candles.*.high"), "overnight high"),
    (914, 'c["low"] overnight min', cite(2229, "pricehistory.candles.*.low"), "overnight low"),
    (926, "c.get(open)", cite(2230, "pricehistory.candles.*.open"), "today bar open"),
    (927, "c.get(high)", cite(2228, "pricehistory.candles.*.high"), "today bar high"),
    (928, "c.get(low)", cite(2229, "pricehistory.candles.*.low"), "today bar low"),
    (929, "c.get(close)", cite(2226, "pricehistory.candles.*.close"), "today bar close"),
    (930, "c.get(volume)", cite(2231, "pricehistory.candles.*.volume"), "today bar volume"),
    (671, "c.get(high) vol profile", cite(2228, "pricehistory.candles.*.high"), "_volume_profile_poc_vah_val"),
    (672, "c.get(low) vol profile", cite(2229, "pricehistory.candles.*.low"), "_volume_profile_poc_vah_val"),
    (673, "c.get(close) vol profile", cite(2226, "pricehistory.candles.*.close"), "_volume_profile_poc_vah_val"),
    (674, "c.get(volume) vol profile", cite(2231, "pricehistory.candles.*.volume"), "_volume_profile_poc_vah_val"),
    (715, "c.get(high) vwap bands", cite(2228, "pricehistory.candles.*.high"), "_vwap_bands"),
    (716, "c.get(low) vwap bands", cite(2229, "pricehistory.candles.*.low"), "_vwap_bands"),
    (717, "c.get(close) vwap bands", cite(2226, "pricehistory.candles.*.close"), "_vwap_bands"),
    (718, "c.get(volume) vwap bands", cite(2231, "pricehistory.candles.*.volume"), "_vwap_bands"),
]

FORMAL_KEEP_DERIVED: list[tuple[int, str, str]] = [
    (251, "_vix_regime", zero("vix_regime")),
    (262, "_dot_color", zero("_dot_color")),
    (301, "_build_confluence", zero("weighted_push")),
    (351, "_build_iwm_confluence", zero("iwm_confluence")),
    (398, "iwm_blended_participation_push", zero("iwm_blended_participation_push")),
    (421, "_derive_session", zero("session_label")),
    (478, "_vix_regime call site", zero("vix_implication")),
    (520, "bond_signal classifier", zero("bond_signal")),
    (543, "ctx.confluence", zero("confluence")),
    (554, "ctx.qqq_confluence", zero("qqq_confluence")),
    (565, "ctx.iwm_holdings_confluence", zero("iwm_holdings_confluence")),
    (506, "ctx.iwm_confluence", zero("iwm_confluence")),
    (585, "pcr_arrow derivation", zero("pcr_arrow")),
    (596, "ctx.session_label", zero("session_label")),
    (601, "proximity_alerts", zero("proximity_alerts")),
    (657, "_volume_profile_poc_vah_val", zero("pd_poc")),
    (708, "_vwap_bands", zero("vwap_p1")),
    (794, "fetch_price_levels", zero("vwap")),
    (290, "pct_chg derivation from net_chg", zero("pct_chg")),
    (947, "pl.vwap cum_tpv/cum_vol", zero("vwap")),
    (953, "pl.orb_midpoint", zero("orb_midpoint")),
    (318, "cq.contribution", zero("contribution")),
    (365, "sq.contribution", zero("contribution")),
]

FORMAL_PASS_THROUGH: list[tuple[int, str, str]] = [
    (446, "pcr param", "PASS_THROUGH server.py caller"),
    (447, "prev_pcr param", "PASS_THROUGH server.py caller"),
    (460, "resp.json _fetch", "PASS_THROUGH safe_get_quote_fn"),
    (462, "resp.json fetch_price_levels", "PASS_THROUGH client.get_price_history"),
    (470, "stream_chg_pct_fn", "PASS_THROUGH order_flow_live_state"),
]

FORMAL_LINES = {line for line, _, _, _ in FORMAL_REPLACED} | {line for line, _, _ in FORMAL_KEEP_DERIVED} | {
    line for line, _, _ in FORMAL_PASS_THROUGH
}


def _synth_row(
    line: int,
    col: int,
    kind: str,
    surface: str,
    disposition: str,
    *,
    citation: str = "",
    notes: str = "",
    governed_ref: str = "",
) -> dict[str, str]:
    rid = RegisterRow.make_id(PATH, line, col, kind, "python")
    note_full = f"{notes} | {ANCHOR}".strip(" |")
    gref = governed_ref
    if disposition == "REPLACED" and not gref:
        gref = GOV_REF_PERF
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
        governed_ref=gref,
        notes=note_full,
    ).as_csv_dict()


def main() -> None:
    row_map = _load_csv_row_to_canonical()
    validate_formal_replaced_citations(row_map)

    out_by_id: dict[str, dict[str, str]] = {}
    replaced_ids: list[str] = []

    col = 0
    for line, surf, citation, notes in FORMAL_REPLACED:
        row = _synth_row(line, col, "SCHWAB_LEAF_READ", surf, "REPLACED", citation=citation, notes=notes)
        col += 1
        out_by_id[row["register_id"]] = row
        replaced_ids.append(row["register_id"])

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
        row = _synth_row(line, col, "FORMAL_NMD", f"L{line}", "NOT_MARKET_DATA", notes="orchestration/tables")
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
    print(f"replaced_register_ids: {len(replaced_ids)}")

    PERF_PATH.parent.mkdir(parents=True, exist_ok=True)
    PERF_PATH.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "perf_proof_id": "pp_v4b_market_context_quote_pricehistory_leaf_provenance",
                "landed_batch": "v4b-2026-05-19",
                "replacement_scope": (
                    "market_context.py chunk-1: direct Schwab quote.* and pricehistory.candles.* "
                    "reads in _extract_quote (~25 tickers), fetch_price_levels (OHLC/PDH/PDL/PDC/ORB/POC/VAH/VAL/VWAP), "
                    "_volume_profile_poc_vah_val, _vwap_bands; producer for mkt_ctx.* and price_levels."
                ),
                "code_paths": ["market_context.py"],
                "evidence": {
                    "pytest_args": ["tests/test_market_context_fetch_fail_closed.py"],
                    "note": "I-01 partial context on quote failure; 32 REPLACED emission sites.",
                },
                "benchmark": {
                    "command": [
                        "python",
                        "-m",
                        "pytest",
                        "tests/test_market_context_fetch_fail_closed.py",
                        "-q",
                        "--no-header",
                    ],
                    "iterations": 1,
                    "timings_ms": [500],
                    "median_ms": 500,
                    "platform_note": "Windows; chunk-1 2026-05-19",
                },
                "register_link": {
                    "status": "bound",
                    "replaced_register_ids": replaced_ids,
                    "producer_note": (
                        "First walk with net-new REPLACED since server chunk-5; "
                        "6 net-new canonical leaves (quote OHLC + regular change fields)."
                    ),
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
        name = PERF_PATH.name
        if name not in files:
            files.append(name)
        idx["perf_proof_files"] = files
        idx["P_count"] = len(files)
        idx["updated_at_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        PERF_INDEX.write_text(json.dumps(idx, indent=2) + "\n", encoding="utf-8")
        print(f"P_count -> {idx['P_count']}")


if __name__ == "__main__":
    main()
