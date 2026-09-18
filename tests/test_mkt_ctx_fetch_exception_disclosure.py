"""
Failed current MarketContext fetch produces no current value.
Neutral MarketContext(error=...) objects must not enter current cache,
persistence, or current-field copies.
"""
from __future__ import annotations

import market_context
import server as srv
from market_state import build_market_state
from tests.test_build_market_state_spot_fail_closed import _base_kwargs


def test_fetch_and_store_mkt_ctx_failed_fetch_produces_no_current(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("simulated schwab client failure")

    monkeypatch.setattr(srv, "fetch_market_context", _boom)
    with srv._cached_mkt_ctx_lock:
        srv._cached_mkt_ctx = None
        srv._cached_mkt_ctx_ts = 0.0
        srv._stale_mkt_ctx = None
        srv._mkt_ctx_fetch_error = None
    ctx = srv._fetch_and_store_mkt_ctx(None)
    assert ctx is None
    with srv._cached_mkt_ctx_lock:
        assert srv._cached_mkt_ctx is None
        assert srv._mkt_ctx_fetch_error
        assert "RuntimeError" in srv._mkt_ctx_fetch_error
        assert "simulated schwab client failure" in srv._mkt_ctx_fetch_error


def test_fetch_and_store_mkt_ctx_failure_does_not_persist_confluence(monkeypatch):
    persisted = {"n": 0}

    class _DB:
        def upsert_confluence_quote_ticks(self, rows):
            persisted["n"] += 1

    def _boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(srv, "fetch_market_context", _boom)
    monkeypatch.setattr(srv, "_HAS_SIGNALS", True)
    monkeypatch.setattr(srv, "get_db", lambda: _DB())
    with srv._cached_mkt_ctx_lock:
        srv._cached_mkt_ctx = None
        srv._stale_mkt_ctx = None
    assert srv._fetch_and_store_mkt_ctx(None) is None
    assert persisted["n"] == 0


def test_failed_fetch_demotes_previous_current_to_stale_not_current(monkeypatch):
    from market_context import MarketContext

    prior = MarketContext(vix=18.5, vix_regime="Normal")
    with srv._cached_mkt_ctx_lock:
        srv._cached_mkt_ctx = prior
        srv._cached_mkt_ctx_ts = 123.0
        srv._cached_mkt_ctx_generation = 7
        srv._stale_mkt_ctx = None

    monkeypatch.setattr(srv, "fetch_market_context", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("x")))
    assert srv._fetch_and_store_mkt_ctx(None) is None
    stale = srv._get_stale_mkt_ctx()
    assert stale is not None
    assert stale["role"] == "stale_historical"
    assert stale["observation"] is prior
    assert stale["fetched_ts"] == 123.0
    assert stale["generation"] == 7
    with srv._cached_mkt_ctx_lock:
        assert srv._cached_mkt_ctx is None


def test_fetch_and_store_refuses_error_bearing_context_as_current(monkeypatch):
    persisted = {"n": 0}

    class _DB:
        def upsert_confluence_quote_ticks(self, rows):
            persisted["n"] += 1

    def _err_ctx(*_a, **_k):
        return market_context.MarketContext(error="SPY: quote unavailable")

    monkeypatch.setattr(srv, "fetch_market_context", _err_ctx)
    monkeypatch.setattr(srv, "_HAS_SIGNALS", True)
    monkeypatch.setattr(srv, "get_db", lambda: _DB())
    with srv._cached_mkt_ctx_lock:
        srv._cached_mkt_ctx = None
        srv._stale_mkt_ctx = None
    assert srv._fetch_and_store_mkt_ctx(None) is None
    with srv._cached_mkt_ctx_lock:
        assert srv._cached_mkt_ctx is None
        assert srv._mkt_ctx_fetch_error
    assert persisted["n"] == 0


def test_fetch_and_store_mkt_ctx_success_path_has_no_error(monkeypatch):
    def _fake_fetch(*_a, **_k):
        return market_context.MarketContext(vix=16.0, vix_regime="Low Vol")

    monkeypatch.setattr(srv, "fetch_market_context", _fake_fetch)
    ctx = srv._fetch_and_store_mkt_ctx(None)
    assert ctx is not None
    assert ctx.error == ""
    assert ctx.vix == 16.0


def test_get_mkt_ctx_expired_does_not_serve_prior_as_current(monkeypatch):
    from market_context import MarketContext
    import time as _t

    old = MarketContext(vix=20.0, vix_regime="Normal")
    with srv._cached_mkt_ctx_lock:
        srv._cached_mkt_ctx = old
        srv._cached_mkt_ctx_ts = _t.time() - srv.MKT_CTX_TTL - 5.0
        srv._mkt_ctx_refresh_inflight = False
        srv._stale_mkt_ctx = None

    entered = []

    def _fake(*_a, **_k):
        entered.append(1)
        return MarketContext(vix=21.0, vix_regime="Elevated")

    monkeypatch.setattr(srv, "fetch_market_context", _fake)
    current = srv._get_mkt_ctx(None)
    assert current is None
    stale = srv._get_stale_mkt_ctx()
    assert stale is not None
    assert stale["observation"] is old
    deadline = _t.time() + 5
    while _t.time() < deadline and not entered:
        _t.sleep(0.02)
    with srv._cached_mkt_ctx_lock:
        srv._mkt_ctx_refresh_inflight = False
        srv._cached_mkt_ctx = None
        srv._stale_mkt_ctx = None


def test_build_market_state_none_mkt_ctx_abstains():
    ms = build_market_state(**_base_kwargs(mkt_ctx=None))
    assert ms.state_error == "market_context_unavailable"
    assert ms.vix_regime == ""
    assert ms.pcr_arrow == ""


def test_build_market_state_surfaces_mkt_ctx_error():
    ctx = market_context.MarketContext(error="mkt_ctx_fetch_exception: RuntimeError: boom")
    ms = build_market_state(**_base_kwargs(mkt_ctx=ctx))
    assert ms.state_error == "market_context_degraded"
    assert "RuntimeError" in (ms.state_error_detail or "")
    assert ms.vix_regime == ""
    assert ms.pcr_arrow == ""


def test_build_market_state_clean_mkt_ctx_copies_only_measured_fields():
    ctx = market_context.MarketContext(vix=18.0, vix_regime="Normal", pcr=0.9, pcr_arrow="↑")
    ms = build_market_state(**_base_kwargs(mkt_ctx=ctx))
    assert ms.state_error is None
    assert ms.vix_regime == "Normal"
    assert ms.pcr_arrow == "↑"
