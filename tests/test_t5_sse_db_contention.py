"""T5 — SSE emission must not starve behind slow _fetch_state / DB lock contention."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _seed_spy_cache(srv, *, gen_id: int = 100) -> tuple:
    ticker, expiry = "SPY", "2099-01-01"
    ck = (ticker, expiry)
    now = time.time()
    srv._state_cache[ck] = {
        "ts": now,
        "generated_at": now,
        "analytics_version": 1,
        "ms_dict": {
            "ticker": ticker,
            "selected_exp": expiry,
            "mhap_rows": [{"horizon": "5c", "call": "WAIT", "confidence": 0.5}],
            "decision_generation_id": gen_id,
            "_server_build_ts": now,
        },
    }
    return ticker, expiry, ck


@pytest.fixture
def srv_module():
    import server as srv

    srv._startup_analytics_executor()
    srv._analytics_bg_shutdown = False
    srv._analytics_inflight.clear()
    srv._analytics_bg_fail_counts.clear()
    srv._analytics_bg_last_error.clear()
    yield srv
    srv._analytics_inflight.clear()


def test_t5_sse_uses_cached_snapshot_when_fetch_in_flight(srv_module, monkeypatch):
    srv = srv_module
    ticker, expiry, ck = _seed_spy_cache(srv)
    inflight_key = srv._tier_c_inflight_key(ticker, expiry)
    with srv._analytics_bg_lock:
        srv._analytics_inflight.add(inflight_key)
    with srv._sse_lock:
        srv._sse_subscribers[ck] = 1

    fanouts: list[str] = []

    def _capture_fanout(t, e, *, inflight_key, fanout_reason):
        fanouts.append(fanout_reason)
        return True

    monkeypatch.setattr(srv, "_maybe_broadcast_sse_cache_fanout", _capture_fanout)
    srv._schedule_analytics_recompute(inflight_key, ticker, expiry, "sse_loop")
    assert fanouts == ["fetch_in_flight"]


def test_t5_sse_recompute_timeout_does_not_starve_broadcast(srv_module, monkeypatch):
    srv = srv_module
    ticker, expiry, ck = _seed_spy_cache(srv)
    inflight_key = srv._tier_c_inflight_key(ticker, expiry)
    with srv._sse_lock:
        srv._sse_subscribers[ck] = 1

    monkeypatch.setattr(srv, "_fetch_state_sse_bounded", lambda *a, **k: None)
    fanouts: list[str] = []

    def _capture_fanout(t, e, *, inflight_key, fanout_reason):
        fanouts.append(fanout_reason)
        return True

    monkeypatch.setattr(srv, "_maybe_broadcast_sse_cache_fanout", _capture_fanout)
    monkeypatch.setattr(srv._analytics_executor, "submit", lambda fn: fn())
    srv._schedule_analytics_recompute(inflight_key, ticker, expiry, "sse_loop")
    assert "fetch_timeout" in fanouts


def test_t5_sse_timeout_preserves_money_path_snapshot_envelope(srv_module, monkeypatch):
    srv = srv_module
    ticker, expiry, ck = _seed_spy_cache(srv)
    inflight_key = srv._tier_c_inflight_key(ticker, expiry)
    with srv._sse_lock:
        srv._sse_subscribers[ck] = 1

    payload = srv._build_sse_cache_fanout_payload(
        ticker,
        expiry,
        inflight_key=inflight_key,
        fanout_reason="unit_test",
    )
    assert payload is not None
    enveloped = srv._attach_money_path_snapshot_envelope(payload)
    assert enveloped.get("money_path_snapshot_kind") == "tier_c"
    assert isinstance(enveloped.get("money_path_snapshot"), dict)
    assert enveloped["money_path_snapshot"].get("ticker") == ticker
    assert enveloped.get("_update_source") == "sse_cache_fanout"
    assert enveloped.get("_sse_cache_fanout_reason") == "unit_test"


def test_step2_honest_viewer_cadence_and_no_websocket():
    """LIVE_OPERATOR_MODE_RESET_V1 Step 2 — single Tier C owner runs at an honest 5s
    cadence with TTL == cadence and stale only after a missed cycle (grace 2×)."""
    import server as srv

    _env = __import__("os").environ
    assert srv.VIEWER_SSE_REFRESH_SEC == float(
        _env.get("ED_VIEWER_SSE_REFRESH_SEC", "5.0")
    )
    assert srv.VIEWER_STATE_CACHE_TTL_SEC == float(
        _env.get("ED_VIEWER_STATE_CACHE_TTL_SEC", "5.0")
    )
    assert srv.ANALYTICS_STALE_GRACE_CYCLES == 2.0
    src = (ROOT / "server.py").read_text(encoding="utf-8", errors="replace")
    assert "@app.websocket" not in src
    assert "WebSocketRoute" not in src


def test_step2_freshness_contract_stale_only_after_missed_cycle(srv_module, monkeypatch):
    """analytics_stale is a missed-cycle statement: age < 2×TTL is NOT stale."""
    srv = srv_module
    monkeypatch.setattr(srv, "VIEWER_STATE_CACHE_TTL_SEC", 5.0)
    monkeypatch.setattr(srv, "CACHE_TTL", 5.0)
    key = ("SPY", "2099-01-01")
    inflight_key = srv._tier_c_inflight_key(*key)
    now = time.time()

    md_fresh: dict = {}
    srv._attach_analytics_freshness_contract(
        md_fresh,
        data_cache_key=key,
        entry={"ms_dict": {"ticker": "SPY"}, "generated_at": now - 7.0, "analytics_version": 3},
        now=now,
        sse_live=True,
        inflight_key=inflight_key,
    )
    assert md_fresh["analytics_stale"] is False  # 7s < 10s grace window
    assert md_fresh["analytics_stale_after_sec"] == 10.0
    assert md_fresh["analytics_refresh_due"] is True

    md_stale: dict = {}
    srv._attach_analytics_freshness_contract(
        md_stale,
        data_cache_key=key,
        entry={"ms_dict": {"ticker": "SPY"}, "generated_at": now - 11.0, "analytics_version": 3},
        now=now,
        sse_live=True,
        inflight_key=inflight_key,
    )
    assert md_stale["analytics_stale"] is True  # missed a full 5s cycle


def test_step2_tick_coherent_callback_not_registered_in_lifespan():
    """Single Tier C owner: lifespan must not wire _on_tick_broadcast_sync into the stream."""
    src = (ROOT / "server.py").read_text(encoding="utf-8", errors="replace")
    assert "on_tick_callback=on_tick" not in src
    assert "on_tick = lambda" not in src
    # Function retained (unit-tested tick logic lives in live_decision_bundle).
    assert "def _on_tick_broadcast_sync" in src


def test_step3_inflight_fanout_runs_outside_analytics_bg_lock(srv_module, monkeypatch):
    """LIVE_OPERATOR_MODE_RESET_V1 Step 3 — deadlock regression lock.

    The in-flight SSE-loop branch must invoke the cache fanout AFTER releasing
    _analytics_bg_lock: the fanout chain re-acquires that same non-reentrant lock
    via _attach_analytics_freshness_contract, which self-deadlocked the event loop
    (py-spy proof 2026-07-02). On the pre-fix code the probe below cannot acquire
    the lock (held by the caller) and this test fails; on the fixed code it passes.
    """
    srv = srv_module
    ticker, expiry, ck = _seed_spy_cache(srv)
    inflight_key = srv._tier_c_inflight_key(ticker, expiry)
    with srv._analytics_bg_lock:
        srv._analytics_inflight.add(inflight_key)
    with srv._sse_lock:
        srv._sse_subscribers[ck] = 1

    probe: dict = {"called": False, "lock_acquirable": None, "fanout_reason": None}

    def _probe_fanout(t, e, *, inflight_key, fanout_reason):
        probe["called"] = True
        probe["fanout_reason"] = fanout_reason
        acquired = srv._analytics_bg_lock.acquire(blocking=False)
        probe["lock_acquirable"] = acquired
        if acquired:
            srv._analytics_bg_lock.release()
        return True

    monkeypatch.setattr(srv, "_maybe_broadcast_sse_cache_fanout", _probe_fanout)
    srv._schedule_analytics_recompute(inflight_key, ticker, expiry, "sse_loop")
    assert probe["called"] is True
    assert probe["fanout_reason"] == "fetch_in_flight"
    assert probe["lock_acquirable"] is True, (
        "fanout invoked while _analytics_bg_lock held — event-loop self-deadlock shape"
    )


def test_t5_sse_loop_cadence_calls_cache_fanout_before_recompute(srv_module, monkeypatch):
    srv = srv_module
    ticker, expiry, ck = _seed_spy_cache(srv)
    order: list[str] = []

    def _fanout(*a, **k):
        order.append("fanout")
        return False

    def _recompute(*a, **k):
        order.append("recompute")

    monkeypatch.setattr(srv, "_maybe_broadcast_sse_cache_fanout", _fanout)
    monkeypatch.setattr(srv, "_schedule_analytics_recompute", _recompute)
    with srv._sse_lock:
        srv._sse_subscribers[ck] = 1

    async def _one_tick():
        with srv._sse_lock:
            subs = list(srv._sse_subscribers.keys())
        for (t, e) in subs:
            ik = srv._tier_c_inflight_key(t, e)
            srv._maybe_broadcast_sse_cache_fanout(
                t, e, inflight_key=ik, fanout_reason="sse_loop_cadence"
            )
            srv._schedule_analytics_recompute(ik, t, e, update_source="sse_loop")

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(_one_tick())
    assert order == ["fanout", "recompute"]


def test_t5_sse_fetch_bounded_uses_timeout_executor(srv_module, monkeypatch):
    srv = srv_module
    calls: list[float] = []

    class _FakeFuture:
        def result(self, timeout=None):
            calls.append(float(timeout))
            raise TimeoutError()

    class _FakePool:
        def submit(self, fn, *a, **k):
            return _FakeFuture()

    monkeypatch.setattr(srv, "_get_sse_fetch_timeout_executor", lambda: _FakePool())
    monkeypatch.setattr(srv, "SSE_RECOMPUTE_FETCH_TIMEOUT_SEC", 7.5)
    out = srv._fetch_state_sse_bounded(
        "SPY", None, update_source="sse_loop", timeout_sec=7.5
    )
    assert out is None
    assert calls == [7.5]
