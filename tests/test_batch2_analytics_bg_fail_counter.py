"""Batch-2: analytics background recompute fail-counter wiring."""

from __future__ import annotations

import pytest


@pytest.fixture()
def _bg_fail_spy():
    import server as srv

    ticker = "ZZZ_BG_FAIL"
    expiry = "2099-03-01"
    cache_key = (ticker, expiry)
    inflight_key = srv._tier_c_inflight_key(ticker, expiry)
    srv._state_cache[cache_key] = {"ms_dict": {"ticker": ticker}, "ts": 1.0}
    srv._analytics_bg_fail_counts.pop(inflight_key, None)
    srv._analytics_bg_last_error.pop(inflight_key, None)
    with srv._analytics_bg_lock:
        srv._analytics_inflight.discard(inflight_key)
    yield ticker, expiry, cache_key, inflight_key, srv
    srv._state_cache.pop(cache_key, None)
    srv._analytics_bg_fail_counts.pop(inflight_key, None)
    srv._analytics_bg_last_error.pop(inflight_key, None)
    with srv._analytics_bg_lock:
        srv._analytics_inflight.discard(inflight_key)


def test_record_analytics_bg_failure_marks_stale_after_threshold(_bg_fail_spy):
    ticker, expiry, cache_key, inflight_key, srv = _bg_fail_spy
    threshold = srv.ANALYTICS_BG_MAX_CONSECUTIVE_FAILURES
    for i in range(threshold - 1):
        srv._record_analytics_bg_failure(inflight_key, ticker, reason="test", detail="boom")
        assert cache_key in srv._state_cache
        assert srv._analytics_bg_fail_counts.get(inflight_key) == i + 1
    srv._record_analytics_bg_failure(inflight_key, ticker, reason="test", detail="boom")
    assert cache_key in srv._state_cache
    md = srv._state_cache[cache_key]["ms_dict"]
    assert md.get("state_error") == "analytics_refresh_failed"
    assert "boom" in str(md.get("state_error_detail", ""))
    assert md.get("analytics_stale") is True
    assert inflight_key not in srv._analytics_bg_fail_counts


def test_schedule_analytics_recompute_wires_fail_counter(monkeypatch, _bg_fail_spy):
    ticker, expiry, cache_key, inflight_key, srv = _bg_fail_spy
    threshold = srv.ANALYTICS_BG_MAX_CONSECUTIVE_FAILURES

    def _boom(*_a, **_k):
        raise RuntimeError("bg fetch failed")

    monkeypatch.setattr(srv, "_fetch_state", _boom)
    monkeypatch.setattr(srv, "_stamp_analytics_freshness_on_completed_fetch", lambda *a, **k: None)
    monkeypatch.setattr(srv._analytics_executor, "submit", lambda fn: fn())

    for _ in range(threshold):
        srv._schedule_analytics_recompute(inflight_key, ticker, expiry, "test_bg_fail")

    assert cache_key in srv._state_cache
    assert srv._state_cache[cache_key]["ms_dict"].get("state_error") == "analytics_refresh_failed"
    assert inflight_key not in srv._analytics_bg_fail_counts


def test_schedule_analytics_recompute_resets_counter_on_success(monkeypatch, _bg_fail_spy):
    ticker, expiry, cache_key, inflight_key, srv = _bg_fail_spy
    calls = {"n": 0}

    def _flaky(*_a, **_k):
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("transient")
        return {"ticker": ticker, "selected_exp": expiry}

    monkeypatch.setattr(srv, "_fetch_state", _flaky)
    monkeypatch.setattr(srv, "_stamp_analytics_freshness_on_completed_fetch", lambda *a, **k: None)
    monkeypatch.setattr(srv._analytics_executor, "submit", lambda fn: fn())

    srv._schedule_analytics_recompute(inflight_key, ticker, expiry, "test_bg_recover")
    assert srv._analytics_bg_fail_counts.get(inflight_key) == 1
    assert cache_key in srv._state_cache

    srv._schedule_analytics_recompute(inflight_key, ticker, expiry, "test_bg_recover")
    assert inflight_key not in srv._analytics_bg_fail_counts
    assert cache_key in srv._state_cache
