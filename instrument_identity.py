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


#: Decimal places a strike is rendered at before trailing zeros are trimmed. Four is well beyond
#: any listed increment (.5, .25, .125), and trimming means a whole-dollar strike reads "320"
#: rather than "320.0000" — the display should look like the ladder, not like a float.
STRIKE_DISPLAY_DECIMALS = 4


def format_strike_for_display(strike) -> str:
    """THE strike-to-text authority for every server-rendered surface. One producer.

    WHY THIS IS A FUNCTION AND NOT A ONE-LINER AT EACH CALL SITE. The rule
    ``str(int(k)) if k.is_integer() else str(k)`` was inlined twice in market_state (the option
    expression and the leg string). Both spellings happened to be correct, but a computation
    duplicated per call site is how the browser side ended up with FOUR different strike rules,
    three of them wrong — chart and exposure rounding 322.5 to "323", the terrain map truncating
    17.25 to "17.3", and exactly one site correct. One displayed strike is one computation.

    WHAT IT GUARANTEES: the text names the SAME price it was given. It is not "print two
    decimals" — a rounded strike is a price at which no contract trades, and on a 0.5 ladder
    rounding also collapses two adjacent real strikes onto one label, erasing one from the
    display entirely.

    Carries no instrument knowledge: no increment, tick size, roster or core-ticker assumption,
    so a symbol this console has never seen renders correctly with no prior knowledge of it.

    BROWSER COUNTERPART: static/js/strike_format.js ``fmtStrike``. The two must agree, and
    tests/test_ui_strike_label_fidelity_v1.py executes both and asserts identical output —
    a shared rule that drifts between runtimes is two rules again.
    """
    if strike is None or strike == "":
        return "—"
    try:
        n = float(strike)
    except (TypeError, ValueError):
        return "—"
    if n != n or n in (float("inf"), float("-inf")):    # NaN / inf are not prices
        return "—"
    s = f"{n:.{STRIKE_DISPLAY_DECIMALS}f}"
    if "." not in s:
        return s
    return s.rstrip("0").rstrip(".")
