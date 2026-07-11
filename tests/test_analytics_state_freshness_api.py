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
    monkeypatch.setattr(srv, "_submit_analytics_task", lambda fn, *a, **k: fn(*a))
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
    monkeypatch.setattr(srv, "_submit_analytics_task", lambda fn, *a, **k: fn(*a))
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
    monkeypatch.setattr(srv, "_submit_analytics_task", lambda fn, *a, **k: fn(*a))
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
    """CHAIN_GATE_V2 (operator-approved 2026-07-10 EVE): concurrency is
    BOUNDED at two global slots — three distinct-ticker threads never exceed
    two inside safe_get_chain."""
    import threading as th

    import server as srv

    monkeypatch.setattr(srv, "_schwab_chain_fetch_gate", srv._ChainGateV2())
    monkeypatch.setattr(srv, "_chain_inflight", {})
    active = {"n": 0, "max": 0}
    lk = th.Lock()

    def _slow_chain(client, ticker, *, strike_count):
        with lk:
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
        time.sleep(0.15)
        with lk:
            active["n"] -= 1
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
    assert active["max"] <= srv.CHAIN_GATE_GLOBAL_SLOTS_MAX == 2


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
    # CHAIN_GATE_V2: two slots — saturate both to force the timeout path.
    assert srv._schwab_chain_fetch_gate.acquire(timeout=1)
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
        srv._schwab_chain_fetch_gate.release()
    # Timeout path must not double-release: exactly two slots acquirable now.
    assert srv._schwab_chain_fetch_gate.acquire(timeout=1)
    assert srv._schwab_chain_fetch_gate.acquire(timeout=1)
    srv._schwab_chain_fetch_gate.release()
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
    """Fidelity lock: helper preserves the exact Schwab call shape; _fetch_state routes through it.

    UI_05_OPERATOR_PRIORITY_ADMISSION_V1 threads a priority flag into the
    gated call — the Schwab call shape inside the helper is unchanged."""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    assert "resp = safe_get_chain(client, ticker, strike_count=strike_count)" in src
    assert "_gated_safe_get_chain, client, ticker," in src
    assert "strike_count=CHAIN_STRIKE_COUNT, priority=_chain_priority," in src
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
    """Isolation lock: the tail never references _state_cache, and the prev-vix
    capture holds structurally (VOL_INPUT_CONTRACT 1.0.0 renamed it to
    _vol_prev_published_vix; the old exact-string anchor was brittle):
    (a) exactly one capture binding exists in _fetch_state;
    (b) it reads _state_cache.get(_cache_key, ...).get("vix") — the prior
        published cache entry under the exact cycle key, no other source;
    (c) it precedes every dict-literal _state_cache[_cache_key] publish that
        carries a "vix" key, so this cycle's publish can never contaminate
        the previous-value calculation."""
    import ast

    fetch, tail = _fetch_state_ast()
    names = {s.id for s in ast.walk(tail) if isinstance(s, ast.Name)}
    assert "_state_cache" not in names

    captures = [
        node for node in ast.walk(fetch)
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_vol_prev_published_vix"
            for t in node.targets
        )
    ]
    assert len(captures) == 1, "exactly one pre-publish prev-vix capture"
    cap = captures[0]
    outer = cap.value
    assert isinstance(outer, ast.Call) and isinstance(outer.func, ast.Attribute)
    assert outer.func.attr == "get"
    assert [a.value for a in outer.args if isinstance(a, ast.Constant)] == ["vix"]
    inner = outer.func.value
    assert isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)
    assert inner.func.attr == "get"
    assert isinstance(inner.func.value, ast.Name)
    assert inner.func.value.id == "_state_cache", "prev vix must come from the state cache"
    assert any(
        isinstance(a, ast.Name) and a.id == "_cache_key" for a in inner.args
    ), "prev vix must read the exact per-cycle cache key"

    publishes = [
        node for node in ast.walk(fetch)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Dict)
        and any(
            isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
            and t.value.id == "_state_cache"
            for t in node.targets
        )
        and "vix" in {
            k.value for k in node.value.keys if isinstance(k, ast.Constant)
        }
    ]
    assert publishes, "expected a vix-carrying _state_cache publish in _fetch_state"
    assert all(cap.lineno < p.lineno for p in publishes), (
        "the prev-vix capture must precede every vix-carrying publish"
    )


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


# ── OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_1 ───────────────────────────────


def test_step1_log_only_inline_source_lock():
    """log_only joins the shutdown inline path for chain/quote and gets a
    sequential inline arm for candle seeds; operator-facing submits remain."""
    src = _fetch_state_source()
    assert "if _analytics_bg_shutdown or _log_only_inline_leaf_fetches(log_only):" in src
    i_inline_seed = src.index("if _log_only_inline_leaf_fetches(log_only):", src.index("def _seed_candles"))
    # Step 2 rebinds the pooled arm to the dedicated leaf pool; the Step 1
    # invariant (inline arm precedes the pooled arm) is pool-independent.
    i_pool_seed = src.index("_seed_pool = (")
    assert i_inline_seed < i_pool_seed, "inline seed arm must precede the pooled arm"
    # Operator-facing bounded parallelism intact (submits still present).
    assert "_cq_pool.submit(" in src or "_chain_fut = _cq_pool.submit(" in src
    assert "_f5 = _seed_pool.submit(_seed_candles, 5)" in src
    assert "_f1 = _seed_pool.submit(_seed_candles, 1)" in src


def test_step1_discriminator_universal_by_signature():
    """The discriminator structurally cannot special-case anything: its only
    parameter is log_only; no ticker/roster/session/horizon/expiry input exists."""
    import ast
    import inspect

    import server as srv

    sig = inspect.signature(srv._log_only_inline_leaf_fetches)
    assert list(sig.parameters) == ["log_only"]
    assert srv._log_only_inline_leaf_fetches(True) is True
    assert srv._log_only_inline_leaf_fetches(False) is False
    tree = ast.parse(_fetch_state_source())
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_log_only_inline_leaf_fetches"
    )
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            assert not (sub.value.isalpha() and sub.value.isupper()), (
                f"ticker/session-literal-shaped constant {sub.value!r} in discriminator"
            )


def test_step1_ticker_matrix_invariance():
    """Anchors + non-anchor universe symbols: the inline decision is invariant
    because the discriminator has no ticker channel at all."""
    import server as srv

    for _ticker in ("SPY", "QQQ", "IWM", "NVDA", "PLTR"):
        # No ticker argument EXISTS to pass — the invariance is structural.
        assert srv._log_only_inline_leaf_fetches(True) is True
        assert srv._log_only_inline_leaf_fetches(False) is False


def test_step1_shutdown_inline_branch_preserved():
    """Shutdown keeps its pre-existing inline behavior via the call-site or."""
    src = _fetch_state_source()
    assert "_analytics_bg_shutdown or _log_only_inline_leaf_fetches(log_only)" in src


# ── OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_2 ───────────────────────────────


def test_step2_leaf_executor_referenced_only_in_fetch_state_leaf_blocks():
    """AST lock: _get_recompute_leaf_executor is called only inside _fetch_state
    (the chain/quote and seed submit blocks) — never by handlers or other code."""
    import ast

    tree = ast.parse(_fetch_state_source())
    callers = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                        and sub.func.id == "_get_recompute_leaf_executor"
                        and node.name != "_get_recompute_leaf_executor"):
                    callers.append(node.name)
    # Nested walk double-counts under enclosing defs; the set must be exactly
    # _fetch_state (call sites live directly in its body, not in nested defs).
    assert set(callers) == {"_fetch_state"}, f"unexpected callers: {sorted(set(callers))}"
    src = _fetch_state_source()
    # Call sites only (the bare substring also matches the def line).
    # UI_05 residual: both sites are now conditional expressions selecting the
    # priority lane vs the shared leaf pool.
    assert src.count("else _get_recompute_leaf_executor()") == 2  # chain/quote + seeds


def test_step2_leaf_functions_have_no_nested_submit():
    """AST leaf lock: leaf functions, schwab_client, and accumulator methods
    contain no .submit() anywhere — the nested-submit deadlock class cannot form."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent

    def submit_sites(path, names=None):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        out = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if names and node.name not in names:
                    continue
                for sub in ast.walk(node):
                    if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                            and sub.func.attr == "submit"):
                        out.append((node.name, sub.lineno))
        return out

    assert submit_sites(root / "server.py",
                        {"_gated_safe_get_chain", "_safe_get_quote_with_retry",
                         "_seed_candles", "seed", "tick", "get_bars", "grid_stale"}) == []
    assert submit_sites(root / "schwab_client.py") == []


def test_step2_concurrent_recomputes_do_not_deadlock():
    """6 concurrent submit+join waves through the leaf pool complete under deadline."""
    import threading
    import time as _time

    import server as srv

    pool = srv._get_recompute_leaf_executor()
    done = []

    def _recompute_like(i):
        f1 = pool.submit(_time.sleep, 0.2)
        f2 = pool.submit(_time.sleep, 0.2)
        f1.result(timeout=10)
        f2.result(timeout=10)
        done.append(i)

    threads = [threading.Thread(target=_recompute_like, args=(i,)) for i in range(6)]
    t0 = _time.monotonic()
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=15)
    elapsed = _time.monotonic() - t0
    assert len(done) == 6, f"only {len(done)}/6 completed"
    assert elapsed < 5.0, f"took {elapsed:.1f}s — queueing/deadlock suspected"


def test_step2_nested_submit_sites_use_leaf_pool_not_route_pool():
    """Source lock: both nested-submit sites bind the leaf pool; the route pool
    is no longer referenced by either block."""
    src = _fetch_state_source()
    # UI_05 residual: both leaf sites select the bounded PRIORITY leaf lane
    # for operator-priority recomputes and the shared leaf pool otherwise —
    # the route pool stays banned at both sites.
    assert src.count("if _chain_priority") >= 2
    assert src.count("else _get_recompute_leaf_executor()") == 2
    assert src.count("_get_priority_leaf_executor()") >= 2
    assert "_cq_pool = _get_route_offload_executor()" not in src
    assert "_seed_pool = _get_route_offload_executor()" not in src


def test_step2_log_only_uses_neither_pool_for_nested_work():
    """Step 1 preserved: the inline arms precede both submit blocks, so log_only
    reaches neither the route pool nor the leaf pool for nested work."""
    src = _fetch_state_source()
    i_inline_cq = src.index("if _analytics_bg_shutdown or _log_only_inline_leaf_fetches(log_only):")
    i_pool_cq = src.index("_cq_pool = (")
    i_inline_seed = src.index("if _log_only_inline_leaf_fetches(log_only):", src.index("def _seed_candles"))
    i_pool_seed = src.index("_seed_pool = (")
    assert i_inline_cq < i_pool_cq
    assert i_inline_seed < i_pool_seed


def test_step2_shutdown_order_and_inline_branch():
    """Leaf-pool teardown comes after the analytics executor shutdown, and the
    _analytics_bg_shutdown condition still forces inline leaf fetches."""
    src = _fetch_state_source()
    i_analytics_shutdown = src.index("_shutdown_analytics_executor(wait=True)")
    i_leaf_teardown = src.index("_recompute_leaf_executor.shutdown(wait=True, cancel_futures=True)")
    assert i_analytics_shutdown < i_leaf_teardown
    assert "_analytics_bg_shutdown or _log_only_inline_leaf_fetches(log_only)" in src


def test_step2_no_ticker_session_horizon_literals():
    """AST lock on the new getter: no uppercase ticker/session literal constants."""
    import ast

    tree = ast.parse(_fetch_state_source())
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_get_recompute_leaf_executor"
    )
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            assert not (sub.value.isalpha() and sub.value.isupper()), (
                f"literal-shaped constant {sub.value!r} in leaf-pool getter"
            )


def test_step2_executor_constants_unchanged_plus_new_leaf_constant():
    """Existing pool sizes untouched; new leaf pool pinned at 8."""
    import server as srv

    assert srv.RECOMPUTE_LEAF_EXECUTOR_MAX_WORKERS == 8
    src = _fetch_state_source()
    assert src.count('max_workers=8,\n            thread_name_prefix="ed_route_offload"') == 1
    assert src.count('max_workers=4,\n            thread_name_prefix="ed_analytics_bg"') == 1
    assert src.count('max_workers=4,\n            thread_name_prefix="ed_quote_hot"') == 1
    assert src.count('thread_name_prefix="ed_recompute_leaf"') == 1


def test_fix_b_constants_unchanged():
    """TTL / grace / executor sizing untouched by the reorder."""
    import server as srv

    assert srv.CACHE_TTL == 5
    assert srv.VIEWER_STATE_CACHE_TTL_SEC == 5.0
    assert srv.ANALYTICS_STALE_GRACE_CYCLES == 2.0
    src = _fetch_state_source()
    assert src.count("max_workers=8,\n            thread_name_prefix=\"ed_route_offload\"") == 1
    assert src.count("max_workers=4,\n            thread_name_prefix=\"ed_analytics_bg\"") == 1


# ── EXEC-03 POST_PUBLISH_LAST_ERROR_OBSERVABILITY_V1 ─────────────────────────


def test_post_publish_last_error_recorder_shape_and_truncation():
    """The recorder captures a fixed-schema dict from inside an except handler:
    exc_type, bounded detail, bounded traceback tail, ticker as runtime data."""
    import server as srv

    srv._post_publish_last_errors.pop("snapshot", None)
    try:
        raise ValueError("boom-" + "x" * 900)
    except ValueError as e:
        srv._record_post_publish_failure("snapshot", "TESTX", 41, e)
    rec = srv._post_publish_last_errors["snapshot"]
    assert set(rec) == {
        "ts_epoch", "ticker", "published_version", "exc_type", "detail", "traceback_tail",
    }
    assert rec["ticker"] == "TESTX"
    assert rec["published_version"] == 41
    assert rec["exc_type"] == "ValueError"
    assert len(rec["detail"]) <= 400
    assert isinstance(rec["traceback_tail"], list) and len(rec["traceback_tail"]) <= 12
    assert any("ValueError" in ln for ln in rec["traceback_tail"])
    srv._post_publish_last_errors.pop("snapshot", None)


def test_post_publish_last_error_recorder_is_passive():
    """Recorder never raises (even outside an except context) and never touches
    the counter dict or _state_cache — counters stay at the call sites."""
    import ast

    import server as srv

    before = dict(srv._analytics_cache_observability)
    srv._record_post_publish_failure("calibration", "TESTX", None, RuntimeError("q"))
    assert dict(srv._analytics_cache_observability) == before
    srv._post_publish_last_errors.pop("calibration", None)

    tree = ast.parse(_fetch_state_source())
    rec = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_record_post_publish_failure"
    )
    names = {s.id for s in ast.walk(rec) if isinstance(s, ast.Name)}
    assert "_state_cache" not in names
    assert "_analytics_cache_observability" not in names


def test_post_publish_last_error_wired_at_both_failure_branches():
    """Both tail except-handlers record cause detail right after their counter
    increment; the payload attaches a copy adjacent to the observability block."""
    src = _fetch_state_source()
    i_snap_inc = src.index('_analytics_cache_observability["post_publish_snapshot_failures"] += 1')
    i_snap_rec = src.index('_record_post_publish_failure("snapshot", ticker, published_version, e)')
    i_cal_inc = src.index('_analytics_cache_observability["post_publish_calibration_failures"] += 1')
    i_cal_rec = src.index(
        '_record_post_publish_failure("calibration", ticker, published_version, _v2_log_e)'
    )
    assert i_snap_inc < i_snap_rec < i_cal_inc < i_cal_rec
    i_obs_attach = src.index('ms_dict["analytics_cache_observability_v1"] = dict(')
    i_err_attach = src.index('ms_dict["post_publish_last_errors_v1"] = {')
    assert i_obs_attach < i_err_attach


def test_tail_mkt_ctx_nonlocal_rebind_restored():
    """The confluence-completion rebind targets _fetch_state's mkt_ctx (nonlocal),
    matching the pre-relocation inline binding; the completion call remains."""
    import ast

    _fetch, tail = _fetch_state_ast()
    declared = set()
    for node in ast.walk(tail):
        if isinstance(node, ast.Nonlocal):
            declared.update(node.names)
    assert "mkt_ctx" in declared
    src = _fetch_state_source()
    assert "mkt_ctx = _ensure_mkt_ctx_confluence_complete(client, mkt_ctx)" in src


def test_tail_no_unbound_shadow_of_fetch_state_locals():
    """Relocation-class lock: no name stored in the tail may shadow a
    _fetch_state-level binding AND be read at-or-before its first tail store
    without a nonlocal declaration (the mkt_ctx UnboundLocalError class).
    Comprehension targets are scope-isolated in py3 and excluded."""
    import ast

    fetch, tail = _fetch_state_ast()

    comp_targets: set[str] = set()
    for node in ast.walk(tail):
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for gen in node.generators:
                for t in ast.walk(gen.target):
                    if isinstance(t, ast.Name):
                        comp_targets.add(t.id)

    nonlocals: set[str] = set()
    for node in ast.walk(tail):
        if isinstance(node, ast.Nonlocal):
            nonlocals.update(node.names)

    def _stores_and_loads(fn):
        stores: dict[str, int] = {}
        loads: dict[str, list[int]] = {}
        for node in ast.walk(fn):
            if isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Store):
                    stores.setdefault(node.id, node.lineno)
                    stores[node.id] = min(stores[node.id], node.lineno)
                elif isinstance(node.ctx, ast.Load):
                    loads.setdefault(node.id, []).append(node.lineno)
        return stores, loads

    fetch_stores, _ = _stores_and_loads(fetch)
    fetch_params = {a.arg for a in fetch.args.args + fetch.args.kwonlyargs}
    tail_stores, tail_loads = _stores_and_loads(tail)

    offenders = []
    for name, first_store in tail_stores.items():
        if name in nonlocals or name in comp_targets:
            continue
        if name not in fetch_stores and name not in fetch_params:
            continue
        early = [ln for ln in tail_loads.get(name, []) if ln <= first_store]
        if early:
            offenders.append((name, first_store, early))
    assert not offenders, f"unbound tail shadows of _fetch_state locals: {offenders}"


def test_post_publish_last_error_no_ticker_literals():
    """Universality: the recorder body carries no ticker-literal-shaped constants
    (its dict keys are lowercase kinds; ticker arrives as runtime data)."""
    import ast

    tree = ast.parse(_fetch_state_source())
    rec = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_record_post_publish_failure"
    )
    for sub in ast.walk(rec):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            assert not (sub.value.isalpha() and sub.value.isupper()), (
                f"ticker-literal-shaped constant {sub.value!r} in recorder"
            )


# ── IDLE_SENTINEL_FRESHNESS_V1 — idle-refresh standing producer locks ─────────


def _idle_seed_cache(srv, monkeypatch, entries):
    """entries: {(ticker, expiry): age_sec | None-for-shell}."""
    import time as _t

    now = _t.time()
    cache = {}
    for key, age in entries.items():
        if age is None:
            cache[key] = {"ts": now, "ms_dict": {}}  # pending-shell-like: empty body
        else:
            cache[key] = {"ts": now - age, "ms_dict": {"ticker": key[0]}}
    monkeypatch.setattr(srv, "_state_cache", cache)
    monkeypatch.setattr(srv, "_analytics_inflight", set())


def test_idle_refresh_selects_nonviewed_stale_key(monkeypatch):
    """Required 1: a non-viewed stale cache key is selected for recompute."""
    import server as srv

    _idle_seed_cache(srv, monkeypatch, {("AAA1", "2026-08-01"): 60.0})
    assert srv._select_idle_stale_keys(owned_keys=set(), max_keys=1) == [("AAA1", "2026-08-01")]


def test_idle_refresh_never_double_owns_viewed_ticker(monkeypatch):
    """Required 2: a subscriber-owned ticker is excluded even when the viewer
    subscribed with a None/default expiry and the cache key carries the
    resolved expiry (single-owner semantics preserved)."""
    import server as srv

    _idle_seed_cache(srv, monkeypatch, {("AAA1", "2026-08-01"): 60.0, ("BBB2", "2026-08-01"): 30.0})
    picked = srv._select_idle_stale_keys(owned_keys={("AAA1", None)}, max_keys=5)
    assert ("AAA1", "2026-08-01") not in picked
    assert picked == [("BBB2", "2026-08-01")]


def test_idle_refresh_oldest_first(monkeypatch):
    """Required 3: oldest stale key drains first."""
    import server as srv

    _idle_seed_cache(
        srv, monkeypatch,
        {("AAA1", "e"): 30.0, ("BBB2", "e"): 300.0, ("CCC3", "e"): 90.0},
    )
    picked = srv._select_idle_stale_keys(owned_keys=set(), max_keys=3)
    assert picked == [("BBB2", "e"), ("CCC3", "e"), ("AAA1", "e")]


def test_idle_refresh_rate_bound_enforced(monkeypatch):
    """Required 4: at most max_keys per tick; constant pinned at 1."""
    import server as srv

    _idle_seed_cache(
        srv, monkeypatch,
        {("AAA1", "e"): 30.0, ("BBB2", "e"): 300.0, ("CCC3", "e"): 90.0},
    )
    assert len(srv._select_idle_stale_keys(owned_keys=set(), max_keys=1)) == 1
    assert srv._select_idle_stale_keys(owned_keys=set(), max_keys=0) == []
    assert srv.IDLE_KEY_REFRESH_MAX_PER_TICK == 1


def test_idle_refresh_ticker_agnostic_guest_style_keys(monkeypatch):
    """Required 5: selection works identically for guest-style keys."""
    import server as srv

    _idle_seed_cache(srv, monkeypatch, {("ZZGUEST9", "2026-09-19"): 45.0})
    assert srv._select_idle_stale_keys(owned_keys=set(), max_keys=1) == [("ZZGUEST9", "2026-09-19")]


def test_idle_refresh_no_ticker_literals_in_selection():
    """Required 6: no ticker-literal-shaped constants drive selection."""
    import ast

    tree = ast.parse(_fetch_state_source())
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_select_idle_stale_keys"
    )
    for node in ast.walk(fn):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not (node.value.isalpha() and node.value.isupper()), (
                f"ticker-literal-shaped constant {node.value!r} in idle selection"
            )


def test_idle_refresh_fresh_keys_not_selected(monkeypatch):
    """Required 7: keys inside the stale budget are never recomputed by the arm."""
    import server as srv

    _idle_seed_cache(srv, monkeypatch, {("AAA1", "e"): 3.0, ("BBB2", "e"): 9.9})
    assert srv._select_idle_stale_keys(owned_keys=set(), max_keys=5) == []


def test_idle_refresh_inflight_keys_skipped(monkeypatch):
    """Required 8: pending/in-progress keys are not duplicated — selection skips
    inflight keys AND the arm schedules only through the deduping scheduler."""
    import server as srv

    _idle_seed_cache(srv, monkeypatch, {("AAA1", "e"): 60.0})
    monkeypatch.setattr(
        srv, "_analytics_inflight", {srv._tier_c_inflight_key("AAA1", "e")}
    )
    assert srv._select_idle_stale_keys(owned_keys=set(), max_keys=1) == []
    src = _fetch_state_source()
    i_loop = src.index("async def _sse_background_loop")
    i_call = src.index("_select_idle_stale_keys(", i_loop)
    i_sched = src.index('update_source="idle_key_refresh"', i_call)
    assert i_loop < i_call < i_sched, "idle arm must schedule via _schedule_analytics_recompute"


def test_idle_refresh_veto_and_budget_untouched(monkeypatch):
    """Required 9: the stale/actionability veto and the 10s budget are intact;
    empty-body (shell) entries are never selected (clobber-guard alignment)."""
    import server as srv

    assert srv.CACHE_TTL == 5
    assert srv.ANALYTICS_STALE_GRACE_CYCLES == 2.0
    _idle_seed_cache(srv, monkeypatch, {("AAA1", "e"): None})
    assert srv._select_idle_stale_keys(owned_keys=set(), max_keys=5) == []
    src = _fetch_state_source()
    assert 'update_source="sse_loop"' in src  # viewed-key owner unchanged
    assert "IDLE_KEY_REFRESH_MAX_PER_TICK" in src


# ── UI_05_OPERATOR_PRIORITY_ADMISSION_V1 — priority admission + gate locks ────


def test_ui05_update_source_classification():
    """Background sources opt in; everything else (incl. unknown/None) is operator-facing."""
    import server as srv

    for bg in ("idle_key_refresh", "startup_warm", "session_open_anchor_warm"):
        assert srv._is_operator_priority_update_source(bg) is False
    for op in ("sse_loop", "rest_poll_legacy", "tick_coherent", "debug_endpoint", None, "future_source"):
        assert srv._is_operator_priority_update_source(op) is True


def test_ui05_priority_pool_bounded_and_separate():
    """Priority lane is a bounded 2-worker pool distinct from the 4-worker analytics pool."""
    import server as srv

    p = srv._get_operator_priority_executor()
    a = srv._get_analytics_executor()
    assert p is not a
    assert p._max_workers == 2
    assert a._max_workers == 4


def test_ui05_submit_routing_by_priority_flag(monkeypatch):
    """_submit_analytics_task routes priority=True to the priority pool, else analytics pool."""
    import server as srv

    class _Rec:
        def __init__(self):
            self.calls = []

        def submit(self, fn, *a, **k):
            self.calls.append(fn)

            class _F:
                pass

            return _F()

    prio, bg = _Rec(), _Rec()
    monkeypatch.setattr(srv, "_analytics_bg_shutdown", False)
    monkeypatch.setattr(srv, "_get_operator_priority_executor", lambda: prio)
    monkeypatch.setattr(srv, "_get_analytics_executor", lambda: bg)
    srv._submit_analytics_task(lambda: None)
    srv._submit_analytics_task(lambda: None, priority=True)
    assert len(bg.calls) == 1 and len(prio.calls) == 1


def test_ui05_scheduler_passes_priority_from_update_source(monkeypatch):
    """_schedule_analytics_recompute classifies its update_source into the priority flag."""
    import server as srv

    captured = []
    monkeypatch.setattr(srv, "_analytics_bg_shutdown", False)
    monkeypatch.setattr(
        srv, "_submit_analytics_task",
        lambda fn, *a, **k: captured.append(k.get("priority")),
    )
    key1 = srv._tier_c_inflight_key("ZZU5A", None)
    srv._schedule_analytics_recompute(key1, "ZZU5A", None, "idle_key_refresh")
    key2 = srv._tier_c_inflight_key("ZZU5B", None)
    srv._schedule_analytics_recompute(key2, "ZZU5B", None, "rest_poll_legacy")
    try:
        assert captured == [False, True]
    finally:
        with srv._analytics_bg_lock:
            srv._analytics_inflight.discard(key1)
            srv._analytics_inflight.discard(key2)


def test_ui05_priority_gate_priority_waiter_acquires_first():
    """With the slot held and one background + one priority waiter queued, the
    priority waiter gets the slot on release."""
    import threading as th

    import server as srv

    gate = srv._ChainGateV2()
    gate.record_result(False, throttled=True)  # degrade to capacity 1
    assert gate.acquire(timeout=1)  # hold the slot
    order = []
    bg_started = th.Event()
    prio_started = th.Event()

    def bg():
        bg_started.set()
        assert gate.acquire(timeout=10)
        order.append("background")
        gate.release()

    def prio():
        prio_started.set()
        assert gate.acquire(timeout=10, priority=True)
        order.append("priority")
        gate.release()

    t_bg = th.Thread(target=bg)
    t_bg.start()
    bg_started.wait(2)
    import time as _t

    _t.sleep(0.15)  # background waiter is queued first
    t_prio = th.Thread(target=prio)
    t_prio.start()
    prio_started.wait(2)
    _t.sleep(0.15)
    gate.release()
    t_prio.join(5)
    t_bg.join(5)
    assert order == ["priority", "background"]
    # slot fully restored
    assert gate.acquire(timeout=1)
    gate.release()


def test_ui05_admission_sla_gate_not_blocked_by_saturated_background_pool(monkeypatch):
    """SLA regression gate (deterministic): with the 4-worker analytics pool
    fully saturated by background jobs, a priority submission still completes
    fast — cold-guest admission no longer queues behind background cycles."""
    import threading as th
    import time as _t

    import server as srv

    monkeypatch.setattr(srv, "_analytics_bg_shutdown", False)
    release_bg = th.Event()
    started = th.Barrier(5, timeout=10)

    def _bg_job():
        started.wait()
        release_bg.wait(20)

    futs = [srv._submit_analytics_task(_bg_job) for _ in range(4)]
    try:
        started.wait()  # all 4 analytics workers busy
        t0 = _t.perf_counter()
        done = th.Event()
        srv._submit_analytics_task(lambda: done.set(), priority=True)
        assert done.wait(2.0), "priority job blocked behind saturated background pool"
        assert _t.perf_counter() - t0 < 2.0
    finally:
        release_bg.set()
        for f in futs:
            f.result(timeout=20)


# ── UI_05 residual — priority leaf lane + startup model prewarm sweep ────────


def test_ui05r_priority_leaf_pool_bounded_and_separate():
    import server as srv

    p = srv._get_priority_leaf_executor()
    shared = srv._get_recompute_leaf_executor()
    assert p is not shared
    # UI_05 final tail: 4 = 3 panel anchors + 1 operator switch (measured).
    assert p._max_workers == 4
    assert shared._max_workers == srv.RECOMPUTE_LEAF_EXECUTOR_MAX_WORKERS == 8


def test_ui05r_leaf_pool_selection_source_lock():
    """Chain/quote and seed legs select the priority lane exactly when the
    recompute is operator-priority (the _chain_priority classifier)."""
    src = _fetch_state_source()
    i_cq = src.index("_cq_pool = (")
    assert "_get_priority_leaf_executor()" in src[i_cq:i_cq + 200]
    assert "else _get_recompute_leaf_executor()" in src[i_cq:i_cq + 260]
    i_seed = src.index("_seed_pool = (")
    assert "_get_priority_leaf_executor()" in src[i_seed:i_seed + 220]
    assert "else _get_recompute_leaf_executor()" in src[i_seed:i_seed + 280]


def test_ui05r_priority_leaf_teardown_present():
    src = _fetch_state_source()
    assert src.count("_priority_leaf_executor.shutdown(wait=True, cancel_futures=True)") == 1


def test_ui05r_prewarm_roster_anchors_first(tmp_path, monkeypatch):
    import server as srv
    import ml_predict as mp

    base = tmp_path / "active"
    for t in ("ZZB", "SPY", "QQQ", "AAA1", "IWM"):
        (base / t).mkdir(parents=True)
    monkeypatch.setattr(mp, "MODEL_DIR", tmp_path)
    roster = srv._startup_model_prewarm_roster()
    assert roster[:3] == ["SPY", "QQQ", "IWM"]
    assert set(roster) == {"SPY", "QQQ", "IWM", "ZZB", "AAA1"}


def test_ui05r_prewarm_sweep_sequential_and_kill_switch(monkeypatch):
    """The sweep runs tickers one at a time on a single named daemon thread,
    honors the env kill switch, and stops on shutdown."""
    import server as srv

    calls: list[str] = []
    monkeypatch.setattr(srv, "_startup_model_prewarm_roster", lambda: ["T1", "T2"])
    monkeypatch.setattr(srv, "_prewarm_inference_models_worker", lambda t: calls.append(t))
    monkeypatch.setattr(srv, "_analytics_bg_shutdown", False)
    srv._startup_model_prewarm_sweep_worker()
    assert calls == ["T1", "T2"]

    monkeypatch.setenv("ED_DISABLE_STARTUP_MODEL_PREWARM", "1")
    started: list[str] = []
    monkeypatch.setattr(
        srv.threading, "Thread",
        lambda *a, **k: started.append(k.get("name")) or type("T", (), {"start": lambda self: None})(),
    )
    srv._schedule_startup_model_prewarm_sweep()
    assert started == []  # kill switch respected


def test_ui05r_sweep_never_bypasses_serve_policy():
    """The sweep loads via the same prewarm worker → same strict load path →
    MODEL-04 withholding still applies (source lock)."""
    src = _fetch_state_source()
    i = src.index("def _startup_model_prewarm_sweep_worker")
    seg = src[i:i + 500]
    assert "_prewarm_inference_models_worker(t)" in seg
    assert "pickle" not in seg and "torch" not in seg  # no direct artifact loads


# ── UI_05 tail closure: market-context single-flight + stale-while-refresh ────


def _mkt_ctx_test_reset(srv, ctx=None, age_sec=0.0):
    with srv._cached_mkt_ctx_lock:
        srv._cached_mkt_ctx = ctx
        srv._cached_mkt_ctx_ts = (time.time() - age_sec) if ctx is not None else 0.0
        srv._mkt_ctx_refresh_inflight = False


def test_mkt_ctx_stale_serve_never_pays_sweep_inline(monkeypatch):
    """Stale cache + previous context: callers get the previous context
    immediately; exactly ONE background sweep runs and lands the new one."""
    import threading as th

    import server as srv
    from market_context import MarketContext

    old_ctx = MarketContext()
    _mkt_ctx_test_reset(srv, old_ctx, age_sec=srv.MKT_CTX_TTL + 5.0)
    calls = {"n": 0}
    done = th.Event()

    def _fake_sweep(client, **kwargs):
        calls["n"] += 1
        time.sleep(0.2)
        done.set()
        return MarketContext()

    monkeypatch.setattr(srv, "fetch_market_context", _fake_sweep)
    t0 = time.perf_counter()
    served = [srv._get_mkt_ctx(None) for _ in range(5)]
    inline_elapsed = time.perf_counter() - t0
    assert all(s is old_ctx for s in served)
    assert inline_elapsed < 0.15, "a caller paid the sweep inline"
    assert done.wait(5)
    deadline = time.time() + 5
    while time.time() < deadline:
        with srv._cached_mkt_ctx_lock:
            if srv._cached_mkt_ctx is not old_ctx and not srv._mkt_ctx_refresh_inflight:
                break
        time.sleep(0.02)
    with srv._cached_mkt_ctx_lock:
        assert srv._cached_mkt_ctx is not old_ctx
        assert srv._mkt_ctx_refresh_inflight is False
    assert calls["n"] == 1
    _mkt_ctx_test_reset(srv)


def test_mkt_ctx_refresh_single_flight_under_concurrency(monkeypatch):
    """Eight concurrent stale-path callers trigger exactly one sweep."""
    import threading as th

    import server as srv
    from market_context import MarketContext

    old_ctx = MarketContext()
    _mkt_ctx_test_reset(srv, old_ctx, age_sec=srv.MKT_CTX_TTL + 5.0)
    calls = {"n": 0}
    lk = th.Lock()
    done = th.Event()

    def _fake_sweep(client, **kwargs):
        with lk:
            calls["n"] += 1
        time.sleep(0.3)
        done.set()
        return MarketContext()

    monkeypatch.setattr(srv, "fetch_market_context", _fake_sweep)
    served: list = []
    slock = th.Lock()

    def _call():
        out = srv._get_mkt_ctx(None)
        with slock:
            served.append(out)

    threads = [th.Thread(target=_call) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert len(served) == 8
    assert all(s is old_ctx for s in served)
    assert done.wait(5)
    deadline = time.time() + 5
    while time.time() < deadline:
        with srv._cached_mkt_ctx_lock:
            if not srv._mkt_ctx_refresh_inflight:
                break
        time.sleep(0.02)
    assert calls["n"] == 1, f"thundering herd: {calls['n']} sweeps for one TTL lapse"
    _mkt_ctx_test_reset(srv)


def test_mkt_ctx_boot_joins_one_synchronous_sweep(monkeypatch):
    """No context yet (boot): concurrent callers block, exactly one sweep
    runs, and every caller returns the context it stored."""
    import threading as th

    import server as srv
    from market_context import MarketContext

    _mkt_ctx_test_reset(srv, None)
    calls = {"n": 0}
    lk = th.Lock()

    def _fake_sweep(client, **kwargs):
        with lk:
            calls["n"] += 1
        time.sleep(0.3)
        return MarketContext()

    monkeypatch.setattr(srv, "fetch_market_context", _fake_sweep)
    served: list = []
    slock = th.Lock()

    def _call():
        out = srv._get_mkt_ctx(None)
        with slock:
            served.append(out)

    threads = [th.Thread(target=_call) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert len(served) == 6
    assert calls["n"] == 1
    assert all(s is served[0] for s in served), "boot joiners got different contexts"
    _mkt_ctx_test_reset(srv)


def test_mkt_ctx_force_sync_performs_fresh_sweep(monkeypatch):
    """force_sync (confluence-completion path) must NOT be served the stale
    object — it fetches (or joins) a real sweep and returns the new context."""
    import server as srv
    from market_context import MarketContext

    old_ctx = MarketContext()
    _mkt_ctx_test_reset(srv, old_ctx, age_sec=srv.MKT_CTX_TTL + 5.0)
    calls = {"n": 0}

    def _fake_sweep(client, **kwargs):
        calls["n"] += 1
        return MarketContext()

    monkeypatch.setattr(srv, "fetch_market_context", _fake_sweep)
    out = srv._get_mkt_ctx(None, force_sync=True)
    assert out is not old_ctx
    assert calls["n"] == 1
    with srv._cached_mkt_ctx_lock:
        assert srv._cached_mkt_ctx is out
        assert srv._mkt_ctx_refresh_inflight is False
    _mkt_ctx_test_reset(srv)


def test_mkt_ctx_refresh_executor_single_worker_and_chain_window_marks():
    """Sizing lock (1 worker = single-flight by construction) + source lock:
    the _chain_ms window carries the four attribution marks so an untraced
    gap cannot reappear silently."""
    import inspect

    import server as srv

    ex = srv._get_mkt_ctx_refresh_executor()
    assert ex._max_workers == 1
    fetch_src = inspect.getsource(srv._fetch_state)
    for mark in (
        "chain_window_preamble_ms",
        "chain_window_mkt_ctx_ms",
        "chain_window_leaf_wall_ms",
        "chain_window_contracts_parse_ms",
    ):
        assert mark in fetch_src, f"chain-window mark {mark} missing from _fetch_state"
