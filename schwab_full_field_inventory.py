#!/usr/bin/env python3
"""
Schwab Full Field Inventory — Extract ALL accessible fields from Schwab market data.

Single utility that:
- Calls all relevant REST market-data endpoints
- Optionally connects to streaming and captures sample payloads
- Saves raw JSON, flattened field lists, merged master catalog
- Writes schwab_all_fields_master.txt and schwab_field_inventory_summary.csv

Run: python schwab_full_field_inventory.py
"""

from __future__ import annotations

import csv
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Any
import logging

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

# Token path — OAuth token file from Schwab login flow
# Override with SCHWAB_TOKEN_PATH env var, or use project default
_TOKEN_PATH = os.getenv("SCHWAB_TOKEN_PATH", "schwab_token.json")
ACCESS_TOKEN_PATH = Path(_TOKEN_PATH)

# Output directory — all inventory files written here
OUTPUT_DIR = Path(os.getenv("SCHWAB_INVENTORY_OUTPUT_DIR", "schwab_field_inventory"))

# Symbols to probe — multiple symbols expose conditional/optional fields
SYMBOLS = ["SPY", "QQQ", "AAPL", "NVDA"]

# Enable streaming — connect and capture sample Level One / book payloads
ENABLE_STREAMING = True

# API credentials — used to build client from token file
# Prefer env vars; fallback to project config if available
API_KEY = os.getenv("SCHWAB_API_KEY")
APP_SECRET = os.getenv("SCHWAB_APP_SECRET")
if not API_KEY or not APP_SECRET:
    try:
        from config import build_config

        _cfg = build_config(str(Path(__file__).resolve().parent))
        API_KEY = API_KEY or _cfg.api_key
        APP_SECRET = APP_SECRET or _cfg.app_secret
    except (ImportError, RuntimeError):
        pass
if not API_KEY or not APP_SECRET:
    API_KEY = os.getenv("SCHWAB_API_KEY", "")
    APP_SECRET = os.getenv("SCHWAB_APP_SECRET", "")


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def flatten_json(obj: Any, prefix: str = "", sep: str = ".") -> set[str]:
    """Recursively flatten nested dict/list into dot paths. Returns set of field paths."""
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
# INVENTORY RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ProbeResult:
    endpoint: str
    symbol: str
    parameter_set: str
    ok: bool
    raw_path: Path | None = None
    fields_path: Path | None = None
    fields: set[str] = field(default_factory=set)
    error: str | None = None


def run_rest_probes(client, output_root: Path, symbols: list[str]) -> list[ProbeResult]:
    """Call all REST market-data endpoints and save raw + flattened fields."""
    results: list[ProbeResult] = []
    ts = _utc_ts()

    # ── 1. QUOTES ───────────────────────────────────────────────────────────
    quote_dir = output_root / "quotes"
    ensure_dir(quote_dir)
    raw_quote = quote_dir / "raw"
    ensure_dir(raw_quote)

    for sym in symbols:
        r = ProbeResult(endpoint="quotes", symbol=sym, parameter_set="single", ok=False)
        try:
            resp = client.get_quote(sym)
            if resp.status_code == 200:
                data = resp.json()
                fn = raw_quote / f"quote_{sym}_{ts}.json"
                with open(fn, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                r.raw_path = fn
                r.fields = flatten_json(data)
                r.ok = True
                ff = quote_dir / f"fields_quote_{sym}.txt"
                with open(ff, "w", encoding="utf-8") as f:
                    f.write("\n".join(sorted(r.fields)))
                r.fields_path = ff
            else:
                r.error = f"HTTP {resp.status_code}"
        except Exception as e:
            r.error = str(e)
        results.append(r)

    # Batch quotes
    r = ProbeResult(endpoint="quotes", symbol=",".join(symbols), parameter_set="batch", ok=False)
    try:
        resp = client.get_quotes(symbols)
        if resp.status_code == 200:
            data = resp.json()
            fn = raw_quote / f"quotes_batch_{ts}.json"
            with open(fn, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            r.raw_path = fn
            r.fields = flatten_json(data)
            r.ok = True
            ff = quote_dir / "fields_quotes_batch.txt"
            with open(ff, "w", encoding="utf-8") as f:
                f.write("\n".join(sorted(r.fields)))
            r.fields_path = ff
        else:
            r.error = f"HTTP {resp.status_code}"
    except Exception as e:
        r.error = str(e)
    results.append(r)

    # ── 2. OPTION CHAINS ────────────────────────────────────────────────────
    chain_dir = output_root / "chains"
    ensure_dir(chain_dir)
    raw_chain = chain_dir / "raw"
    ensure_dir(raw_chain)

    try:
        import schwab.client
        OC = getattr(schwab.client.Client.Options, "ContractType", None)
        chain_param_sets = [
            ("default", {}),
            ("with_underlying", {"include_underlying_quote": True}),
        ]
        if OC:
            chain_param_sets.extend([
                ("calls_only", {"contract_type": OC.CALL}),
                ("puts_only", {"contract_type": OC.PUT}),
            ])
    except Exception:
        chain_param_sets = [
            ("default", {}),
            ("with_underlying", {"include_underlying_quote": True}),
        ]

    for sym in symbols[:2]:
        for param_set, chain_kw in chain_param_sets:
            r = ProbeResult(endpoint="chains", symbol=sym, parameter_set=param_set, ok=False)
            try:
                kw = {"strike_count": 15, **chain_kw}
                resp = client.get_option_chain(sym, **kw)
                if resp.status_code == 200:
                    data = resp.json()
                    fn = raw_chain / f"chain_{sym}_{param_set}_{ts}.json"
                    with open(fn, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                    r.raw_path = fn
                    r.fields = flatten_json(data)
                    r.ok = True
                    ff = chain_dir / f"fields_chain_{sym}_{param_set}.txt"
                    with open(ff, "w", encoding="utf-8") as f:
                        f.write("\n".join(sorted(r.fields)))
                    r.fields_path = ff
                else:
                    r.error = f"HTTP {resp.status_code}"
            except Exception as e:
                r.error = str(e)
            results.append(r)

    # ── 3. PRICE HISTORY ───────────────────────────────────────────────────
    ph_dir = output_root / "pricehistory"
    ensure_dir(ph_dir)
    raw_ph = ph_dir / "raw"
    ensure_dir(raw_ph)

    freq_sets = {
        "SPY": ["minute", "five_min", "ten_min", "thirty_min", "day", "week"],
        "QQQ": ["minute", "five_min", "day"],
    }
    freq_methods = {
        "minute": "get_price_history_every_minute",
        "five_min": "get_price_history_every_five_minutes",
        "ten_min": "get_price_history_every_ten_minutes",
        "thirty_min": "get_price_history_every_thirty_minutes",
        "day": "get_price_history_every_day",
        "week": "get_price_history_every_week",
    }
    for sym in symbols:
        freqs = freq_sets.get(sym, ["minute", "five_min", "day"])
        for freq_name in freqs:
            method = freq_methods.get(freq_name, "get_price_history_every_minute")
            r = ProbeResult(endpoint="pricehistory", symbol=sym, parameter_set=freq_name, ok=False)
            try:
                m = getattr(client, method, None)
                if m:
                    resp = m(sym)
                    if resp.status_code == 200:
                        data = resp.json()
                        fn = raw_ph / f"ph_{sym}_{freq_name}_{ts}.json"
                        with open(fn, "w", encoding="utf-8") as f:
                            json.dump(data, f, indent=2)
                        r.raw_path = fn
                        r.fields = flatten_json(data)
                        r.ok = True
                        ff = ph_dir / f"fields_ph_{sym}_{freq_name}.txt"
                        with open(ff, "w", encoding="utf-8") as f:
                            f.write("\n".join(sorted(r.fields)))
                        r.fields_path = ff
                    else:
                        r.error = f"HTTP {resp.status_code}"
            except Exception as e:
                r.error = str(e)
            results.append(r)

    # ── 4. INSTRUMENTS (FUNDAMENTAL, SEARCH) ─────────────────────────────────
    inst_dir = output_root / "instruments"
    ensure_dir(inst_dir)
    raw_inst = inst_dir / "raw"
    ensure_dir(raw_inst)

    try:
        import schwab.client
        Inst = getattr(schwab.client.Client.Instrument, "Projection", None)
    except Exception:
        Inst = None

    inst_projections = [
        ("fundamental", "fundamental", True),
        ("symbol_search", "symbol-search", False),
        ("desc_search", "desc-search", False),
        ("symbol_regex", "symbol-regex", False),
    ]
    for sym in symbols[:2]:
        for proj_name, proj_val, use_list in inst_projections:
            r = ProbeResult(endpoint="instruments", symbol=sym, parameter_set=proj_name, ok=False)
            try:
                proj = proj_val
                if Inst:
                    try:
                        _map = {"fundamental": Inst.FUNDAMENTAL, "symbol-search": Inst.SYMBOL_SEARCH,
                                "desc-search": Inst.DESCRIPTION_SEARCH, "symbol-regex": Inst.SYMBOL_REGEX}
                        proj = _map.get(proj_val, proj_val)
                    except Exception:
                        proj = proj_val
                else:
                    proj = proj_val
                symbols_arg = [sym] if use_list else ("apple" if proj_name == "desc_search" else f"{sym}.*")
                resp = client.get_instruments(symbols_arg, proj)
                if resp.status_code == 200:
                    data = resp.json()
                    fn = raw_inst / f"instruments_{sym}_{proj_name}_{ts}.json"
                    with open(fn, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                    r.raw_path = fn
                    r.fields = flatten_json(data)
                    r.ok = True
                    ff = inst_dir / f"fields_instruments_{sym}_{proj_name}.txt"
                    with open(ff, "w", encoding="utf-8") as f:
                        f.write("\n".join(sorted(r.fields)))
                    r.fields_path = ff
                else:
                    r.error = f"HTTP {resp.status_code}"
            except Exception as e:
                r.error = str(e)
            results.append(r)

    # ── 5. MOVERS ───────────────────────────────────────────────────────────
    movers_dir = output_root / "movers"
    ensure_dir(movers_dir)
    raw_movers = movers_dir / "raw"
    ensure_dir(raw_movers)

    try:
        import schwab.client
        Movers = schwab.client.Client.Movers
        indices = [(Movers.Index.SPX, "SPX"), (Movers.Index.DJI, "DJI"), (Movers.Index.COMPX, "COMPX"), (Movers.Index.NASDAQ, "NASDAQ")]
        sort_orders = [(Movers.SortOrder.PERCENT_CHANGE_UP, "pct_up"), (Movers.SortOrder.PERCENT_CHANGE_DOWN, "pct_down")]
    except Exception:
        indices = [("$SPX", "SPX"), ("$DJI", "DJI"), ("$COMPX", "COMPX"), ("NASDAQ", "NASDAQ")]
        sort_orders = [("PERCENT_CHANGE_UP", "pct_up"), ("PERCENT_CHANGE_DOWN", "pct_down")]

    for idx_val, idx_name in indices:
        for so_val, so_name in sort_orders:
            r = ProbeResult(endpoint="movers", symbol=idx_name, parameter_set=so_name, ok=False)
            try:
                resp = client.get_movers(idx_val, sort_order=so_val)
                if resp.status_code == 200:
                    data = resp.json()
                    fn = raw_movers / f"movers_{idx_name}_{so_name}_{ts}.json"
                    with open(fn, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                    r.raw_path = fn
                    r.fields = flatten_json(data)
                    r.ok = True
                    ff = movers_dir / f"fields_movers_{idx_name}_{so_name}.txt"
                    with open(ff, "w", encoding="utf-8") as f:
                        f.write("\n".join(sorted(r.fields)))
                    r.fields_path = ff
                else:
                    r.error = f"HTTP {resp.status_code}"
            except Exception as e:
                r.error = str(e)
            results.append(r)

    # ── 6. MARKET HOURS ─────────────────────────────────────────────────────
    hours_dir = output_root / "market_hours"
    ensure_dir(hours_dir)
    raw_hours = hours_dir / "raw"
    ensure_dir(raw_hours)

    try:
        import schwab.client
        MH = schwab.client.Client.MarketHours
        markets = [MH.Market.EQUITY, MH.Market.OPTION, MH.Market.BOND, MH.Market.FUTURE, MH.Market.FOREX]
    except Exception:
        markets = ["equity", "option", "bond", "future", "forex"]

    for mkt in markets:
        r = ProbeResult(endpoint="market_hours", symbol=str(mkt), parameter_set="today", ok=False)
        try:
            resp = client.get_market_hours([mkt], date=date.today())
            if resp.status_code == 200:
                data = resp.json()
                fn = raw_hours / f"hours_{mkt}_{ts}.json"
                with open(fn, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                r.raw_path = fn
                r.fields = flatten_json(data)
                r.ok = True
                ff = hours_dir / f"fields_hours_{mkt}.txt"
                with open(ff, "w", encoding="utf-8") as f:
                    f.write("\n".join(sorted(r.fields)))
                r.fields_path = ff
            else:
                r.error = f"HTTP {resp.status_code}"
        except Exception as e:
            r.error = str(e)
        results.append(r)

    return results


def run_streaming_probes(client, output_root: Path, symbols: list[str], account_id: str | int) -> list[ProbeResult]:
    """Connect to streaming, capture sample payloads, flatten fields."""
    results: list[ProbeResult] = []
    stream_dir = output_root / "streaming"
    ensure_dir(stream_dir)
    raw_stream = stream_dir / "raw"
    ensure_dir(raw_stream)

    try:
        from schwab.streaming import StreamClient
    except ImportError:
        results.append(ProbeResult(
            endpoint="streaming", symbol="", parameter_set="", ok=False,
            error="schwab.streaming not available",
        ))
        return results

    samples: list[dict] = []
    sample_limit = 10

    def make_handler(svc: str, acc: list):
        def h(msg):
            if len(acc) < sample_limit:
                acc.append({"service": svc, "payload": msg})
        return h

    try:
        stream_client = StreamClient(client, account_id=account_id)
        import asyncio

        async def _run():
            await stream_client.login()
            # Level One Quotes
            level1_samples = []
            stream_client.add_level_one_equity_handler(make_handler("LEVEL_ONE_EQUITY", level1_samples))
            await stream_client.level_one_equity_subs(symbols[:2])
            # Book (Level Two)
            book_samples = []
            try:
                stream_client.add_nasdaq_book_handler(make_handler("NASDAQ_BOOK", book_samples))
                await stream_client.nasdaq_book_subs(symbols[:2])
            except Exception as e:
                log.debug("schwab field inventory: %s", e, exc_info=True)
            # Chart equity
            chart_samples = []
            try:
                stream_client.add_chart_equity_handler(make_handler("CHART_EQUITY", chart_samples))
                await stream_client.chart_equity_subs(symbols[:2])
            except Exception as e:
                log.debug("schwab field inventory: %s", e, exc_info=True)
            # Wait for a few messages
            for _ in range(30):
                try:
                    await asyncio.wait_for(stream_client.handle_message(), timeout=2.0)
                except asyncio.TimeoutError:
                    break
                except Exception:
                    break

            await stream_client.logout()
            return level1_samples + book_samples + chart_samples

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            samples = loop.run_until_complete(_run())
        finally:
            loop.close()
    except Exception as e:
        results.append(ProbeResult(
            endpoint="streaming", symbol=",".join(symbols[:2]), parameter_set="level1+book+chart",
            ok=False, error=str(e),
        ))
        return results

    if not samples:
        results.append(ProbeResult(
            endpoint="streaming", symbol=",".join(symbols[:2]), parameter_set="level1+book+chart",
            ok=True, fields=set(), error="No messages received (possibly outside RTH)",
        ))
        return results

    ts = _utc_ts()
    fn = raw_stream / f"streaming_samples_{ts}.json"
    try:
        with open(fn, "w", encoding="utf-8") as f:
            json.dump(samples, f, indent=2)
    except Exception as e:
        results.append(ProbeResult(endpoint="streaming", symbol="", parameter_set="", ok=False, error=str(e)))
        return results

    all_stream_fields: set[str] = set()
    for s in samples:
        payload = s.get("payload", s)
        all_stream_fields.update(flatten_json(payload))

    ff = stream_dir / "fields_streaming.txt"
    with open(ff, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(all_stream_fields)))

    results.append(ProbeResult(
        endpoint="streaming", symbol=",".join(symbols[:2]),
        parameter_set="level1+book+chart", ok=True,
        raw_path=fn, fields_path=ff, fields=all_stream_fields,
    ))
    return results


def merge_and_write(results: list[ProbeResult], output_root: Path) -> tuple[list[str], list[tuple]]:
    """Merge all fields into master.txt and summary.csv. Returns (all_paths, csv_rows)."""
    all_fields: set[str] = set()
    csv_rows: list[tuple] = [("endpoint", "symbol", "parameter_set", "field_path")]

    for r in results:
        for fp in r.fields:
            all_fields.add(fp)
            csv_rows.append((r.endpoint, r.symbol, r.parameter_set, fp))

    master_path = output_root / "schwab_all_fields_master.txt"
    with open(master_path, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(all_fields)))

    csv_path = output_root / "schwab_field_inventory_summary.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerows(csv_rows)

    return sorted(all_fields), csv_rows


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    output_root = Path(OUTPUT_DIR).resolve()
    ensure_dir(output_root)

    if not ACCESS_TOKEN_PATH.exists():
        print(f"ERROR: Token file not found: {ACCESS_TOKEN_PATH}")
        print("Run the Schwab OAuth login flow first (e.g. python reauth_schwab.py)")
        return 1

    if not API_KEY or not APP_SECRET:
        print("ERROR: API_KEY and APP_SECRET required. Set SCHWAB_API_KEY, SCHWAB_APP_SECRET env vars or use config.py")
        return 1

    try:
        from schwab import auth
        client = auth.client_from_token_file(
            str(ACCESS_TOKEN_PATH),
            API_KEY,
            APP_SECRET,
            enforce_enums=False,
        )
    except Exception as e:
        print(f"ERROR: Invalid token or client init failed: {e}")
        return 1

    print(f"Output: {output_root}")
    print(f"Symbols: {SYMBOLS}")
    print()

    results: list[ProbeResult] = []

    # REST probes
    print("Running REST probes...")
    rest_results = run_rest_probes(client, output_root, SYMBOLS)
    results.extend(rest_results)

    # Streaming (optional)
    if ENABLE_STREAMING:
        print("Running streaming probes...")
        account_id = None
        try:
            resp = client.get_account_numbers()
            if resp.status_code == 200 and resp.json():
                accs = resp.json()
                raw = accs[0].get("accountNumber") or accs[0].get("hashValue")  # external-key-ok: Schwab /accounts payload (accountNumber/hashValue are the account identity leaves)
                if not raw and accs:
                    raw = list(accs[0].values())[0]
                if raw:
                    account_id = int(raw) if str(raw).isdigit() else raw
        except Exception as e:
            print(f"  Note: Could not get account number for streaming: {e}")
        if account_id is not None:
            stream_results = run_streaming_probes(client, output_root, SYMBOLS, account_id)
            results.extend(stream_results)
        else:
            results.append(ProbeResult(
                endpoint="streaming", symbol="", parameter_set="", ok=False,
                error="No account number available",
            ))

    # Merge and write master catalog
    print("Merging and writing master catalog...")
    all_paths, csv_rows = merge_and_write(results, output_root)

    # Summary
    ok_count = sum(1 for r in results if r.ok)
    fail_count = len(results) - ok_count
    files_written = sum(1 for r in results if r.raw_path or r.fields_path)
    by_endpoint: dict[str, set[str]] = {}
    for r in results:
        if r.endpoint not in by_endpoint:
            by_endpoint[r.endpoint] = set()
        by_endpoint[r.endpoint].update(r.fields)

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Requests made:     {len(results)}")
    print(f"  Successful:        {ok_count}")
    print(f"  Failed:            {fail_count}")
    print(f"  Raw/field files:   {files_written}")
    print("  Unique fields per endpoint:")
    for ep, fields in sorted(by_endpoint.items()):
        print(f"    {ep}: {len(fields)}")
    print(f"  Total unique fields: {len(all_paths)}")
    print()
    print(f"  Master catalog: {output_root / 'schwab_all_fields_master.txt'}")
    print(f"  CSV summary:     {output_root / 'schwab_field_inventory_summary.csv'}")
    print("=" * 60)

    # Required output format
    master_path = output_root / "schwab_all_fields_master.txt"
    csv_path = output_root / "schwab_field_inventory_summary.csv"
    print()
    print("FIELD INVENTORY COMPLETE")
    print()
    print("Output directory:")
    print(f"  {output_root}\\")
    print()
    print("Master field file:")
    print(f"  {master_path}")
    print()
    print("Field summary CSV:")
    print(f"  {csv_path}")
    print()
    print(f"Total unique fields discovered: {len(all_paths)}")
    print()

    if fail_count > 0:
        print("\nFailed probes:")
        for r in results:
            if not r.ok:
                print(f"  - {r.endpoint} / {r.symbol} / {r.parameter_set}: {r.error}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
