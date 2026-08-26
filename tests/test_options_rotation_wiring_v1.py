"""The core+rotating coverage architecture is RUNNING, not merely present in code.

WHAT WAS WRONG. options_stream_subscription.py defined RotationPolicy, rotation_cohort() and
split_budget(), and NOTHING in production imported them. order_flow_streaming did ONE selection
at stream start, subscribed the whole budget once, opened coverage epochs once, and never
rotated. So the enrolled universe outside the core was permanently unobserved while the code
that would have rotated it sat there looking finished.

WHAT THESE TESTS HOLD:
  * CORE coverage is CONTINUOUS — a core underlying is never unsubscribed at a slice boundary,
    because its history is the money path and must not be sampled.
  * ROTATION is DETERMINISTIC — the cohort is a pure function of the clock and the roster, so a
    replay can reconstruct which underlyings were eligible at a past instant from those two
    alone, and two processes agree without coordinating.
  * COVERAGE IS UNIVERSAL WITHIN A BOUNDED GAP — every non-core underlying gets a real turn
    within full_cycle_slices. Rotation does not claim simultaneous coverage; it claims
    eligibility with a KNOWN gap, and the gap is asserted here rather than hoped for.
  * THE RECONCILER TOUCHES ONLY THE DELTA, and orders vendor calls against the coverage record
    so the record can never claim observability the account did not have.
  * THE BUDGET IS NEVER EXCEEDED — options must not crowd out the equity/book stream the
    console actually depends on.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from options_stream_subscription import (  # noqa: E402
    RotationPolicy,
    contract_budget_from_key_limit,
    rotation_cohort,
    split_budget,
)

UNIVERSE = [f"T{i:02d}" for i in range(58)] + ["SPY", "QQQ", "IWM"]


# ── the coverage math ───────────────────────────────────────────────────────────────────────

def test_core_is_eligible_in_every_slice():
    """Continuous, not sampled. A core name absent from any slice is a hole in the money path."""
    pol = RotationPolicy()
    for i in range(40):
        c = rotation_cohort(UNIVERSE, i * pol.slice_seconds + 1.0, pol)
        for name in pol.core:
            if name in UNIVERSE:
                assert name in c["eligible"], f"{name} dropped out of slice {c['slice_index']}"


def test_the_cohort_is_a_pure_function_of_the_clock():
    """Two processes must agree on a past instant without coordinating — replay depends on it."""
    pol = RotationPolicy()
    for t in (0.0, 1.0, 12_345.0, 1_787_000_000.0):
        a = rotation_cohort(UNIVERSE, t, pol)
        b = rotation_cohort(list(reversed(UNIVERSE)), t, pol)
        assert a["rotating"] == b["rotating"], "cohort depends on roster ORDER, not just membership"
        assert a["slice_index"] == b["slice_index"]


def test_every_non_core_underlying_gets_a_turn_within_the_declared_cycle():
    """THE UNIVERSALITY CLAIM, asserted rather than assumed.

    The gap is bounded and REPORTED (full_cycle_slices); this proves the report is true.
    """
    pol = RotationPolicy()
    first = rotation_cohort(UNIVERSE, 0.0, pol)
    cycle = first["full_cycle_slices"]
    assert cycle > 1, "the fixture does not exercise rotation — everything fits in one slice"
    seen: set[str] = set()
    for i in range(cycle):
        seen |= set(rotation_cohort(UNIVERSE, i * pol.slice_seconds + 1.0, pol)["rotating"])
    non_core = set(UNIVERSE) - set(pol.core)
    missing = sorted(non_core - seen)
    assert not missing, (
        f"{len(missing)} underlying(s) never appear in a full cycle of {cycle} slices: "
        f"{missing[:8]} — coverage is not universal and the reported cycle is a false claim")


def test_consecutive_slices_actually_advance():
    """A rotation that returns the same cohort forever is a fixed sliver wearing a policy."""
    pol = RotationPolicy()
    a = rotation_cohort(UNIVERSE, 0.0, pol)["rotating"]
    b = rotation_cohort(UNIVERSE, pol.slice_seconds + 1.0, pol)["rotating"]
    assert a != b, "the cohort did not change across a slice boundary"


def test_the_budget_reserves_depth_for_core_and_never_exceeds_capacity():
    pol = RotationPolicy()
    budget = contract_budget_from_key_limit(equity_symbols=1, book_enabled=True)
    total = budget["contracts_allowed"]
    split = split_budget(total, n_core=3, n_rotating=pol.rotating_per_slice, policy=pol)
    assert split["core"] + split["rotating"] <= total, "the split spends more than the budget"
    assert split["core"] > 0, "core received no budget, so its depth collapses"
    assert split["rotating"] > 0, "the cohort received no budget, so nothing rotates"


def test_more_equity_symbols_shrink_the_options_budget():
    """Options can never crowd out the stream the console depends on."""
    a = contract_budget_from_key_limit(equity_symbols=1, book_enabled=True)["contracts_allowed"]
    b = contract_budget_from_key_limit(equity_symbols=40, book_enabled=True)["contracts_allowed"]
    assert b < a, "the options ceiling ignores the keys the equity path is holding"


# ── the reconciler ──────────────────────────────────────────────────────────────────────────

class _Recorder:
    """Records the ORDER of vendor calls and coverage writes."""

    def __init__(self):
        self.events: list[tuple] = []

    async def subscribe(self, _sc, symbols, **_kw):
        self.events.append(("subscribe", tuple(symbols)))
        return {"level_one": True, "book": True, "errors": []}

    async def unsubscribe(self, _sc, symbols, **_kw):
        self.events.append(("unsubscribe", tuple(symbols)))
        return {"ok": True}

    def open_epochs(self, _db, symbols, **kw):
        self.events.append(("open_epochs", tuple(symbols), kw.get("service")))

    def close_epochs(self, _db, symbols, **kw):
        self.events.append(("close_epochs", tuple(symbols), kw.get("service")))

    def kinds(self) -> list[str]:
        return [e[0] for e in self.events]


@pytest.fixture()
def wired(monkeypatch):
    """Drive _apply_options_slice with fakes; no vendor, no database, no stream."""
    import calibration.options_stream_coverage as cov
    import options_stream_subscription as sub
    import order_flow_streaming as ofs

    rec = _Recorder()
    monkeypatch.setattr(sub, "subscribe_options", rec.subscribe, raising=False)
    monkeypatch.setattr(sub, "unsubscribe_options", rec.unsubscribe, raising=False)
    monkeypatch.setattr(cov, "open_epochs", rec.open_epochs, raising=False)
    monkeypatch.setattr(cov, "close_epochs", rec.close_epochs, raising=False)
    monkeypatch.setattr(ofs, "_options_subscribed_syms", [], raising=False)
    monkeypatch.setattr(ofs, "_subscribed_equity_syms", ["SPY"], raising=False)
    return ofs, rec


def _plan(monkeypatch, ofs, symbols, **extra):
    plan = {"at_epoch_s": 0.0, "slice_index": 1, "slice_seconds": 900,
            "core": ["SPY"], "rotating": ["T01"], "non_core_total": 58,
            "full_cycle_slices": 8, "full_cycle_seconds": 7200,
            "budget": {"contracts_allowed": 200}, "split": {"core": 100, "rotating": 100},
            "symbols": list(symbols), "per_underlying": {}, "notes": [], "policy": "test"}
    plan.update(extra)
    monkeypatch.setattr(ofs, "options_desired_for_slice", lambda *a, **k: plan, raising=False)
    return plan


def test_the_reconciler_subscribes_only_what_is_new(wired, monkeypatch):
    ofs, rec = wired
    _plan(monkeypatch, ofs, ["A", "B"])
    asyncio.run(ofs._apply_options_slice(object(), 0.0, "stream_start"))
    assert ("subscribe", ("A", "B")) in rec.events
    rec.events.clear()
    _plan(monkeypatch, ofs, ["B", "C"])          # A leaves, C arrives, B stays
    asyncio.run(ofs._apply_options_slice(object(), 900.0, "rotation"))
    assert ("unsubscribe", ("A",)) in rec.events, "a departing contract was not unsubscribed"
    assert ("subscribe", ("C",)) in rec.events, "an arriving contract was not subscribed"
    assert not any(e[0] == "subscribe" and "B" in e[1] for e in rec.events), (
        "a contract that stayed was re-subscribed — churn the vendor did not need")


def test_core_is_never_unsubscribed_across_a_boundary(wired, monkeypatch):
    """Continuity, driven through the real reconciler rather than argued about."""
    ofs, rec = wired
    _plan(monkeypatch, ofs, ["SPY_C", "T01_C"])
    asyncio.run(ofs._apply_options_slice(object(), 0.0, "stream_start"))
    rec.events.clear()
    _plan(monkeypatch, ofs, ["SPY_C", "T02_C"])   # same core symbol, cohort advances
    asyncio.run(ofs._apply_options_slice(object(), 900.0, "rotation"))
    unsub = [s for e in rec.events if e[0] == "unsubscribe" for s in e[1]]
    assert "SPY_C" not in unsub, "a core contract was unsubscribed at a slice boundary"
    assert "T01_C" in unsub, "the departing cohort contract was not unsubscribed"


def test_the_vendor_call_precedes_the_coverage_write(wired, monkeypatch):
    """ORDERING. The record must never claim observability the account did not have.

    unsubscribe BEFORE close (nothing can arrive inside a window the record says was shut),
    subscribe BEFORE open (never claim coverage the vendor may not have granted).
    """
    ofs, rec = wired
    _plan(monkeypatch, ofs, ["A"])
    asyncio.run(ofs._apply_options_slice(object(), 0.0, "stream_start"))
    rec.events.clear()
    _plan(monkeypatch, ofs, ["B"])
    asyncio.run(ofs._apply_options_slice(object(), 900.0, "rotation"))
    k = rec.kinds()
    assert k.index("unsubscribe") < k.index("close_epochs"), (
        "an epoch was closed before the vendor unsubscribed — frames could land inside a "
        "window the coverage record says was shut")
    assert k.index("subscribe") < k.index("open_epochs"), (
        "an epoch was opened before the vendor accepted the subscribe — that claims coverage "
        "the account may never have been granted")


def test_a_failed_unsubscribe_keeps_the_record_matching_reality(wired, monkeypatch):
    """The SAFE failure is staying subscribed; closing the epoch anyway would be a false gap."""
    ofs, rec = wired
    import options_stream_subscription as sub

    _plan(monkeypatch, ofs, ["A"])
    asyncio.run(ofs._apply_options_slice(object(), 0.0, "stream_start"))
    rec.events.clear()

    async def _boom(*_a, **_k):
        raise RuntimeError("vendor refused")

    monkeypatch.setattr(sub, "unsubscribe_options", _boom, raising=False)
    _plan(monkeypatch, ofs, ["B"])
    asyncio.run(ofs._apply_options_slice(object(), 900.0, "rotation"))
    assert "close_epochs" not in rec.kinds(), (
        "an epoch was closed for a contract that is still subscribed — the record would show a "
        "gap that did not happen")
    assert "A" in ofs._options_subscribed_syms, "the still-subscribed contract was forgotten"


def test_the_slice_record_makes_rotation_observable(wired, monkeypatch):
    """Frames arriving proves collection. Only this proves the ROTATION is advancing."""
    ofs, rec = wired
    _plan(monkeypatch, ofs, ["A"], slice_index=7)
    asyncio.run(ofs._apply_options_slice(object(), 0.0, "rotation"))
    st = ofs.options_stream_status()
    assert st.get("last_slice"), "options_stream_status exposes no slice record"
    assert st["last_slice"]["slice_index"] == 7
    assert "rotation_running" in st, "an operator cannot tell whether rotation is alive"


# ── the wiring itself ───────────────────────────────────────────────────────────────────────

def test_production_actually_imports_the_rotation_machinery():
    """THE ORIGINAL DEFECT. rotation_cohort/split_budget existed and nothing used them."""
    import ast

    src = (REPO / "order_flow_streaming.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and (n.module or "").endswith("options_stream_subscription"):
            imported |= {a.name for a in n.names}
    for required in ("rotation_cohort", "split_budget", "RotationPolicy", "unsubscribe_options"):
        assert required in imported, (
            f"production never imports {required} — the rotation architecture is present in "
            f"code and absent from the running system")


def test_start_and_rotation_share_one_reconciler():
    """ONE FAUCET: start-up and steady state must not be able to drift apart."""
    import ast

    src = (REPO / "order_flow_streaming.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    callers: set[str] = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for c in ast.walk(fn):
            if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_apply_options_slice":
                callers.add(fn.name)
    assert {"_start_options_collection", "_options_rotation_loop"} <= callers, (
        f"start-up and rotation do not both go through _apply_options_slice: {sorted(callers)}")


def test_the_rotation_task_is_cancelled_on_teardown():
    src = (REPO / "order_flow_streaming.py").read_text(encoding="utf-8")
    i = src.find("def _stop_options_collection")
    block = src[i:i + 1200]
    assert "_options_rotation_task" in block and "cancel()" in block, (
        "the rotation task is not cancelled on teardown — it would keep subscribing against a "
        "client being torn down")
