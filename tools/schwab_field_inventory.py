"""Every field Schwab has sent us: docs/schwab_fields.csv, one row per field path, cumulative.

Each run calls every REST market-data and account endpoint (several asset types and request
variants), reads the key names the capture daemon received on the stream (read-only from
stream_capture.db) and schwab-py's field list for every streaming service. Rows already in the
CSV and not seen this run are kept with their last_seen date; nothing is dropped. A run writes
field names and JSON types, never values; it keeps the schwab_doc and sample columns, which are
written from a probe's raw replies. Opens no streaming socket (Schwab allows one per user: the
daemon's).

Paths: `endpoint.key.key`; a list item and an option chain's expiry and strike keys are `*`;
market-hours products are kept (market_hours.future.GC.isOpen). Containers are rows too.

    python -m tools.schwab_field_inventory
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

import time_et
from app.market_data.schwab.streaming.capture import stored_watchlist, streaming_fields
from config import build_config, load_dotenv_file
from db_authority import canonical_stream_db_path
from runtime_layout import runtime_root
from schwab_client import build_client_from_token

REPO = Path(__file__).resolve().parent.parent
log = logging.getLogger(__name__)

OUT = REPO / "docs" / "schwab_fields.csv"
#: schwab_doc: where Schwab's docs define the field, or "not in Schwab's doc"; sample: values Schwab
#: sent. Both are written by hand from a probe's raw replies; this tool keeps them.
COLUMNS = [
    "canonical_field",
    "endpoint",
    "type",
    "variants",
    "first_seen",
    "last_seen",
    "schwab_doc",
    "sample",
]
#: every asset type Schwab quotes, beside the roster: index, future, forex, mutual fund, a
#: hard-to-borrow stock (its borrow fields)
EXTRA_QUOTES = [
    "$SPX",
    "$VIX",
    "$NDX",
    "$DJI",
    "/ES",
    "/CL",
    "EUR/USD",
    "VFIAX",
    "GME",
    "BRK.B",
    "TOITF",
    "CNSWF",
    "./ESZ26C6800",
]
#: underlyings whose full chains are read: ETF, index, stock, adjusted-deliverable candidates
CHAIN_SYMBOLS = ["SPY", "$SPX", "AAPL", "GME", "TSLA"]
#: the JSON types json.loads returns
TYPES = {
    bool: "bool",
    int: "number",
    float: "number",
    str: "string",
    dict: "object",
    list: "array",
    type(None): "null",
}


def paths(obj, prefix: str, out: dict[str, str]) -> None:
    """Every path in `obj`, containers included, as {path: json type}; a list item is *."""
    out[prefix] = TYPES[type(obj)]
    if isinstance(obj, dict):
        for k, v in obj.items():
            paths(v, f"{prefix}.{k}", out)
    elif isinstance(obj, list):
        for v in obj:
            paths(v, prefix if prefix.endswith(".*") else f"{prefix}.*", out)


def chain_paths(body: dict, out: dict[str, str]) -> None:
    """Add a chain's paths to `out`, its expiry and strike keys read as data.

    The form is chains.callExpDateMap.*.<contract field>.
    """
    paths({k: v for k, v in body.items() if not k.endswith("ExpDateMap")}, "chains", out)
    for side in ("callExpDateMap", "putExpDateMap"):
        if side not in body:  # a spread strategy answers with monthlyStrategyList instead
            continue
        out[f"chains.{side}"] = "object"
        out[f"chains.{side}.*"] = "object"
        for strikes in body[side].values():
            for contracts in strikes.values():
                for contract in contracts:
                    paths(contract, f"chains.{side}.*", out)


def _option_symbols(c) -> list[str]:
    """One call and one put contract per chain underlying, for their quotes."""
    out = []
    for sym in CHAIN_SYMBOLS:
        body = c.get_option_chain(sym, strike_count=1).json()
        for side in ("callExpDateMap", "putExpDateMap"):
            for strikes in body[side].values():
                out.append(next(iter(strikes.values()))[0]["symbol"])
                break
    return out


def _expirations(c, symbol: str) -> list[dt.date]:
    body = c.get_option_expiration_chain(symbol).json()
    return [dt.date.fromisoformat(e["expirationDate"][:10]) for e in body["expirationList"]]


def _paced(call):
    """Schwab allows 120 requests a minute."""
    time.sleep(0.55)
    return call()


def rest_rows(
    c, roster: list[str]
) -> tuple[dict[tuple[str, str], set[str]], dict[str, str], dict[str, object]]:
    """Return ({(path, type): variants}, {path: endpoint}, {call: status}).

    Every endpoint is called, with every option it takes; the widest date range each accepts.
    """
    now = dt.datetime.fromtimestamp(time_et.now())
    today = now.date()
    P, M = c.Instrument.Projection, c.Movers
    hashes = [a["hashValue"] for a in c.get_account_numbers().json()]
    calls = [  # (endpoint, variant, call)
        ("quotes", "", lambda: c.get_quotes(roster + EXTRA_QUOTES + _option_symbols(c))),
        # a whole SPY or $SPX chain is too large for one response (502): one call per expiration,
        # every strike, every expiration
        *[
            (
                "chains",
                f"{s} {d}",
                lambda s=s, d=d: _paced(
                    lambda: c.get_option_chain(
                        s,
                        include_underlying_quote=True,
                        strike_range=c.Options.StrikeRange.ALL,
                        from_date=d,
                        to_date=d,
                    )
                ),
            )
            for s in CHAIN_SYMBOLS
            for d in _expirations(c, s)
        ],
        *[
            (
                "chains",
                f"SPY analytical {d}",
                lambda d=d: _paced(
                    lambda: c.get_option_chain(
                        "SPY",
                        strategy=c.Options.Strategy.ANALYTICAL,
                        include_underlying_quote=True,
                        strike_range=c.Options.StrikeRange.ALL,
                        from_date=d,
                        to_date=d,
                    )
                ),
            )
            for d in _expirations(c, "SPY")
        ],
        # the spread strategies answer with monthlyStrategyList instead of the expiry maps
        *[
            (
                "chains",
                f"SPY {st.value}",
                lambda st=st: _paced(
                    lambda: c.get_option_chain(
                        "SPY",
                        strategy=st,
                        interval=5,
                        strike_count=2,
                        include_underlying_quote=True,
                        from_date=today,
                        to_date=today + dt.timedelta(days=45),
                    )
                ),
            )
            for st in c.Options.Strategy
            if st.name not in ("SINGLE", "ANALYTICAL")
        ],
        *[
            ("expirationchain", s, lambda s=s: c.get_option_expiration_chain(s))
            for s in CHAIN_SYMBOLS
        ],
        *[
            (
                "pricehistory",
                f.__name__,
                lambda f=f: f("SPY", need_extended_hours_data=True, need_previous_close=True),
            )
            for f in (
                c.get_price_history_every_minute,
                c.get_price_history_every_five_minutes,
                c.get_price_history_every_ten_minutes,
                c.get_price_history_every_fifteen_minutes,
                c.get_price_history_every_thirty_minutes,
                c.get_price_history_every_day,
                c.get_price_history_every_week,
            )
        ],
        *[
            (
                "movers",
                f"{i.value} {s.value} {f.value}",
                lambda i=i, s=s, f=f: c.get_movers(i, sort_order=s, frequency=f),
            )
            for i in M.Index
            for s in M.SortOrder
            for f in (M.Frequency.ZERO, M.Frequency.TEN)
        ],
        *[
            (
                "market_hours",
                str(d),
                lambda d=d: c.get_market_hours(list(c.MarketHours.Market), date=d),
            )
            for d in (today, today + dt.timedelta(days=1), today + dt.timedelta(days=5))
        ],
        (
            "instruments",
            "fundamental",
            lambda: c.get_instruments(roster + EXTRA_QUOTES, P.FUNDAMENTAL),
        ),
        ("instruments", "symbol_search", lambda: c.get_instruments(roster, P.SYMBOL_SEARCH)),
        ("instruments", "symbol_regex", lambda: c.get_instruments(["AAP.*"], P.SYMBOL_REGEX)),
        (
            "instruments",
            "description_search",
            lambda: c.get_instruments(["Apple"], P.DESCRIPTION_SEARCH),
        ),
        (
            "instruments",
            "description_regex",
            lambda: c.get_instruments(["Apple.*"], P.DESCRIPTION_REGEX),
        ),
        ("instruments", "search", lambda: c.get_instruments(["SPY"], P.SEARCH)),
        ("accountnumbers", "", lambda: c.get_account_numbers()),
        ("accounts", "positions", lambda: c.get_accounts(fields=[c.Account.Fields.POSITIONS])),
        *[
            (
                "accounts",
                "one account",
                lambda h=h: c.get_account(h, fields=[c.Account.Fields.POSITIONS]),
            )
            for h in hashes
        ],
        (
            "orders",
            "all accounts",
            lambda: c.get_orders_for_all_linked_accounts(
                from_entered_datetime=now - dt.timedelta(days=364), to_entered_datetime=now
            ),
        ),
        *[
            (
                "transactions",
                "one year",
                lambda h=h: c.get_transactions(
                    h, start_date=now - dt.timedelta(days=364), end_date=now
                ),
            )
            for h in hashes
        ],
        ("userpreference", "", lambda: c.get_user_preferences()),
    ]
    rows: dict[tuple[str, str], set[str]] = {}
    endpoint_of: dict[str, str] = {}
    status: dict[str, object] = {}
    for endpoint, variant, call in calls:
        name = f"{endpoint} {variant}".strip()
        try:
            r = call()
            status[name] = r.status_code
            if r.status_code != 200:
                continue
            body = r.json()
        except Exception as e:  # an endpoint that fails is reported with its error
            log.warning("%s failed", name, exc_info=True)
            status[name] = f"error: {type(e).__name__}"
            continue
        found: dict[str, str] = {}
        if endpoint == "instruments":  # {"instruments": [...]}: the wrapper key is not a field
            body = body["instruments"]
        if (
            endpoint == "quotes"
        ):  # keyed by symbol: the symbol level is dropped, the asset type kept
            for q in body.values():
                one: dict[str, str] = {}
                paths(q, "quotes", one)
                for p, t in one.items():
                    # an entry Schwab sent with no asset type (its errors) names no variant
                    rows.setdefault((p, t), set()).add(q.get("assetMainType"))
                    endpoint_of[p] = endpoint
            continue
        if endpoint == "chains":
            chain_paths(body, found)
        else:
            paths(body, endpoint, found)
        for p, t in found.items():
            rows.setdefault((p, t), set()).add(variant)
            endpoint_of[p] = endpoint
    return rows, endpoint_of, status


def captured_stream_paths(db: Path) -> dict[tuple[str, str], set[str]]:
    """Return every path the daemon received (the newest 20,000 messages of each table).

    Each is written as streaming.content.*.<path>, the form the stream's content items take.
    """
    tables = {
        "stream_quotes_raw": "LEVELONE_EQUITIES",
        "stream_options_quotes_raw": "LEVELONE_OPTIONS",
        "stream_book_raw": "BOOK",
        "stream_news_raw": "NEWS",
        "stream_bars_raw": "CHART_EQUITY",
    }
    rows: dict[tuple[str, str], set[str]] = {}
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        for table, service in tables.items():
            for (raw,) in con.execute(
                f"SELECT native_json FROM {table} WHERE native_json IS NOT NULL "
                "ORDER BY rowid DESC LIMIT 20000"
            ):
                found: dict[str, str] = {}
                paths(json.loads(raw), "streaming.content.*", found)
                for p, t in found.items():
                    rows.setdefault((p, t), set()).add(service)
    finally:
        con.close()
    return rows


def _read(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {r["canonical_field"]: r for r in csv.DictReader(f)}


def main() -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    load_dotenv_file(runtime_root() / ".env")
    cfg = build_config()
    state = build_client_from_token(cfg.token_path, cfg.api_key, cfg.app_secret)
    if not state.ok:
        print(state.message)
        return 1
    today = dt.datetime.fromtimestamp(time_et.now()).date().isoformat()
    roster = [t for t in stored_watchlist(canonical_stream_db_path()) if not t.startswith("$")]
    rest, endpoint_of, status = rest_rows(state.client, roster)
    stream_seen = captured_stream_paths(canonical_stream_db_path())
    documented = streaming_fields()

    rows = _read(OUT)

    def seen(field: str, endpoint: str, typ: str, variants: set[str]) -> None:
        r = rows.setdefault(
            field,
            {
                "canonical_field": field,
                "endpoint": endpoint,
                "type": typ,
                "variants": "",
                "first_seen": today,
                "last_seen": today,
            },
        )
        r.update(
            endpoint=endpoint,
            type=typ,
            last_seen=today,
            first_seen=r["first_seen"] or today,  # never seen before: first seen today
            variants=";".join(sorted(set(filter(None, r["variants"].split(";"))) | variants)),
        )

    for (field, typ), variants in rest.items():
        seen(field, endpoint_of[field], typ, {v for v in variants if v})
    for (field, typ), services in stream_seen.items():
        seen(field, "streaming", typ, services)
    received = {f.rsplit(".", 1)[-1] for f, _ in stream_seen}
    for service, fields in documented.items():
        for name in fields:
            field = f"streaming.{service}.{name}"
            r = rows.setdefault(
                field,
                {
                    "canonical_field": field,
                    "endpoint": "streaming",
                    "type": "",
                    "variants": "schwab-py list",
                    "first_seen": today,
                    "last_seen": "",
                },
            )
            if name in received:
                r.update(last_seen=today, first_seen=r["first_seen"] or today)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="\n") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        for field in sorted(rows):
            # a field this run added has no schwab_doc or sample yet: written empty
            w.writerow(rows[field])

    n_today = sum(1 for r in rows.values() if r["last_seen"] == today)
    by_endpoint: dict[str, int] = {}
    for r in rows.values():
        by_endpoint[r["endpoint"]] = by_endpoint.get(r["endpoint"], 0) + 1
    print(f"fields {len(rows)} (seen today {n_today})")
    for e, n in sorted(by_endpoint.items(), key=lambda x: -x[1]):
        print(f"  {e}: {n}")
    print("calls:", status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
