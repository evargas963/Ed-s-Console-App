"""Bounded two-slot chain gate locks (operator-approved 2026-07-10 EVE).

Deterministic concurrency coverage: capacity, per-ticker single-flight,
coalescing, priority handoff, timeout fail-open, throttle/auth breaker,
degradation + recovery, exception propagation, no cross-ticker delivery,
shutdown-safe release.
"""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path

import pytest

import server as srv


def _fresh_gate(monkeypatch):
    gate = srv._ChainGateV2()
    monkeypatch.setattr(srv, "_schwab_chain_fetch_gate", gate)
    monkeypatch.setattr(srv, "_chain_inflight", {})
    return gate


# ─────────────────────────────────────────────────────────────────────────────
# RC-279 — a double must PROVE it can still stand in for what it replaces
# ─────────────────────────────────────────────────────────────────────────────

def _forwarded_kwargs_at_the_gated_call_site() -> set[str]:
    """The keywords `_gated_safe_get_chain` actually passes to `safe_get_chain`.

    Read from the source rather than restated here, because a list of keywords
    maintained by hand is the same defect one level up.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(srv._gated_safe_get_chain).lstrip())
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "safe_get_chain"):
            return {kw.arg for kw in node.keywords if kw.arg}
    raise AssertionError("no call to safe_get_chain found in _gated_safe_get_chain")


def _doubles_installed_in_this_file() -> list[tuple[int, ast.AST]]:
    """Every callable this file monkeypatches over `safe_get_chain`, by source line."""
    import ast as _ast

    src = Path(__file__).read_text(encoding="utf-8")
    out: list[tuple[int, _ast.AST]] = []
    tree = _ast.parse(src)
    funcs = {n.name: n for n in _ast.walk(tree)
             if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))}
    for node in _ast.walk(tree):
        if not (isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute)
                and node.func.attr == "setattr" and len(node.args) == 3):
            continue
        target = node.args[1]
        if not (isinstance(target, _ast.Constant) and target.value == "safe_get_chain"):
            continue
        repl = node.args[2]
        if isinstance(repl, _ast.Lambda):
            out.append((repl.lineno, repl.args))
        elif isinstance(repl, _ast.Name) and repl.id in funcs:
            out.append((funcs[repl.id].lineno, funcs[repl.id].args))
    return out


def test_the_gated_call_site_still_matches_the_real_callee():
    """If these two drift, every behavioural test below fails for the wrong reason."""
    import inspect

    forwarded = _forwarded_kwargs_at_the_gated_call_site()
    assert forwarded, "the gated call site forwards nothing — re-read it"
    inspect.signature(srv.safe_get_chain).bind(
        None, "ZZZ", **{k: None for k in forwarded})


def test_every_double_can_stand_in_for_the_real_safe_get_chain():
    """RC-279: ten of this file's fourteen tests once failed on ONE stale double shape.

    `safe_get_chain` gained `to_date`; all 13 doubles were pinned to
    `(client, ticker, *, strike_count)`, so `TypeError: <lambda>() got an unexpected
    keyword argument 'to_date'` was raised INSIDE the code under test — and inside a
    worker thread — where it reads like a product failure. The concurrency behaviour
    these tests exist to protect went unverified while the suite was loudly red.

    RC-239 hit this first and repaired the three doubles that happened to be failing,
    leaving ten identical ones. So the lock is not "add the keyword"; it is that a
    substitute must accept whatever the real call site forwards, checked here, where
    a failure names the double instead of blaming the subject.
    """
    forwarded = _forwarded_kwargs_at_the_gated_call_site()
    doubles = _doubles_installed_in_this_file()
    assert len(doubles) >= 10, f"expected the file's doubles to be found, saw {len(doubles)}"

    for lineno, args in doubles:
        named = {a.arg for a in list(args.args) + list(args.kwonlyargs)}
        assert args.kwarg is not None or forwarded <= named, (
            f"tests/test_chain_gate_v2.py:{lineno}: this double cannot accept "
            f"{sorted(forwarded - named)}, which the gated call site forwards. It will "
            f"raise TypeError inside the code under test and look like a product bug. "
            f"Give it **kwargs.")


def test_capacity_is_two_and_bounded(monkeypatch):
    gate = _fresh_gate(monkeypatch)
    assert gate.acquire(timeout=1)
    assert gate.acquire(timeout=1)
    assert gate.acquire(timeout=0.2) is False   # global max 2
    gate.release()
    assert gate.acquire(timeout=1)
    gate.release(); gate.release()


def test_two_different_tickers_run_concurrently(monkeypatch):
    _fresh_gate(monkeypatch)
    active = {"n": 0, "max": 0}
    lk = threading.Lock()

    def _slow_chain(client, ticker, **kwargs):
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

    def _slow_chain(client, ticker, **kwargs):
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
        lambda client, ticker, **kwargs: f"RESP_{ticker}",
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
    monkeypatch.setattr(srv, "safe_get_chain", lambda c, t, **kwargs: "OK")
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

    monkeypatch.setattr(srv, "safe_get_chain", lambda c, t, **kwargs: _R429())
    srv._gated_safe_get_chain(None, "ZZTH", strike_count=5)
    snap = gate.snapshot()
    assert snap["degraded"] is True
    assert snap["capacity_now"] == 1
    assert snap["degraded_reason_last"] == "http_throttled"


def test_auth_error_degrades_and_propagates(monkeypatch):
    gate = _fresh_gate(monkeypatch)

    def _boom(c, t, **kwargs):
        raise srv.SchwabAuthError("refresh token revoked")

    monkeypatch.setattr(srv, "safe_get_chain", _boom)
    with pytest.raises(srv.SchwabAuthError):
        srv._gated_safe_get_chain(None, "ZZAU", strike_count=5)
    snap = gate.snapshot()
    assert snap["degraded"] is True
    assert snap["degraded_reason_last"] == "auth_unstable"


def test_consecutive_failures_trip_breaker_and_recover(monkeypatch):
    gate = _fresh_gate(monkeypatch)

    def _fail(c, t, **kwargs):
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
    monkeypatch.setattr(srv, "safe_get_chain", lambda c, t, **kwargs: "OK")
    srv._gated_safe_get_chain(None, "ZZOK", strike_count=5)
    assert gate.snapshot()["consecutive_failures"] == 0


def test_coalesced_waiters_receive_owner_exception(monkeypatch):
    _fresh_gate(monkeypatch)
    started = threading.Event()

    def _slow_boom(c, t, **kwargs):
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
    monkeypatch.setattr(srv, "safe_get_chain", lambda c, t, **kwargs: "OK")
    srv._gated_safe_get_chain(None, "ZZCL", strike_count=5)
    with srv._chain_inflight_lock:
        assert "ZZCL" not in srv._chain_inflight


def test_no_deadlock_under_mixed_load(monkeypatch):
    _fresh_gate(monkeypatch)
    monkeypatch.setattr(
        srv, "safe_get_chain",
        lambda c, t, **kwargs: (time.sleep(0.05), f"R_{t}")[1],
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
