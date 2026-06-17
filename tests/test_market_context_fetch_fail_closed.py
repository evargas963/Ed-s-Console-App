"""I-01: fetch_market_context never raises; partial context on quote failure."""
from __future__ import annotations

import inspect

from market_context import fetch_market_context, fetch_price_levels


def test_fetch_market_context_quote_failure_returns_partial_context() -> None:
    def _fail_quote(_client, _sym):
        raise RuntimeError("quote unavailable")

    ctx = fetch_market_context(None, _fail_quote)
    assert ctx.vix is None
    assert ctx.spy_last is None
    assert ctx.error


def test_extract_quote_returns_none_on_bad_payload() -> None:
    from market_context import _extract_quote

    last, pct = _extract_quote("SPY", {"SPY": {"quote": {}}})
    assert last is None
    assert pct is None


def test_fetch_price_levels_uses_rth_open_mins_authority() -> None:
    """FIND-MC-1: market_context.fetch_price_levels imports time_et RTH authority
    (RTH_OPEN_MINS / RTH_END_MINS) rather than inlining RTH_OPEN_HOUR / RTH_OPEN_MIN /
    RTH_CLOSE_HOUR. 5th consumer of the time_et minute-of-day authority after
    order_flow_live_state (STACK-WIRE-5 FIND-WIRE5-1)."""
    src = inspect.getsource(fetch_price_levels)
    assert "RTH_OPEN_HOUR" not in src
    assert "RTH_OPEN_MIN " not in src
    assert "RTH_CLOSE_HOUR" not in src
    assert "9 * 60 + 30" not in src
    assert "RTH_OPEN_MINS" in src
    assert "RTH_END_MINS" in src
