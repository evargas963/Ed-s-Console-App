"""S2A/S2B — Tier C /api/analytics/state card_freshness_v1 + operator mirror contract tests."""

from __future__ import annotations

import json
import time
from copy import deepcopy

import pytest

_CARD_FRESHNESS_V1_REQUIRED_KEYS = frozenset(
    {
        "card_trust_state",
        "card_actionable",
        "analytics_age_sec",
        "quote_age_sec",
        "bundle_age_sec",
        "analytics_ttl_sec",
        "quote_stale_sec",
        "bundle_trust_sec",
        "fallback_status",
        "carry_forward_status",
        "source_freshness",
        "stale_reason_codes",
        "quote_ts",
        "bundle_ts",
        "mhap_bundle_ts",
        "tier_c_cache_revalidated",
        "tier_c_cache_gate_ok",
        "analytics_stale",
        "analytics_generated_at",
        "analytics_refresh_in_progress",
        "quote_source_detail.carried_forward",
        "quote_source_detail.schwab_auth_degraded",
    }
)

_OPERATOR_MIRROR_KEYS = frozenset(
    {
        "operator_card_actionable",
        "operator_card_trust_state",
        "operator_stale_reason_codes",
        "operator_actionability_reason",
    }
)

_RAW_TRADE_FIELDS = (
    "final_tradeable",
    "call_signal",
    "call_state",
    "validation_passed",
    "analytics_stale",
)


def _mhap_four() -> list[dict]:
    return [{"horizon": h, "call": {"dir": "flat"}} for h in ("1c", "5c", "15c", "60c")]


def _trusted_ms_dict(*, ticker: str = "ZZZ_CF1", bundle_ts: float | None = None) -> dict:
    now = time.time()
    ts = bundle_ts if bundle_ts is not None else now - 1.0
    return {
        "ticker": ticker,
        "selected_exp": "2099-12-01",
        "final_tradeable": True,
        "call_signal": "wait",
        "call_state": "WATCH",
        "validation_passed": True,
        "fusion_available": True,
        "mhap_rows": _mhap_four(),
        "_server_build_ts": ts,
        "spot": 500.0,
    }


@pytest.fixture()
def tier_c_cache_spy(monkeypatch):
    import server as srv

    monkeypatch.setattr(srv, "_schedule_analytics_recompute", lambda *a, **k: None)
    monkeypatch.setattr(srv, "_attach_db_contention_operator_surface", lambda md: None)
    monkeypatch.setattr(srv, "_touch_tracked_ticker_view", lambda *a, **k: None)
    try:
        import market_state as ms

        monkeypatch.setattr(ms, "attach_operator_visible_field_lineage", lambda md: None)
    except ImportError:
        pass
    keys_before = set(srv._state_cache.keys())
    yield srv
    for key in list(srv._state_cache.keys()):
        if key not in keys_before:
            srv._state_cache.pop(key, None)


def _seed_cache(srv, ticker: str, expiry: str, ms_dict: dict, *, age_sec: float = 1.0) -> tuple:
    now = time.time()
    gen = now - age_sec
    key = (ticker, expiry)
    ms = dict(ms_dict)
    ms.setdefault("_server_build_ts", gen)
    srv._state_cache[key] = {
        "ms_dict": ms,
        "ts": gen,
        "generated_at": gen,
        "analytics_version": 2,
    }
    return key


def _response_body(resp) -> dict:
    return json.loads(resp.body)


def _operator_mirrors(body: dict) -> dict:
    return {k: body.get(k) for k in _OPERATOR_MIRROR_KEYS}


def _assert_operator_mirrors_nested(body: dict) -> None:
    block = body["card_freshness_v1"]
    assert body["operator_card_actionable"] is block["card_actionable"]
    assert body["operator_card_trust_state"] == block["card_trust_state"]
    assert body["operator_stale_reason_codes"] == block["stale_reason_codes"]
    if block["card_actionable"]:
        assert body["operator_actionability_reason"] is None
    else:
        assert body["operator_actionability_reason"] is not None


def test_operator_mirror_fields_present_on_analytics_state(tier_c_cache_spy):
    srv = tier_c_cache_spy
    ticker = "ZZZ_OP_PRESENT"
    expiry = "2099-12-10"
    _seed_cache(srv, ticker, expiry, _trusted_ms_dict(ticker=ticker), age_sec=1.0)
    body = _response_body(srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2b1"))
    assert _OPERATOR_MIRROR_KEYS <= set(body.keys())
    _assert_operator_mirrors_nested(body)


def test_operator_mirrors_equal_nested_card_freshness_v1(tier_c_cache_spy):
    srv = tier_c_cache_spy
    ticker = "ZZZ_OP_MIRROR"
    expiry = "2099-12-11"
    _seed_cache(srv, ticker, expiry, _trusted_ms_dict(ticker=ticker), age_sec=1.0)
    body = _response_body(srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2b1"))
    _assert_operator_mirrors_nested(body)


def test_operator_card_actionable_true_on_trusted_payload(tier_c_cache_spy, monkeypatch):
    srv = tier_c_cache_spy
    ticker = "ZZZ_OP_TRUE"
    expiry = "2099-12-12"
    now = time.time()
    _seed_cache(
        srv,
        ticker,
        expiry,
        _trusted_ms_dict(ticker=ticker, bundle_ts=now - 2.0),
        age_sec=1.0,
    )
    monkeypatch.setattr(
        srv._lmp,
        "get_quote",
        lambda t: {
            "fast_server_ts": now - 3.0,
            "quote_source_detail": {"carried_forward": False, "schwab_auth_degraded": False},
        },
    )
    body = _response_body(srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2b1"))
    assert body["operator_card_actionable"] is True
    assert body["operator_actionability_reason"] is None
    _assert_operator_mirrors_nested(body)


def test_operator_card_actionable_false_on_analytics_stale(tier_c_cache_spy):
    srv = tier_c_cache_spy
    ticker = "ZZZ_OP_ASTALE"
    expiry = "2099-12-13"
    md = _trusted_ms_dict(ticker=ticker)
    md["analytics_stale"] = True
    # Step 2 honest staleness: analytics_stale is recomputed from age — seed past the
    # missed-cycle grace window (TTL × ANALYTICS_STALE_GRACE_CYCLES), not one beat.
    _seed_cache(
        srv,
        ticker,
        expiry,
        md,
        age_sec=srv.CACHE_TTL * srv.ANALYTICS_STALE_GRACE_CYCLES + 2.0,
    )
    body = _response_body(srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2b1"))
    assert body["operator_card_actionable"] is False
    assert body["operator_actionability_reason"] is not None
    assert "analytics_stale" in body["operator_stale_reason_codes"]
    _assert_operator_mirrors_nested(body)


def test_operator_card_actionable_false_on_revalidate_quarantine(tier_c_cache_spy, monkeypatch):
    srv = tier_c_cache_spy
    ticker = "ZZZ_OP_RQ"
    expiry = "2099-12-14"
    now = time.time()
    md = _trusted_ms_dict(ticker=ticker, bundle_ts=now - 2.0)
    _seed_cache(srv, ticker, expiry, md, age_sec=1.0)
    monkeypatch.setattr(
        srv._lmp,
        "get_quote",
        lambda t: {
            "fast_server_ts": now - 1.0,
            "quote_source_detail": {"carried_forward": False, "schwab_auth_degraded": False},
        },
    )

    import trade_impacting_gate as tig

    def _quarantine(ms_dict, *, route, stale):
        out = dict(ms_dict)
        out["tier_c_cache_gate_ok"] = False
        return out

    monkeypatch.setattr(tig, "revalidate_cached_decision", _quarantine)
    body = _response_body(srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2b1"))
    assert body["operator_card_actionable"] is False
    assert "revalidate_quarantine" in body["operator_stale_reason_codes"]
    _assert_operator_mirrors_nested(body)


def test_operator_card_actionable_false_on_quote_newer_than_signal(tier_c_cache_spy, monkeypatch):
    srv = tier_c_cache_spy
    ticker = "ZZZ_OP_QN"
    expiry = "2099-12-15"
    now = time.time()
    _seed_cache(
        srv,
        ticker,
        expiry,
        _trusted_ms_dict(ticker=ticker, bundle_ts=now - 120.0),
        age_sec=1.0,
    )
    monkeypatch.setattr(
        srv._lmp,
        "get_quote",
        lambda t: {"fast_server_ts": now - 5.0, "quote_source_detail": {"carried_forward": False}},
    )
    body = _response_body(srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2b1"))
    assert body["operator_card_actionable"] is False
    assert "quote_newer_than_signal" in body["operator_stale_reason_codes"]
    _assert_operator_mirrors_nested(body)


def test_operator_card_actionable_false_on_quote_carried_forward(tier_c_cache_spy, monkeypatch):
    srv = tier_c_cache_spy
    ticker = "ZZZ_OP_CFW"
    expiry = "2099-12-16"
    now = time.time()
    _seed_cache(srv, ticker, expiry, _trusted_ms_dict(ticker=ticker, bundle_ts=now - 2.0), age_sec=1.0)
    monkeypatch.setattr(
        srv._lmp,
        "get_quote",
        lambda t: {
            "fast_server_ts": now - 1.0,
            "quote_source_detail": {"carried_forward": True, "schwab_auth_degraded": False},
        },
    )
    body = _response_body(srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2b1"))
    assert body["operator_card_actionable"] is False
    assert "quote_carried_forward" in body["operator_stale_reason_codes"]
    _assert_operator_mirrors_nested(body)


def test_regression_raw_trade_fields_unchanged_via_tier_c_response(tier_c_cache_spy, monkeypatch):
    srv = tier_c_cache_spy
    ticker = "ZZZ_OP_RAW"
    expiry = "2099-12-17"
    now = time.time()
    md = {
        "ticker": ticker,
        "final_tradeable": True,
        "call_signal": "wait",
        "call_state": "WATCH",
        "validation_passed": True,
        "analytics_stale": False,
        "fusion_available": True,
        "mhap_rows": _mhap_four(),
        "_server_build_ts": now - 2.0,
    }
    expected_raw = {k: md[k] for k in _RAW_TRADE_FIELDS}
    _seed_cache(srv, ticker, expiry, md, age_sec=1.0)
    monkeypatch.setattr(
        srv._lmp,
        "get_quote",
        lambda t: {
            "fast_server_ts": now - 1.0,
            "quote_source_detail": {"carried_forward": False, "schwab_auth_degraded": False},
        },
    )
    body = _response_body(srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2b1"))
    for key in _RAW_TRADE_FIELDS:
        assert body[key] == expected_raw[key]
    assert _OPERATOR_MIRROR_KEYS <= set(body.keys())


def test_card_freshness_v1_block_present_on_analytics_state(tier_c_cache_spy):
    srv = tier_c_cache_spy
    ticker = "ZZZ_CF_PRESENT"
    expiry = "2099-12-01"
    _seed_cache(srv, ticker, expiry, _trusted_ms_dict(ticker=ticker), age_sec=1.0)
    resp = srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2a")
    body = _response_body(resp)
    block = body.get("card_freshness_v1")
    assert isinstance(block, dict)
    assert _CARD_FRESHNESS_V1_REQUIRED_KEYS <= set(block.keys())


def test_analytics_age_exceeded_reason_code(tier_c_cache_spy):
    srv = tier_c_cache_spy
    ticker = "ZZZ_CF_AGE"
    expiry = "2099-12-02"
    _seed_cache(
        srv,
        ticker,
        expiry,
        _trusted_ms_dict(ticker=ticker),
        age_sec=srv.CACHE_TTL + 10.0,
    )
    resp = srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2a")
    codes = _response_body(resp)["card_freshness_v1"]["stale_reason_codes"]
    assert "analytics_age_exceeded" in codes
    assert "analytics_stale" in codes


def test_tier_c_stale_cache_serve_reason_codes(tier_c_cache_spy):
    srv = tier_c_cache_spy
    ticker = "ZZZ_CF_STALE"
    expiry = "2099-12-03"
    _seed_cache(
        srv,
        ticker,
        expiry,
        _trusted_ms_dict(ticker=ticker),
        age_sec=srv.CACHE_TTL + 5.0,
    )
    resp = srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2a")
    block = _response_body(resp)["card_freshness_v1"]
    assert "tier_c_cache_stale_serve" in block["stale_reason_codes"]
    assert block["card_trust_state"] in ("STALE", "DEGRADED", "UNAVAILABLE")


def test_quote_carried_forward_reason_code(tier_c_cache_spy, monkeypatch):
    srv = tier_c_cache_spy
    ticker = "ZZZ_CF_CFW"
    expiry = "2099-12-04"
    now = time.time()
    _seed_cache(srv, ticker, expiry, _trusted_ms_dict(ticker=ticker, bundle_ts=now - 2.0), age_sec=1.0)

    def _carried_quote(t):
        return {
            "ticker": t,
            "spot": 501.0,
            "fast_server_ts": now - 1.0,
            "quote_source_detail": {
                "carried_forward": True,
                "schwab_auth_degraded": True,
            },
        }

    monkeypatch.setattr(srv._lmp, "get_quote", _carried_quote)
    resp = srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2a")
    block = _response_body(resp)["card_freshness_v1"]
    assert block["quote_source_detail.carried_forward"] is True
    assert "quote_carried_forward" in block["stale_reason_codes"]
    assert "auth_fallback" in block["stale_reason_codes"]
    assert block["card_actionable"] is False


def test_auth_degraded_reason_code(tier_c_cache_spy, monkeypatch):
    srv = tier_c_cache_spy
    ticker = "ZZZ_CF_AUTH"
    expiry = "2099-12-05"
    now = time.time()
    _seed_cache(srv, ticker, expiry, _trusted_ms_dict(ticker=ticker), age_sec=1.0)

    monkeypatch.setattr(
        srv._lmp,
        "get_quote",
        lambda t: {
            "fast_server_ts": now - 1.0,
            "quote_source_detail": {
                "carried_forward": False,
                "schwab_auth_degraded": True,
            },
        },
    )
    block = _response_body(
        srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2a")
    )["card_freshness_v1"]
    assert block["quote_source_detail.schwab_auth_degraded"] is True
    assert "auth_degraded" in block["stale_reason_codes"]


def test_quote_newer_than_signal_simulated(tier_c_cache_spy, monkeypatch):
    srv = tier_c_cache_spy
    ticker = "ZZZ_CF_QN"
    expiry = "2099-12-06"
    now = time.time()
    bundle_ts = now - 120.0
    quote_ts = now - 5.0
    _seed_cache(
        srv,
        ticker,
        expiry,
        _trusted_ms_dict(ticker=ticker, bundle_ts=bundle_ts),
        age_sec=1.0,
    )
    monkeypatch.setattr(
        srv._lmp,
        "get_quote",
        lambda t: {"fast_server_ts": quote_ts, "quote_source_detail": {"carried_forward": False}},
    )
    codes = _response_body(
        srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2a")
    )["card_freshness_v1"]["stale_reason_codes"]
    assert "quote_newer_than_signal" in codes
    assert "mhap_older_than_quote" in codes


def test_card_actionable_false_when_trust_withheld(tier_c_cache_spy):
    srv = tier_c_cache_spy
    ticker = "ZZZ_CF_NA"
    expiry = "2099-12-07"
    md = _trusted_ms_dict(ticker=ticker)
    md["analytics_stale"] = True
    _seed_cache(srv, ticker, expiry, md, age_sec=srv.CACHE_TTL + 2.0)
    block = _response_body(
        srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2a")
    )["card_freshness_v1"]
    assert block["card_actionable"] is False
    assert block["card_trust_state"] == "STALE"


def test_regression_existing_trade_fields_unchanged(tier_c_cache_spy):
    srv = tier_c_cache_spy
    now = time.time()
    md = {
        "ticker": "SPY",
        "final_tradeable": True,
        "call_signal": "wait",
        "call_state": "WATCH",
        "validation_passed": True,
        "analytics_stale": False,
        "analytics_age_sec": 1.0,
        "analytics_generated_at": "2026-01-01T00:00:00+00:00",
        "analytics_refresh_in_progress": False,
        "mhap_rows": _mhap_four(),
        "fusion_available": True,
        "_server_build_ts": now - 2.0,
        "fast_server_ts": now - 1.0,
    }
    before = deepcopy(md)
    srv._attach_card_freshness_v1_block(
        md,
        ticker="SPY",
        now=now,
        analytics_ttl_sec=5.0,
        tier_c_cache_stale_serve=False,
        plane_quote={
            "fast_server_ts": now - 1.0,
            "quote_source_detail": {"carried_forward": False, "schwab_auth_degraded": False},
        },
    )
    for key, value in before.items():
        assert md[key] == value
    assert isinstance(md.get("card_freshness_v1"), dict)


# ── SESSION_OPEN_ANCHOR_WARM_SLICE_V1 — RTH-open anchor warm locks ───────────


def test_session_open_anchor_warm_schedules_all_base_anchors(monkeypatch):
    """Warm queues SPY/QQQ/IWM through the shared panel-warm worker with the session source."""
    import server as srv

    submitted: list[tuple] = []
    monkeypatch.setattr(srv, "_submit_analytics_task", lambda fn, *a, **k: submitted.append((fn, a)))
    srv._run_session_open_anchor_warm()
    assert srv.UI_MAXIMIZE_PANEL_WARM_TICKERS == ("SPY", "QQQ", "IWM")
    assert [a[0] for _fn, a in submitted] == ["SPY", "QQQ", "IWM"]
    for fn, args in submitted:
        assert fn is srv._warm_panel_ticker_after_delay
        assert args[2] == srv.SESSION_OPEN_ANCHOR_WARM_UPDATE_SOURCE == "session_open_anchor_warm"


def test_session_open_anchor_warm_uses_existing_recompute_path_and_mutates_no_cache(monkeypatch):
    """Warm delegates to _schedule_analytics_recompute (existing dedupe cone); no direct state writes."""
    import server as srv

    scheduled: list[tuple] = []
    monkeypatch.setattr(srv, "_submit_analytics_task", lambda fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(srv, "_prewarm_inference_models_worker", lambda t: None)
    monkeypatch.setattr(
        srv,
        "_schedule_analytics_recompute",
        lambda key, t, e, src: scheduled.append((key, t, e, src)),
    )
    cache_before = dict(srv._state_cache)
    srv._run_session_open_anchor_warm()
    assert scheduled == [
        (srv._tier_c_inflight_key(t, None), t, None, "session_open_anchor_warm")
        for t in ("SPY", "QQQ", "IWM")
    ]
    assert srv._state_cache == cache_before


def test_session_open_anchor_warm_respects_inflight_dedupe(monkeypatch):
    """An in-flight recompute for the same key absorbs the warm — no duplicate storm."""
    import server as srv

    submitted: list = []
    monkeypatch.setattr(srv, "_analytics_bg_shutdown", False)
    monkeypatch.setattr(srv, "_submit_analytics_task", lambda fn, *a, **k: submitted.append(fn))
    key = srv._tier_c_inflight_key("SPY", None)
    with srv._analytics_bg_lock:
        srv._analytics_inflight.add(key)
    try:
        srv._schedule_analytics_recompute(key, "SPY", None, "session_open_anchor_warm")
        assert submitted == []
    finally:
        with srv._analytics_bg_lock:
            srv._analytics_inflight.discard(key)
    # Control: with the key no longer in flight, the same call DOES submit work.
    srv._schedule_analytics_recompute(key, "SPY", None, "session_open_anchor_warm")
    try:
        assert len(submitted) == 1
    finally:
        with srv._analytics_bg_lock:
            srv._analytics_inflight.discard(key)


def test_session_open_anchor_warm_due_predicate_rth_gate_and_daily_latch():
    """Due only on ET weekdays inside RTH, and only once per ET date."""
    import server as srv
    from datetime import datetime

    from time_et import ET

    rth_monday = datetime(2026, 7, 6, 9, 31, tzinfo=ET)
    pre_open = datetime(2026, 7, 6, 9, 29, tzinfo=ET)
    post_close = datetime(2026, 7, 6, 16, 30, tzinfo=ET)
    saturday = datetime(2026, 7, 4, 10, 0, tzinfo=ET)
    assert srv._session_open_anchor_warm_due(rth_monday, None) is True
    assert srv._session_open_anchor_warm_due(rth_monday, "2026-07-05") is True
    assert srv._session_open_anchor_warm_due(rth_monday, "2026-07-06") is False
    assert srv._session_open_anchor_warm_due(pre_open, None) is False
    assert srv._session_open_anchor_warm_due(post_close, None) is False
    assert srv._session_open_anchor_warm_due(saturday, None) is False


def test_startup_warm_unchanged_uses_startup_source(monkeypatch):
    """Regression: startup warm still queues the same anchors with update_source=startup_warm."""
    import server as srv

    submitted: list[tuple] = []
    monkeypatch.setattr(srv, "_analytics_bg_shutdown", False)
    monkeypatch.setattr(srv, "_submit_analytics_task", lambda fn, *a, **k: submitted.append((fn, a)))
    srv._schedule_startup_analytics_warm()
    assert [a[0] for _fn, a in submitted] == ["SPY", "QQQ", "IWM"]
    for fn, args in submitted:
        assert fn is srv._warm_panel_ticker_after_delay
        assert args[2] == "startup_warm"


def test_freshness_constants_unchanged_by_warm_slice():
    """TTL / grace semantics are untouched by SESSION_OPEN_ANCHOR_WARM_SLICE_V1."""
    import server as srv

    assert srv.CACHE_TTL == 5
    assert srv.VIEWER_STATE_CACHE_TTL_SEC == 5.0
    assert srv.ANALYTICS_STALE_GRACE_CYCLES == 2.0


def test_analytics_recompute_duration_instrumentation_recorded(monkeypatch):
    """Completed recompute records additive duration (module dict + payload field) pre-stamp."""
    import server as srv

    ticker = "ZZZ_WARMDUR"
    stamped: dict = {}
    monkeypatch.setattr(srv, "_analytics_bg_shutdown", False)
    monkeypatch.setattr(srv, "_submit_analytics_task", lambda fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(
        srv,
        "_fetch_state",
        lambda t, e, update_source=None: {"ticker": t, "selected_exp": None},
    )
    monkeypatch.setattr(
        srv,
        "_stamp_analytics_freshness_on_completed_fetch",
        lambda md, t, k: stamped.update(md),
    )
    monkeypatch.setattr(srv, "_attach_card_freshness_v1_block", lambda *a, **k: None)
    srv._analytics_recompute_last_duration_sec.pop(ticker, None)
    key = srv._tier_c_inflight_key(ticker, None)
    srv._schedule_analytics_recompute(key, ticker, None, "session_open_anchor_warm")
    dur = srv._analytics_recompute_last_duration_sec.get(ticker)
    assert dur is not None and dur >= 0.0
    assert stamped.get("analytics_recompute_duration_sec") == dur
    with srv._analytics_bg_lock:
        assert key not in srv._analytics_inflight


# ── TIER_C_STAGE_TIMER_INSTRUMENTATION_V1 — stage timing + cache observability locks ──


def test_executor_queue_wait_recorded_on_completed_recompute(monkeypatch):
    """Completed recompute carries analytics_executor_queue_wait_sec (>= 0, additive)."""
    import server as srv

    ticker = "ZZZ_QWAIT"
    stamped: dict = {}
    monkeypatch.setattr(srv, "_analytics_bg_shutdown", False)
    monkeypatch.setattr(srv, "_submit_analytics_task", lambda fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(
        srv,
        "_fetch_state",
        lambda t, e, update_source=None: {"ticker": t, "selected_exp": None},
    )
    monkeypatch.setattr(
        srv,
        "_stamp_analytics_freshness_on_completed_fetch",
        lambda md, t, k: stamped.update(md),
    )
    monkeypatch.setattr(srv, "_attach_card_freshness_v1_block", lambda *a, **k: None)
    key = srv._tier_c_inflight_key(ticker, None)
    srv._schedule_analytics_recompute(key, ticker, None, "sse_loop_test")
    assert "analytics_executor_queue_wait_sec" in stamped
    assert stamped["analytics_executor_queue_wait_sec"] >= 0.0
    assert "analytics_recompute_duration_sec" in stamped
    with srv._analytics_bg_lock:
        assert key not in srv._analytics_inflight


def test_cache_observability_counters_are_passive_observation_only():
    """Shell builds / expiry evictions / bg-failure stale-marks increment counters without behavior change."""
    import server as srv

    before = dict(srv._analytics_cache_observability)

    shell = srv._minimal_analytics_pending_dict("ZZZ_OBS1", None)
    assert shell["analytics_pending_shell"] is True
    assert (
        srv._analytics_cache_observability["pending_shell_builds"]
        == before["pending_shell_builds"] + 1
    )

    srv._state_cache[("ZZZ_OBS2", "2099-01-01")] = {"ms_dict": {"ticker": "ZZZ_OBS2"}}
    srv._state_cache[("ZZZ_OBS2", "2099-02-01")] = {"ms_dict": {"ticker": "ZZZ_OBS2"}}
    try:
        srv._evict_old_expiry_entries("ZZZ_OBS2", "2099-01-01")
        assert ("ZZZ_OBS2", "2099-02-01") not in srv._state_cache
        assert ("ZZZ_OBS2", "2099-01-01") in srv._state_cache
        assert (
            srv._analytics_cache_observability["expiry_evictions"]
            == before["expiry_evictions"] + 1
        )

        srv._invalidate_analytics_cache_after_bg_failures(
            ("ZZZ_OBS2", "2099-01-01"), "ZZZ_OBS2", reason="test_reason"
        )
        marked = srv._state_cache[("ZZZ_OBS2", "2099-01-01")]["ms_dict"]
        assert marked["analytics_stale"] is True
        assert (
            srv._analytics_cache_observability["bg_failure_stale_marks"]
            == before["bg_failure_stale_marks"] + 1
        )
    finally:
        srv._state_cache.pop(("ZZZ_OBS2", "2099-01-01"), None)
        srv._state_cache.pop(("ZZZ_OBS2", "2099-02-01"), None)


def test_executor_sizing_unchanged_by_stage_timer_slice():
    """Hard constraint: analytics executor stays at 4 workers (no sizing change in this slice)."""
    import server as srv

    assert srv._get_analytics_executor()._max_workers == 4


def test_timing_fields_do_not_affect_trust_or_actionability(tier_c_cache_spy, monkeypatch):
    """Identical payloads with/without timing fields produce identical operator actionability."""
    srv = tier_c_cache_spy
    now = time.time()
    monkeypatch.setattr(
        srv._lmp,
        "get_quote",
        lambda t: {
            "fast_server_ts": now - 1.0,
            "quote_source_detail": {"carried_forward": False, "schwab_auth_degraded": False},
        },
    )
    plain = _trusted_ms_dict(ticker="ZZZ_TIM1", bundle_ts=now - 2.0)
    timed = _trusted_ms_dict(ticker="ZZZ_TIM2", bundle_ts=now - 2.0)
    timed.update(
        {
            "analytics_recompute_duration_sec": 42.0,
            "analytics_executor_queue_wait_sec": 9.5,
            "_finalize_tail_ms": 1234,
            "_compute_breakdown": {"schwab_chain_ms": 9000.0, "chain_gate_wait_ms": 3200.0},
            "chain_gate_wait_sec": 3.2,
            "analytics_cache_observability_v1": {"pending_shell_builds": 99},
        }
    )
    _seed_cache(srv, "ZZZ_TIM1", "2099-12-20", plain, age_sec=1.0)
    _seed_cache(srv, "ZZZ_TIM2", "2099-12-21", timed, age_sec=1.0)
    body_plain = _response_body(
        srv._tier_c_analytics_json_response("ZZZ_TIM1", "2099-12-20", False, "test_timing")
    )
    body_timed = _response_body(
        srv._tier_c_analytics_json_response("ZZZ_TIM2", "2099-12-21", False, "test_timing")
    )
    assert body_plain["operator_card_actionable"] == body_timed["operator_card_actionable"]
    assert body_plain["operator_card_trust_state"] == body_timed["operator_card_trust_state"]
    assert body_plain["analytics_stale"] == body_timed["analytics_stale"]


def test_stage_timer_surfaces_present_in_fetch_state_source():
    """Source lock: stage marks + additive timing fields exist in the Tier C recompute path."""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    for needle in (
        '_stage_marks.append(("stack_runtime_governance_attach"',
        '_stage_marks.append(("db_snapshot_write_accuracy"',
        '_stage_marks.append(("signals_engine_build_market_state"',
        'ms_dict["_compute_breakdown"]',
        'ms_dict["_finalize_tail_ms"]',
        'result["analytics_executor_queue_wait_sec"]',
        'ms_dict["analytics_cache_observability_v1"]',
    ):
        assert needle in src, f"missing stage-timer surface: {needle}"


# ── TIER_C_CHAIN_FETCH_GATE_IMPLEMENTATION_V1 — chain-fetch gate locks ────────


def test_chain_fetch_gate_serializes_concurrent_fetches(monkeypatch):
    """Three threads through _gated_safe_get_chain never overlap inside safe_get_chain."""
    import threading as th

    import server as srv

    windows: list[tuple[float, float]] = []
    win_lock = th.Lock()

    def _slow_chain(client, ticker, *, strike_count):
        entered = time.monotonic()
        time.sleep(0.15)
        with win_lock:
            windows.append((entered, time.monotonic()))
        return f"RESP_{ticker}"

    monkeypatch.setattr(srv, "safe_get_chain", _slow_chain)
    threads = [
        th.Thread(target=srv._gated_safe_get_chain, args=(None, f"ZZZ_G{i}"), kwargs={"strike_count": 5})
        for i in range(3)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert len(windows) == 3
    ordered = sorted(windows)
    for (_, a_end), (b_start, _) in zip(ordered, ordered[1:]):
        assert b_start >= a_end - 0.01, "chain fetches overlapped — gate did not serialize"


def test_chain_fetch_gate_fail_open_on_timeout(monkeypatch):
    """Gate held elsewhere + short timeout: fetch still executes; timeout counter increments."""
    import server as srv

    monkeypatch.setattr(srv, "CHAIN_FETCH_GATE_ACQUIRE_TIMEOUT_SEC", 0.05)
    calls: list[str] = []
    monkeypatch.setattr(
        srv,
        "safe_get_chain",
        lambda client, ticker, *, strike_count: (calls.append(ticker), "RESP")[1],
    )
    assert srv._schwab_chain_fetch_gate.acquire(timeout=1)
    try:
        before = srv._chain_fetch_gate_timeout_count
        resp, gate_wait_sec, fetch_sec = srv._gated_safe_get_chain(None, "ZZZ_TMO", strike_count=5)
        assert resp == "RESP"
        assert calls == ["ZZZ_TMO"]
        assert srv._chain_fetch_gate_timeout_count == before + 1
        assert gate_wait_sec >= 0.05
        assert fetch_sec >= 0.0
    finally:
        srv._schwab_chain_fetch_gate.release()
    # Timeout path must not double-release: gate is acquirable exactly once now.
    assert srv._schwab_chain_fetch_gate.acquire(timeout=1)
    srv._schwab_chain_fetch_gate.release()


def test_chain_fetch_gate_returns_timings_on_normal_path(monkeypatch):
    """Uncontended gate: response + non-negative gate wait + fetch duration."""
    import server as srv

    monkeypatch.setattr(srv, "safe_get_chain", lambda client, ticker, *, strike_count: "OK")
    resp, gate_wait_sec, fetch_sec = srv._gated_safe_get_chain(None, "ZZZ_NORM", strike_count=5)
    assert resp == "OK"
    assert gate_wait_sec >= 0.0
    assert fetch_sec >= 0.0
    # Gate released: immediately acquirable.
    assert srv._schwab_chain_fetch_gate.acquire(timeout=1)
    srv._schwab_chain_fetch_gate.release()


def test_chain_fetch_call_shape_and_gated_site_source_lock():
    """Fidelity lock: helper preserves the exact Schwab call shape; _fetch_state routes through it."""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    assert "resp = safe_get_chain(client, ticker, strike_count=strike_count)" in src
    assert "_gated_safe_get_chain, client, ticker, strike_count=CHAIN_STRIKE_COUNT" in src
    assert 'ms_dict["chain_gate_wait_sec"]' in src
    assert '_stage_ms["chain_gate_wait_ms"]' in src


# ── ANCHOR_QUOTE_LANE_REFRESHER_V1 ────────────────────────────────────────────


class _FakePlane:
    """Minimal live_market_plane stand-in: per-ticker rows, read-only for the refresher."""

    def __init__(self, rows: dict):
        self.rows = rows

    def get_quote(self, ticker: str):
        return self.rows.get(ticker)


def test_anchor_quote_lane_needs_refresh_predicate():
    """Absent row, missing/garbled fast_server_ts, or age > max-age ⇒ refresh; fresh ⇒ skip."""
    import server as srv

    now = 1_000_000.0
    max_age = srv.ANCHOR_QUOTE_LANE_MAX_AGE_SEC
    assert srv._anchor_quote_lane_needs_refresh(None, now) is True
    assert srv._anchor_quote_lane_needs_refresh({}, now) is True
    assert srv._anchor_quote_lane_needs_refresh({"fast_server_ts": None}, now) is True
    assert srv._anchor_quote_lane_needs_refresh({"fast_server_ts": "bogus"}, now) is True
    assert srv._anchor_quote_lane_needs_refresh({"fast_server_ts": now - max_age - 0.1}, now) is True
    assert srv._anchor_quote_lane_needs_refresh({"fast_server_ts": now - max_age + 0.1}, now) is False
    assert srv._anchor_quote_lane_needs_refresh({"fast_server_ts": now}, now) is False


def test_anchor_lane_refresh_bootstraps_missing_lane(monkeypatch):
    """Missing-lane case (IWM shape): absent plane row is bootstrapped with prev=None."""
    import server as srv

    now = 2_000_000.0
    monkeypatch.setattr(srv, "UI_MAXIMIZE_PANEL_WARM_TICKERS", ("ZZQA",))
    monkeypatch.setattr(srv, "_lmp", _FakePlane({}))
    calls: list[tuple] = []
    monkeypatch.setattr(
        srv,
        "_record_rest_fast_quote_with_auth_fallback",
        lambda tkr, prev, ing: calls.append((tkr, prev, ing)),
    )
    boots_before = srv._anchor_quote_lane_refresh_counts["bootstraps"]
    assert srv._run_anchor_quote_lane_refresh_once(now) == 1
    assert calls == [("ZZQA", None, "rest_anchor_lane_refresher")]
    assert srv._anchor_quote_lane_refresh_counts["bootstraps"] == boots_before + 1


def test_anchor_lane_refresh_recovers_frozen_lane(monkeypatch):
    """Frozen-lane case (QQQ shape): old fast_server_ts is refreshed, prev row passed through."""
    import server as srv

    now = 3_000_000.0
    frozen = {"fast_server_ts": now - 7_120.0, "spot": 500.0}
    monkeypatch.setattr(srv, "UI_MAXIMIZE_PANEL_WARM_TICKERS", ("ZZQB",))
    monkeypatch.setattr(srv, "_lmp", _FakePlane({"ZZQB": frozen}))
    calls: list[tuple] = []
    monkeypatch.setattr(
        srv,
        "_record_rest_fast_quote_with_auth_fallback",
        lambda tkr, prev, ing: calls.append((tkr, prev, ing)),
    )
    refreshes_before = srv._anchor_quote_lane_refresh_counts["refreshes"]
    assert srv._run_anchor_quote_lane_refresh_once(now) == 1
    assert calls == [("ZZQB", frozen, "rest_anchor_lane_refresher")]
    assert srv._anchor_quote_lane_refresh_counts["refreshes"] == refreshes_before + 1


def test_anchor_lane_refresh_skips_fresh_lane_no_stream_interference(monkeypatch):
    """A lane younger than max-age (e.g. actively streamed ticker) is left alone entirely."""
    import server as srv

    now = 4_000_000.0
    fresh = {"fast_server_ts": now - 1.0, "spot": 600.0}
    monkeypatch.setattr(srv, "UI_MAXIMIZE_PANEL_WARM_TICKERS", ("ZZQC",))
    monkeypatch.setattr(srv, "_lmp", _FakePlane({"ZZQC": fresh}))
    calls: list[tuple] = []
    monkeypatch.setattr(
        srv,
        "_record_rest_fast_quote_with_auth_fallback",
        lambda tkr, prev, ing: calls.append((tkr, prev, ing)),
    )
    assert srv._run_anchor_quote_lane_refresh_once(now) == 0
    assert calls == []


def test_anchor_lane_refresh_error_isolated_per_ticker(monkeypatch):
    """One ticker's REST failure is counted and does not block the rest of the roster."""
    import server as srv

    now = 5_000_000.0
    monkeypatch.setattr(srv, "UI_MAXIMIZE_PANEL_WARM_TICKERS", ("ZZQD", "ZZQE"))
    monkeypatch.setattr(srv, "_lmp", _FakePlane({}))
    calls: list[str] = []

    def _boom_then_ok(tkr, prev, ing):
        calls.append(tkr)
        if tkr == "ZZQD":
            raise RuntimeError("rest failure")

    monkeypatch.setattr(srv, "_record_rest_fast_quote_with_auth_fallback", _boom_then_ok)
    errors_before = srv._anchor_quote_lane_refresh_counts["errors"]
    assert srv._run_anchor_quote_lane_refresh_once(now) == 1
    assert calls == ["ZZQD", "ZZQE"]
    assert srv._anchor_quote_lane_refresh_counts["errors"] == errors_before + 1


def test_anchor_lane_refresh_ticker_agnostic_no_literals():
    """AST lock: the refresher functions carry no uppercase ticker string literals."""
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    targets = {
        "_anchor_quote_lane_needs_refresh",
        "_run_anchor_quote_lane_refresh_once",
        "_anchor_quote_lane_refresh_loop",
    }
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in targets:
            found.add(node.name)
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    assert not (sub.value.isalpha() and sub.value.isupper()), (
                        f"ticker-literal-shaped constant {sub.value!r} in {node.name}"
                    )
    assert found == targets


def test_anchor_lane_refresh_lifespan_wiring_source_lock():
    """Lifespan starts the refresher daemon and stops it on shutdown."""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    assert "target=_anchor_quote_lane_refresh_loop" in src
    assert src.count("_anchor_quote_lane_refresh_stop.set()") == 1
    assert src.count("_anchor_quote_lane_refresh_stop.clear()") == 1


def test_anchor_lane_refresh_constants_inside_trust_threshold():
    """Lane max-age + poll stay under the 30s quote-trust threshold; TTL/grace untouched."""
    import server as srv

    assert srv.ANCHOR_QUOTE_LANE_REFRESH_POLL_SEC == 20.0
    assert srv.ANCHOR_QUOTE_LANE_MAX_AGE_SEC == 20.0
    assert srv.ANCHOR_QUOTE_LANE_MAX_AGE_SEC < srv._CARD_FRESHNESS_V1_QUOTE_STALE_SEC == 30.0
    assert srv.CACHE_TTL == 5
    assert srv.ANALYTICS_STALE_GRACE_CYCLES == 2.0


# ── ANALYTICS_LOG_ONLY_CACHE_CLOBBER_GUARD_V1 ────────────────────────────────


def _full_bundle_entry(version: int, gen_ts: float) -> dict:
    """Fixture: cache entry shaped like a full Tier C publish (server.py full-write site)."""
    return {
        "ts": gen_ts,
        "generated_at": gen_ts,
        "analytics_version": version,
        "ms_dict": {"mhap_rows": [{"h": "1c"}], "fusion_available": True, "spot": 100.0},
        "pcr_val": 0.9,
        "spot_f": 100.0,
        "vix": 15.0,
        "price_levels": {"lvl": 1},
        "pl_date": "2026-07-07",
        "pl_mono": 123.0,
    }


def _clear_fixture_cache_keys(srv, ticker: str) -> None:
    for k in [k for k in list(srv._state_cache) if k[0] == ticker]:
        del srv._state_cache[k]


def test_analytics_cache_entry_is_full_bundle_predicate():
    """Shape predicate: bundle ⇔ non-empty ms_dict AND generated_at; shells/minimal excluded."""
    import server as srv

    assert srv._analytics_cache_entry_is_full_bundle(None) is False
    assert srv._analytics_cache_entry_is_full_bundle({}) is False
    assert srv._analytics_cache_entry_is_full_bundle({"ms_dict": {}, "generated_at": 1.0}) is False
    assert srv._analytics_cache_entry_is_full_bundle({"ms_dict": {"spot": 1}}) is False
    assert srv._analytics_cache_entry_is_full_bundle(_full_bundle_entry(3, 1000.0)) is True


def test_log_only_touch_preserves_full_bundle():
    """Logger touch on a full bundle: ms_dict/generated_at/version/ts intact, scalars refreshed."""
    import server as srv

    tkr = "ZZLA"
    key = (tkr, "2026-07-07")
    try:
        seeded = _full_bundle_entry(version=7, gen_ts=1000.0)
        srv._state_cache[key] = seeded
        action = srv._log_only_cache_touch(key, tkr, "2026-07-07", 1.1, 101.5, 16.5)
        assert action == "preserved_full_bundle"
        ent = srv._state_cache[key]
        assert ent is seeded
        assert ent["ms_dict"] == {"mhap_rows": [{"h": "1c"}], "fusion_available": True, "spot": 100.0}
        assert ent["generated_at"] == 1000.0
        assert ent["ts"] == 1000.0
        assert ent["analytics_version"] == 7
        assert ent["pcr_val"] == 1.1
        assert ent["spot_f"] == 101.5
        assert ent["vix"] == 16.5
        # None scalars never degrade existing observations.
        srv._log_only_cache_touch(key, tkr, "2026-07-07", None, None, None)
        assert ent["pcr_val"] == 1.1 and ent["spot_f"] == 101.5 and ent["vix"] == 16.5
    finally:
        _clear_fixture_cache_keys(srv, tkr)


def test_log_only_touch_version_monotonic_across_logger_interleave():
    """full v7 → logger touch → next full write increments to 8 (no reset to 1)."""
    import server as srv

    tkr = "ZZLB"
    key = (tkr, "2026-07-07")
    try:
        srv._state_cache[key] = _full_bundle_entry(version=7, gen_ts=1000.0)
        srv._log_only_cache_touch(key, tkr, "2026-07-07", 1.0, 100.0, 15.0)
        prev_ent = srv._state_cache.get(key) or {}
        # Same expression as the full-publish site (_next_ver).
        assert int(prev_ent.get("analytics_version", 0)) + 1 == 8
        assert srv._analytics_cache_entry_is_full_bundle(prev_ent) is True
    finally:
        _clear_fixture_cache_keys(srv, tkr)


def test_log_only_touch_legacy_minimal_write_when_no_bundle():
    """No entry (or empty-ms_dict entry): legacy minimal write, never masquerading as a bundle."""
    import server as srv

    tkr = "ZZLC"
    key = (tkr, "2026-07-07")
    try:
        assert srv._state_cache.get(key) is None
        action = srv._log_only_cache_touch(key, tkr, "2026-07-07", 0.8, 55.0, 14.0)
        assert action == "legacy_minimal_write"
        ent = srv._state_cache[key]
        assert ent["ms_dict"] == {}
        assert "generated_at" not in ent
        assert "analytics_version" not in ent
        assert srv._analytics_cache_entry_is_full_bundle(ent) is False
        # Repeat touch on the minimal entry stays minimal (does not get worse or better).
        action2 = srv._log_only_cache_touch(key, tkr, "2026-07-07", 0.9, 56.0, 14.5)
        assert action2 == "legacy_minimal_write"
        assert srv._state_cache[key]["ms_dict"] == {}
    finally:
        _clear_fixture_cache_keys(srv, tkr)


def test_log_only_touch_preserves_partial_and_error_shells():
    """Progressive partials and error shells (bundle-shaped) survive logger touches."""
    import server as srv

    tkr = "ZZLD"
    key = (tkr, "2026-07-07")
    try:
        partial = {
            "ts": 2000.0,
            "generated_at": 2000.0,
            "analytics_version": 0,
            "ms_dict": {"analytics_partial_tier_c": True, "mhap_rows": [], "spot": 50.0},
            "pcr_val": None,
            "spot_f": 50.0,
            "vix": None,
        }
        srv._state_cache[key] = partial
        assert srv._log_only_cache_touch(key, tkr, "2026-07-07", 0.7, 51.0, 13.0) == "preserved_full_bundle"
        assert srv._state_cache[key] is partial
        assert srv._state_cache[key]["ms_dict"]["analytics_partial_tier_c"] is True
        assert srv._state_cache[key]["generated_at"] == 2000.0

        error_shell = {
            "ts": 3000.0,
            "generated_at": 3000.0,
            "analytics_version": 0,
            "ms_dict": {"state_error": "analytics_refresh_failed", "mhap_rows": []},
            "pcr_val": None,
            "spot_f": None,
            "vix": None,
        }
        srv._state_cache[key] = error_shell
        assert srv._log_only_cache_touch(key, tkr, "2026-07-07", None, None, None) == "preserved_full_bundle"
        assert srv._state_cache[key]["ms_dict"]["state_error"] == "analytics_refresh_failed"
    finally:
        _clear_fixture_cache_keys(srv, tkr)


def test_log_only_touch_still_evicts_other_expiry_keys():
    """The guard keeps the pre-existing other-expiry eviction on both paths."""
    import server as srv

    tkr = "ZZLE"
    try:
        srv._state_cache[(tkr, "2026-07-08")] = {"ms_dict": {}, "ts": 1.0}
        srv._state_cache[(tkr, "2026-07-07")] = _full_bundle_entry(version=2, gen_ts=1000.0)
        srv._log_only_cache_touch((tkr, "2026-07-07"), tkr, "2026-07-07", 1.0, 100.0, 15.0)
        assert (tkr, "2026-07-08") not in srv._state_cache
        assert (tkr, "2026-07-07") in srv._state_cache
    finally:
        _clear_fixture_cache_keys(srv, tkr)


def test_log_only_branch_routes_through_guard_source_lock():
    """Source lock: the log_only branch calls _log_only_cache_touch; no inline clobber remains."""
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    assert "_log_only_cache_touch(" in src
    # The old inline clobber wrote ms_dict {} directly at the log_only branch;
    # the only remaining empty-ms_dict cache write lives inside the guarded helper.
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_fetch_state")
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Assign):
            for tgt in sub.targets:
                if (isinstance(tgt, ast.Subscript) and isinstance(tgt.value, ast.Name)
                        and tgt.value.id == "_state_cache" and isinstance(sub.value, ast.Dict)):
                    dict_keys = {k.value for k in sub.value.keys if isinstance(k, ast.Constant)}
                    assert "generated_at" in dict_keys, (
                        "_fetch_state writes a _state_cache dict without generated_at "
                        "(log_only clobber shape) — must route through _log_only_cache_touch"
                    )


def test_log_only_guard_ticker_agnostic_no_literals():
    """AST lock: no uppercase ticker literals in the guard functions."""
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    targets = {"_analytics_cache_entry_is_full_bundle", "_log_only_cache_touch"}
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in targets:
            found.add(node.name)
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    assert not (sub.value.isalpha() and sub.value.isupper()), (
                        f"ticker-literal-shaped constant {sub.value!r} in {node.name}"
                    )
    assert found == targets


# ── FIX_B_PUBLISH_BEFORE_LOG_REORDER_V1 ──────────────────────────────────────


def _fetch_state_source() -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")


def _fetch_state_ast():
    import ast

    tree = ast.parse(_fetch_state_source())
    fetch = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_fetch_state"
    )
    tail = next(
        n for n in ast.walk(fetch)
        if isinstance(n, ast.FunctionDef) and n.name == "_post_publish_persistence_tail"
    )
    return fetch, tail


def test_fix_b_publish_precedes_persistence_tail_source_lock():
    """Stage-order lock: the generated_at-stamping publish precedes the full-path
    tail call; the persistence stage marks live inside the tail def, which is
    defined before but executed after the publish."""
    src = _fetch_state_source()
    i_pub = src.index('"generated_at": _gen_ts')
    i_full_call = src.index("_post_publish_persistence_tail(_next_ver")
    i_tail_def = src.index("def _post_publish_persistence_tail(")
    i_snap_mark = src.index('_stage_marks.append(("db_snapshot_write_accuracy"')
    i_cal_mark = src.index('_stage_marks.append(("v2_calibration_logging"')
    assert i_pub < i_full_call, "full-path tail call must come AFTER the publish"
    assert i_tail_def < i_snap_mark < i_cal_mark < i_pub, (
        "persistence stage marks must live inside the tail def, "
        "which is defined before (but executed after) the publish"
    )


def test_fix_b_payload_shape_keys_still_served():
    """Payload-shape regression: counters/accuracy keys still assembled pre-publish
    (documented one-cycle lag; values come from the pre-read count + module cache)."""
    src = _fetch_state_source()
    assert 'ms_dict["total_snapshots"]  = db_counts.get("total", 0)' in src
    assert 'ms_dict["filled_snapshots"] = db_counts.get("filled", 0)' in src
    assert 'ms_dict["accuracy_scope"] = "rth_0930_1600_et"' in src
    # The pre-read count SELECT (read-only) still precedes the block.
    assert "db_counts = _ed_db.count_snapshots(ticker, CANONICAL_TIMEFRAME)" in src


def test_fix_b_once_per_cycle_call_sites():
    """Once-per-cycle: exactly one tail def; exactly two mutually-exclusive call
    sites (log_only pre-return, full-path post-publish); exactly one calibration
    append inside the tail."""
    import ast

    fetch, tail = _fetch_state_ast()
    defs = [
        n for n in ast.walk(fetch)
        if isinstance(n, ast.FunctionDef) and n.name == "_post_publish_persistence_tail"
    ]
    assert len(defs) == 1
    calls = [
        n for n in ast.walk(fetch)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "_post_publish_persistence_tail"
    ]
    assert len(calls) == 2, "exactly log_only pre-return + full-path post-publish"
    appends = [
        n for n in ast.walk(tail)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "append_live_v2_calibration_decision"
    ]
    assert len(appends) == 1
    # The log_only branch returns before the full path can reach the second call.
    src = _fetch_state_source()
    i_log_only_call = src.index("_post_publish_persistence_tail(None, _v2_decision_for_response)")
    i_log_only_return = src.index("return {}", i_log_only_call)
    i_full_call = src.index("_post_publish_persistence_tail(_next_ver")
    assert i_log_only_call < i_log_only_return < i_full_call


def test_fix_b_failure_visibility_counters_wired():
    """Failure-visibility: both post_publish_* counters exist in the observability
    dict and each tail except-handler increments its counter and warns with the
    published version."""
    import server as srv

    assert "post_publish_snapshot_failures" in srv._analytics_cache_observability
    assert "post_publish_calibration_failures" in srv._analytics_cache_observability
    src = _fetch_state_source()
    assert '_analytics_cache_observability["post_publish_snapshot_failures"] += 1' in src
    assert '_analytics_cache_observability["post_publish_calibration_failures"] += 1' in src
    assert "post-publish snapshot persistence failed ticker=" in src
    assert "post-publish calibration append failed ticker=" in src
    assert src.count("published_version") >= 4  # def params + both warnings


def test_fix_b_v2_decision_parity_served_equals_logged():
    """v2_decision parity: the full-path tail call passes the SERVED object
    (ms_dict['v2_decision']); the log_only path passes the built decision."""
    src = _fetch_state_source()
    assert '_post_publish_persistence_tail(_next_ver, ms_dict["v2_decision"])' in src
    assert "_post_publish_persistence_tail(None, _v2_decision_for_response)" in src
    assert "v2_decision=v2_decision_for_log," in src


def test_fix_b_tail_never_touches_state_cache():
    """Isolation lock: the tail never references _state_cache (the pre-publish
    prev-vix capture happens outside the tail)."""
    import ast

    _fetch, tail = _fetch_state_ast()
    names = {s.id for s in ast.walk(tail) if isinstance(s, ast.Name)}
    assert "_state_cache" not in names
    src = _fetch_state_source()
    assert '_pre_publish_prev_vix = _state_cache.get(_cache_key, {}).get("vix")' in src


def test_fix_b_no_new_ticker_special_casing():
    """AST lock: the tail carries no locked-ticker CONDITIONAL branches — every
    uppercase literal inside it must be a dict-key/kwarg mapping already
    allowlisted in the universality lock, never an if-comparison."""
    import ast

    from tools.check_universal_ticker_lock import (
        LOCKED_TICKER_LITERALS,
        TICKER_LITERAL_ALLOWLIST,
    )

    _fetch, tail = _fetch_state_ast()
    for sub in ast.walk(tail):
        if isinstance(sub, ast.Compare):
            for cmp_node in ast.walk(sub):
                if isinstance(cmp_node, ast.Constant) and cmp_node.value in LOCKED_TICKER_LITERALS:
                    raise AssertionError(
                        f"ticker-conditional comparison on {cmp_node.value!r} in tail"
                    )
    for lit in ("NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "AVGO", "META", "TSLA"):
        assert ("server.py", "_post_publish_persistence_tail", lit) in TICKER_LITERAL_ALLOWLIST


def test_fix_b_constants_unchanged():
    """TTL / grace / executor sizing untouched by the reorder."""
    import server as srv

    assert srv.CACHE_TTL == 5
    assert srv.VIEWER_STATE_CACHE_TTL_SEC == 5.0
    assert srv.ANALYTICS_STALE_GRACE_CYCLES == 2.0
    src = _fetch_state_source()
    assert src.count("max_workers=8,\n            thread_name_prefix=\"ed_route_offload\"") == 1
    assert src.count("max_workers=4,\n            thread_name_prefix=\"ed_analytics_bg\"") == 1
