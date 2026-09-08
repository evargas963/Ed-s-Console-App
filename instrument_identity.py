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
``market_context.py`` uses ``$VIX`` / ``$VXN`` / ``$RVX`` for vol-index fetches.
"""
from __future__ import annotations

# Uppercase roots (no `$`) that must resolve to broker-prefixed keys in DB.
# RC-126 (operator /goal: levels for ALL tickers): NDX/RUT/DJX/XSP/OEX added — the widely
# traded Schwab dollar-indexes an operator will type bare. Extend here, nowhere else: this
# set IS the query-boundary alias authority since the terrain/quote/bars endpoints
# canonicalize through ticker_storage_key.
BROKER_INDEX_BARE_ROOTS: frozenset[str] = frozenset(
    {"SPX", "DJI", "COMPX", "VIX", "VXN", "RVX", "NDX", "RUT", "DJX", "XSP", "OEX"},
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


def vendor_option_root(symbol: str | None) -> str:
    """Option root already encoded in a Schwab/OCC OSI vendor symbol.

    Does not construct a symbol. Production Schwab ``symbol`` fields in this repo
    are the 21-character OSI form: 6-char space-padded root + YYMMDD + C/P +
    8-digit strike (see ``tests/fixtures/real_cde_complete_chain_half_dollar.json``).
    """
    raw = (symbol or "").strip().upper()
    if len(raw) != 21:
        return ""
    if not raw[6:12].isdigit() or raw[12] not in "CP" or not raw[13:].isdigit():
        return ""
    return raw[:6].rstrip()


def option_underlying_root(ticker: str | None) -> str:
    """Ticker root to compare against ``vendor_option_root``.

    Uses ``ticker_storage_key`` and the existing ``BROKER_INDEX_BARE_ROOTS`` alias
    set. ``$SPX`` on disk is the same instrument as OSI root ``SPX``. Weekly
    suffix roots (``SPXW``) are not invented here.
    """
    key = ticker_storage_key(ticker)
    if not key:
        return ""
    if key.startswith("$"):
        bare = key[1:]
        if bare in BROKER_INDEX_BARE_ROOTS:
            return bare
    return key

