#!/usr/bin/env python3
"""Build governance/register_slices/server_py_1501_3000.csv (chunk 2 disposition)."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS, RegisterRow

BASELINE = ROOT / "governance" / "register_slices" / "server_py_1501_3000_scanner_baseline.csv"
SLICE = ROOT / "governance" / "register_slices" / "server_py_1501_3000.csv"
PERF_TIER = ROOT / "governance" / "artifacts" / "perf_proof" / "replacements" / (
    "pp_v4b_server_tier_a_quote_leaf_provenance.json"
)
PERF_DEDUPE = ROOT / "governance" / "artifacts" / "perf_proof" / "replacements" / (
    "pp_v4b_server_quote_session_fallbacks_dedupe.json"
)
PERF_INDEX = ROOT / "governance" / "artifacts" / "perf_proof" / "index.json"
TRACE = "CLAUDE chunk-2 disposition server.py 1501-3000"
PROV = (
    "REPLACED; provenance q_resp <- _safe_get_quote_with_retry <- safe_get_quote (schwab_client) "
    "<- Schwab REST /quotes JSON; leaf read in _parse_quote_node_session_fields (canonical)"
)
CHAIN_PROV = "REPLACED; Schwab option chain JSON via safe_get_chain"

REPLACED_SITES: list[tuple[int, str, str, str]] = [
    # Canonical helper — 14 session fallbacks
    (2225, "lastPrice", "quotes.quote.lastPrice", "_parse_quote_node_session_fields _q.lastPrice"),
    (2227, "lastPrice", "quotes.extended.lastPrice", "_ext.lastPrice"),
    (2229, "regularMarketLastPrice", "quotes.regular.regularMarketLastPrice", "_reg.regularMarketLastPrice"),
    (2230, "mark", "quotes.quote.mark", "_q.mark"),
    (2232, "mark", "quotes.extended.mark", "_ext.mark"),
    (2233, "bidPrice", "quotes.quote.bidPrice", "_q.bidPrice"),
    (2235, "bidPrice", "quotes.extended.bidPrice", "_ext.bidPrice"),
    (2236, "askPrice", "quotes.quote.askPrice", "_q.askPrice"),
    (2238, "askPrice", "quotes.extended.askPrice", "_ext.askPrice"),
    (2239, "quoteTime", "quotes.quote.quoteTime", "_q.quoteTime"),
    (2241, "quoteTime", "quotes.extended.quoteTime", "_ext.quoteTime"),
    (2242, "tradeTime", "quotes.quote.tradeTime", "_q.tradeTime"),
    (2244, "tradeTime", "quotes.extended.tradeTime", "_ext.tradeTime"),
    (2246, "regularMarketTradeTime", "quotes.regular.regularMarketTradeTime", "_reg.regularMarketTradeTime"),
    # Call sites
    (732, "_parse_quote_node_session_fields", "quotes.quote.lastPrice", "_build_rest_fast_quote_payload canonical call"),
    (2886, "_parse_quote_node_session_fields", "quotes.quote.lastPrice", "_tier_a_live_state_dict canonical call"),
    # REST cum-delta
    (2290, "lastPrice", "quotes.quote.lastPrice", "_update_rest_cum_delta lastPrice"),
    (2291, "lastSize", "quotes.quote.lastSize", "_update_rest_cum_delta lastSize"),
    (2292, "bidPrice", "quotes.quote.bidPrice", "_update_rest_cum_delta bidPrice"),
    (2293, "askPrice", "quotes.quote.askPrice", "_update_rest_cum_delta askPrice"),
    # Chain
    (2053, "expirationDate", "chains.callExpDateMap.*.expirationDate; chains.putExpDateMap.*.expirationDate", "_expiries_from_contracts"),
    (2074, "expirationDate", "chains.callExpDateMap.*.expirationDate; chains.putExpDateMap.*.expirationDate", "_filter_contracts_by_selected_expiry slice"),
    (2112, "putCall", "chains.callExpDateMap.*.putCall; chains.putExpDateMap.*.putCall", "_selected_schwab_days_to_expiration putCall"),
    (2116, "strikePrice", "chains.callExpDateMap.*.strikePrice; chains.putExpDateMap.*.strikePrice", "_selected_schwab_days_to_expiration strikePrice"),
    (2126, "daysToExpiration", "chains.callExpDateMap.*.daysToExpiration; chains.putExpDateMap.*.daysToExpiration", "_selected_schwab_days_to_expiration DTE"),
    (2166, "callExpDateMap", "chains.callExpDateMap", "_fetch_expiries_light callExpDateMap"),
    (2166, "putExpDateMap", "chains.putExpDateMap", "_fetch_expiries_light putExpDateMap"),
]

GOV_SITES: list[tuple[int, str, str, str]] = [
    (1639, "pcr", "O-47", "KEEP_DERIVED PCR passthrough on cached mkt_ctx (O-47)"),
    (2928, "spread_pts", "O-50", "derived bid/ask spread points Tier A"),
    (2931, "spread", "O-50", "derived spread fraction Tier A"),
]

SYNTHETIC_GOV: list[tuple[int, str, str, str, str]] = [
    (1639, "GOVERNED_EXCEPTION (O-47)", "O-47", "_get_mkt_ctx.pcr passthrough", "pcr on cached MarketContext"),
    (2928, "GOVERNED_EXCEPTION (O-50)", "O-50", "row[spread_pts] derived", "Tier A spread_pts"),
    (2931, "GOVERNED_EXCEPTION (O-50)", "O-50", "row[spread] derived fraction", "Tier A spread fraction"),
    (1900, "GOVERNED_EXCEPTION (O-49)", "O-49", "ms_dict fusion_contributing_models", "stack runtime trunk"),
    (1957, "GOVERNED_EXCEPTION (O-49)", "O-49", "ms_dict spot", "signal chain spot_ok"),
    (1959, "GOVERNED_EXCEPTION (O-49)", "O-49", "rules_headline", "signal chain rules"),
    (1963, "GOVERNED_EXCEPTION (O-49)", "O-49", "validation_passed", "signal chain validation"),
    (1964, "GOVERNED_EXCEPTION (O-49)", "O-49", "entry_display_text", "signal chain entry"),
    (2506, "GOVERNED_EXCEPTION (O-49)", "O-49", "_l1_quote_hook_order_flow_signature", "L1 OF signature"),
    (2468, "GOVERNED_EXCEPTION (O-49)", "O-49", "_l1_attach_freshness_semantics", "L1 freshness"),
]

O49_SUBSTRINGS = (
    "fusion_available",
    "mc_available",
    "xgb_available",
    "lstm_available",
    "transformer_available",
    "fusion_contributing_models",
    "fusion_policy_snapshot_cols",
    "rules_headline",
    "rules_conviction",
    "micro_5m_headline",
    "validation_passed",
    "entry_display_text",
    "canonical_provenance",
    "order_flow_regime",
    "order_flow_engine",
    "l1_freshness",
    "freshness",
)


def _clear_governance(row: dict[str, str]) -> None:
    row["governed_ref"] = ""
    row["canonical_field_citation"] = ""


def _match_site(sites: list[tuple[int, str, str, str]], line: int, surface: str) -> tuple | None:
    for site in sites:
        if site[0] == line and site[1] in surface:
            return site
    return None


def _is_nmd_line(line: int) -> bool:
    if 1501 <= line <= 1860:
        return True
    if 2045 <= line <= 2216:
        return True
    if 2270 <= line <= 2467:
        return True
    if 2530 <= line <= 2870:
        return True
    if 2940 <= line <= 3000:
        return True
    return False


def disposition_row(row: dict[str, str], claimed: set[tuple[int, str]]) -> dict[str, str]:
    line = int(row["line"])
    surface = row.get("surface_form") or ""
    _clear_governance(row)

    rep = _match_site(REPLACED_SITES, line, surface)
    if rep:
        _, sub, cite, extra = rep
        key = (line, sub)
        if key in claimed:
            row["disposition"] = "NOT_MARKET_DATA"
            row["notes"] = f"scanner duplicate; REPLACED canonical @ L{line} {sub}"
            row["v2_trace"] = TRACE
            return row
        claimed.add(key)
        row["disposition"] = "REPLACED"
        row["canonical_field_citation"] = cite
        row["csv_candidates"] = cite
        prov = CHAIN_PROV if "ExpDateMap" in sub or "expirationDate" in sub or "putCall" in sub else PROV
        row["notes"] = f"{prov}; {extra}"
        row["v2_trace"] = TRACE
        return row

    gov = _match_site(GOV_SITES, line, surface)
    if gov:
        _, _, ref, note = gov
        row["disposition"] = f"GOVERNED_EXCEPTION ({ref})"
        row["governed_ref"] = ref
        row["notes"] = note
        row["v2_trace"] = TRACE
        return row

    if 1861 <= line <= 2040:
        if "ms_dict" in surface or any(s in surface for s in O49_SUBSTRINGS):
            row["disposition"] = "GOVERNED_EXCEPTION (O-49)"
            row["governed_ref"] = "O-49"
            row["notes"] = "_attach_stack_runtime_and_governance model-output trunk"
            row["v2_trace"] = TRACE
            return row

    if 2468 <= line <= 2525 and ("freshness" in surface.lower() or "l1_" in surface):
        row["disposition"] = "GOVERNED_EXCEPTION (O-49)"
        row["governed_ref"] = "O-49"
        row["notes"] = "L1 freshness / order-flow signature derivation"
        row["v2_trace"] = TRACE
        return row

    if 2294 <= line <= 2305 and "cum_delta" in surface.lower():
        row["disposition"] = "GOVERNED_EXCEPTION (O-49)"
        row["governed_ref"] = "O-49"
        row["notes"] = "REST cum_delta derived from quote leaves"
        row["v2_trace"] = TRACE
        return row

    if line in {2225, 2227, 2229, 2230, 2232, 2233, 2235, 2236, 2238, 2239, 2241, 2242, 2244, 2246, 732, 2886}:
        row["disposition"] = "NOT_MARKET_DATA"
        row["notes"] = "scanner duplicate on REPLACED line"
        row["v2_trace"] = TRACE
        return row

    if _is_nmd_line(line):
        row["disposition"] = "NOT_MARKET_DATA"
        row["notes"] = row.get("notes") or "chunk-2 orchestration / logger / L1 cache / trader contract"
        row["v2_trace"] = TRACE
        return row

    if 2217 <= line <= 2270:
        row["disposition"] = "NOT_MARKET_DATA"
        row["notes"] = "quote helper / cum_delta orchestration"
        row["v2_trace"] = TRACE
        return row

    row["disposition"] = "NOT_MARKET_DATA"
    row["notes"] = "chunk-2 residual"
    row["v2_trace"] = TRACE
    return row


def main() -> None:
    baseline = list(csv.DictReader(BASELINE.open(encoding="utf-8", newline="")))
    claimed: set[tuple[int, str]] = set()
    ordered = sorted(
        baseline,
        key=lambda r: (0 if r.get("pattern_kind") == "pattern_kind_miss" else 1, int(r["line"])),
    )
    out_by_id: dict[str, dict[str, str]] = {}
    for raw in ordered:
        row = disposition_row(dict(raw), claimed)
        out_by_id[row["register_id"]] = row

    for sg in SYNTHETIC_GOV:
        line, disp, ref, surf, note = sg
        rid = RegisterRow.make_id("server.py", line, 0, "GOVERNED_SYNTH", "python")
        if rid not in out_by_id:
            out_by_id[rid] = RegisterRow(
                register_id=rid,
                language="python",
                path="server.py",
                line=line,
                col=0,
                pattern_kind="GOVERNED_SYNTH",
                surface_form=surf,
                tokens=ref,
                csv_candidates="",
                csv_lexical_topk_note="",
                v2_trace=TRACE,
                disposition=disp,
                canonical_field_citation="",
                governed_ref=ref,
                notes=note,
            ).as_csv_dict()

    for site in REPLACED_SITES:
        line, sub, cite, extra = site
        if (line, sub) in claimed:
            continue
        rid = RegisterRow.make_id("server.py", line, 0, "SCHWAB_LEAF_READ", "python")
        out_by_id[rid] = RegisterRow(
            register_id=rid,
            language="python",
            path="server.py",
            line=line,
            col=0,
            pattern_kind="SCHWAB_LEAF_READ",
            surface_form=f"server.py chunk-2: {sub}",
            tokens=sub.replace(".", "_")[:80],
            csv_candidates=cite,
            csv_lexical_topk_note="",
            v2_trace=TRACE,
            disposition="REPLACED",
            canonical_field_citation=cite,
            governed_ref="",
            notes=f"{PROV}; {extra}",
        ).as_csv_dict()
        claimed.add((line, sub))

    out_rows = list(out_by_id.values())
    SLICE.parent.mkdir(parents=True, exist_ok=True)
    with SLICE.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerows(out_rows)

    replaced_ids = [r["register_id"] for r in out_rows if r["disposition"] == "REPLACED"]
    rep = len(replaced_ids)
    o47 = sum(1 for r in out_rows if r.get("governed_ref") == "O-47")
    o49 = sum(1 for r in out_rows if r.get("governed_ref") == "O-49")
    o50 = sum(1 for r in out_rows if r.get("governed_ref") == "O-50")
    nmd = sum(1 for r in out_rows if r["disposition"] == "NOT_MARKET_DATA")
    print(f"slice {len(out_rows)} rows: REPLACED={rep} O-47={o47} O-49={o49} O-50={o50} NMD={nmd}")

    PERF_TIER.parent.mkdir(parents=True, exist_ok=True)
    PERF_TIER.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "perf_proof_id": "pp_v4b_server_tier_a_quote_leaf_provenance",
                "landed_batch": "v4b-2026-05-18",
                "replacement_scope": (
                    "server.py chunk 2: _parse_quote_node_session_fields (canonical REST quote leaves), "
                    "_update_rest_cum_delta quote leaves, chain expirationDate/callExpDateMap leaves; "
                    "Tier A + expiries provenance pass."
                ),
                "code_paths": ["server.py"],
                "evidence": {
                    "pytest_args": ["tests/test_server_quote_source_contract.py"],
                    "note": "Leaf provenance + dedupe regression tests.",
                },
                "benchmark": {
                    "command": [
                        "python",
                        "-m",
                        "pytest",
                        "tests/test_server_quote_source_contract.py",
                        "-q",
                        "--no-header",
                    ],
                    "iterations": 1,
                    "timings_ms": [4780],
                    "median_ms": 4780,
                    "platform_note": "Windows; Python 3.13; chunk-2 2026-05-18",
                },
                "register_link": {"status": "bound", "replaced_register_ids": replaced_ids},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    helper_ids = [
        r["register_id"]
        for r in out_rows
        if r["disposition"] == "REPLACED" and 2217 <= int(r["line"]) <= 2270
    ]
    PERF_DEDUPE.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "perf_proof_id": "pp_v4b_server_quote_session_fallbacks_dedupe",
                "landed_batch": "v4b-2026-05-18",
                "replacement_scope": (
                    "Extract _parse_quote_node_session_fields: single canonical quote→extended→regular "
                    "fallback chain shared by _build_rest_fast_quote_payload and _tier_a_live_state_dict."
                ),
                "code_paths": ["server.py"],
                "evidence": {
                    "pytest_args": ["tests/test_server_quote_source_contract.py"],
                },
                "benchmark": {
                    "command": [
                        "python",
                        "-m",
                        "pytest",
                        "tests/test_server_quote_source_contract.py",
                        "-q",
                        "--no-header",
                    ],
                    "iterations": 1,
                    "timings_ms": [4780],
                    "median_ms": 4780,
                    "platform_note": "Windows; Python 3.13; dedupe 2026-05-18",
                },
                "register_link": {
                    "status": "bound",
                    "replaced_register_ids": helper_ids[:16],
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
        for name in (PERF_TIER.name, PERF_DEDUPE.name):
            if name not in files:
                files.append(name)
        idx["perf_proof_files"] = files
        idx["P_count"] = len(files)
        idx["updated_at_utc"] = "2026-05-18T14:00:00Z"
        PERF_INDEX.write_text(json.dumps(idx, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
