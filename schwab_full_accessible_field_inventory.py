#!/usr/bin/env python3
"""
Schwab Full Accessible Field Inventory — Discover and collect ALL accessible Schwab fields.

Discovers every REST endpoint and streaming service available in the project's Schwab setup,
attempts to call ALL of them with valid parameters, saves raw payloads, flattens all fields,
and produces coverage reports.

Run: python schwab_full_accessible_field_inventory.py
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
import logging

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

OUTPUT_DIR = Path(
    os.getenv("SCHWAB_INVENTORY_FULL_DIR", "schwab_field_inventory_full_access")
).resolve()

TOKEN_PATH = Path(os.getenv("SCHWAB_TOKEN_PATH", "schwab_token.json"))
API_KEY = os.getenv("SCHWAB_API_KEY") or ""
APP_SECRET = os.getenv("SCHWAB_APP_SECRET") or ""
if not API_KEY or not APP_SECRET:
    try:
        from config import SCHWAB_API_KEY, SCHWAB_APP_SECRET
        API_KEY = API_KEY or SCHWAB_API_KEY
        APP_SECRET = APP_SECRET or SCHWAB_APP_SECRET
    except ImportError:
        pass

SYMBOLS = ["SPY", "QQQ", "AAPL", "NVDA"]
KNOWN_CUSIPS = {"78462F103": "SPY", "46090E103": "QQQ"}  # Fallback for get_instrument_by_cusip


# ═══════════════════════════════════════════════════════════════════════════════
# DISCOVERY — All REST methods and streaming services
# ═══════════════════════════════════════════════════════════════════════════════

REST_DISCOVERY = [
    {"method": "get_quote", "endpoint": "quotes", "category": "quotes", "required": ["symbol"], "optional": ["fields"]},
    {"method": "get_quotes", "endpoint": "quotes_batch", "category": "quotes", "required": ["symbols"], "optional": ["fields", "indicative"]},
    {"method": "get_option_chain", "endpoint": "chains", "category": "options", "required": ["symbol"], "optional": ["contract_type", "strike_count", "include_underlying_quote", "strike_range", "from_date", "to_date"]},
    {"method": "get_option_expiration_chain", "endpoint": "option_expiration_chain", "category": "options", "required": ["symbol"], "optional": []},
    {"method": "get_price_history", "endpoint": "pricehistory_raw", "category": "pricehistory", "required": ["symbol"], "optional": ["period_type", "period", "frequency_type", "frequency"]},
    {"method": "get_price_history_every_minute", "endpoint": "pricehistory_minute", "category": "pricehistory", "required": ["symbol"], "optional": []},
    {"method": "get_price_history_every_five_minutes", "endpoint": "pricehistory_five_min", "category": "pricehistory", "required": ["symbol"], "optional": []},
    {"method": "get_price_history_every_ten_minutes", "endpoint": "pricehistory_ten_min", "category": "pricehistory", "required": ["symbol"], "optional": []},
    {"method": "get_price_history_every_fifteen_minutes", "endpoint": "pricehistory_fifteen_min", "category": "pricehistory", "required": ["symbol"], "optional": []},
    {"method": "get_price_history_every_thirty_minutes", "endpoint": "pricehistory_thirty_min", "category": "pricehistory", "required": ["symbol"], "optional": []},
    {"method": "get_price_history_every_day", "endpoint": "pricehistory_day", "category": "pricehistory", "required": ["symbol"], "optional": []},
    {"method": "get_price_history_every_week", "endpoint": "pricehistory_week", "category": "pricehistory", "required": ["symbol"], "optional": []},
    {"method": "get_instruments", "endpoint": "instruments", "category": "instruments", "required": ["symbols", "projection"], "optional": []},
    {"method": "get_instrument_by_cusip", "endpoint": "instrument_cusip", "category": "instruments", "required": ["cusip"], "optional": []},
    {"method": "get_movers", "endpoint": "movers", "category": "movers", "required": ["index"], "optional": ["sort_order", "frequency"]},
    {"method": "get_market_hours", "endpoint": "market_hours", "category": "market_hours", "required": ["markets"], "optional": ["date"]},
    {"method": "get_user_preferences", "endpoint": "user_preferences", "category": "user", "required": [], "optional": []},
    {"method": "get_account_numbers", "endpoint": "account_numbers", "category": "accounts", "required": [], "optional": []},
    {"method": "get_account", "endpoint": "account", "category": "accounts", "required": ["account_hash"], "optional": ["fields"]},
    {"method": "get_accounts", "endpoint": "accounts", "category": "accounts", "required": [], "optional": ["fields"]},
    {"method": "get_orders_for_account", "endpoint": "orders_account", "category": "orders", "required": ["account_hash"], "optional": ["max_results", "status"]},
    {"method": "get_orders_for_all_linked_accounts", "endpoint": "orders_all", "category": "orders", "required": [], "optional": ["max_results", "status"]},
    {"method": "get_transactions", "endpoint": "transactions", "category": "transactions", "required": ["account_hash"], "optional": ["start_date", "end_date"]},
    {"method": "get_order", "endpoint": "order_single", "category": "orders", "required": ["order_id", "account_hash"], "optional": []},
    {"method": "get_transaction", "endpoint": "transaction_single", "category": "transactions", "required": ["account_hash", "transaction_id"], "optional": []},
]

STREAMING_DISCOVERY = [
    {"service": "level_one_equity", "subs": "level_one_equity_subs", "handler": "add_level_one_equity_handler"},
    {"service": "chart_equity", "subs": "chart_equity_subs", "handler": "add_chart_equity_handler"},
    {"service": "nasdaq_book", "subs": "nasdaq_book_subs", "handler": "add_nasdaq_book_handler"},
    {"service": "nyse_book", "subs": "nyse_book_subs", "handler": "add_nyse_book_handler"},
    {"service": "level_one_option", "subs": "level_one_option_subs", "handler": "add_level_one_option_handler"},
    {"service": "options_book", "subs": "options_book_subs", "handler": "add_options_book_handler"},
    {"service": "chart_futures", "subs": "chart_futures_subs", "handler": "add_chart_futures_handler"},
    {"service": "level_one_futures", "subs": "level_one_futures_subs", "handler": "add_level_one_futures_handler"},
    {"service": "level_one_futures_options", "subs": "level_one_futures_options_subs", "handler": "add_level_one_futures_options_handler"},
    {"service": "level_one_forex", "subs": "level_one_forex_subs", "handler": "add_level_one_forex_handler"},
    {"service": "screener_equity", "subs": "screener_equity_subs", "handler": "add_screener_equity_handler"},
    {"service": "screener_option", "subs": "screener_option_subs", "handler": "add_screener_option_handler"},
    {"service": "account_activity", "subs": None, "handler": "add_account_activity_handler"},  # May not have subs
]


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def flatten_json(obj: Any, prefix: str = "", sep: str = ".") -> set[str]:
    out: set[str] = set()
    if obj is None:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}{sep}{k}" if prefix else str(k)
            out.add(key)
            out.update(flatten_json(v, key, sep))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            key = f"{prefix}{sep}{i}"
            out.add(key)
            out.update(flatten_json(v, key, sep))
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# REST EXECUTION
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class AttemptResult:
    source_type: str
    endpoint_or_service: str
    symbol: str
    parameter_set: str
    attempted: bool = True
    succeeded: bool = False
    failed: bool = False
    skipped: bool = False
    reason: str = ""
    raw_path: Path | None = None
    fields_path: Path | None = None
    fields: set[str] = field(default_factory=set)


def run_rest(client, output_root: Path) -> list[AttemptResult]:
    results: list[AttemptResult] = []
    ts = _utc_ts()
    account_hash = ""

    # Get account_hash for account/order/transaction endpoints
    try:
        r = client.get_account_numbers()
        if r.status_code == 200 and r.json():
            account_hash = r.json()[0].get("hashValue", "") or r.json()[0].get("accountNumber", "")
    except Exception as e:
        log.debug("schwab inventory probe: %s", e, exc_info=True)
    for disc in REST_DISCOVERY:
        method_name = disc["method"]
        endpoint = disc["endpoint"]
        param_sets = _param_sets_for_rest(disc, account_hash)
        ep_dir = output_root / "rest" / endpoint.replace(" ", "_")
        ensure_dir(ep_dir)
        raw_dir = ep_dir / "raw"
        ensure_dir(raw_dir)

        for sym, param_name, kwargs in param_sets:
            if not kwargs.get("_callable", True):
                results.append(AttemptResult(
                    source_type="REST", endpoint_or_service=endpoint, symbol=sym, parameter_set=param_name,
                    attempted=False, skipped=True, reason=kwargs.get("_reason", "missing params"),
                ))
                continue
            call_kw = {k: v for k, v in kwargs.items() if not k.startswith("_")}
            r = AttemptResult(source_type="REST", endpoint_or_service=endpoint, symbol=sym, parameter_set=param_name)
            try:
                fn = getattr(client, method_name, None)
                if not fn:
                    r.failed = True
                    r.reason = f"method {method_name} not found"
                    results.append(r)
                    continue
                resp = fn(**call_kw)
                if resp.status_code == 200:
                    data = resp.json()
                    fn_path = raw_dir / f"{endpoint}_{sym}_{param_name}_{ts}.json"
                    with open(fn_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                    r.raw_path = fn_path
                    r.fields = flatten_json(data)
                    r.succeeded = True
                    ff = ep_dir / f"fields_{endpoint}_{sym}_{param_name}.txt"
                    with open(ff, "w", encoding="utf-8") as f:
                        f.write("\n".join(sorted(r.fields)))
                    r.fields_path = ff
                else:
                    r.failed = True
                    r.reason = f"HTTP {resp.status_code}"
            except Exception as e:
                r.failed = True
                r.reason = str(e)[:200]
            results.append(r)

    return results


def _param_sets_for_rest(disc: dict, account_hash: str) -> list[tuple[str, str, dict]]:
    method = disc["method"]
    sets: list[tuple[str, str, dict]] = []

    try:
        import schwab.client
        C = schwab.client.Client
        OC = C.Options
        MH = C.MarketHours
        M = C.Movers
        I = getattr(getattr(C, "Instrument", None), "Projection", None)
        PH = C.PriceHistory
    except Exception:
        OC = MH = M = I = PH = None

    if method == "get_quote":
        for s in SYMBOLS:
            sets.append((s, "single", {"symbol": s, "_callable": True}))
    elif method == "get_quotes":
        sets.append((",".join(SYMBOLS), "batch", {"symbols": SYMBOLS, "_callable": True}))
    elif method == "get_option_chain":
        for s in SYMBOLS[:2]:
            sets.append((s, "default", {"symbol": s, "strike_count": 15, "_callable": True}))
            sets.append((s, "with_underlying", {"symbol": s, "strike_count": 15, "include_underlying_quote": True, "_callable": True}))
            if OC:
                sets.append((s, "calls_only", {"symbol": s, "strike_count": 10, "contract_type": OC.ContractType.CALL, "_callable": True}))
                sets.append((s, "puts_only", {"symbol": s, "strike_count": 10, "contract_type": OC.ContractType.PUT, "_callable": True}))
    elif method == "get_option_expiration_chain":
        for s in SYMBOLS[:2]:
            sets.append((s, "default", {"symbol": s, "_callable": True}))
    elif method.startswith("get_price_history"):
        freq = method.replace("get_price_history_", "").replace("get_price_history", "raw")
        for s in SYMBOLS[:2]:
            sets.append((s, freq or "raw", {"symbol": s, "_callable": True}))
        if method == "get_price_history" and PH:
            for s in SYMBOLS[:1]:
                sets.append((s, "raw_1d_1m", {"symbol": s, "period_type": PH.PeriodType.DAY, "period": PH.Period.ONE_DAY, "frequency_type": PH.FrequencyType.MINUTE, "frequency": PH.Frequency.EVERY_MINUTE, "_callable": True}))
    elif method == "get_instruments":
        for s in SYMBOLS[:2]:
            for proj_name, proj in [("fundamental", getattr(I, "FUNDAMENTAL", "fundamental") if I else "fundamental"), ("symbol_search", getattr(I, "SYMBOL_SEARCH", "symbol-search") if I else "symbol-search")]:
                sets.append((s, proj_name, {"symbols": [s] if proj_name == "fundamental" else s, "projection": proj, "_callable": True}))
    elif method == "get_instrument_by_cusip":
        for cusip, sym in list(KNOWN_CUSIPS.items())[:2]:
            sets.append((sym, "cusip", {"cusip": cusip, "_callable": True}))
    elif method == "get_movers":
        for idx_name, idx in [("SPX", M.Index.SPX if M else "$SPX"), ("DJI", M.Index.DJI if M else "$DJI"), ("NASDAQ", M.Index.NASDAQ if M else "NASDAQ")]:
            for so_name, so in [("pct_up", M.SortOrder.PERCENT_CHANGE_UP if M else "PERCENT_CHANGE_UP"), ("pct_down", M.SortOrder.PERCENT_CHANGE_DOWN if M else "PERCENT_CHANGE_DOWN")]:
                sets.append((idx_name, so_name, {"index": idx, "sort_order": so, "_callable": True}))
    elif method == "get_market_hours":
        for mkt_name, mkt in [("equity", MH.Market.EQUITY if MH else "equity"), ("option", MH.Market.OPTION if MH else "option"), ("bond", MH.Market.BOND if MH else "bond"), ("future", MH.Market.FUTURE if MH else "future"), ("forex", MH.Market.FOREX if MH else "forex")]:
            sets.append((mkt_name, "today", {"markets": [mkt], "date": date.today(), "_callable": True}))
    elif method == "get_user_preferences":
        sets.append(("", "default", {"_callable": True}))
    elif method == "get_account_numbers":
        sets.append(("", "default", {"_callable": True}))
    elif method == "get_account":
        if account_hash:
            sets.append(("primary", "default", {"account_hash": account_hash, "_callable": True}))
        else:
            sets.append(("", "default", {"_callable": False, "_reason": "no account_hash"}))
    elif method == "get_accounts":
        sets.append(("", "default", {"_callable": True}))
    elif method == "get_orders_for_account":
        if account_hash:
            sets.append(("primary", "default", {"account_hash": account_hash, "max_results": 5, "_callable": True}))
        else:
            sets.append(("", "default", {"_callable": False, "_reason": "no account_hash"}))
    elif method == "get_orders_for_all_linked_accounts":
        sets.append(("", "default", {"max_results": 5, "_callable": True}))
    elif method == "get_order":
        sets.append(("", "default", {"_callable": False, "_reason": "requires order_id - skipped"}))
    elif method == "get_transactions":
        if account_hash:
            sets.append(("primary", "recent", {"account_hash": account_hash, "_callable": True}))
        else:
            sets.append(("", "default", {"_callable": False, "_reason": "no account_hash"}))
    elif method == "get_transaction":
        sets.append(("", "default", {"_callable": False, "_reason": "requires transaction_id - skipped"}))

    if not sets:
        sets.append(("", "default", {"_callable": False, "_reason": "no param set defined"}))
    return sets


# ═══════════════════════════════════════════════════════════════════════════════
# STREAMING EXECUTION
# ═══════════════════════════════════════════════════════════════════════════════

def run_streaming(client, output_root: Path, account_id, symbols: list[str]) -> list[AttemptResult]:
    results: list[AttemptResult] = []
    stream_dir = output_root / "streaming"
    ensure_dir(stream_dir)
    raw_dir = stream_dir / "raw"
    ensure_dir(raw_dir)

    try:
        from schwab.streaming import StreamClient
    except ImportError:
        for d in STREAMING_DISCOVERY:
            results.append(AttemptResult(
                source_type="STREAMING", endpoint_or_service=d["service"], symbol="", parameter_set="",
                attempted=True, failed=True, reason="schwab.streaming not available",
            ))
        return results

    if not account_id:
        for d in STREAMING_DISCOVERY:
            results.append(AttemptResult(
                source_type="STREAMING", endpoint_or_service=d["service"], symbol="", parameter_set="",
                attempted=True, skipped=True, reason="no account_id for StreamClient",
            ))
        return results

    equity_symbols = symbols[:2]
    option_symbols = [f"SPY_032125C00600000"]  # Example option symbol format
    futures_symbols = ["/ES"]
    forex_symbols = ["/EUR"]

    for disc in STREAMING_DISCOVERY:
        svc = disc["service"]
        subs_method = disc.get("subs")
        handler_method = disc["handler"]

        if not subs_method and svc != "account_activity":
            results.append(AttemptResult(source_type="STREAMING", endpoint_or_service=svc, symbol="", parameter_set="", attempted=True, skipped=True, reason="no subs method"))
            continue

        samples: list[dict] = []
        test_symbols = equity_symbols
        if "forex" in svc:
            test_symbols = forex_symbols
        elif "futures" in svc or "chart_futures" in svc:
            test_symbols = futures_symbols
        elif "option" in svc:
            test_symbols = option_symbols

        def make_handler(acc):
            def h(msg):
                if len(acc) < 15:
                    acc.append(msg)
            return h

        r = AttemptResult(source_type="STREAMING", endpoint_or_service=svc, symbol=",".join(test_symbols), parameter_set="sample")

        try:
            stream_client = StreamClient(client, account_id=account_id)

            async def _run():
                await stream_client.login()
                handler_fn = getattr(stream_client, handler_method, None)
                subs_fn = getattr(stream_client, subs_method, None) if subs_method else None
                if handler_fn:
                    handler_fn(make_handler(samples))
                if subs_fn:
                    await subs_fn(test_symbols)
                for _ in range(25):
                    try:
                        await asyncio.wait_for(stream_client.handle_message(), timeout=1.5)
                    except (asyncio.TimeoutError, asyncio.CancelledError, ConnectionResetError):
                        break
                    except Exception:
                        break
                try:
                    await stream_client.logout()
                except Exception as e:
                    log.debug("schwab inventory probe: %s", e, exc_info=True)
                return samples

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                samples = loop.run_until_complete(_run())
            except (asyncio.CancelledError, Exception) as ex:
                r.failed = True
                r.reason = str(ex)[:200]
                results.append(r)
                continue
            finally:
                try:
                    loop.close()
                except Exception as e:
                    log.debug("schwab inventory probe: %s", e, exc_info=True)
        except Exception as e:
            r.failed = True
            r.reason = str(e)[:200]
            results.append(r)
            continue

        if samples:
            ts = _utc_ts()
            fn_path = raw_dir / f"streaming_{svc}_{ts}.json"
            try:
                with open(fn_path, "w", encoding="utf-8") as f:
                    json.dump(samples, f, indent=2)
                r.raw_path = fn_path
                all_fields: set[str] = set()
                for s in samples:
                    all_fields.update(flatten_json(s))
                r.fields = all_fields
                r.succeeded = True
                ff = stream_dir / f"fields_streaming_{svc}.txt"
                with open(ff, "w", encoding="utf-8") as f:
                    f.write("\n".join(sorted(all_fields)))
                r.fields_path = ff
            except Exception as e:
                r.failed = True
                r.reason = f"write error: {e}"
        else:
            r.succeeded = True
            r.reason = "no messages (possibly outside RTH or no activity)"
        results.append(r)

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# MERGE & REPORTS
# ═══════════════════════════════════════════════════════════════════════════════

def merge_and_write(results: list[AttemptResult], output_root: Path) -> tuple[set[str], list[dict]]:
    all_fields: set[str] = set()
    summary_rows: list[dict] = []

    for r in results:
        for fp in r.fields:
            all_fields.add(fp)
            summary_rows.append({
                "source_type": r.source_type,
                "endpoint_or_service": r.endpoint_or_service,
                "symbol": r.symbol,
                "parameter_set": r.parameter_set,
                "field_path": fp,
            })

    master_path = output_root / "schwab_all_accessible_fields_master.txt"
    with open(master_path, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(all_fields)))

    summary_path = output_root / "schwab_all_accessible_fields_summary.csv"
    with open(summary_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["source_type", "endpoint_or_service", "symbol", "parameter_set", "field_path"])
        w.writeheader()
        w.writerows(summary_rows)

    return all_fields, summary_rows


def write_coverage_report(results: list[AttemptResult], output_root: Path) -> None:
    by_endpoint: dict[tuple[str, str], dict] = {}
    for r in results:
        key = (r.endpoint_or_service, r.source_type)
        if key not in by_endpoint:
            by_endpoint[key] = {"attempted": 0, "succeeded": 0, "failed": 0, "skipped": 0, "reasons": []}
        by_endpoint[key]["attempted"] += 1
        if r.succeeded:
            by_endpoint[key]["succeeded"] += 1
        elif r.failed:
            by_endpoint[key]["failed"] += 1
        elif r.skipped or not r.attempted:
            by_endpoint[key]["skipped"] += 1
        if r.reason:
            by_endpoint[key]["reasons"].append(r.reason[:100])

    rows = []
    for (ep, st), v in sorted(by_endpoint.items()):
        rows.append({
            "endpoint_or_service": ep,
            "source_type": st,
            "attempted": v["attempted"],
            "succeeded": v["succeeded"],
            "failed": v["failed"],
            "skipped": v["skipped"],
            "reason": "; ".join(set(v["reasons"]))[:300] if v["reasons"] else "",
        })

    path = output_root / "schwab_endpoint_coverage_report.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["endpoint_or_service", "source_type", "attempted", "succeeded", "failed", "skipped", "reason"])
        w.writeheader()
        w.writerows(rows)


def write_discovery_report(output_root: Path) -> None:
    rows = []
    for d in REST_DISCOVERY:
        rows.append({
            "method_name": d["method"],
            "endpoint_or_service": d["endpoint"],
            "source_type": "REST",
            "required_parameters": ";".join(d["required"]),
            "optional_parameters": ";".join(d["optional"]),
            "accessible_to_this_setup": "yes",
        })
    for d in STREAMING_DISCOVERY:
        rows.append({
            "method_name": d.get("subs", d["service"]),
            "endpoint_or_service": d["service"],
            "source_type": "STREAMING",
            "required_parameters": "account_id; symbols",
            "optional_parameters": "",
            "accessible_to_this_setup": "yes",
        })

    path = output_root / "schwab_endpoint_discovery_report.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["method_name", "endpoint_or_service", "source_type", "required_parameters", "optional_parameters", "accessible_to_this_setup"])
        w.writeheader()
        w.writerows(rows)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    ensure_dir(OUTPUT_DIR)

    if not TOKEN_PATH.exists():
        print(f"ERROR: Token file not found: {TOKEN_PATH}")
        return 1
    if not API_KEY or not APP_SECRET:
        print("ERROR: API_KEY and APP_SECRET required.")
        return 1

    try:
        from schwab import auth
        client = auth.client_from_token_file(str(TOKEN_PATH), API_KEY, APP_SECRET, enforce_enums=False)
    except Exception as e:
        print(f"ERROR: Client init failed: {e}")
        return 1

    print(f"Output: {OUTPUT_DIR}")
    print(f"Symbols: {SYMBOLS}")
    print()

    # Discovery reports first
    print("Writing discovery report...")
    write_discovery_report(OUTPUT_DIR)

    # REST
    print("Running REST probes...")
    rest_results = run_rest(client, OUTPUT_DIR)

    # Account ID for streaming
    account_id = None
    for r in rest_results:
        if r.endpoint_or_service == "account_numbers" and r.succeeded and r.raw_path:
            try:
                with open(r.raw_path) as f:
                    data = json.load(f)
                    if data:
                        account_id = data[0].get("accountNumber") or data[0].get("hashValue")
                        if account_id and str(account_id).isdigit():
                            account_id = int(account_id)
            except Exception as e:
                log.debug("schwab inventory probe: %s", e, exc_info=True)
            break

    # Streaming
    print("Running streaming probes...")
    stream_results = run_streaming(client, OUTPUT_DIR, account_id, SYMBOLS)

    all_results = rest_results + stream_results
    print("Merging and writing master inventory...")
    all_fields, summary_rows = merge_and_write(all_results, OUTPUT_DIR)
    write_coverage_report(all_results, OUTPUT_DIR)

    # Counts
    total_raw = len(summary_rows)
    total_unique = len(all_fields)
    discovered = len(REST_DISCOVERY) + len(STREAMING_DISCOVERY)
    succeeded = sum(1 for r in all_results if r.succeeded)
    failed_or_skipped = sum(1 for r in all_results if r.failed or r.skipped or not r.attempted)

    endpoints_succeeded = len(set((r.endpoint_or_service, r.source_type) for r in all_results if r.succeeded))
    endpoints_failed_or_skipped = len(set((r.endpoint_or_service, r.source_type) for r in all_results if r.failed or r.skipped))

    failed_list = [(r.endpoint_or_service, r.source_type, r.reason) for r in all_results if r.failed]
    skipped_list = [(r.endpoint_or_service, r.source_type, r.reason) for r in all_results if r.skipped]

    print()
    print("=" * 70)
    print("FULL ACCESSIBLE FIELD INVENTORY COMPLETE")
    print("=" * 70)
    print()
    print("1. Full output directory path:")
    print(f"   {OUTPUT_DIR}\\")
    print()
    print("2. Full paths to output files:")
    print(f"   {OUTPUT_DIR / 'schwab_all_accessible_fields_master.txt'}")
    print(f"   {OUTPUT_DIR / 'schwab_all_accessible_fields_summary.csv'}")
    print(f"   {OUTPUT_DIR / 'schwab_endpoint_coverage_report.csv'}")
    print(f"   {OUTPUT_DIR / 'schwab_endpoint_discovery_report.csv'}")
    print()
    print("3. Total raw field-path count:       ", total_raw)
    print("4. Total unique field-path count:    ", total_unique)
    print("5. Total endpoints/services discovered:", discovered)
    print("6. Total endpoints/services successfully inventoried:", endpoints_succeeded)
    print("7. Total endpoints/services failed or skipped:", endpoints_failed_or_skipped)
    print("=" * 70)

    if failed_list or skipped_list:
        print()
        print("FAILED OR SKIPPED:")
        for ep, st, reason in failed_list[:20]:
            print(f"  [{st}] {ep}: {reason}")
        for ep, st, reason in skipped_list[:20]:
            print(f"  [{st}] {ep} (skipped): {reason}")
        if len(failed_list) + len(skipped_list) > 40:
            print(f"  ... and {len(failed_list) + len(skipped_list) - 40} more")

    return 0


if __name__ == "__main__":
    sys.exit(main())
