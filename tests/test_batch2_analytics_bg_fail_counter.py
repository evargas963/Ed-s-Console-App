"""Batch-2: analytics background recompute fail-counter wiring."""

from __future__ import annotations

from pathlib import Path

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
    srv._startup_analytics_executor()

    def _boom(*_a, **_k):
        raise RuntimeError("bg fetch failed")

    monkeypatch.setattr(srv, "_fetch_state", _boom)
    monkeypatch.setattr(srv, "_stamp_analytics_freshness_on_completed_fetch", lambda *a, **k: None)
    monkeypatch.setattr(srv._analytics_executor, "submit", lambda fn: fn())
    # UI_05: operator-class sources route to the priority pool — pin it to the
    # same inline-submit executor so this test stays synchronous.
    monkeypatch.setattr(srv, "_get_operator_priority_executor", lambda: srv._analytics_executor)

    for _ in range(threshold):
        srv._schedule_analytics_recompute(inflight_key, ticker, expiry, "test_bg_fail")

    assert cache_key in srv._state_cache
    assert srv._state_cache[cache_key]["ms_dict"].get("state_error") == "analytics_refresh_failed"
    assert inflight_key not in srv._analytics_bg_fail_counts


def test_schedule_analytics_recompute_resets_counter_on_success(monkeypatch, _bg_fail_spy):
    ticker, expiry, cache_key, inflight_key, srv = _bg_fail_spy
    calls = {"n": 0}
    srv._startup_analytics_executor()

    def _flaky(*_a, **_k):
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("transient")
        return {"ticker": ticker, "selected_exp": expiry}

    monkeypatch.setattr(srv, "_fetch_state", _flaky)
    monkeypatch.setattr(srv, "_stamp_analytics_freshness_on_completed_fetch", lambda *a, **k: None)
    monkeypatch.setattr(srv._analytics_executor, "submit", lambda fn: fn())
    # UI_05: operator-class sources route to the priority pool — pin it to the
    # same inline-submit executor so this test stays synchronous.
    monkeypatch.setattr(srv, "_get_operator_priority_executor", lambda: srv._analytics_executor)

    srv._schedule_analytics_recompute(inflight_key, ticker, expiry, "test_bg_recover")
    assert srv._analytics_bg_fail_counts.get(inflight_key) == 1
    assert cache_key in srv._state_cache

    srv._schedule_analytics_recompute(inflight_key, ticker, expiry, "test_bg_recover")
    assert inflight_key not in srv._analytics_bg_fail_counts
    assert cache_key in srv._state_cache


def test_safe_get_chain_raises_schwab_auth_error_on_invalid_grant(monkeypatch: pytest.MonkeyPatch):
    import schwab_client as sc

    monkeypatch.setenv("SCHWAB_API_KEY", "unit-test-key-not-live")
    monkeypatch.setenv("SCHWAB_APP_SECRET", "unit-test-secret-not-live")
    monkeypatch.delenv("ED_CI_OFFLINE", raising=False)
    sc._schwab_auth_failure_until_mono = 0.0

    class _FakeClient:
        def get_option_chain(self, *_a, **_k):
            raise RuntimeError(
                'unsupported_token_type: 400 Bad Request: "invalid_grant refresh token revoked"'
            )

    with pytest.raises(sc.SchwabAuthError):
        sc.safe_get_chain(_FakeClient(), "SPY")
    assert sc._schwab_auth_latched()


def test_safe_get_chain_latched_skips_second_call(monkeypatch: pytest.MonkeyPatch):
    import schwab_client as sc

    monkeypatch.setenv("SCHWAB_API_KEY", "unit-test-key-not-live")
    monkeypatch.setenv("SCHWAB_APP_SECRET", "unit-test-secret-not-live")
    monkeypatch.delenv("ED_CI_OFFLINE", raising=False)
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


def test_api_state_symbol_alias_routes_to_symbol(monkeypatch):
    import server as srv
    from starlette.testclient import TestClient

    seen: dict[str, str] = {}

    def fake_tier(ticker, expiry, force, update_source):
        seen["ticker"] = ticker
        from fastapi.responses import JSONResponse

        return JSONResponse({"ticker": ticker, "update_source": update_source})

    monkeypatch.setattr(srv, "_tier_c_analytics_json_response", fake_tier)
    with TestClient(srv.app) as client:
        r = client.get("/api/state", params={"symbol": "QQQ"})
        assert r.status_code == 200
        assert r.json()["ticker"] == "QQQ"
    assert seen["ticker"] == "QQQ"


def test_api_build_exposes_git_sha(monkeypatch):
    """BUILD_IDENTITY semantics (operator-approved 2026-07-10): git_sha is the
    STARTUP process identity; request-time repo state lives only under
    repository_state_now.repo_head_now."""
    import server as srv
    from starlette.testclient import TestClient

    monkeypatch.setattr(srv, "_repo_git_head_sha", lambda: "abc123deadbeef")
    with TestClient(srv.app) as client:
        r = client.get("/api/build")
        assert r.status_code == 200
        body = r.json()
        assert body["git_sha"] == body["process_identity"]["startup_git_sha"]
        assert body["repository_state_now"]["repo_head_now"] == "abc123deadbeef"
        assert body["git_sha_semantics"] == "startup_process_identity"
        assert body["contract"] == "meet_or_exceed_v1"


def test_publish_progressive_tier_c_cache_non_pending_shell():
    import server as srv
    from math_levels import ExposureRow, WallsRow, TotalsRow

    ticker = "ZZZ_PROG"
    exp = "2099-06-01"
    cache_key = (ticker, exp)
    inflight_key = srv._tier_c_inflight_key(ticker, None)
    srv._state_cache.pop(cache_key, None)
    # RC-128/134: kl_* walls come only from terrain overlay — seed a fresh terrain row
    # so the progressive shell proves carriage, not a resurrected analytics wall book.
    with srv._terrain_cache_lock:
        srv._terrain_cache[(ticker.upper())] = {
            "call_wall": 510.0,
            "put_wall": 490.0,
            "levels_stale": False,
            "computed_ts_utc": 1.0,
        }

    row = ExposureRow("CONSENSUS", None, 1.0, -1.0, 500.0, None, None, None, "Low", "Neutral")
    wall = WallsRow(
        "CONSENSUS",
        None,
        510.0,
        100.0,
        490.0,
        90.0,
        "CALL",
        510.0,
        100.0,
        505.0,
        80.0,
        495.0,
        70.0,
        "PUT",
        495.0,
        70.0,
        500.0,
        60.0,
        490.0,
        50.0,
        "CALL",
        500.0,
        60.0,
        490.0,
        50.0,
    )
    total = TotalsRow(
        "CONSENSUS",
        None,
        1.0,
        -1.0,
        0.0,
        1.0,
        -1.0,
        0.0,
        1000.0,
        900.0,
        100.0,
        0.9,
        0.2,
        0.1,
    )

    srv._publish_progressive_tier_c_cache(
        ticker=ticker,
        cache_key=cache_key,
        inflight_key=inflight_key,
        selected_exp=exp,
        expiries=[exp, "2099-06-08"],
        today_str="2099-01-01",
        spot_f=500.0,
        bid=499.9,
        ask=500.1,
        session_label="RTH",
        rows=[row],
        walls=[wall],
        totals=[total],
        consensus_summary=row,
        exposures={500.0: {"net_gex_1pct": 1.0}},
        gamma_flip=501.0,
        gamma_voids=[],
        charm_net=100.0,
        charm_dir="buying",
        charm_toward=500.0,
        pcr_val=0.9,
        kl_expiry_source="default_expiry",
        quote_spread_pts=0.2,
        quote_spread_source="schwab_bid_ask_live",
        update_source="test_progressive",
    )

    ent = srv._state_cache.get(cache_key)
    assert ent is not None
    md = ent["ms_dict"]
    assert md.get("analytics_pending_shell") is False
    assert md.get("analytics_partial_tier_c") is True
    assert md.get("analytics_refresh_in_progress") is True
    assert md.get("expiries") == [exp, "2099-06-08"]
    assert md.get("selected_exp") == exp
    assert md.get("kl_call_gamma_wall") == 510.0
    assert len(md.get("summary_rows") or []) == 1
    srv._state_cache.pop(cache_key, None)
    with srv._terrain_cache_lock:
        srv._terrain_cache.pop(ticker.upper(), None)


def test_post_analytics_warm_schedules_recompute_and_prewarm(monkeypatch):
    import server as srv
    from fastapi.testclient import TestClient

    scheduled: list[tuple] = []

    monkeypatch.setattr(
        srv,
        "_schedule_analytics_warm",
        lambda ticker, expiry, source, **kw: scheduled.append((ticker, expiry, source, kw))
        or {"ok": True, "ticker": ticker, "scheduled_refresh": True},
    )
    monkeypatch.setattr(srv, "_touch_tracked_ticker_view", lambda _t: None)

    client = TestClient(srv.app)
    resp = client.post("/api/analytics/warm?ticker=SPY")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("ok") is True
    assert body.get("ticker") == "SPY"
    assert scheduled
    assert scheduled[0][0] == "SPY"
    assert scheduled[0][2] == "client_warm_post"


def test_api_build_exposes_ui_maximize_sla():
    import server as srv
    from fastapi.testclient import TestClient

    client = TestClient(srv.app)
    resp = client.get("/api/build")
    assert resp.status_code == 200
    body = resp.json()
    sla = body.get("ui_maximize_sla_ms") or {}
    assert sla.get("first_quote") == srv.UI_MAXIMIZE_SLA_MS["first_quote"]
    assert sla.get("fusion_cards_panel_warm") == srv.UI_MAXIMIZE_SLA_MS["fusion_cards_panel_warm"]
    warm = body.get("ui_maximize_panel_warm_tickers") or []
    assert "SPY" in warm


def test_candle_seed_does_not_nest_analytics_executor():
    """Regression: parallel candle seed on _analytics_executor deadlocked Tier C
    (UI-MAXIMIZE). OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_2 moved the seed
    futures to the dedicated recompute-leaf pool — the invariant is unchanged:
    seeds never nest into the analytics pool."""
    text = Path(__file__).resolve().parent.parent.joinpath("server.py").read_text(encoding="utf-8")
    idx = text.find("UI-MAXIMIZE: parallel seed")
    assert idx != -1
    block = text[idx : idx + 800]  # UI_05 residual: window covers the priority-lane selection comment
    assert "_get_recompute_leaf_executor()" in block
    assert "_analytics_executor.submit(_seed_candles" not in text


def test_start_ed_console_bat_opens_edge_not_chrome():
    bat = (Path(__file__).resolve().parent.parent / "start_ed_console.bat").read_text(encoding="utf-8")
    assert "msedge.exe" in bat.lower()
    assert "chrome.exe" not in bat.lower()
    assert ">>>" not in bat
    assert 'set "PF86=%ProgramFiles(x86)%"' in bat
    assert 'start "" cmd /c "timeout /t 2 /nobreak >nul' in bat
    assert "ED_LIVE_ABLATION_EXPERIMENT" not in bat
