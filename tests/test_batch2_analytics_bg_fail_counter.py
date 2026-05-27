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


def test_record_analytics_bg_failure_writes_cold_cache_error_shell(_bg_fail_spy):
    ticker, expiry, cache_key, inflight_key, srv = _bg_fail_spy
    srv._state_cache.pop(cache_key, None)
    srv._record_analytics_bg_failure(
        inflight_key,
        ticker,
        reason="schwab_auth",
        detail="Refresh token is invalid, expired or revoked",
        token_invalid=True,
    )
    md, ck = srv._latest_cached_ms_and_key_for_ticker(ticker)
    assert md is not None
    assert ck is not None
    assert md.get("state_error") == "token_invalid"
    assert md.get("analytics_pending_shell") is False
    assert md.get("error") == "token_invalid"
    assert "reauth_schwab" in str(md.get("remediation", ""))


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


def test_safe_get_chain_raises_schwab_auth_error_on_invalid_grant():
    import schwab_client as sc

    sc._schwab_auth_failure_until_mono = 0.0

    class _FakeClient:
        def get_option_chain(self, *_a, **_k):
            raise RuntimeError(
                'unsupported_token_type: 400 Bad Request: "invalid_grant refresh token revoked"'
            )

    with pytest.raises(sc.SchwabAuthError):
        sc.safe_get_chain(_FakeClient(), "SPY")
    assert sc._schwab_auth_latched()


def test_safe_get_chain_latched_skips_second_call():
    import schwab_client as sc

    sc._schwab_auth_failure_until_mono = sc.time.monotonic() + 60.0
    calls = {"n": 0}

    class _FakeClient:
        def get_option_chain(self, *_a, **_k):
            calls["n"] += 1
            return object()

    with pytest.raises(sc.SchwabAuthError):
        sc.safe_get_chain(_FakeClient(), "SPY")
    assert calls["n"] == 0


def test_analytics_stale_not_sse_connected_only():
    import server as srv
    import time

    now = time.time()
    md: dict = {}
    entry = {
        "ms_dict": {"ticker": "SPY", "mhap_rows": [{"horizon": "1c"}]},
        "ts": now,
        "generated_at": now,
        "analytics_version": 3,
    }
    srv._attach_analytics_freshness_contract(
        md,
        data_cache_key=("SPY", "2099-01-01"),
        entry=entry,
        now=now + 0.5,
        sse_live=True,
        inflight_key=srv._tier_c_inflight_key("SPY", None),
    )
    assert md.get("analytics_stale") is False
    assert md.get("analytics_refresh_due") is True
    assert md.get("analytics_age_sec", 99) < 2.0


def test_resolve_ticker_param_symbol_alias():
    import server as srv

    assert srv._resolve_ticker_param("SPY", None) == "SPY"
    assert srv._resolve_ticker_param("SPY", "QQQ") == "QQQ"
    assert srv._resolve_ticker_param("SPY", "  qqq  ") == "QQQ"
