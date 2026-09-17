"""
No-fallback lock repair (2026-09-17): server.py's _fetch_and_store_mkt_ctx used to swallow
a genuine fetch_market_context exception into a bare `MarketContext()` -- an object whose
every field (vix_regime="—", pcr_arrow="→", etc.) carries the SAME neutral-looking default
as a real "nothing computed yet" state, indistinguishable from a genuine failure. Repaired
to route the real exception through the same ctx.error disclosure channel
fetch_market_context's own internal per-symbol soft-error path already uses, and
market_state.build_market_state() now surfaces a non-empty mkt_ctx.error into
ms.state_error/state_error_detail.
"""
from __future__ import annotations

import market_context
import server as srv
from market_state import build_market_state
from tests.test_build_market_state_spot_fail_closed import _base_kwargs


def test_fetch_and_store_mkt_ctx_discloses_exception_via_error_field(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("simulated schwab client failure")

    monkeypatch.setattr(srv, "fetch_market_context", _boom)
    ctx = srv._fetch_and_store_mkt_ctx(None)
    assert ctx.error
    assert "mkt_ctx_fetch_exception" in ctx.error
    assert "RuntimeError" in ctx.error
    assert "simulated schwab client failure" in ctx.error
    # The rest of the object still carries neutral display defaults -- that's expected
    # (MarketContext's own field shape), but the failure is no longer silently absent.
    assert ctx.vix is None


def test_fetch_and_store_mkt_ctx_success_path_has_no_error(monkeypatch):
    def _fake_fetch(*_a, **_k):
        return market_context.MarketContext()

    monkeypatch.setattr(srv, "fetch_market_context", _fake_fetch)
    ctx = srv._fetch_and_store_mkt_ctx(None)
    assert ctx.error == ""


def test_build_market_state_surfaces_mkt_ctx_error(monkeypatch):
    ctx = market_context.MarketContext(error="mkt_ctx_fetch_exception: RuntimeError: boom")
    ms = build_market_state(**_base_kwargs(mkt_ctx=ctx))
    assert ms.state_error == "market_context_degraded"
    assert "RuntimeError" in (ms.state_error_detail or "")


def test_build_market_state_clean_mkt_ctx_does_not_set_state_error(monkeypatch):
    ctx = market_context.MarketContext()
    assert ctx.error == ""
    ms = build_market_state(**_base_kwargs(mkt_ctx=ctx))
    assert ms.state_error is None
