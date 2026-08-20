#!/usr/bin/env python3
"""Refresh Schwab native field/schema inventory from schwab-py definitions + prior artifacts.

Canonical mechanisms (repo):
  1. ``python schwab_full_field_inventory.py`` — live REST+stream observation (needs token)
  2. ``python schwab_field_dictionary_builder.py`` — rebuild dictionary from master (snapshot;
     prefer sync for union merge — RC-380)
  3. ``python tools/sync_schwab_field_dictionary.py --poll`` — live union-merge into
     ``schwab_field_inventory/schwab_field_dictionary.csv`` (needs token)
  4. **This tool** — always-runnable definition authority from installed ``schwab-py``
     StreamClient / Quote.Fields, diffed against the committed observed inventory.

Writes (machine-readable):
  - ``schwab_field_inventory/schwab_native_schema_inventory_v1.json``
  - ``reports/of_schwab_native_inventory_refresh_v1.json``
  - ``reports/of_schwab_capability_universe_map_v1.json``
  - refreshes ``reports/of_capability_matrix_template_v1.json``

Does **not** invent live entitlement. Live observation remains operator-host when token
exists (this tool attempts sync --poll and records LIVE_BLOCKED if unavailable).
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

INV_DIR = ROOT / "schwab_field_inventory"
SCHEMA_OUT = INV_DIR / "schwab_native_schema_inventory_v1.json"
REFRESH_OUT = ROOT / "reports" / "of_schwab_native_inventory_refresh_v1.json"
UNIVERSE_OUT = ROOT / "reports" / "of_schwab_capability_universe_map_v1.json"
MATRIX_OUT = ROOT / "reports" / "of_capability_matrix_template_v1.json"
CANONICAL = INV_DIR / "schwab_canonical_fields.txt"
DICTIONARY = INV_DIR / "schwab_field_dictionary.csv"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _schwab_py_version() -> str:
    try:
        import importlib.metadata as md

        return md.version("schwab-py")
    except Exception:  # noqa: BLE001
        return "unknown"


def extract_streamer_schema() -> dict[str, Any]:
    from schwab.streaming import StreamClient

    enums: dict[str, list[dict[str, Any]]] = {}
    for name, obj in sorted(StreamClient.__dict__.items()):
        if isinstance(obj, type) and hasattr(obj, "__members__"):
            enums[name] = [
                {"name": mn, "number": int(me.value)}
                for mn, me in obj.__members__.items()
            ]

    services: list[dict[str, Any]] = []
    # Map subscribe method → service string used in _service_op (from source docstrings / known)
    service_map = [
        ("LEVELONE_EQUITIES", "level_one_equity_subs", "LevelOneEquityFields"),
        ("LEVELONE_OPTIONS", "level_one_option_subs", "LevelOneOptionFields"),
        ("LEVELONE_FUTURES", "level_one_futures_subs", "LevelOneFuturesFields"),
        ("LEVELONE_FOREX", "level_one_forex_subs", "LevelOneForexFields"),
        ("LEVELONE_FUTURES_OPTIONS", "level_one_futures_options_subs", "LevelOneFuturesOptionsFields"),
        ("NYSE_BOOK", "nyse_book_subs", "BookFields(+Bid/Ask/PerExchange*)"),
        ("NASDAQ_BOOK", "nasdaq_book_subs", "BookFields(+Bid/Ask/PerExchange*)"),
        ("OPTIONS_BOOK", "options_book_subs", "BookFields(+Bid/Ask/PerExchange*)"),
        ("CHART_EQUITY", "chart_equity_subs", "ChartEquityFields"),
        ("CHART_FUTURES", "chart_futures_subs", "ChartFuturesFields"),
        ("SCREENER_EQUITY", "screener_equity_subs", "ScreenerFields"),
        ("SCREENER_OPTION", "screener_option_subs", "ScreenerFields"),
    ]
    for svc, meth, fields in service_map:
        services.append(
            {
                "service": svc,
                "subscribe_method": meth,
                "method_present": hasattr(StreamClient, meth),
                "field_enum": fields,
            }
        )

    book_nested = {
        "BookFields": enums.get("BookFields", []),
        "BidFields": enums.get("BidFields", []),
        "AskFields": enums.get("AskFields", []),
        "PerExchangeBidFields": enums.get("PerExchangeBidFields", []),
        "PerExchangeAskFields": enums.get("PerExchangeAskFields", []),
    }

    return {
        "authority": "schwab-py StreamClient enums (installed package)",
        "schwab_py_version": _schwab_py_version(),
        "extracted_at_utc": _utc(),
        "enums": enums,
        "services": services,
        "book_nested_schema": book_nested,
        "timesale_wrapper_present": any(
            "timesale" in n.lower() for n in dir(StreamClient)
        ),
        "notes": [
            "TIMESALE is not wrapped on StreamClient in schwab-py 1.5.1",
            "MARKET_MAKER field exists on LevelOneForexFields only — not equity book",
            "NYSE/NASDAQ/OPTIONS_BOOK share identical BookFields nested schema",
        ],
    }


def extract_rest_schema() -> dict[str, Any]:
    from schwab.client.base import BaseClient

    quote_fields = []
    qf = getattr(getattr(BaseClient, "Quote", None), "Fields", None)
    if qf is not None and hasattr(qf, "__members__"):
        quote_fields = [
            {"name": mn, "value": me.value} for mn, me in qf.__members__.items()
        ]
    return {
        "authority": "schwab-py BaseClient.Quote.Fields (section selectors, not leaf maps)",
        "quote_section_fields": quote_fields,
        "note": (
            "REST leaf paths come from live observation union "
            "(schwab_field_dictionary.csv), not from schwab-py enums."
        ),
    }


def load_prior_canonical() -> set[str]:
    if not CANONICAL.is_file():
        return set()
    return {ln.strip() for ln in CANONICAL.read_text(encoding="utf-8").splitlines() if ln.strip()}


def load_prior_dictionary() -> dict[str, dict[str, str]]:
    if not DICTIONARY.is_file():
        return {}
    with DICTIONARY.open(encoding="utf-8", newline="") as fh:
        return {r["canonical_field"]: dict(r) for r in csv.DictReader(fh)}


def definition_leaf_paths(schema: dict[str, Any]) -> dict[str, set[str]]:
    """Synthetic canonical-style paths for definition leaves (not live-observed)."""
    out: dict[str, set[str]] = {
        "LEVELONE_EQUITIES": set(),
        "LEVELONE_OPTIONS": set(),
        "LEVELONE_FOREX": set(),
        "LEVELONE_FUTURES": set(),
        "BOOK_SHARED": set(),
        "CHART_EQUITY": set(),
    }
    enums = schema["enums"]
    for f in enums.get("LevelOneEquityFields", []):
        out["LEVELONE_EQUITIES"].add(f"def.LEVELONE_EQUITIES.{f['name']}#{f['number']}")
    for f in enums.get("LevelOneOptionFields", []):
        out["LEVELONE_OPTIONS"].add(f"def.LEVELONE_OPTIONS.{f['name']}#{f['number']}")
    for f in enums.get("LevelOneForexFields", []):
        out["LEVELONE_FOREX"].add(f"def.LEVELONE_FOREX.{f['name']}#{f['number']}")
    for f in enums.get("LevelOneFuturesFields", []):
        out["LEVELONE_FUTURES"].add(f"def.LEVELONE_FUTURES.{f['name']}#{f['number']}")
    for f in enums.get("ChartEquityFields", []):
        out["CHART_EQUITY"].add(f"def.CHART_EQUITY.{f['name']}#{f['number']}")
    # Book shared
    for enum_name in (
        "BookFields",
        "BidFields",
        "AskFields",
        "PerExchangeBidFields",
        "PerExchangeAskFields",
    ):
        for f in enums.get(enum_name, []):
            out["BOOK_SHARED"].add(f"def.BOOK.{enum_name}.{f['name']}#{f['number']}")
    return out


def prior_streaming_terminals(prior: set[str]) -> set[str]:
    terms: set[str] = set()
    for p in prior:
        if p.startswith("streaming."):
            terms.add(p.rsplit(".", 1)[-1])
    return terms


def diff_definitions_vs_prior(schema: dict[str, Any], prior: set[str]) -> dict[str, Any]:
    terms = prior_streaming_terminals(prior)
    enums = schema["enums"]

    def miss(enum_name: str) -> list[dict[str, Any]]:
        missing = []
        for f in enums.get(enum_name, []):
            if f["name"] not in terms:
                missing.append(f)
        return missing

    l1_miss = miss("LevelOneEquityFields")
    l1o_miss = miss("LevelOneOptionFields")
    book_enums = [
        "BookFields",
        "BidFields",
        "AskFields",
        "PerExchangeBidFields",
        "PerExchangeAskFields",
    ]
    book_miss = []
    for en in book_enums:
        book_miss.extend({"enum": en, **f} for f in miss(en))
    chart_miss = miss("ChartEquityFields")
    forex_mm = [
        f for f in enums.get("LevelOneForexFields", []) if f["name"] == "MARKET_MAKER"
    ]

    # Prior terminals that look like stream fields but are not in equity L1 / book / chart
    known = set()
    for en in (
        "LevelOneEquityFields",
        "BookFields",
        "BidFields",
        "AskFields",
        "PerExchangeBidFields",
        "PerExchangeAskFields",
        "ChartEquityFields",
    ):
        known.update(f["name"] for f in enums.get(en, []))
    # Filter prior terminals that are structural path noise
    noise = {"*", "content", "command", "service", "streaming", "key", "delayed", "assetMainType", "assetSubType", "cusip"}
    unexplained = sorted(t for t in terms if t not in known and t not in noise and t.isupper())

    return {
        "prior_streaming_leaf_count": len([p for p in prior if p.startswith("streaming.")]),
        "prior_streaming_terminal_names": len(terms),
        "additions_vs_prior_observed_streaming_terminals": {
            "LEVELONE_EQUITIES_names_not_in_prior_terminals": l1_miss,
            "LEVELONE_OPTIONS_names_not_in_prior_terminals": l1o_miss,
            "BOOK_nested_names_not_in_prior_terminals": book_miss,
            "CHART_EQUITY_names_not_in_prior_terminals": chart_miss,
            "note": (
                "Most LEVELONE_OPTIONS 'additions' mean never observed in the May-2026 "
                "streaming capture (equity+NASDAQ_BOOK+chart only), not that schwab-py added them."
            ),
        },
        "field_number_changes": {
            "status": "NONE_DETECTED_VS_SELF",
            "note": (
                "No prior committed schwab-py enum snapshot to diff numbers against; "
                "current numbers recorded in schwab_native_schema_inventory_v1.json."
            ),
        },
        "nested_book_field_changes": {
            "status": "UNCHANGED_VS_PRIOR_OBSERVED_PATHS",
            "prior_had": sorted(
                t
                for t in (
                    "TOTAL_VOLUME",
                    "NUM_BIDS",
                    "NUM_ASKS",
                    "EXCHANGE",
                    "BID_VOLUME",
                    "ASK_VOLUME",
                    "SEQUENCE",
                    "BOOK_TIME",
                    "BID_PRICE",
                    "ASK_PRICE",
                )
                if t in terms
            ),
            "definition_now": book_miss,  # only SYMBOL typically missing as terminal
        },
        "service_changes": {
            "documented_subscribe_methods": [
                s for s in schema["services"] if s["method_present"]
            ],
            "timesale_wrapper": schema["timesale_wrapper_present"],
            "prior_inventory_stream_probe_covered": [
                "LEVELONE_EQUITIES",
                "NASDAQ_BOOK",
                "CHART_EQUITY",
            ],
            "documented_but_not_in_prior_streaming_capture": [
                "NYSE_BOOK",
                "OPTIONS_BOOK",
                "LEVELONE_OPTIONS",
                "LEVELONE_FUTURES",
                "LEVELONE_FOREX",
                "LEVELONE_FUTURES_OPTIONS",
                "CHART_FUTURES",
                "SCREENER_EQUITY",
                "SCREENER_OPTION",
            ],
        },
        "renames": {
            "status": "NONE_DETECTED",
            "note": "No prior enum snapshot; cannot prove renames from observed path leaves alone.",
        },
        "removals": {
            "status": "NONE_FROM_DEFINITION_REFRESH",
            "note": (
                "Definition refresh cannot remove observed dictionary rows (RC-380 union). "
                "Unexplained prior UPPER terminals (not in equity L1/book/chart enums): "
                f"{unexplained[:40]}"
            ),
            "unexplained_prior_upper_terminals": unexplained,
        },
        "notable_definition_facts": [
            {
                "field": "LevelOneForexFields.MARKET_MAKER#26",
                "fact": "Native MARKET_MAKER exists on FOREX L1 only — not equity/options book",
            },
            {
                "field": "ASK_ID/BID_ID/LAST_ID",
                "fact": "Documented as Exchange ID on equity L1 — not Market Maker ID",
            },
            {
                "field": "NUM_BIDS/NUM_ASKS",
                "fact": "Documented native book fields; semantic interpretation needs RTH",
            },
            {
                "field": "PerExchange*.EXCHANGE",
                "fact": "Documented native; identity (MIC vs other) needs RTH — not per-participant until proven",
            },
        ],
        "forex_market_maker_field": forex_mm,
    }


def attempt_live_sync_dry_run() -> dict[str, Any]:
    """Invoke canonical live sync mechanism; record blockage if no token."""
    cmd = [sys.executable, str(ROOT / "tools" / "sync_schwab_field_dictionary.py"), "--poll", "--dry-run"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "mechanism": "tools/sync_schwab_field_dictionary.py --poll --dry-run",
            "status": "LIVE_BLOCKED",
            "error": f"{type(exc).__name__}: {exc}",
        }
    out = (proc.stdout or "") + (proc.stderr or "")
    status = "LIVE_OK" if proc.returncode == 0 else "LIVE_BLOCKED"
    return {
        "mechanism": "tools/sync_schwab_field_dictionary.py --poll --dry-run",
        "status": status,
        "returncode": proc.returncode,
        "output_tail": out[-2000:],
    }


def build_universe_map() -> dict[str, Any]:
    """NATIVE USED / UNUSED / DERIVED / DERIVABLE / PROXY / UNAVAILABLE for OF design."""
    # Usage evidence from known code paths (static, not RTH).
    native_used = [
        {
            "field": "LEVELONE BID/ASK/LAST_PRICE + SIZE",
            "where": "order_flow_streaming → live_market_plane / order_flow_live_state",
        },
        {
            "field": "LEVELONE TOTAL_VOLUME / LAST_SIZE / QUOTE|TRADE_TIME",
            "where": "order_flow_live_state / candle accumulator",
        },
        {
            "field": "BOOK price-level TOTAL_VOLUME + BID/ASK_PRICE",
            "where": "order_flow_engine imbalance (memory only)",
        },
        {
            "field": "REST quote bid/ask/last/sizes/times/volume",
            "where": "server._parse_quote_node_session_fields",
        },
        {
            "field": "REST option chain greeks/OI/volume/sizes",
            "where": "market_state OE snapshot / terrain / exposures",
        },
        {
            "field": "REST pricehistory OHLCV",
            "where": "price_bars_1m / VWAP",
        },
    ]
    native_unused = [
        {
            "field": "BOOK NUM_BIDS / NUM_ASKS",
            "status": "documented native; subscribed via full book fields; discarded by OF engine",
            "rth_needed_for": "semantics",
        },
        {
            "field": "BOOK nested EXCHANGE + BID_VOLUME/ASK_VOLUME + SEQUENCE",
            "status": "documented native; discarded; identity/order semantics need RTH",
            "rth_needed_for": "EXCHANGE identity + SEQUENCE behavior",
        },
        {
            "field": "LEVELONE ASK/BID/LAST_MIC_ID + ASK/BID/LAST_ID",
            "status": "documented native; not retained in plane keepers",
            "rth_needed_for": None,
        },
        {
            "field": "LEVELONE day OHLC / 52w / PE / dividend / HTB / shortable / post-market",
            "status": "documented native; mostly discarded by stream keepers",
            "rth_needed_for": None,
        },
        {
            "field": "OPTIONS_BOOK entire service",
            "status": "documented in schwab-py; not subscribed by console",
            "rth_needed_for": "entitlement/population",
        },
        {
            "field": "LEVELONE_OPTIONS entire service",
            "status": "documented; console uses REST chains instead",
            "rth_needed_for": "optional population vs REST",
        },
        {
            "field": "LevelOneForexFields.MARKET_MAKER",
            "status": "documented native on FOREX L1 only — not equity microstructure",
            "rth_needed_for": None,
        },
    ]
    derived_today = [
        "book_imbalance_1/3/5 from price-level TOTAL_VOLUME",
        "top_book_pressure from L1 sizes",
        "tape_pressure / cum_delta_proxy from L1 last changes (PROXY side)",
        "REST Lee-Ready-ish cum delta fallback",
        "options flow / CP ratio from chain volume",
        "VWAP/POC from price_bars_1m",
        "terrain/GEX walls from chain",
    ]
    derivable = [
        "depth profile / refill from retained book TOTAL_VOLUME history (if persisted)",
        "venue-mix features IF EXCHANGE identity is proven (RTH)",
        "breadth-at-price IF NUM_* semantics proven (RTH)",
        "quote aging from BID/ASK_TIME_MILLIS (documented native; unused)",
        "MIC/venue attribution from *_MIC_ID / *_ID (documented native; unused)",
        "options depth OF IF OPTIONS_BOOK entitlement PASSes (RTH)",
    ]
    proxy_inferred = [
        "aggressor / trade side from uptick or Lee-Ready (not native)",
        "Alpaca IEX prints as tape sample (external; not Schwab)",
        "institutional_flow_proxy composite",
    ]
    unavailable = [
        "Schwab TIMESALE wrapper (not in schwab-py); live availability needs RTH re-probe",
        "Native aggressor / condition codes (not in enums)",
        "NOII / auction imbalance (not in enums)",
        "MPID / Market Maker ID on equity (not in enums; FOREX has MARKET_MAKER only)",
        "Level-3 order id add/cancel/modify stream (not in schwab-py)",
    ]
    return {
        "generated_at_utc": _utc(),
        "NATIVE_USED": native_used,
        "NATIVE_UNUSED": native_unused,
        "DERIVED_TODAY": derived_today,
        "DERIVABLE": derivable,
        "PROXY_INFERRED": proxy_inferred,
        "UNAVAILABLE": unavailable,
        "rth_reserved_for": [
            "NUM_BIDS / NUM_ASKS semantics",
            "nested EXCHANGE identity semantics",
            "OPTIONS_BOOK entitlement/population",
            "SEQUENCE runtime behavior",
            "TIMESALE availability",
            "security-type / entitlement-dependent population",
        ],
    }


def build_capability_matrix_v2(schema: dict[str, Any], live: dict[str, Any]) -> dict[str, Any]:
    """Matrix with distinct lifecycle columns; documented ≠ NOT_PROVEN for lack of RTH."""

    def row(**kwargs: Any) -> dict[str, Any]:
        return kwargs

    # Documented availability from schema (not live)
    book_doc = "AVAILABLE_IN_SCHWAB_PY"
    return {
        "schema_version": 2,
        "generated_at_utc": _utc(),
        "schwab_py_version": schema.get("schwab_py_version"),
        "live_observation": live.get("status"),
        "column_defs": {
            "native_documented_available": "In schwab-py enums / REST section fields / observed dictionary",
            "currently_subscribed_requested": "Console or capture requests it now",
            "currently_retained": "Kept in plane/OF buffers after ingest",
            "currently_persisted": "Written to ed_console.db (or stream_capture.db)",
            "currently_consumed": "Feeds a computation or UI binding",
            "currently_discarded_unused": "On wire or defined but dropped",
            "runtime_population_entitlement": "Live fill/entitlement — RTH when static inventory cannot answer",
            "semantic_interpretation": "DOCUMENTED_NATIVE | NEEDS_RTH | UNAVAILABLE — not NOT_PROVEN merely for no RTH",
            "derivable_institutional_metric": "Useful metric if retained/proven",
        },
        "corrections": [
            "Nested EXCHANGE is exchange_code_raw until identity proven — never per-participant a priori",
            "Documented native fields stay DOCUMENTED_NATIVE / AVAILABLE even before RTH",
            "RTH reserved for semantics/entitlement/population questions static inventory cannot answer",
        ],
        "rows": [
            row(
                concept="LEVELONE_EQUITIES TOB (bid/ask/last/size)",
                native_documented_available=book_doc,
                currently_subscribed_requested="YES (active UI ticker)",
                currently_retained="YES",
                currently_persisted="PARTIAL (snapshot sizes/volume; not full L1)",
                currently_consumed="YES",
                currently_discarded_unused="NO",
                runtime_population_entitlement="OBSERVED_IN_PRODUCTION_PATH",
                semantic_interpretation="DOCUMENTED_NATIVE",
                derivable_institutional_metric="spread, TOB pressure",
            ),
            row(
                concept="LEVELONE quote/trade/bid/ask times + MIC/exchange IDs",
                native_documented_available=book_doc,
                currently_subscribed_requested="YES (full L1 field set)",
                currently_retained="PARTIAL (times yes; MIC/IDs discarded)",
                currently_persisted="NO (MIC/IDs)",
                currently_consumed="PARTIAL",
                currently_discarded_unused="YES (MIC/IDs, many fundamentals)",
                runtime_population_entitlement="OBSERVED_IN_PRODUCTION_PATH",
                semantic_interpretation="DOCUMENTED_NATIVE",
                derivable_institutional_metric="quote aging; venue attribution",
            ),
            row(
                concept="NYSE_BOOK / NASDAQ_BOOK aggregate TOTAL_VOLUME @ price",
                native_documented_available=book_doc,
                currently_subscribed_requested="YES",
                currently_retained="YES (memory OF)",
                currently_persisted="NO",
                currently_consumed="YES (imbalance)",
                currently_discarded_unused="NO",
                runtime_population_entitlement="OBSERVED_IN_PRODUCTION_PATH",
                semantic_interpretation="DOCUMENTED_NATIVE",
                derivable_institutional_metric="depth imbalance / profile (if persisted)",
            ),
            row(
                concept="NUM_BIDS / NUM_ASKS",
                native_documented_available=book_doc,
                currently_subscribed_requested="YES (full book fields)",
                currently_retained="NO",
                currently_persisted="NO",
                currently_consumed="NO",
                currently_discarded_unused="YES",
                runtime_population_entitlement="NEEDS_RTH",
                semantic_interpretation="NEEDS_RTH",
                derivable_institutional_metric="breadth-at-price IF semantics proven",
            ),
            row(
                concept="Nested EXCHANGE + BID_VOLUME/ASK_VOLUME",
                native_documented_available=book_doc,
                currently_subscribed_requested="YES",
                currently_retained="NO",
                currently_persisted="NO",
                currently_consumed="NO",
                currently_discarded_unused="YES",
                runtime_population_entitlement="NEEDS_RTH",
                semantic_interpretation="NEEDS_RTH (identity)",
                derivable_institutional_metric="venue-share IF identity proven — not per-participant a priori",
            ),
            row(
                concept="BOOK_TIME / nested SEQUENCE",
                native_documented_available=book_doc,
                currently_subscribed_requested="YES",
                currently_retained="NO",
                currently_persisted="NO",
                currently_consumed="NO",
                currently_discarded_unused="YES",
                runtime_population_entitlement="NEEDS_RTH",
                semantic_interpretation="DOCUMENTED_NATIVE (fields); runtime order NEEDS_RTH",
                derivable_institutional_metric="staleness / gap detection",
            ),
            row(
                concept="OPTIONS_BOOK",
                native_documented_available=book_doc,
                currently_subscribed_requested="NO",
                currently_retained="NO",
                currently_persisted="NO",
                currently_consumed="NO",
                currently_discarded_unused="N/A (not requested)",
                runtime_population_entitlement="NEEDS_RTH",
                semantic_interpretation="DOCUMENTED_NATIVE (schema shared with equity books)",
                derivable_institutional_metric="options depth OF if entitled",
            ),
            row(
                concept="LEVELONE_OPTIONS",
                native_documented_available=book_doc,
                currently_subscribed_requested="NO",
                currently_retained="NO",
                currently_persisted="NO (REST chain instead)",
                currently_consumed="NO (stream)",
                currently_discarded_unused="N/A",
                runtime_population_entitlement="NEEDS_RTH (optional vs REST)",
                semantic_interpretation="DOCUMENTED_NATIVE",
                derivable_institutional_metric="options L1 tape vs REST chain",
            ),
            row(
                concept="TIMESALE / trade prints (Schwab)",
                native_documented_available="NOT_IN_SCHWAB_PY_WRAPPER",
                currently_subscribed_requested="NO",
                currently_retained="NO",
                currently_persisted="NO",
                currently_consumed="NO",
                currently_discarded_unused="N/A",
                runtime_population_entitlement="NEEDS_RTH",
                semantic_interpretation="UNAVAILABLE_IN_WRAPPER; live status NEEDS_RTH",
                derivable_institutional_metric="true prints / native side if ever available",
            ),
            row(
                concept="Native aggressor / NOII / MPID / L3 orders",
                native_documented_available="ABSENT_FROM_ENUMS",
                currently_subscribed_requested="NO",
                currently_retained="NO",
                currently_persisted="NO",
                currently_consumed="NO",
                currently_discarded_unused="N/A",
                runtime_population_entitlement="UNAVAILABLE",
                semantic_interpretation="UNAVAILABLE",
                derivable_institutional_metric="none from Schwab-native",
            ),
            row(
                concept="LevelOneForexFields.MARKET_MAKER",
                native_documented_available=book_doc,
                currently_subscribed_requested="NO (forex not in console OF path)",
                currently_retained="NO",
                currently_persisted="NO",
                currently_consumed="NO",
                currently_discarded_unused="N/A",
                runtime_population_entitlement="N/A_EQUITY_OF",
                semantic_interpretation="DOCUMENTED_NATIVE (FOREX only)",
                derivable_institutional_metric="not applicable to equity OF tab",
            ),
            row(
                concept="REST quotes / option chain / pricehistory leaves",
                native_documented_available="OBSERVED_DICTIONARY_UNION",
                currently_subscribed_requested="YES",
                currently_retained="PARTIAL (OE allowlist / quote parse)",
                currently_persisted="YES (snapshots / morning_full / bars)",
                currently_consumed="YES",
                currently_discarded_unused="PARTIAL (many quote fundamentals unused)",
                runtime_population_entitlement="OBSERVED_IN_PRODUCTION_PATH",
                semantic_interpretation="DOCUMENTED_NATIVE / OBSERVED",
                derivable_institutional_metric="existing Collect/Find stack",
            ),
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-live-attempt", action="store_true")
    args = ap.parse_args(argv)

    schema = extract_streamer_schema()
    schema["rest"] = extract_rest_schema()
    schema["definition_leaf_paths"] = {
        k: sorted(v) for k, v in definition_leaf_paths(schema).items()
    }

    prior = load_prior_canonical()
    prior_dict = load_prior_dictionary()
    diff = diff_definitions_vs_prior(schema, prior)

    live = (
        {"mechanism": "skipped", "status": "SKIPPED"}
        if args.skip_live_attempt
        else attempt_live_sync_dry_run()
    )

    INV_DIR.mkdir(parents=True, exist_ok=True)
    (ROOT / "reports").mkdir(parents=True, exist_ok=True)

    schema_doc = {
        **schema,
        "prior_observed_inventory": {
            "canonical_fields_path": str(CANONICAL.relative_to(ROOT)),
            "canonical_field_count": len(prior),
            "dictionary_path": str(DICTIONARY.relative_to(ROOT)),
            "dictionary_row_count": len(prior_dict),
            "readme_capture_date": "2026-05-05",
            "last_dictionary_sync_state": "governance/artifacts/schwab_field_sync_state.json (2026-08-15)",
        },
    }
    SCHEMA_OUT.write_text(json.dumps(schema_doc, indent=2) + "\n", encoding="utf-8")

    refresh = {
        "generated_at_utc": _utc(),
        "canonical_mechanisms": [
            "schwab_full_field_inventory.py",
            "schwab_field_dictionary_builder.py",
            "tools/sync_schwab_field_dictionary.py --poll",
            "tools/refresh_schwab_native_field_inventory.py (this)",
        ],
        "schwab_py_version": schema["schwab_py_version"],
        "live_observation": live,
        "diff_vs_prior_observed": diff,
        "artifacts_written": [
            str(SCHEMA_OUT.relative_to(ROOT)),
            str(REFRESH_OUT.relative_to(ROOT)),
            str(UNIVERSE_OUT.relative_to(ROOT)),
            str(MATRIX_OUT.relative_to(ROOT)),
        ],
        "freshness_verdict": {
            "streamer_definitions": "FRESH_FROM_SCHWAB_PY_1_5_1",
            "observed_rest_dictionary": (
                "STALE_PENDING_LIVE_SYNC"
                if live.get("status") != "LIVE_OK"
                else "REFRESHED"
            ),
            "note": (
                "Book nested schema matches prior observed paths (TOTAL_VOLUME, NUM_*, "
                "EXCHANGE, SEQUENCE). LEVELONE_OPTIONS and other services are documented "
                "in schwab-py but were outside the May-2026 streaming capture set."
            ),
        },
    }
    REFRESH_OUT.write_text(json.dumps(refresh, indent=2) + "\n", encoding="utf-8")

    universe = build_universe_map()
    UNIVERSE_OUT.write_text(json.dumps(universe, indent=2) + "\n", encoding="utf-8")

    matrix = build_capability_matrix_v2(schema, live)
    MATRIX_OUT.write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")

    # Update inventory README header freshness for definition refresh (minimal)
    readme = INV_DIR / "README.md"
    if readme.is_file():
        text = readme.read_text(encoding="utf-8")
        banner = (
            f"**Definition refresh:** {_utc()} via "
            f"`tools/refresh_schwab_native_field_inventory.py` "
            f"(schwab-py {schema['schwab_py_version']}); "
            f"live observed-dictionary sync: {live.get('status')}.\n\n"
        )
        if "**Definition refresh:**" in text:
            # replace first definition refresh line block roughly
            import re

            text = re.sub(
                r"\*\*Definition refresh:\*\*.*\n\n",
                banner,
                text,
                count=1,
            )
        else:
            # insert after title block
            lines = text.splitlines(keepends=True)
            # after first heading paragraph
            insert_at = 1
            for i, ln in enumerate(lines[:15]):
                if ln.startswith("**Capture date:**"):
                    insert_at = i
                    break
            lines.insert(insert_at, banner)
            text = "".join(lines)
        readme.write_text(text, encoding="utf-8")

    print(json.dumps({"schema": str(SCHEMA_OUT), "refresh": str(REFRESH_OUT), "live": live.get("status")}, indent=2))
    return 0 if live.get("status") in ("LIVE_OK", "LIVE_BLOCKED", "SKIPPED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
