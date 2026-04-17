"""
Canonical ticker key for SQLite tables keyed like Schwab/stream ingestion: `snapshots`,
`price_bars_1m`, and exact-match Issue 19 SQL.

Policy (Repair v1):
- Equity-style symbols: uppercase alphanumeric, e.g. `spy` -> `SPY`.
- Index-style symbols with leading `$` (e.g. `$SPX`): **preserve** `$` and uppercase
  the remainder → `$SPX`. This matches stored bars and `fill_outcomes` joins.

Do **not** strip `$` for DB retrieval or anchor keys intended to hit those rows.

P1 repair: some Schwab **index** symbols are persisted with a leading `$` while anchors,
APIs, or human input use the bare root (`SPX` vs `$SPX`). For exact SQLite joins with
`price_bars_1m`, bare roots listed in ``BROKER_INDEX_BARE_ROOTS`` map to the stored form.
Source: ``schwab_full_field_inventory.py`` fallback index tuple labels SPX/DJI/COMPX;
``market_context.py`` uses ``$VIX`` for fetches.
"""
from __future__ import annotations

# Uppercase roots (no `$`) that must resolve to broker-prefixed keys in DB.
BROKER_INDEX_BARE_ROOTS: frozenset[str] = frozenset(
    {"SPX", "DJI", "COMPX", "VIX"},
)


def ticker_storage_key(ticker: str | None) -> str:
    """
    Normalize user/JSON ticker to the string stored in `snapshots.ticker` and
    `price_bars_1m.ticker` for exact SQL equality.
    """
    t = (ticker or "").strip()
    if not t:
        return ""
    if t.startswith("$"):
        rest = t[1:].strip()
        if not rest:
            return "$"
        return "$" + rest.upper()
    u = t.upper()
    if u in BROKER_INDEX_BARE_ROOTS:
        return "$" + u
    return u
