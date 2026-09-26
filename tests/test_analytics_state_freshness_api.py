"""S2A/S2B — Tier C /api/analytics/state card_freshness_v1 + operator mirror contract tests."""

from __future__ import annotations

import time



# ── TIER_C_STAGE_TIMER_INSTRUMENTATION_V1 — stage timing + cache observability locks ──


def test_executor_sizing_unchanged_by_stage_timer_slice():
    """Hard constraint: analytics executor stays at 4 workers (no sizing change in this slice)."""
    import server as srv

    assert srv._get_analytics_executor()._max_workers == 4


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


# ── ANCHOR_QUOTE_LANE_REFRESHER_V1 ────────────────────────────────────────────


def test_no_rest_quote_refresher_feeds_the_live_plane():
    """The ANCHOR_QUOTE_LANE_REFRESHER re-quoted SPY/QQQ/IWM over REST every 20s into the
    live plane whenever their streamed quote aged past 20s -- a REST fallback for three named
    tickers. Deleted (operator rules 2026-09-23: no fallbacks, universality): a stale streamed
    quote now reads stale."""
    import inspect

    import server as srv
    src = inspect.getsource(srv)
    assert "_anchor_quote_lane" not in src and "rest_anchor_lane_refresher" not in src


# ── FIX_B_PUBLISH_BEFORE_LOG_REORDER_V1 ──────────────────────────────────────


def _fetch_state_source() -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")


# ── OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_2 ───────────────────────────────


def test_step2_leaf_functions_have_no_nested_submit():
    """AST leaf lock: leaf functions, schwab_client, and the price_bars_1m readers
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
                         "_read_bars_1m", "_bars_1m", "_bars_5m"}) == []
    assert submit_sites(root / "schwab_client.py") == []


# ── UI_05_OPERATOR_PRIORITY_ADMISSION_V1 — priority admission + gate locks ────


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


# ── UI_05 residual — priority leaf lane + startup model prewarm sweep ────────


def test_ui05r_priority_leaf_teardown_present():
    src = _fetch_state_source()
    assert src.count("_priority_leaf_executor.shutdown(wait=True, cancel_futures=True)") == 1
