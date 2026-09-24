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


def test_extended_trade_is_not_a_stand_in_for_quote_last() -> None:
    """T-11: extended.lastPrice is a different book — missing quote.lastPrice stays missing."""
    last, _pct = _extract_quote("ZZVIX", _payload(
        "ZZVIX",
        quote={},
        extended={"lastPrice": 744.54},
        regular={"regularMarketLastPrice": 743.29},
    ))
    assert last is None


def test_close_is_never_current_last() -> None:
    """A session close is a different quantity. It must not become last-traded."""
    last, _pct = _extract_quote("SPY", _payload(
        "SPY",
        quote={},
        extended={},
        regular={"regularMarketLastPrice": 743.29},
    ))
    assert last is None


def test_zero_quote_last_does_not_use_extended() -> None:
    """0.0 is not a trade; T-11 forbids substituting extended.lastPrice."""
    last, _pct = _extract_quote("ZZVIX", _payload(
        "ZZVIX",
        quote={"lastPrice": 0.0},
        extended={"lastPrice": 744.54},
        regular={},
    ))
    assert last is None


def test_missing_symbol_fails_closed() -> None:
    last, pct = _extract_quote("SPY", {})
    assert last is None and pct is None
