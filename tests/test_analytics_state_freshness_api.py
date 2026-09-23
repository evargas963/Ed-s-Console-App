"""Tier C /api/analytics/state contract tests (S2A/S2B card_freshness_v1 + operator mirror
tests removed 2026-09-21: confirmed dead -- CARD_TRUST_CONTRACT.md's resolveCardTrustGate,
the sole intended consumer, does not exist anywhere in the rebuilt static/index.html or
static/js/*.js, and neither do card_freshness_v1/operator_card_actionable/
operator_card_trust_state/operator_stale_reason_codes/operator_actionability_reason have any
other Python-side reader or database column. The remaining tests below cover unrelated Tier C
behavior (bg recompute timing instrumentation, executor queue wait, etc.) that only
incidentally stubbed the now-deleted _attach_card_freshness_v1_block as noise suppression."""

from __future__ import annotations

import json
import time

import pytest



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
    ms.setdefault("_server_build_ts", gen)  # caps-ok: fixture builder: a caller-supplied _server_build_ts wins, otherwise the seeded entry is stamped with the fixture's own generation time
    srv._state_cache[key] = {
        "ms_dict": ms,
        "ts": gen,
        "generated_at": gen,
        "analytics_version": 2,
    }
    return key


def _response_body(resp) -> dict:
    return json.loads(resp.body)


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
    # RC-REHAB-1 (2026-09-23, module extraction, thirtieth slice):
    # _schedule_analytics_recompute moved out of server.py, into
    # analytics_bg_recompute.py; its own _work() closure calls
    # _stamp_analytics_freshness_on_completed_fetch as a bare name, resolved
    # against that module's own globals -- a mock must patch it there, not on
    # server's re-export, to be picked up.
    import analytics_bg_recompute as abr

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
        abr,
        "_stamp_analytics_freshness_on_completed_fetch",
        lambda md, t, k: stamped.update(md),
    )
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
    # RC-REHAB-1 (2026-09-23, thirtieth slice): see the identical comment in
    # test_analytics_recompute_duration_instrumentation_recorded above.
    import analytics_bg_recompute as abr

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
        abr,
        "_stamp_analytics_freshness_on_completed_fetch",
        lambda md, t, k: stamped.update(md),
    )
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


def test_stage_timer_surfaces_present_in_fetch_state_source():
    """Source lock: stage marks + additive timing fields exist in the Tier C recompute path.

    RC-REHAB-1 (2026-09-23): _post_publish_persistence_tail (one of these stage marks'
    home, `db_snapshot_write_accuracy`) moved to server_state_persistence_tail.py.
    RC-REHAB-1 (2026-09-23, thirtieth slice): _schedule_analytics_recompute (the
    other stage marks' home, and the queue-wait field's own stamp site) moved to
    analytics_bg_recompute.py. Check all three files' source, not just server.py's."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    src = (root / "server.py").read_text(encoding="utf-8")
    src += (root / "server_state_persistence_tail.py").read_text(encoding="utf-8")
    src += (root / "analytics_bg_recompute.py").read_text(encoding="utf-8")
    src += (root / "server_state_publish.py").read_text(encoding="utf-8")  # thirty-seventh slice
    for needle in (
        'stage_marks.append(("stack_runtime_governance_attach"',
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

    # RC-239: the production call site passes `to_date=` as well; a stub that omits it does
    # not stand in for the real callee, it just raises TypeError inside the gate. Cursor-audit F2
    # added `from_date=` (single-expiry near-edge bound) — the stub mirrors the real signature.
    # OPTIONS_ORDER_FLOW_V1 round 3 added `strike_range=` (see the source-shape lock test above).
    def _slow_chain(client, ticker, *, strike_count=None, strike_range=None, to_date=None, from_date=None):
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

    # Order-independence: use a FRESH gate, never the process-global one. This test
    # asserts the gate starts fully free; any earlier test that leaks a slot on the
    # shared instance would otherwise fail it (observed 2026-07-19 only inside the
    # full 301-file run, never standalone). Same construction as the sibling
    # concurrency test above.
    monkeypatch.setattr(srv, "_schwab_chain_fetch_gate", srv._ChainGateV2())
    monkeypatch.setattr(srv, "_chain_inflight", {})
    monkeypatch.setattr(srv, "CHAIN_FETCH_GATE_ACQUIRE_TIMEOUT_SEC", 0.05)
    calls: list[str] = []
    monkeypatch.setattr(
        srv,
        "safe_get_chain",
        lambda client, ticker, *, strike_count=None, strike_range=None, to_date=None, from_date=None: (calls.append(ticker), "RESP")[1],
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

    # Order-independence: fresh gate (see the timeout test above). The final
    # "immediately acquirable" assertion requires a gate no other test has touched.
    monkeypatch.setattr(srv, "_schwab_chain_fetch_gate", srv._ChainGateV2())
    monkeypatch.setattr(srv, "_chain_inflight", {})
    monkeypatch.setattr(
        srv, "safe_get_chain",
        lambda client, ticker, *, strike_count=None, strike_range=None, to_date=None, from_date=None: "OK")
    resp, gate_wait_sec, fetch_sec = srv._gated_safe_get_chain(None, "ZZZ_NORM", strike_count=5)
    assert resp == "OK"
    assert gate_wait_sec >= 0.0
    assert fetch_sec >= 0.0
    # Gate released: immediately acquirable.
    assert srv._schwab_chain_fetch_gate.acquire(timeout=1)
    srv._schwab_chain_fetch_gate.release()


def test_chain_fetch_call_shape_and_gated_site_source_lock():
    """Fidelity lock: helper preserves the exact Schwab call shape; _fetch_state routes through it.

    UI_05_OPERATOR_PRIORITY_ADMISSION_V1 threads a priority flag into the gated call — the Schwab
    call shape inside the helper is unchanged.

    RC-59 UPDATE: the WIDTH source changed deliberately. _fetch_state used to pass the hardcoded
    CHAIN_STRIKE_COUNT (20), which analysed the console on a ~±6.6%-of-spot chain while terrain
    used geometry-sized widths — the same ticker measured two ways. Width now comes from the ONE
    faucet, resolve_chain_strike_count(). This lock therefore asserts the INTENT (gated helper +
    priority flag + faucet-sourced width) rather than a frozen literal, so a genuine improvement
    does not read as a regression while a real drift still fails.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
    # RC-239: the call shape gained `to_date=` (expiry scoping); Cursor-audit F2 added `from_date=`
    # (single-expiry near-edge bound). The lock asserts the SHAPE — gated helper, faucet-sourced
    # width, and every kwarg named — rather than a frozen literal that goes stale the moment a
    # legitimate argument is added.
    assert "resp = safe_get_chain(client, ticker, strike_count=strike_count, strike_range=strike_range,\n                              to_date=to_date, from_date=from_date)" in src
    intake = _intake_source()
    assert "pool.submit(_srv._gated_safe_get_chain, client, ticker, **chain_kwargs)" in intake
    assert "_srv._gated_safe_get_chain(\n                client, ticker, **chain_kwargs)" in intake
    # Width comes from the faucet, never a bare constant (enforced repo-wide by
    # tools/check_institutional_correctness.py::check_chain_width_single_faucet).
    assert "strike_count=_srv.resolve_chain_strike_count(ticker)" in intake
    assert "CHAIN_STRIKE_COUNT" not in intake, (
        "the console chain fetch regressed to the hardcoded 20-strike width (RC-59)"
    )
    assert "priority=chain_priority," in intake
    assert "_fetch_chain_and_quote_for_state(" in src
    pub = (Path(__file__).resolve().parent.parent / "server_state_publish.py").read_text(encoding="utf-8")
    assert 'ms_dict["chain_gate_wait_sec"]' in pub  # thirty-seventh slice: timing lives in the publish phase
    assert 'stage_ms["chain_gate_wait_ms"]' in pub


# ── ANCHOR_QUOTE_LANE_REFRESHER_V1 ────────────────────────────────────────────


class _FakePlane:
    """Minimal live_market_plane stand-in: per-ticker rows, read-only for the refresher."""

    def __init__(self, rows: dict):
        self.rows = rows

    def get_quote(self, ticker: str):
        return self.rows.get(ticker)


def test_anchor_quote_lane_needs_refresh_predicate():
    """Absent row, missing/garbled exchange_quote_ts, or age > max-age ⇒ refresh; fresh ⇒ skip."""
    import server as srv

    now = 1_000_000.0
    max_age = srv.ANCHOR_QUOTE_LANE_MAX_AGE_SEC
    assert srv._anchor_quote_lane_needs_refresh(None, now) is True
    assert srv._anchor_quote_lane_needs_refresh({}, now) is True
    assert srv._anchor_quote_lane_needs_refresh({"exchange_quote_ts": None}, now) is True
    assert srv._anchor_quote_lane_needs_refresh({"exchange_quote_ts": "bogus"}, now) is True
    assert srv._anchor_quote_lane_needs_refresh({"exchange_quote_ts": now - max_age - 0.1}, now) is True
    assert srv._anchor_quote_lane_needs_refresh({"exchange_quote_ts": now - max_age + 0.1}, now) is False
    assert srv._anchor_quote_lane_needs_refresh({"exchange_quote_ts": now}, now) is False


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
    """Frozen-lane case (QQQ shape): old exchange_quote_ts is refreshed, prev row passed through."""
    import server as srv

    now = 3_000_000.0
    frozen = {"exchange_quote_ts": now - 7_120.0, "spot": 500.0}
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
    fresh = {"exchange_quote_ts": now - 1.0, "spot": 600.0}
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


def test_anchor_lane_refresh_constants_stay_pinned():
    """Lane max-age/poll + TTL/grace stay pinned to their measured values.

    2026-09-21: dropped the comparison against _CARD_FRESHNESS_V1_QUOTE_STALE_SEC (the
    card_freshness_v1 system's own 30s threshold) -- that system was removed as confirmed
    dead (no frontend, no other Python reader, no database column anywhere), so "stays under
    its threshold" is no longer a real invariant to protect. The remaining constants are
    still real and still worth pinning."""
    import server as srv

    assert srv.ANCHOR_QUOTE_LANE_REFRESH_POLL_SEC == 20.0
    assert srv.ANCHOR_QUOTE_LANE_MAX_AGE_SEC == 20.0
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
        assert int(prev_ent.get("analytics_version", 0)) + 1 == 8  # caps-ok: deliberately the same expression as server's full-publish _next_ver site; a lost version reads 0 and 0+1 != 8 fails the assertion
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
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_fetch_state")  # caps-ok: scanner false positive: next() here has NO default argument; a missing match raises StopIteration and fails the test
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


def _intake_source() -> str:
    """RC-REHAB-1 (thirty-fourth slice): the chain/quote pool selection, chain gate call and
    inline-vs-pooled arms moved from _fetch_state's body to server_state_intake.py."""
    from pathlib import Path

    return (Path(__file__).resolve().parent.parent / "server_state_intake.py").read_text(encoding="utf-8")


def _persistence_tail_source() -> str:
    """RC-REHAB-1 (2026-09-23, module extraction, twentieth slice):
    _post_publish_persistence_tail moved out of server.py into its own file. Tests that
    check the tail's OWN internal structure read this instead of _fetch_state_source();
    tests that check _fetch_state's two CALL sites still read _fetch_state_source(),
    since those call sites remain in server.py."""
    from pathlib import Path

    return (Path(__file__).resolve().parent.parent / "server_state_persistence_tail.py").read_text(encoding="utf-8")


def _fetch_state_ast():
    import ast

    tree = ast.parse(_fetch_state_source())
    fetch = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_fetch_state"
    )
    # RC-REHAB-1 (2026-09-23, module extraction, twentieth slice):
    # _post_publish_persistence_tail moved out of server.py entirely, into
    # server_state_persistence_tail.py -- no longer any FunctionDef node in server.py's
    # own tree at all (not even at module scope, as the nineteenth slice above found it).
    # Parsed from the new module's own source instead.
    tail_tree = ast.parse(_persistence_tail_source())
    tail = next(
        n for n in tail_tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_post_publish_persistence_tail"
    )
    return fetch, tail


def test_fix_b_publish_precedes_persistence_tail_source_lock():
    """Stage-order lock: the generated_at-stamping publish precedes the full-path
    tail call; the persistence stage marks live inside the tail def, which is
    defined before but executed after the publish.

    RC-REHAB-1 (2026-09-23, module extraction, twentieth slice): the tail def moved to
    server_state_persistence_tail.py -- "defined before executed" is now enforced by
    Python's own import semantics (the module-level `from server_state_persistence_tail
    import _post_publish_persistence_tail` must run, and therefore the def must exist,
    before any call in server.py's own body can execute), checked here by asserting the
    import exists; the stage marks' internal ordering is checked within the tail's own
    file, not server.py's."""
    src = _fetch_state_source()
    assert "from server_state_persistence_tail import _post_publish_persistence_tail" in src
    # RC-REHAB-1 (thirty-seventh slice): the generated_at-stamping publish is
    # _finalize_and_publish_state; its CALL must precede the full-path tail call.
    from pathlib import Path as _P

    assert '"generated_at": gen_ts' in (_P(__file__).resolve().parent.parent / "server_state_publish.py").read_text(encoding="utf-8")
    i_pub = src.index("_next_ver = _finalize_and_publish_state(")
    # RC-REHAB-1 (nineteenth slice): the full-path call is now multi-line
    # (`_post_publish_persistence_tail(\n        _next_ver, ...`) since it passes 61
    # keyword-only arguments -- the exact old single-line substring no longer exists.
    i_full_call = src.index('_post_publish_persistence_tail(\n        _next_ver')
    assert i_pub < i_full_call, "full-path tail call must come AFTER the publish"

    tail_src = _persistence_tail_source()
    i_snap_mark = tail_src.index('_stage_marks.append(("db_snapshot_write_accuracy"')
    i_cal_mark = tail_src.index('_stage_marks.append(("v2_calibration_logging"')
    assert i_snap_mark < i_cal_mark, "persistence stage marks must be ordered snapshot then calibration"


def test_fix_b_payload_shape_keys_still_served():
    """Payload-shape regression: counters/accuracy keys still assembled pre-publish
    (documented one-cycle lag; values come from the pre-read count + module cache).

    RC-REHAB-1 (2026-09-23, module extraction, twentieth slice): the pre-read count
    SELECT lives in the tail's own file now (server_state_persistence_tail.py); the
    ms_dict keys it feeds are still assembled in server.py's own body."""
    # RC-REHAB-1 (thirty-third slice): the payload projection moved to server_state_payload.py.
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "server_state_payload.py").read_text(encoding="utf-8")
    # CAPS RC-REHAB-1: the counts are read from the always-keyed db_counts dict (None =
    # unknown when no DB / failed query) instead of a `.get(..., 0)` served-zero default.
    assert 'ms_dict["total_snapshots"] = db_counts["total"]' in src
    assert 'ms_dict["filled_snapshots"] = db_counts["filled"]' in src
    assert '"rth_0930_1600_et" if ms_dict["accuracy"] is not None else None' in src
    # The pre-read count SELECT (read-only) still precedes the block.
    assert "db_counts = _ed_db.count_snapshots(ticker, CANONICAL_TIMEFRAME)" in _persistence_tail_source()


def test_fix_b_once_per_cycle_call_sites():
    """Once-per-cycle: exactly one tail def; exactly two mutually-exclusive call
    sites (log_only pre-return, full-path post-publish); exactly one calibration
    append inside the tail.

    RC-REHAB-1 (nineteenth slice): the tail def is module-level, so its own single
    definition is checked directly against the module tree (not ast.walk(fetch));
    the two CALL SITES are still inside _fetch_state's own body, checked there.

    RC-REHAB-1 (2026-09-23, module extraction, twentieth slice): the def moved out of
    server.py entirely -- its single-definition check now runs against
    server_state_persistence_tail.py's own tree instead."""
    import ast

    fetch, tail = _fetch_state_ast()
    tail_tree = ast.parse(_persistence_tail_source())
    defs = [
        n for n in tail_tree.body
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
    # RC-REHAB-1 (nineteenth slice): both call sites are now multi-line (61 keyword
    # args each) -- matched on their unique opening substring, not the full old
    # single-line call.
    src = _fetch_state_source()
    i_log_only_call = src.index('_post_publish_persistence_tail(\n        None, _v2_decision_for_response')
    i_log_only_return = src.index("return {}", i_log_only_call)
    i_full_call = src.index('_post_publish_persistence_tail(\n        _next_ver')
    assert i_log_only_call < i_log_only_return < i_full_call


def test_fix_b_failure_visibility_counters_wired():
    """Failure-visibility: both post_publish_* counters exist in the observability
    dict and each tail except-handler increments its counter and warns with the
    published version.

    RC-REHAB-1 (2026-09-23, module extraction, twentieth slice): the tail's own
    except-handlers (counter increments, warnings, published_version threading) moved
    to server_state_persistence_tail.py; _analytics_cache_observability itself is
    unchanged (still a server.py module-global with other callers, reached lazily)."""
    import server as srv

    assert "post_publish_snapshot_failures" in srv._analytics_cache_observability
    assert "post_publish_calibration_failures" in srv._analytics_cache_observability
    src = _persistence_tail_source()
    assert '_analytics_cache_observability["post_publish_snapshot_failures"] += 1' in src
    assert '_analytics_cache_observability["post_publish_calibration_failures"] += 1' in src
    assert "post-publish snapshot persistence failed ticker=" in src
    assert "post-publish calibration append failed ticker=" in src
    assert src.count("published_version") >= 4  # def params + both warnings


def test_fix_b_v2_decision_parity_served_equals_logged():
    """v2_decision parity: the full-path tail call passes the SERVED object
    (ms_dict['v2_decision']); the log_only path passes the built decision.

    RC-REHAB-1 (nineteenth slice): both call sites are now multi-line (61 keyword
    args each) -- matched on the still-exact positional-argument substring.

    RC-REHAB-1 (2026-09-23, module extraction, twentieth slice): the tail's own read of
    v2_decision_for_log moved to server_state_persistence_tail.py with it; the two call
    sites remain in server.py."""
    src = _fetch_state_source()
    assert '_post_publish_persistence_tail(\n        _next_ver, ms_dict["v2_decision"],' in src
    assert '_post_publish_persistence_tail(\n        None, _v2_decision_for_response,' in src
    assert "v2_decision=v2_decision_for_log," in _persistence_tail_source()


def test_fix_b_tail_never_touches_state_cache():
    """Isolation lock: the tail never references _state_cache, and the prev-vix
    capture holds structurally (VOL_INPUT_CONTRACT 1.0.0 renamed it to
    _vol_prev_published_vix; the old exact-string anchor was brittle):
    (a) exactly one capture binding exists;
    (b) it reads _state_cache.get(cache_key, ...).get("vix") — the prior
        published cache entry under the exact cycle key, no other source;
    (c) it precedes every dict-literal _state_cache[_cache_key] publish that
        carries a "vix" key, so this cycle's publish can never contaminate
        the previous-value calculation.

    RC-REHAB-1 (Phase 4, _fetch_state decomposition, sixteenth slice): the prev-vix
    capture moved from _fetch_state's own body into _vol_envelope_and_sector_for_state
    (a module-level function, like the persistence tail below), and its scratch-var
    name dropped its underscore prefix (_vol_prev_published_vix -> vol_prev_published_vix,
    _cache_key -> cache_key, the function's own parameter).

    RC-REHAB-1 (2026-09-23, module extraction, twenty-second slice): the function
    itself moved out of server.py entirely, into server_state_vol_envelope_sector.py,
    and the capture's _state_cache read became a `_srv._state_cache` attribute access
    (the established lazy `import server as _srv` pattern for server.py-local state
    with other callers) rather than a bare name. Since the capture now lives in a
    different file than the publish sites it must precede, the line-number ordering
    check below compares the CALL SITE of _vol_envelope_and_sector_for_state (which
    is what actually runs the capture) against the publish sites' line numbers within
    _fetch_state's own body, instead of comparing the capture's own (now foreign,
    incomparable) line number directly."""
    import ast
    from pathlib import Path

    ves_src = (Path(__file__).resolve().parent.parent / "server_state_vol_envelope_sector.py").read_text(encoding="utf-8")
    ves_tree = ast.parse(ves_src)
    fetch, tail = _fetch_state_ast()
    vol_fn = next(
        n for n in ves_tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_vol_envelope_and_sector_for_state"
    )
    names = {s.id for s in ast.walk(tail) if isinstance(s, ast.Name)}
    assert "_state_cache" not in names

    captures = [
        node for node in ast.walk(vol_fn)
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "vol_prev_published_vix"
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
    assert isinstance(inner.func.value, ast.Attribute), (
        "prev vix must come from the lazily-imported _srv._state_cache attribute access"
    )
    assert inner.func.value.attr == "_state_cache", "prev vix must come from the state cache"
    assert isinstance(inner.func.value.value, ast.Name) and inner.func.value.value.id == "_srv"
    assert any(
        isinstance(a, ast.Name) and a.id == "cache_key" for a in inner.args
    ), "prev vix must read the exact per-cycle cache key"

    call_sites = [
        node for node in ast.walk(fetch)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "_vol_envelope_and_sector_for_state"
    ]
    assert len(call_sites) == 1, "_fetch_state must call _vol_envelope_and_sector_for_state exactly once"
    call_site = call_sites[0]

    # RC-REHAB-1 (thirty-seventh slice): the vix-carrying publish moved into
    # server_state_publish._finalize_and_publish_state (`_srv._state_cache[cache_key] = {...}`);
    # ordering is the order of the two CALLS inside _fetch_state.
    pub_tree = ast.parse((Path(__file__).resolve().parent.parent / "server_state_publish.py").read_text(encoding="utf-8"))
    pub_fn = next(n for n in pub_tree.body if isinstance(n, ast.FunctionDef) and n.name == "_finalize_and_publish_state")  # caps-ok: scanner false positive: next() has NO default argument; a missing publish function raises StopIteration and fails the test
    vix_publishes = [
        node for node in ast.walk(pub_fn)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Dict)
        and any(
            isinstance(t, ast.Subscript) and isinstance(t.value, ast.Attribute)
            and t.value.attr == "_state_cache"
            for t in node.targets
        )
        and "vix" in {
            k.value for k in node.value.keys if isinstance(k, ast.Constant)
        }
    ]
    assert vix_publishes, "expected a vix-carrying _state_cache publish in the publish phase"
    publishes = [
        node for node in ast.walk(fetch)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "_finalize_and_publish_state"
    ]
    assert len(publishes) == 1, "_fetch_state must call the publish phase exactly once"
    assert all(call_site.lineno < p.lineno for p in publishes), (
        "the _vol_envelope_and_sector_for_state call (which runs the prev-vix capture) "
        "must precede every vix-carrying publish"
    )


# ── OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_1 ───────────────────────────────


def test_step1_log_only_inline_source_lock():
    """log_only joins the shutdown inline path for chain/quote and gets a
    sequential inline arm for candle seeds; operator-facing submits remain.

    RC-REHAB-1 (2026-09-23, module extraction, twenty-third slice): the candle-seed
    arm (both its inline check and its pooled arm) moved with _exposures_for_state
    into server_state_exposures.py; the chain/quote arm stays in _fetch_state's own
    body, in server.py. Checked against each site's own file."""
    src = _intake_source()
    assert "if _srv._analytics_bg_shutdown or _srv._log_only_inline_leaf_fetches(log_only):" in src
    from pathlib import Path

    exp_src = (Path(__file__).resolve().parent.parent / "server_state_exposures.py").read_text(encoding="utf-8")
    i_inline_seed = exp_src.index("if _srv._log_only_inline_leaf_fetches(log_only):", exp_src.index("def _seed_candles"))
    # Step 2 rebinds the pooled arm to the dedicated leaf pool; the Step 1
    # invariant (inline arm precedes the pooled arm) is pool-independent.
    i_pool_seed = exp_src.index("_seed_pool = (")
    assert i_inline_seed < i_pool_seed, "inline seed arm must precede the pooled arm"
    # Operator-facing bounded parallelism intact (submits still present).
    assert "chain_fut = pool.submit(" in src
    assert "_f5 = _seed_pool.submit(_seed_candles, 5)" in exp_src
    assert "_f1 = _seed_pool.submit(_seed_candles, 1)" in exp_src


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
    src = _intake_source()
    assert "_srv._analytics_bg_shutdown or _srv._log_only_inline_leaf_fetches(log_only)" in src


# ── OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_2 ───────────────────────────────


def test_step2_leaf_executor_referenced_only_in_fetch_state_leaf_blocks():
    """AST lock: _get_recompute_leaf_executor is called only inside _fetch_state
    (the chain/quote submit block) or _exposures_for_state (the candle-seed submit
    block, extracted from _fetch_state's own body) — never by handlers or other code.

    RC-REHAB-1 (Phase 4, _fetch_state decomposition, ninth slice): the candle-seed
    leaf-pool selection moved out of _fetch_state's own body into
    _exposures_for_state. This test's own literal expectation was never updated
    when that slice landed (caught later, during the nineteenth slice's broader
    verification sweep) -- the underlying invariant (leaf-executor calls stay
    inside _fetch_state's own decomposition, never leak into route handlers or
    unrelated code) still holds; only the accepted caller set needed widening.

    RC-REHAB-1 (2026-09-23, module extraction, twenty-third slice): _exposures_for_state
    itself moved out of server.py entirely, into server_state_exposures.py, where its
    leaf-executor call is now `_srv._get_recompute_leaf_executor()` (the established
    lazy `import server as _srv` pattern) rather than a bare name call -- checked
    against that file's own tree instead of server.py's."""
    import ast
    from pathlib import Path

    tree = ast.parse(_fetch_state_source())
    callers = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                        and sub.func.id == "_get_recompute_leaf_executor"
                        and node.name != "_get_recompute_leaf_executor"):
                    callers.append(node.name)
    exp_src = (Path(__file__).resolve().parent.parent / "server_state_exposures.py").read_text(encoding="utf-8")
    intake_src = _intake_source()
    for extracted in (exp_src, intake_src):
        for node in ast.walk(ast.parse(extracted)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for sub in ast.walk(node):
                    if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                            and sub.func.attr == "_get_recompute_leaf_executor"):
                        callers.append(node.name)
    # Nested walk double-counts under enclosing defs; the set must be exactly the two
    # extracted leaf sites -- the chain/quote leg (server_state_intake, thirty-fourth
    # slice) and the candle-seed leg (server_state_exposures). server.py itself no longer
    # calls the leaf executor anywhere except its own definition.
    assert set(callers) == {"_fetch_chain_and_quote_for_state", "_exposures_for_state"}, (
        f"unexpected callers: {sorted(set(callers))}"
    )
    # UI_05 residual: both sites are conditional expressions selecting the priority lane vs
    # the shared leaf pool.
    assert intake_src.count("else _srv._get_recompute_leaf_executor()") == 1  # chain/quote
    assert exp_src.count("else _srv._get_recompute_leaf_executor()") == 1  # seeds


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
    is no longer referenced by either block.

    RC-REHAB-1 (Phase 4, _fetch_state decomposition, ninth slice): the candle-seed
    site moved into _exposures_for_state, where its own parameter dropped the
    `_fetch_state`-scratch-variable underscore prefix (`_chain_priority` ->
    `chain_priority`) -- counted together with the chain/quote site's original
    spelling, still inside _fetch_state itself, rather than one literal pattern.

    RC-REHAB-1 (2026-09-23, module extraction, twenty-third slice): _exposures_for_state
    itself moved out of server.py, into server_state_exposures.py, where its leaf-
    executor calls are `_srv._get_priority_leaf_executor()`/
    `_srv._get_recompute_leaf_executor()` (the lazy `import server as _srv` pattern)
    rather than bare names -- checked per-file below instead of one shared count."""
    src = _intake_source()
    from pathlib import Path

    exp_src = (Path(__file__).resolve().parent.parent / "server_state_exposures.py").read_text(encoding="utf-8")
    # UI_05 residual: both leaf sites select the bounded PRIORITY leaf lane
    # for operator-priority recomputes and the shared leaf pool otherwise —
    # the route pool stays banned at both sites.
    assert src.count("if chain_priority") >= 1
    assert exp_src.count("if chain_priority") >= 1
    assert src.count("else _srv._get_recompute_leaf_executor()") == 1
    assert exp_src.count("else _srv._get_recompute_leaf_executor()") == 1
    assert src.count("_srv._get_priority_leaf_executor()") >= 1
    assert exp_src.count("_srv._get_priority_leaf_executor()") >= 1
    assert "_get_route_offload_executor" not in src
    assert "_seed_pool = _get_route_offload_executor()" not in exp_src


def test_step2_log_only_uses_neither_pool_for_nested_work():
    """Step 1 preserved: the inline arms precede both submit blocks, so log_only
    reaches neither the route pool nor the leaf pool for nested work.

    RC-REHAB-1 (2026-09-23, module extraction, twenty-third slice): the candle-seed
    site (both its inline check and its pooled arm) moved with _exposures_for_state
    into server_state_exposures.py; the chain/quote site stays in _fetch_state's own
    body, in server.py."""
    src = _intake_source()
    i_inline_cq = src.index("if _srv._analytics_bg_shutdown or _srv._log_only_inline_leaf_fetches(log_only):")
    i_pool_cq = src.index("pool = (")
    assert i_inline_cq < i_pool_cq

    from pathlib import Path

    exp_src = (Path(__file__).resolve().parent.parent / "server_state_exposures.py").read_text(encoding="utf-8")
    i_inline_seed = exp_src.index("if _srv._log_only_inline_leaf_fetches(log_only):", exp_src.index("def _seed_candles"))
    i_pool_seed = exp_src.index("_seed_pool = (")
    assert i_inline_seed < i_pool_seed


def test_step2_shutdown_order_and_inline_branch():
    """Leaf-pool teardown comes after the analytics executor shutdown, and the
    _analytics_bg_shutdown condition still forces inline leaf fetches."""
    src = _fetch_state_source()
    i_analytics_shutdown = src.index("_shutdown_analytics_executor(wait=True)")
    i_leaf_teardown = src.index("_recompute_leaf_executor.shutdown(wait=True, cancel_futures=True)")
    assert i_analytics_shutdown < i_leaf_teardown
    assert "_srv._analytics_bg_shutdown or _srv._log_only_inline_leaf_fetches(log_only)" in _intake_source()


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
    increment; the payload attaches a copy adjacent to the observability block.

    RC-REHAB-1 (2026-09-23, module extraction, twentieth slice): the tail's own
    except-handlers moved to server_state_persistence_tail.py with it; the ms_dict
    payload-attachment ordering remains a server.py-only concern (both attach sites
    are in _fetch_state's own body, unrelated to where the tail itself now lives)."""
    tail_src = _persistence_tail_source()
    i_snap_inc = tail_src.index('_analytics_cache_observability["post_publish_snapshot_failures"] += 1')
    i_snap_rec = tail_src.index('_record_post_publish_failure("snapshot", ticker, published_version, e)')
    i_cal_inc = tail_src.index('_analytics_cache_observability["post_publish_calibration_failures"] += 1')
    i_cal_rec = tail_src.index(
        '_record_post_publish_failure("calibration", ticker, published_version, _v2_log_e)'
    )
    assert i_snap_inc < i_snap_rec < i_cal_inc < i_cal_rec

    from pathlib import Path as _P

    # RC-REHAB-1 (thirty-seventh slice): both attachments live in the publish phase.
    src = (_P(__file__).resolve().parent.parent / "server_state_publish.py").read_text(encoding="utf-8")
    i_obs_attach = src.index('ms_dict["analytics_cache_observability_v1"] = dict(')
    i_err_attach = src.index('ms_dict["post_publish_last_errors_v1"] = {')
    assert i_obs_attach < i_err_attach


def test_tail_mkt_ctx_nonlocal_rebind_restored():
    """The confluence-completion rebind targets mkt_ctx; the completion call remains.

    RC-REHAB-1 (Phase 4, _fetch_state decomposition, nineteenth slice):
    _post_publish_persistence_tail was promoted from a nested closure to a
    module-level function, so `mkt_ctx` is now a plain keyword-only PARAMETER
    rather than a `nonlocal`-declared name -- a `nonlocal` statement in a
    module-level (non-nested) function is a SyntaxError, so its absence here is
    required, not a regression. The reassignment itself is an ordinary local
    rebind now (parameters are always bound before the function body runs, so
    the UnboundLocalError class this used to guard against cannot occur for a
    parameter); verified it is NOT returned to the caller because nothing in
    _fetch_state reads mkt_ctx again after either of the tail's two call sites.

    RC-REHAB-1 (2026-09-23, module extraction, twentieth slice): the rebind moved with
    the tail to server_state_persistence_tail.py; _ensure_mkt_ctx_confluence_complete
    itself stayed in server.py (it has other callers), reached lazily as
    `_srv._ensure_mkt_ctx_confluence_complete` -- the call-site substring now carries
    that prefix."""
    import ast

    _fetch, tail = _fetch_state_ast()
    declared = set()
    for node in ast.walk(tail):
        if isinstance(node, ast.Nonlocal):
            declared.update(node.names)
    assert declared == set(), (
        "a module-level function must not declare `nonlocal` at all -- it would "
        "be a SyntaxError with no enclosing function scope to bind to"
    )
    tail_params = {a.arg for a in tail.args.args + tail.args.kwonlyargs}
    assert "mkt_ctx" in tail_params, "mkt_ctx must be threaded in as an explicit parameter"
    src = _persistence_tail_source()
    assert "mkt_ctx = _srv._ensure_mkt_ctx_confluence_complete(client, mkt_ctx)" in src


def test_tail_no_unbound_shadow_of_fetch_state_locals():
    """Relocation-class lock: no name stored in the tail may shadow a
    _fetch_state-level binding AND be read at-or-before its first tail store
    without a nonlocal declaration OR being one of the tail's own parameters
    (the mkt_ctx UnboundLocalError class). Comprehension targets are
    scope-isolated in py3 and excluded.

    RC-REHAB-1 (Phase 4, _fetch_state decomposition, nineteenth slice): the tail
    is now a module-level function with all 61 former free variables threaded in
    as explicit parameters. A parameter is ALWAYS bound before the function body
    executes, so the specific bug class this test protects against (a nested
    closure reading a name before Python's compile-time scope inference has
    given it a local binding, without `nonlocal`) is structurally impossible for
    a plain function's own parameters -- there is no "first store point" for a
    parameter inside the body to be read-before. Parameter names are exempted
    from the offender check for exactly this reason, alongside `nonlocals` (now
    always empty for a module-level function) and comprehension targets."""
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
    tail_params = {a.arg for a in tail.args.args + tail.args.kwonlyargs}
    nonlocals |= tail_params

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
    # RC-483: the idle standing producer now keeps only ENROLLED cards warm (an un-enrolled
    # viewed-once card must not be resurrected — the CRM/DKS defect). These tests exercise the
    # selection MECHANICS (oldest-first, rate-bound, owner-exclusion), so their seeded tickers
    # are enrolled here; the enrollment-scoping itself is pinned in
    # tests/test_idle_producer_enrolled_only_v1.py.
    monkeypatch.setattr(srv, "_logger_tickers", [k[0] for k in entries], raising=False)


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
    recompute is operator-priority (the _chain_priority classifier).

    RC-REHAB-1 (2026-09-23, module extraction, twenty-third slice): the seed leg
    moved with _exposures_for_state into server_state_exposures.py, where its
    leaf-executor calls are `_srv._get_priority_leaf_executor()`/
    `_srv._get_recompute_leaf_executor()` (the lazy `import server as _srv`
    pattern)."""
    src = _intake_source()
    i_cq = src.index("pool = (")
    assert "_srv._get_priority_leaf_executor()" in src[i_cq:i_cq + 200]
    assert "else _srv._get_recompute_leaf_executor()" in src[i_cq:i_cq + 280]

    from pathlib import Path

    exp_src = (Path(__file__).resolve().parent.parent / "server_state_exposures.py").read_text(encoding="utf-8")
    i_seed = exp_src.index("_seed_pool = (")
    assert "_srv._get_priority_leaf_executor()" in exp_src[i_seed:i_seed + 220]
    assert "else _srv._get_recompute_leaf_executor()" in exp_src[i_seed:i_seed + 280]


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
    entered = th.Event()
    release = th.Event()
    sweep_threads: list = []

    # RC-17: no wall-clock assertions. "Not inline" is proven MECHANICALLY:
    # (a) callers return the OLD context while the sweep is still held open
    # (an inline sweep would hand back the new one), and (b) the sweep
    # records its executing thread, which must not be the caller's. Holding
    # the fake sweep open until after the herd of calls finishes prevents a
    # fast executor from publishing a fresh cache mid-loop (which would
    # correctly return the NEW object on later calls — not an inline pay).
    def _fake_sweep(client, **kwargs):
        calls["n"] += 1
        sweep_threads.append(th.current_thread())
        entered.set()
        assert release.wait(30), "test never released the held sweep"
        return MarketContext()

    monkeypatch.setattr(srv, "fetch_market_context", _fake_sweep)
    caller_thread = th.current_thread()
    first = srv._get_mkt_ctx(None)
    assert first is old_ctx
    assert entered.wait(30), "background sweep never entered"
    served = [first] + [srv._get_mkt_ctx(None) for _ in range(4)]
    assert all(s is old_ctx for s in served), "a caller was handed the new context inline"
    assert sweep_threads and all(t is not caller_thread for t in sweep_threads), \
        "sweep executed inline on the caller thread"
    release.set()
    deadline = time.time() + 30
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

    # RC-17: the barrier makes overlap CERTAIN instead of hoping threads
    # collide inside a scheduling window; waits are generous upper bounds.
    barrier = th.Barrier(8, timeout=30)

    def _fake_sweep(client, **kwargs):
        with lk:
            calls["n"] += 1
        time.sleep(0.25)   # hold the inflight window open so a herd CAN collide
        done.set()
        return MarketContext()

    monkeypatch.setattr(srv, "fetch_market_context", _fake_sweep)
    served: list = []
    slock = th.Lock()

    def _call():
        barrier.wait()
        out = srv._get_mkt_ctx(None)
        with slock:
            served.append(out)

    threads = [th.Thread(target=_call) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads), "caller thread hung"
    assert len(served) == 8
    assert all(s is old_ctx for s in served)
    assert done.wait(30), "background sweep never executed"
    deadline = time.time() + 30
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

    # RC-17: barrier guarantees the callers actually overlap; joins are
    # generous upper bounds with an explicit liveness assert.
    barrier = th.Barrier(6, timeout=30)

    def _fake_sweep(client, **kwargs):
        with lk:
            calls["n"] += 1
        time.sleep(0.25)   # hold the sweep open so boot joiners CAN overlap
        return MarketContext()

    monkeypatch.setattr(srv, "fetch_market_context", _fake_sweep)
    served: list = []
    slock = th.Lock()

    def _call():
        barrier.wait()
        out = srv._get_mkt_ctx(None)
        with slock:
            served.append(out)

    threads = [th.Thread(target=_call) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads), "caller thread hung"
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
    # RC-REHAB-1 (thirty-fourth slice): the two leaf marks are appended by the intake phase
    # into the SAME list _fetch_state owns (window_marks=_chain_window_marks).
    import server_state_intake

    fetch_src = inspect.getsource(srv._fetch_state) + inspect.getsource(
        server_state_intake._fetch_chain_and_quote_for_state)
    assert "window_marks=_chain_window_marks" in inspect.getsource(srv._fetch_state)
    for mark in (
        "chain_window_preamble_ms",
        "chain_window_mkt_ctx_ms",
        "chain_window_leaf_wall_ms",
        "chain_window_contracts_parse_ms",
    ):
        assert mark in fetch_src, f"chain-window mark {mark} missing from _fetch_state"
