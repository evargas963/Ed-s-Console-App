"""RC-16 repo-wide — a "last price" ladder may only contain actual TRADES.

`market_context._extract_quote` had the same defect as the terrain spot authority: it
ranked `regularMarketLastPrice` and `quote.mark` inside a "last" ladder. Both are the
regular-session CLOSE once trading stops. Verified on the wire 2026-07-19 after hours:
quote.mark and regularMarketLastPrice read 743.29 (Friday's close) while quote.lastPrice
read 742.4861 (the true post-market trade).

A close reported as a last price is not a rounding difference -- it is the previous
session's number presented as the current one.
"""

from __future__ import annotations

from market_context import _extract_quote


def _payload(sym: str, **sections) -> dict:
    return {sym: {k: v for k, v in sections.items()}}


def test_live_trade_wins_over_the_close() -> None:
    """The exact after-hours shape that produced 743.29 vs 742.49."""
    last, _pct = _extract_quote("SPY", _payload(
        "SPY",
        quote={"lastPrice": 742.4861, "mark": 743.29, "netPercentChange": -0.108},
        regular={"regularMarketLastPrice": 743.29},
    ))
    assert last == 742.4861, "a real trade must beat the session close"


def test_mark_is_never_used_as_a_last_price() -> None:
    """`mark` is pinned to the close when not trading — it must not fill a 'last' slot."""
    last, _pct = _extract_quote("SPY", _payload(
        "SPY",
        quote={"mark": 743.29},          # only a mark, no trade anywhere
        regular={},
        extended={},
    ))
    assert last is None, "mark is a valuation mark, not a trade — it must not become 'last'"


def test_extended_trade_is_accepted_when_regular_quote_is_empty() -> None:
    last, _pct = _extract_quote("SPY", _payload(
        "SPY",
        quote={},
        extended={"lastPrice": 744.54},
        regular={"regularMarketLastPrice": 743.29},
    ))
    assert last == 744.54, "an extended-session trade is still a trade"


def test_close_is_the_last_resort_only() -> None:
    """With no trade in any session the close may be used — nothing newer exists."""
    last, _pct = _extract_quote("SPY", _payload(
        "SPY",
        quote={},
        extended={},
        regular={"regularMarketLastPrice": 743.29},
    ))
    assert last == 743.29


def test_zero_does_not_fall_through_the_ladder() -> None:
    """`or` chaining treated a legitimate 0.0 as absent; explicit checks must not."""
    last, _pct = _extract_quote("SPY", _payload(
        "SPY",
        quote={"lastPrice": 0.0},
        extended={"lastPrice": 744.54},
        regular={},
    ))
    assert last == 744.54, "a zero price is not a trade; the next real trade must be used"


def test_missing_symbol_fails_closed() -> None:
    last, pct = _extract_quote("SPY", {})
    assert last is None and pct is None
