"""I-01: fetch_market_context never raises; partial context on quote failure."""
from __future__ import annotations

from market_context import fetch_market_context


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
