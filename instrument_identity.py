"""
Canonical ticker key: Schwab's own symbol, the key of every value the console holds and every
row the capture daemon records (stream_capture.db).

Policy (Repair v1):
- Equity-style symbols: uppercase alphanumeric, e.g. `spy` -> `SPY`.
- Index-style symbols with leading `$` (e.g. `$SPX`): **preserve** `$` and uppercase
  the remainder → `$SPX`, as Schwab sends it.

Do **not** strip `$`.

Schwab names **index** symbols with a leading `$` while pages and human input may use the bare
root (`SPX` vs `$SPX`): bare roots listed in ``BROKER_INDEX_BARE_ROOTS`` map to Schwab's form.
"""
from __future__ import annotations

# Index roots an operator types bare, mapped to Schwab's own name for the index ("$" + root).
# Schwab names indexes only with "$" and knows none of these bare (instruments symbol-search and
# quotes, 2026-09-28, tests/fixtures/real_schwab_index_identity_2026_09_28.json); a root joins
# only with that evidence (test_every_bare_index_root_is_what_schwab_names_an_index_with_dollar).
BROKER_INDEX_BARE_ROOTS: frozenset[str] = frozenset(
    {"SPX", "DJI", "COMPX", "VIX", "VXN", "RVX", "NDX", "RUT", "DJX", "XSP", "OEX"},
)


def ticker_storage_key(ticker: str | None) -> str:
    """
    Normalize user/JSON ticker to Schwab's symbol, the key the console and the capture
    daemon's record use.
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


def display_symbol(key: str) -> str:
    """How the screen names the instrument whose storage key is `key` ("$SPX" -> "SPX"): the one
    display form, served with the key so the page never re-derives either."""
    return key[1:] if key.startswith("$") else key


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
