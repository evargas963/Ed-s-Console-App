"""I-01: fetch_market_context never raises; partial context on quote failure."""
from __future__ import annotations

import inspect
from pathlib import Path

from market_context import fetch_market_context, fetch_price_levels

_REPO_ROOT = Path(__file__).resolve().parents[1]


class _MockQuoteResponse:
    def __init__(self, payload: dict, *, status_code: int = 200):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _quote_fn(*, fail: frozenset[str] = frozenset(), prices: dict[str, float] | None = None):
    """Minimal safe_get_quote stub: fail-closed per symbol."""

    def _quote(_client, sym: str):
        if sym in fail:
            raise RuntimeError(f"{sym} unavailable")
        if prices and sym in prices:
            return _MockQuoteResponse({sym: {"quote": {"lastPrice": prices[sym]}}})
        return _MockQuoteResponse({})

    return _quote


def test_fetch_market_context_quote_failure_returns_partial_context() -> None:
    def _fail_quote(_client, _sym):
        raise RuntimeError("quote unavailable")

    ctx = fetch_market_context(None, _fail_quote)
    assert ctx.vix is None
    assert ctx.vxn is None
    assert ctx.rvx is None
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


def test_fetch_market_context_vol_indices_all_present() -> None:
    ctx = fetch_market_context(
        None,
        _quote_fn(prices={"$VIX": 18.5, "$VXN": 22.1, "$RVX": 24.3}),
    )
    assert ctx.vix == 18.5
    assert ctx.vxn == 22.1
    assert ctx.rvx == 24.3
    assert ctx.vix_regime != "—"


def test_fetch_market_context_vxn_failure_vix_unchanged() -> None:
    ctx = fetch_market_context(
        None,
        _quote_fn(fail=frozenset({"$VXN"}), prices={"$VIX": 17.0, "$RVX": 23.0}),
    )
    assert ctx.vix == 17.0
    assert ctx.vxn is None
    assert ctx.rvx == 23.0


def test_fetch_market_context_rvx_failure_vix_unchanged() -> None:
    ctx = fetch_market_context(
        None,
        _quote_fn(fail=frozenset({"$RVX"}), prices={"$VIX": 16.0, "$VXN": 21.0}),
    )
    assert ctx.vix == 16.0
    assert ctx.vxn == 21.0
    assert ctx.rvx is None


def test_fetch_market_context_missing_vol_index_leaves_none_no_exception() -> None:
    ctx = fetch_market_context(
        None,
        _quote_fn(prices={"$VIX": 15.0}),
    )
    assert ctx.vix == 15.0
    assert ctx.vxn is None
    assert ctx.rvx is None


def test_vol_index_lane_v1_no_consumer_wiring() -> None:
    """Negative scope: V1 lane must not wire ctx.vxn/ctx.rvx into money-path consumers."""
    refs = ("ctx.vxn", "ctx.rvx", "mkt_ctx.vxn", "mkt_ctx.rvx", "native_vol_")
    forbidden = (
        "market_state.py",
        "server.py",
        "signal_types.py",
        "volatility_regime.py",
        "signals.py",
        "call_engine.py",
        "static/index.html",
    )
    for rel in forbidden:
        src = (_REPO_ROOT / rel).read_text(encoding="utf-8")
        for ref in refs:
            assert ref not in src, f"{rel} must not reference {ref} in V1 lane"


def test_signalinput_vix_still_macro_vix_only() -> None:
    from market_state import build_market_state

    src = inspect.getsource(build_market_state)
    assert "vix_level=mkt_ctx.vix" in src
    assert "vxn_level" not in src
    assert "rvx_level" not in src
