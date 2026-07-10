"""Bounded two-slot chain gate locks (operator-approved 2026-07-10 EVE).

Deterministic concurrency coverage: capacity, per-ticker single-flight,
coalescing, priority handoff, timeout fail-open, throttle/auth breaker,
degradation + recovery, exception propagation, no cross-ticker delivery,
shutdown-safe release.
"""

from __future__ import annotations

import threading
import time

import pytest

import server as srv


def _fresh_gate(monkeypatch):
    gate = srv._ChainGateV2()
    monkeypatch.setattr(srv, "_schwab_chain_fetch_gate", gate)
    monkeypatch.setattr(srv, "_chain_inflight", {})
    return gate


def test_capacity_is_two_and_bounded(monkeypatch):
    gate = _fresh_gate(monkeypatch)
    assert gate.acquire(timeout=1)
    assert gate.acquire(timeout=1)
    assert gate.acquire(timeout=0.2) is False   # global max 2
    gate.release()
    assert gate.acquire(timeout=1)
    gate.release(); gate.release()


def test_two_different_tickers_run_concurrently(monkeypatch):
    gate = _fresh_gate(monkeypatch)
    active = {"n": 0, "max": 0}
    lk = threading.Lock()

    def _slow_chain(client, ticker, *, strike_count):
        with lk:
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
        time.sleep(0.25)
        with lk:
            active["n"] -= 1
        return f"RESP_{ticker}"

    monkeypatch.setattr(srv, "safe_get_chain", _slow_chain)
    threads = [
        threading.Thread(target=srv._gated_safe_get_chain, args=(None, t), kwargs={"strike_count": 5})
        for t in ("ZZGA", "ZZGB", "ZZGC")
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert active["max"] == 2, f"expected exactly 2 concurrent, saw {active['max']}"


def test_same_ticker_requests_coalesce_single_fetch(monkeypatch):
    gate = _fresh_gate(monkeypatch)
    calls = {"n": 0}

    def _slow_chain(client, ticker, *, strike_count):
        calls["n"] += 1
        time.sleep(0.3)
        return f"RESP_{ticker}"

    monkeypatch.setattr(srv, "safe_get_chain", _slow_chain)
    results = []

    def _go():
        results.append(srv._gated_safe_get_chain(None, "ZZCO", strike_count=5))

    threads = [threading.Thread(target=_go) for _ in range(3)]
    for t in threads:
        t.start()
        time.sleep(0.05)  # ensure the first registers as owner
    for t in threads:
        t.join(timeout=10)
    assert calls["n"] == 1, "duplicate same-ticker requests must coalesce"
    assert gate.metrics["coalesced_hits"] == 2
    assert {r[0] for r in results} == {"RESP_ZZCO"}


def test_no_cross_ticker_result_delivery(monkeypatch):
    _fresh_gate(monkeypatch)
    monkeypatch.setattr(
        srv, "safe_get_chain",
        lambda client, ticker, *, strike_count: f"RESP_{ticker}",
    )
    out = {}

    def _go(t):
        out[t] = srv._gated_safe_get_chain(None, t, strike_count=5)[0]

    threads = [threading.Thread(target=_go, args=(t,)) for t in ("ZZX1", "ZZX2", "ZZX3")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert out == {"ZZX1": "RESP_ZZX1", "ZZX2": "RESP_ZZX2", "ZZX3": "RESP_ZZX3"}


def test_priority_waiter_acquires_before_background(monkeypatch):
    """Degraded (capacity-1) mode exercises the pure handoff discipline."""
    gate = _fresh_gate(monkeypatch)
    gate.record_result(False, throttled=True)   # force capacity 1
    assert gate.acquire(timeout=1)              # hold the single slot
    order = []
    bg_started = threading.Event()
    prio_started = threading.Event()

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

    t_bg = threading.Thread(target=bg); t_bg.start()
    bg_started.wait(2); time.sleep(0.15)
    t_prio = threading.Thread(target=prio); t_prio.start()
    prio_started.wait(2); time.sleep(0.15)
    gate.release()
    t_prio.join(5); t_bg.join(5)
    assert order == ["priority", "background"]


def test_timeout_fail_open_counts(monkeypatch):
    gate = _fresh_gate(monkeypatch)
    assert gate.acquire(timeout=1) and gate.acquire(timeout=1)  # saturate both slots
    monkeypatch.setattr(srv, "CHAIN_FETCH_GATE_ACQUIRE_TIMEOUT_SEC", 0.1)
    monkeypatch.setattr(srv, "safe_get_chain", lambda c, t, *, strike_count: "OK")
    before = srv._chain_fetch_gate_timeout_count
    resp, wait_s, fetch_s = srv._gated_safe_get_chain(None, "ZZTM", strike_count=5)
    assert resp == "OK"
    assert srv._chain_fetch_gate_timeout_count == before + 1
    assert wait_s >= 0.1
    gate.release(); gate.release()
    # no double-release: both slots acquirable exactly twice
    assert gate.acquire(timeout=1) and gate.acquire(timeout=1)
    assert gate.acquire(timeout=0.1) is False
    gate.release(); gate.release()


def test_http_throttle_degrades_to_one_slot(monkeypatch):
    gate = _fresh_gate(monkeypatch)

    class _R429:
        status_code = 429

    monkeypatch.setattr(srv, "safe_get_chain", lambda c, t, *, strike_count: _R429())
    srv._gated_safe_get_chain(None, "ZZTH", strike_count=5)
    snap = gate.snapshot()
    assert snap["degraded"] is True
    assert snap["capacity_now"] == 1
    assert snap["degraded_reason_last"] == "http_throttled"


def test_auth_error_degrades_and_propagates(monkeypatch):
    gate = _fresh_gate(monkeypatch)

    def _boom(c, t, *, strike_count):
        raise srv.SchwabAuthError("refresh token revoked")

    monkeypatch.setattr(srv, "safe_get_chain", _boom)
    with pytest.raises(srv.SchwabAuthError):
        srv._gated_safe_get_chain(None, "ZZAU", strike_count=5)
    snap = gate.snapshot()
    assert snap["degraded"] is True
    assert snap["degraded_reason_last"] == "auth_unstable"


def test_consecutive_failures_trip_breaker_and_recover(monkeypatch):
    gate = _fresh_gate(monkeypatch)

    def _fail(c, t, *, strike_count):
        raise RuntimeError("boom")

    monkeypatch.setattr(srv, "safe_get_chain", _fail)
    for i in range(srv.CHAIN_GATE_BREAKER_FAILURE_THRESHOLD):
        with pytest.raises(RuntimeError):
            srv._gated_safe_get_chain(None, f"ZZF{i}", strike_count=5)
    assert gate.snapshot()["degraded"] is True
    assert gate.snapshot()["degraded_reason_last"] == "consecutive_failures"
    # recovery at cooldown expiry
    with gate._cond:
        gate._degraded_until = time.monotonic() - 1
    assert gate.snapshot()["degraded"] is False
    assert gate.snapshot()["capacity_now"] == srv.CHAIN_GATE_GLOBAL_SLOTS_MAX
    # success resets the failure counter
    monkeypatch.setattr(srv, "safe_get_chain", lambda c, t, *, strike_count: "OK")
    srv._gated_safe_get_chain(None, "ZZOK", strike_count=5)
    assert gate.snapshot()["consecutive_failures"] == 0


def test_coalesced_waiters_receive_owner_exception(monkeypatch):
    _fresh_gate(monkeypatch)
    started = threading.Event()

    def _slow_boom(c, t, *, strike_count):
        started.set()
        time.sleep(0.3)
        raise RuntimeError("owner failed")

    monkeypatch.setattr(srv, "safe_get_chain", _slow_boom)
    errs = []

    def _owner():
        try:
            srv._gated_safe_get_chain(None, "ZZEX", strike_count=5)
        except RuntimeError as e:
            errs.append(("owner", str(e)))

    def _waiter():
        started.wait(2)
        time.sleep(0.05)
        try:
            srv._gated_safe_get_chain(None, "ZZEX", strike_count=5)
        except RuntimeError as e:
            errs.append(("waiter", str(e)))

    to = threading.Thread(target=_owner); tw = threading.Thread(target=_waiter)
    to.start(); tw.start(); to.join(10); tw.join(10)
    assert ("owner", "owner failed") in errs
    assert ("waiter", "owner failed") in errs   # propagated, never swallowed


def test_gate_metrics_snapshot_shape(monkeypatch):
    gate = _fresh_gate(monkeypatch)
    snap = gate.snapshot()
    for k in ("acquisitions", "priority_acquisitions", "timeouts", "queue_wait_max_ms",
              "coalesced_hits", "degraded_entries", "degraded_reason_last",
              "in_use", "capacity_now", "global_slots_max", "degraded",
              "priority_waiting", "consecutive_failures"):
        assert k in snap, k
    assert snap["global_slots_max"] == 2


def test_diagnostics_endpoint_serves_snapshot(monkeypatch):
    _fresh_gate(monkeypatch)
    body = srv.api_chain_gate_diagnostics()
    assert body["gate"]["global_slots_max"] == 2
    assert body["breaker_failure_threshold"] == srv.CHAIN_GATE_BREAKER_FAILURE_THRESHOLD
    assert isinstance(body["inflight_tickers"], list)


def test_inflight_registry_cleared_after_completion(monkeypatch):
    _fresh_gate(monkeypatch)
    monkeypatch.setattr(srv, "safe_get_chain", lambda c, t, *, strike_count: "OK")
    srv._gated_safe_get_chain(None, "ZZCL", strike_count=5)
    with srv._chain_inflight_lock:
        assert "ZZCL" not in srv._chain_inflight


def test_no_deadlock_under_mixed_load(monkeypatch):
    _fresh_gate(monkeypatch)
    monkeypatch.setattr(
        srv, "safe_get_chain",
        lambda c, t, *, strike_count: (time.sleep(0.05), f"R_{t}")[1],
    )
    done = []

    def _go(i):
        t = f"ZZM{i % 4}"   # mixes coalescing + distinct tickers
        srv._gated_safe_get_chain(None, t, strike_count=5, priority=(i % 2 == 0))
        done.append(i)

    threads = [threading.Thread(target=_go, args=(i,)) for i in range(12)]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    assert len(done) == 12, f"only {len(done)}/12 completed"
    assert time.monotonic() - t0 < 10
