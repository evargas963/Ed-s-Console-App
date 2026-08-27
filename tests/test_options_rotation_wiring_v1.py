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


# ── USEFUL depth, not merely rotating ───────────────────────────────────────────────────────
#
# The operator asked for rotating USEFUL-DEPTH coverage. A rotation that turns but hands each
# name a sliver is the same permanent-sliver failure it was built to end, wearing the policy's
# name. MEASURED against real production chains with the ceiling lifted, select_contracts
# returns 32 contracts for 49 of the 55 enrolled names with a fresh chain — so 32 is what an
# underlying costs to describe, and the fixed rotating_per_slice=8 delivered 119//8 = 14.

def test_the_fixed_cohort_size_would_have_delivered_a_sliver():
    """The defect, kept as a measurement so the fix cannot be quietly reverted."""
    pol = RotationPolicy()
    budget = contract_budget_from_key_limit(equity_symbols=1, book_enabled=True)
    sp = split_budget(budget["contracts_allowed"], 3, 8, pol)
    each_at_fixed_8 = sp["rotating"] // 8
    assert each_at_fixed_8 < pol.useful_depth_contracts, (
        f"the fixture no longer reproduces the defect: a fixed 8-per-slice gives "
        f"{each_at_fixed_8}, which already meets the {pol.useful_depth_contracts} target")


def test_the_derived_cohort_delivers_at_least_useful_depth():
    """Depth is the invariant; the cohort size is what gives way."""
    pol = RotationPolicy()
    for book in (True, False):
        budget = contract_budget_from_key_limit(equity_symbols=1, book_enabled=book)
        provisional = split_budget(budget["contracts_allowed"], 3, pol.rotating_per_slice, pol)
        n = pol.cohort_size_for_budget(provisional["rotating"])
        final = split_budget(budget["contracts_allowed"], 3, n, pol)
        each = final["rotating"] // max(1, n)
        assert each >= pol.useful_depth_contracts, (
            f"book_enabled={book}: each rotating name gets {each} contracts, below the measured "
            f"useful depth of {pol.useful_depth_contracts} — this is a sliver, not coverage")


def test_the_cohort_size_never_collapses_to_zero():
    """A tiny budget must still rotate ONE name rather than silently stopping."""
    pol = RotationPolicy()
    for tiny in (0, 1, 5, 31):
        assert pol.cohort_size_for_budget(tiny) >= 1, (
            f"a rotating budget of {tiny} produced a cohort of zero — rotation would halt")


def test_the_plan_reports_the_depth_it_actually_delivers(monkeypatch):
    """The gap must be a KNOWN quantity, visible in the slice record."""
    import order_flow_streaming as ofs

    monkeypatch.setattr(ofs, "_subscribed_equity_syms", ["SPY"], raising=False)
    plan = ofs.options_desired_for_slice(0.0, equity_symbols=1, book_enabled=True)
    for key in ("useful_depth_contracts", "rotating_depth_each", "rotating_per_slice",
                "full_cycle_seconds"):
        assert key in plan, f"the slice plan does not report {key}"
    if plan["rotating"]:
        assert plan["rotating_depth_each"] >= plan["useful_depth_contracts"], (
            f"the plan delivers {plan['rotating_depth_each']} per rotating name against a "
            f"{plan['useful_depth_contracts']} target")


# ── SUBS replaces, ADD extends: the vendor set must survive rotation ─────────────────────────
#
# Verified against the installed schwab-py: level_one_option_subs / options_book_subs issue the
# streaming command 'SUBS', level_one_option_add / options_book_add issue 'ADD'. In the Schwab
# protocol a SUBS sends the whole key list and REPLACES that service's subscription set. These
# controls run the REAL subscribe_options / unsubscribe_options and _apply_options_slice against
# a fake client that models exactly that per-service state machine — no monkeypatched helpers.


class _VendorState:
    """A StreamClient that models the real SUBS/ADD/UNSUBS semantics per service.

    SUBS replaces the service's key set; ADD appends; UNSUBS removes. This is the behaviour the
    reconciler must respect, so the fake enforces it and the test reads the resulting set.
    """

    class LevelOneOptionFields:
        @staticmethod
        def all_fields():
            return list(range(56))

    def __init__(self, refuse_subs=(), refuse_add=(), refuse_unsub=()):
        self.lvl: set[str] = set()
        self.book: set[str] = set()
        self.refuse_subs = set(refuse_subs)
        self.refuse_add = set(refuse_add)
        self.refuse_unsub = set(refuse_unsub)
        self.ops: list[tuple] = []

    async def level_one_option_subs(self, syms, fields=None):
        self.ops.append(("LEVELONE_OPTIONS", "SUBS", tuple(syms)))
        if "LEVELONE_OPTIONS" in self.refuse_subs:
            raise RuntimeError("SUBS refused")
        self.lvl = set(syms)

    async def level_one_option_add(self, syms, fields=None):
        self.ops.append(("LEVELONE_OPTIONS", "ADD", tuple(syms)))
        if "LEVELONE_OPTIONS" in self.refuse_add:
            raise RuntimeError("ADD refused")
        self.lvl |= set(syms)

    async def level_one_option_unsubs(self, syms):
        self.ops.append(("LEVELONE_OPTIONS", "UNSUBS", tuple(syms)))
        if "LEVELONE_OPTIONS" in self.refuse_unsub:
            raise RuntimeError("UNSUBS refused")
        self.lvl -= set(syms)

    async def options_book_subs(self, syms):
        self.ops.append(("OPTIONS_BOOK", "SUBS", tuple(syms)))
        if "OPTIONS_BOOK" in self.refuse_subs:
            raise RuntimeError("SUBS refused")
        self.book = set(syms)

    async def options_book_add(self, syms):
        self.ops.append(("OPTIONS_BOOK", "ADD", tuple(syms)))
        if "OPTIONS_BOOK" in self.refuse_add:
            raise RuntimeError("ADD refused")
        self.book |= set(syms)

    async def options_book_unsubs(self, syms):
        self.ops.append(("OPTIONS_BOOK", "UNSUBS", tuple(syms)))
        if "OPTIONS_BOOK" in self.refuse_unsub:
            raise RuntimeError("UNSUBS refused")
        self.book -= set(syms)


def _wire_real_helpers(monkeypatch):
    """Wire the REAL subscribe/unsubscribe helpers; only epochs and locks are stubbed."""
    import calibration.options_stream_coverage as cov
    import order_flow_streaming as ofs

    monkeypatch.setattr(cov, "open_epochs", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(cov, "close_epochs", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(ofs, "_options_subscribed",
                        {s: set() for s in ofs.OPTIONS_SERVICES}, raising=False)
    monkeypatch.setattr(ofs, "_subscribed_equity_syms", ["SPY"], raising=False)
    monkeypatch.setattr(ofs, "_stream_resubscribe_lock", None, raising=False)
    return ofs


def _plan_real(monkeypatch, ofs, symbols):
    plan = {"at_epoch_s": 0.0, "roster_ok": True, "slice_index": 1, "slice_seconds": 900,
            "core": ["SPY"], "rotating": ["T"], "non_core_total": 1, "full_cycle_slices": 1,
            "full_cycle_seconds": 900, "budget": {"contracts_allowed": 500},
            "split": {"core": 250, "rotating": 250}, "symbols": list(symbols),
            "per_underlying": {}, "notes": [], "policy": "test",
            "useful_depth_contracts": 32, "rotating_depth_each": 0, "rotating_per_slice": 1}
    monkeypatch.setattr(ofs, "options_desired_for_slice", lambda *a, **k: plan, raising=False)
    return plan


def test_repeated_subs_would_replace_the_vendor_set():
    """THE DEFECT, at the helper: a second SUBS drops what the first established."""
    import options_stream_subscription as sub

    v = _VendorState()
    asyncio.run(sub.subscribe_options(v, ["SPY", "T01"], operation="subs"))
    assert v.lvl == {"SPY", "T01"}
    asyncio.run(sub.subscribe_options(v, ["T02"], operation="subs"))
    assert v.lvl == {"T02"}, (
        "SUBS did not replace — the fixture no longer models the protocol this fix depends on")


def test_add_extends_the_vendor_set_without_replacing():
    import options_stream_subscription as sub

    v = _VendorState()
    asyncio.run(sub.subscribe_options(v, ["SPY", "T01"], operation="subs"))
    asyncio.run(sub.subscribe_options(v, ["T02"], operation="add"))
    assert v.lvl == {"SPY", "T01", "T02"}, "ADD did not extend the established set"


def test_rotation_preserves_core_at_the_vendor(monkeypatch):
    """THE DECISIVE CONTROL. Drive the real reconciler; read the real vendor set.

    A rotation that SUBBed the incoming cohort would leave the vendor holding only the cohort,
    with continuous core silently gone.
    """
    ofs = _wire_real_helpers(monkeypatch)
    v = _VendorState()

    _plan_real(monkeypatch, ofs, ["SPY", "T01"])
    asyncio.run(ofs._apply_options_slice(v, 0.0, "stream_start"))
    assert v.lvl == {"SPY", "T01"} and v.book == {"SPY", "T01"}, "establishment failed"

    _plan_real(monkeypatch, ofs, ["SPY", "T02"])         # rotate T01 -> T02, keep core SPY
    asyncio.run(ofs._apply_options_slice(v, 900.0, "rotation"))
    assert v.lvl == {"SPY", "T02"}, (
        f"LEVELONE_OPTIONS vendor set is {sorted(v.lvl)} after rotation — core SPY was dropped "
        f"or the cohort replaced everything")
    assert v.book == {"SPY", "T02"}, f"OPTIONS_BOOK vendor set wrong: {sorted(v.book)}"


def test_the_first_subscribe_uses_subs_and_later_additions_use_add(monkeypatch):
    """The operation must be SUBS to establish an empty service, ADD to extend it."""
    ofs = _wire_real_helpers(monkeypatch)
    v = _VendorState()

    _plan_real(monkeypatch, ofs, ["SPY", "T01"])
    asyncio.run(ofs._apply_options_slice(v, 0.0, "stream_start"))
    establish = [o for o in v.ops if o[0] == "LEVELONE_OPTIONS"]
    assert establish and establish[0][1] == "SUBS", (
        f"the first subscription was not a SUBS: {establish[:2]}")

    v.ops.clear()
    _plan_real(monkeypatch, ofs, ["SPY", "T02"])
    asyncio.run(ofs._apply_options_slice(v, 900.0, "rotation"))
    adds = [o for o in v.ops if o[0] == "LEVELONE_OPTIONS" and o[1] == "ADD"]
    subs = [o for o in v.ops if o[0] == "LEVELONE_OPTIONS" and o[1] == "SUBS"]
    assert adds and not subs, (
        f"a rotation that already holds core issued SUBS again: adds={adds} subs={subs}")


def test_a_service_re_establishes_with_subs_after_it_empties(monkeypatch):
    """If a service was fully unsubscribed, the next add must SUBS (its set is empty), not ADD."""
    ofs = _wire_real_helpers(monkeypatch)
    v = _VendorState()

    _plan_real(monkeypatch, ofs, ["T01"])
    asyncio.run(ofs._apply_options_slice(v, 0.0, "stream_start"))
    v.ops.clear()
    # T01 rotates entirely out and nothing replaces it this slice, emptying the service...
    _plan_real(monkeypatch, ofs, [])
    asyncio.run(ofs._apply_options_slice(v, 900.0, "rotation"))
    assert not ofs._options_subscribed["LEVELONE_OPTIONS"], "service did not empty"
    v.ops.clear()
    # ...then a later slice brings a name back: it must SUBS to re-establish.
    _plan_real(monkeypatch, ofs, ["T09"])
    asyncio.run(ofs._apply_options_slice(v, 1800.0, "rotation"))
    lvl_ops = [o for o in v.ops if o[0] == "LEVELONE_OPTIONS"]
    assert lvl_ops and lvl_ops[0][1] == "SUBS", (
        f"re-establishing an empty service did not SUBS: {lvl_ops}")
    assert v.lvl == {"T09"}


# ── actual vendor-held keys must never exceed the budget, even when unsubscribe fails ────────
#
# A Schwab key is one (service, symbol). If the vendor REFUSES to unsubscribe the old cohort,
# those contracts stay live and keep their keys, but rotation still wants to ADD the new cohort.
# Adding on top of undroppable contracts pushes |LEVELONE| + |BOOK| past the account limit and
# takes the equity stream with it. The cap must be against ACTUAL post-drop held keys.

def _key_vendor(refuse_unsub=False):
    class V(_VendorState):
        async def level_one_option_unsubs(self, syms):
            self.ops.append(("LEVELONE_OPTIONS", "UNSUBS", tuple(syms)))
            if refuse_unsub:
                raise RuntimeError("unsub refused")
            self.lvl -= set(syms)

        async def options_book_unsubs(self, syms):
            self.ops.append(("OPTIONS_BOOK", "UNSUBS", tuple(syms)))
            if refuse_unsub:
                raise RuntimeError("unsub refused")
            self.book -= set(syms)
    return V()


def _reconcile(ofs, v, symbols, reason, keys_available):
    import options_stream_subscription as sub

    plan = {"at_epoch_s": 0.0, "roster_ok": True, "slice_index": 0, "slice_seconds": 900,
            "core": ["SPY"], "rotating": [], "non_core_total": 1, "full_cycle_slices": 1,
            "full_cycle_seconds": 900, "budget": {}, "split": {}, "symbols": list(symbols),
            "per_underlying": {}, "notes": [], "policy": "p", "useful_depth_contracts": 32,
            "rotating_depth_each": 0, "rotating_per_slice": 1}
    return asyncio.run(ofs._reconcile_options_subscription(
        v, plan, list(symbols), reason, keys_available=keys_available, capture_db=None,
        close_epochs=lambda *a, **k: None, open_epochs=lambda *a, **k: None,
        subscribe_options=sub.subscribe_options, unsubscribe_options=sub.unsubscribe_options))


def test_a_failed_unsubscribe_cannot_push_vendor_keys_over_budget(monkeypatch):
    """THE CAPACITY BUG. Undroppable old cohort + fresh ADD must stay under the key ceiling."""
    ofs = _wire_real_helpers(monkeypatch)
    KEYS = 20                                        # small ceiling: 10 contracts x 2 services
    v = _key_vendor(refuse_unsub=True)

    old = ["SPY"] + [f"OLD{i}" for i in range(9)]    # 10 contracts -> 20 keys, at the ceiling
    _reconcile(ofs, v, old, "s0", KEYS)
    assert len(v.lvl) + len(v.book) == KEYS, "the fixture did not fill the ceiling"

    new = ["SPY"] + [f"NEW{i}" for i in range(9)]    # rotate all OLD out (refused), bring NEW in
    _reconcile(ofs, v, new, "s1", KEYS)
    held = len(v.lvl) + len(v.book)
    assert held <= KEYS, (
        f"vendor holds {held} keys against a ceiling of {KEYS} — a refused unsubscribe let "
        f"rotation ADD on top of stranded contracts and blow the key budget")
    assert "SPY" in v.lvl and "SPY" in v.book, "core was dropped while capping additions"


def test_repeated_failed_rotations_never_exceed_budget(monkeypatch):
    """Stranding must not accumulate past the ceiling over many failed slices."""
    ofs = _wire_real_helpers(monkeypatch)
    KEYS = 20
    v = _key_vendor(refuse_unsub=True)
    peak = 0
    for sl in range(6):
        cohort = ["SPY"] + [f"S{sl}_{i}" for i in range(9)]
        _reconcile(ofs, v, cohort, f"s{sl}", KEYS)
        peak = max(peak, len(v.lvl) + len(v.book))
    assert peak <= KEYS, f"peak vendor keys {peak} exceeded the ceiling {KEYS} across failures"
    assert "SPY" in v.lvl and "SPY" in v.book, "core lost across repeated failed rotations"


def test_a_clean_rotation_still_fills_to_the_budget(monkeypatch):
    """The cap must not starve a healthy rotation — full turnover fits when drops succeed."""
    ofs = _wire_real_helpers(monkeypatch)
    KEYS = 20
    v = _key_vendor(refuse_unsub=False)
    _reconcile(ofs, v, ["SPY"] + [f"OLD{i}" for i in range(9)], "s0", KEYS)
    _reconcile(ofs, v, ["SPY"] + [f"NEW{i}" for i in range(9)], "s1", KEYS)
    assert len(v.lvl) + len(v.book) == KEYS, "a clean rotation did not refill to the ceiling"
    assert not any(k.startswith("OLD") for k in v.lvl), "the old cohort was not released"


def test_a_partial_unsubscribe_failure_still_respects_the_key_budget(monkeypatch):
    """One service refuses to drop; its stranded keys still count against the ceiling."""
    ofs = _wire_real_helpers(monkeypatch)
    KEYS = 20

    class V(_VendorState):
        async def options_book_unsubs(self, syms):   # BOOK refuses; LEVELONE drops cleanly
            self.ops.append(("OPTIONS_BOOK", "UNSUBS", tuple(syms)))
            raise RuntimeError("book unsub refused")

    v = V()
    _reconcile(ofs, v, ["SPY"] + [f"OLD{i}" for i in range(9)], "s0", KEYS)
    _reconcile(ofs, v, ["SPY"] + [f"NEW{i}" for i in range(9)], "s1", KEYS)
    held = len(v.lvl) + len(v.book)
    assert held <= KEYS, (
        f"vendor holds {held} keys; the refused BOOK service's stranded keys were not counted")
    assert "SPY" in v.lvl and "SPY" in v.book, "core lost under a partial unsubscribe failure"


# ── planned vs actually admitted coverage must be truthful ──────────────────────────────────
#
# When the key cap admits only part of a planned rotation, last_slice must not report the
# PLANNED rotating/per_underlying as though they were actual. ADMITTED is derived from what is
# genuinely held at the vendor now.

def _partial_plan(sym_und, core, rotating, per_underlying):
    return {"at_epoch_s": 0.0, "roster_ok": True, "slice_index": 3, "slice_seconds": 900,
            "core": core, "rotating": rotating, "non_core_total": len(rotating),
            "full_cycle_slices": 1, "full_cycle_seconds": 900, "budget": {}, "split": {},
            "symbols": list(sym_und), "per_underlying": per_underlying,
            "symbol_underlying": dict(sym_und), "notes": [], "policy": "p",
            "useful_depth_contracts": 2, "rotating_depth_each": 2, "rotating_per_slice": 2}


def test_last_slice_reports_admitted_not_planned_when_the_cap_bites(monkeypatch):
    """THE REPORTING BUG. Planned coverage was claimed as actual under a partial cap."""
    import options_stream_subscription as sub

    ofs = _wire_real_helpers(monkeypatch)
    v = _VendorState()
    sym_und = {"SPY1": "SPY", "SPY2": "SPY", "AMD1": "AMD", "AMD2": "AMD",
               "TSLA1": "TSLA", "TSLA2": "TSLA"}
    plan = _partial_plan(sym_und, ["SPY"], ["AMD", "TSLA"], {"SPY": 2, "AMD": 2, "TSLA": 2})
    # ceiling 6 keys = 3 contracts x 2 services; core-first, so SPY(2) + one AMD survive.
    asyncio.run(ofs._reconcile_options_subscription(
        v, plan, list(sym_und), "rotation", keys_available=6, capture_db=None,
        close_epochs=lambda *a, **k: None, open_epochs=lambda *a, **k: None,
        subscribe_options=sub.subscribe_options, unsubscribe_options=sub.unsubscribe_options))
    ls = ofs._options_last_slice

    assert ls["rotating_planned"] == ["AMD", "TSLA"], "planned rotating was not preserved"
    assert ls["per_underlying_planned"] == {"SPY": 2, "AMD": 2, "TSLA": 2}
    # ...and the admitted values tell the truth about what actually got on.
    assert "TSLA" not in ls["rotating_admitted"], (
        f"TSLA was reported admitted but the cap left no room: {ls['rotating_admitted']}")
    assert ls["per_underlying_admitted"].get("TSLA", 0) == 0, "TSLA has no admitted contracts"
    assert ls["per_underlying_admitted"].get("SPY") == 2, "core SPY was not fully admitted"
    assert ls["fully_admitted"] is False, "a partially-admitted slice claimed full admission"
    # planned and admitted must actually differ here, or the test proves nothing.
    assert ls["rotating_admitted"] != ls["rotating_planned"]


def test_a_fully_admitted_slice_marks_itself_fully_admitted(monkeypatch):
    """When everything fits, planned == admitted and fully_admitted is True."""
    import options_stream_subscription as sub

    ofs = _wire_real_helpers(monkeypatch)
    v = _VendorState()
    sym_und = {"SPY1": "SPY", "AMD1": "AMD"}
    plan = _partial_plan(sym_und, ["SPY"], ["AMD"], {"SPY": 1, "AMD": 1})
    asyncio.run(ofs._reconcile_options_subscription(
        v, plan, list(sym_und), "rotation", keys_available=100, capture_db=None,
        close_epochs=lambda *a, **k: None, open_epochs=lambda *a, **k: None,
        subscribe_options=sub.subscribe_options, unsubscribe_options=sub.unsubscribe_options))
    ls = ofs._options_last_slice
    assert ls["fully_admitted"] is True, "a fully-admitted slice was not marked so"
    assert sorted(ls["rotating_admitted"]) == ["AMD"]
    assert ls["per_underlying_admitted"] == {"SPY": 1, "AMD": 1}


def test_a_partial_subscribe_failure_shows_in_admitted_coverage(monkeypatch):
    """Admitted must reflect vendor refusals too, not only the key cap."""
    import options_stream_subscription as sub

    ofs = _wire_real_helpers(monkeypatch)

    class V(_VendorState):
        async def options_book_subs(self, syms):     # BOOK refuses; LEVELONE accepts
            self.ops.append(("OPTIONS_BOOK", "SUBS", tuple(syms)))
            raise RuntimeError("book refused")

    v = V()
    sym_und = {"AMD1": "AMD"}
    plan = _partial_plan(sym_und, [], ["AMD"], {"AMD": 1})
    asyncio.run(ofs._reconcile_options_subscription(
        v, plan, ["AMD1"], "rotation", keys_available=100, capture_db=None,
        close_epochs=lambda *a, **k: None, open_epochs=lambda *a, **k: None,
        subscribe_options=sub.subscribe_options, unsubscribe_options=sub.unsubscribe_options))
    ls = ofs._options_last_slice
    # AMD1 is held on LEVELONE only, so it IS observed and counts as admitted once.
    assert ls["per_underlying_admitted"].get("AMD") == 1
    assert ls["services_in_agreement"] is False, "one service refused; agreement should be False"


def test_a_stranded_symbol_from_a_prior_slice_still_counts_as_coverage(monkeypatch):
    """An UNDROPPABLE held symbol not in THIS plan's map is recovered from the option root.

    It rotated out of the plan but the vendor refused to unsubscribe it, so it is still live and
    still real coverage — its underlying must be counted even though this plan never named it.
    """
    import options_stream_subscription as sub

    ofs = _wire_real_helpers(monkeypatch)

    class V(_VendorState):
        async def level_one_option_unsubs(self, syms):   # refuse: the contract strands
            self.ops.append(("LEVELONE_OPTIONS", "UNSUBS", tuple(syms)))
            raise RuntimeError("unsub refused")

    v = V()
    v.lvl = {"XOM   260828C00070000"}
    ofs._options_subscribed = {"LEVELONE_OPTIONS": {"XOM   260828C00070000"},
                               "OPTIONS_BOOK": set()}
    sym_und = {"AMD1": "AMD"}                              # this plan does not mention XOM
    plan = _partial_plan(sym_und, [], ["AMD"], {"AMD": 1})
    asyncio.run(ofs._reconcile_options_subscription(
        v, plan, ["AMD1"], "rotation", keys_available=100, capture_db=None,
        close_epochs=lambda *a, **k: None, open_epochs=lambda *a, **k: None,
        subscribe_options=sub.subscribe_options, unsubscribe_options=sub.unsubscribe_options))
    ls = ofs._options_last_slice
    assert ls["per_underlying_admitted"].get("XOM") == 1, (
        f"an undroppable XOM contract was not counted as real coverage: "
        f"{ls['per_underlying_admitted']}")


# ── the roster must fail explicit, not open ─────────────────────────────────────────────────

def test_roster_failure_produces_no_symbols_not_a_fresh_chain_fallback(monkeypatch):
    """A failed roster read must NOT fall back to the nondeterministic fresh-chain universe."""
    import order_flow_streaming as ofs

    class _Fail:
        def logging_universe_authoritative_tickers(self):
            raise RuntimeError("db locked")

    monkeypatch.setattr("db.get_db", lambda: _Fail(), raising=False)
    monkeypatch.setattr(ofs, "_subscribed_equity_syms", ["SPY"], raising=False)
    plan = ofs.options_desired_for_slice(1_787_000_000.0, equity_symbols=1)
    assert plan["roster_ok"] is False, "a failed roster read was not flagged"
    assert plan["symbols"] == [], (
        "a failed roster read still produced a symbol plan — it fell back to the fresh-chain "
        "universe this fix proved reshuffles cohorts")
    assert any("roster unavailable" in n for n in plan["notes"])


def test_empty_roster_is_treated_as_failure_not_an_empty_universe(monkeypatch):
    import order_flow_streaming as ofs

    class _Empty:
        def logging_universe_authoritative_tickers(self):
            return []

    monkeypatch.setattr("db.get_db", lambda: _Empty(), raising=False)
    monkeypatch.setattr(ofs, "_subscribed_equity_syms", ["SPY"], raising=False)
    plan = ofs.options_desired_for_slice(1_787_000_000.0, equity_symbols=1)
    assert plan["roster_ok"] is False and plan["symbols"] == []


def test_roster_failure_holds_the_subscription_unchanged(monkeypatch):
    """THE SAFETY PROPERTY. A transient DB hiccup must not UNSUB continuous core."""
    ofs = _wire_real_helpers(monkeypatch)

    class _Fail:
        def logging_universe_authoritative_tickers(self):
            raise RuntimeError("db locked")

    monkeypatch.setattr("db.get_db", lambda: _Fail(), raising=False)
    ofs._options_subscribed = {"LEVELONE_OPTIONS": {"SPY", "T01"}, "OPTIONS_BOOK": {"SPY"}}
    v = _VendorState()
    v.lvl, v.book = {"SPY", "T01"}, {"SPY"}
    before = ({k: set(x) for k, x in ofs._options_subscribed.items()}, set(v.lvl), set(v.book))
    res = asyncio.run(ofs._apply_options_slice(v, 1_787_000_000.0, "rotation"))
    after = ({k: set(x) for k, x in ofs._options_subscribed.items()}, set(v.lvl), set(v.book))
    assert res.get("roster_ok") is False
    assert before == after, "a roster failure disturbed the live subscription"
    assert not v.ops, f"the reconciler issued vendor calls on a roster failure: {v.ops}"


# ── the reconciler ──────────────────────────────────────────────────────────────────────────

class _Recorder:
    """Records the ORDER of vendor calls and coverage writes, with REAL receipt shapes.

    The production helpers report failure in the RECEIPT and do not raise — subscribe_options
    catches per service and returns {level_one, book, errors}, and unsubscribe_options did the
    same and never raised at all. Negative controls that inject exceptions therefore test a
    path the vendor never takes; these return receipts instead.

    `refuse` names the services whose calls come back NOT acknowledged.
    """

    def __init__(self, refuse_subscribe=(), refuse_unsubscribe=()):
        self.events: list[tuple] = []
        self.refuse_sub = set(refuse_subscribe)
        self.refuse_unsub = set(refuse_unsubscribe)

    async def subscribe(self, _sc, symbols, *, level_one=True, book=True, **_kw):
        service = "LEVELONE_OPTIONS" if level_one else "OPTIONS_BOOK"
        self.events.append(("subscribe", tuple(symbols), service))
        ok = service not in self.refuse_sub
        key = "level_one" if level_one else "book"
        r = {"requested": len(list(symbols)), "level_one": None, "book": None, "errors": []}
        if ok:
            r[key] = {"symbols": len(list(symbols))}
        else:
            r["errors"].append(f"{service}: refused by fixture")
        return r

    async def unsubscribe(self, _sc, symbols, **_kw):
        self.events.append(("unsubscribe", tuple(symbols)))
        return {"requested": len(list(symbols)),
                "level_one": "LEVELONE_OPTIONS" not in self.refuse_unsub,
                "book": "OPTIONS_BOOK" not in self.refuse_unsub,
                "errors": [f"{s}: refused by fixture" for s in self.refuse_unsub]}

    def open_epochs(self, _db, symbols, **kw):
        self.events.append(("open_epochs", tuple(symbols), kw.get("service")))

    def close_epochs(self, _db, symbols, **kw):
        self.events.append(("close_epochs", tuple(symbols), kw.get("service")))

    def kinds(self) -> list[str]:
        return [e[0] for e in self.events]


def _wire(monkeypatch, rec):
    import calibration.options_stream_coverage as cov
    import options_stream_subscription as sub
    import order_flow_streaming as ofs

    monkeypatch.setattr(sub, "subscribe_options", rec.subscribe, raising=False)
    monkeypatch.setattr(sub, "unsubscribe_options", rec.unsubscribe, raising=False)
    monkeypatch.setattr(cov, "open_epochs", rec.open_epochs, raising=False)
    monkeypatch.setattr(cov, "close_epochs", rec.close_epochs, raising=False)
    monkeypatch.setattr(ofs, "_options_subscribed",
                        {s: set() for s in ofs.OPTIONS_SERVICES}, raising=False)
    monkeypatch.setattr(ofs, "_subscribed_equity_syms", ["SPY"], raising=False)
    monkeypatch.setattr(ofs, "_stream_resubscribe_lock", None, raising=False)
    return ofs, rec


@pytest.fixture()
def wired(monkeypatch):
    """Drive _apply_options_slice with fakes; no vendor, no database, no stream."""
    return _wire(monkeypatch, _Recorder())


def _plan(monkeypatch, ofs, symbols, **extra):
    plan = {"at_epoch_s": 0.0, "slice_index": 1, "slice_seconds": 900,
            "core": ["SPY"], "rotating": ["T01"], "non_core_total": 58,
            "full_cycle_slices": 8, "full_cycle_seconds": 7200,
            "budget": {"contracts_allowed": 200}, "split": {"core": 100, "rotating": 100},
            "symbols": list(symbols), "per_underlying": {}, "notes": [], "policy": "test"}
    plan.update(extra)
    monkeypatch.setattr(ofs, "options_desired_for_slice", lambda *a, **k: plan, raising=False)
    return plan


def _subscribed_syms(events):
    return {s for e in events if e[0] == "subscribe" for s in e[1]}


def test_the_reconciler_subscribes_only_what_is_new(wired, monkeypatch):
    ofs, rec = wired
    _plan(monkeypatch, ofs, ["A", "B"])
    asyncio.run(ofs._apply_options_slice(object(), 0.0, "stream_start"))
    assert _subscribed_syms(rec.events) == {"A", "B"}
    rec.events.clear()
    _plan(monkeypatch, ofs, ["B", "C"])          # A leaves, C arrives, B stays
    asyncio.run(ofs._apply_options_slice(object(), 900.0, "rotation"))
    unsub = {s for e in rec.events if e[0] == "unsubscribe" for s in e[1]}
    assert "A" in unsub, "a departing contract was not unsubscribed"
    assert "C" in _subscribed_syms(rec.events), "an arriving contract was not subscribed"
    assert "B" not in _subscribed_syms(rec.events), (
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


def test_an_unacknowledged_unsubscribe_keeps_the_contract_and_its_epoch(monkeypatch):
    """THE KEY-LEAK DEFECT, driven by a RECEIPT rather than an exception.

    unsubscribe_options never raises — it catches per service and reports in the receipt. An
    earlier reconciler wrapped it in try/except, so the except could not fire: it closed the
    epoch and dropped the contract while the contract stayed LIVE at the vendor, still sending
    frames the record placed outside any epoch and still holding a Schwab KEY nothing would
    ever release. Rotations leak keys until the account passes its limit and the EQUITY stream
    is refused.
    """
    ofs, rec = _wire(monkeypatch, _Recorder(refuse_unsubscribe=("LEVELONE_OPTIONS",
                                                               "OPTIONS_BOOK")))
    _plan(monkeypatch, ofs, ["A"])
    asyncio.run(ofs._apply_options_slice(object(), 0.0, "stream_start"))
    rec.events.clear()
    _plan(monkeypatch, ofs, ["B"])
    asyncio.run(ofs._apply_options_slice(object(), 900.0, "rotation"))

    assert "close_epochs" not in rec.kinds(), (
        "an epoch was closed for a contract the vendor did NOT release — the record would show "
        "a gap that did not happen while frames kept arriving")
    for svc in ofs.OPTIONS_SERVICES:
        assert "A" in ofs._options_subscribed[svc], (
            f"{svc}: the still-subscribed contract was forgotten — its vendor key is now "
            f"unaccounted for and will never be released")


def test_a_partly_acknowledged_unsubscribe_releases_only_that_service(monkeypatch):
    """Services fail independently; releasing the union would forget a live key."""
    ofs, rec = _wire(monkeypatch, _Recorder(refuse_unsubscribe=("OPTIONS_BOOK",)))
    _plan(monkeypatch, ofs, ["A"])
    asyncio.run(ofs._apply_options_slice(object(), 0.0, "stream_start"))
    rec.events.clear()
    _plan(monkeypatch, ofs, ["B"])
    asyncio.run(ofs._apply_options_slice(object(), 900.0, "rotation"))

    assert "A" not in ofs._options_subscribed["LEVELONE_OPTIONS"], (
        "the acknowledged service did not release the contract")
    assert "A" in ofs._options_subscribed["OPTIONS_BOOK"], (
        "the REFUSED service released the contract anyway — its key is now unaccounted for")
    closed = [e for e in rec.events if e[0] == "close_epochs"]
    assert closed and all(e[2] == "LEVELONE_OPTIONS" for e in closed), (
        f"an epoch was closed for a service that did not acknowledge: {closed}")


def test_a_partial_subscribe_is_not_recorded_as_fully_subscribed(monkeypatch):
    """The RETRY defect. A refused service must stay out of the set so the next slice tries it."""
    ofs, rec = _wire(monkeypatch, _Recorder(refuse_subscribe=("OPTIONS_BOOK",)))
    _plan(monkeypatch, ofs, ["A"])
    asyncio.run(ofs._apply_options_slice(object(), 0.0, "stream_start"))

    assert "A" in ofs._options_subscribed["LEVELONE_OPTIONS"], "the accepted service was lost"
    assert "A" not in ofs._options_subscribed["OPTIONS_BOOK"], (
        "a REFUSED subscribe was recorded as subscribed — the service will never be retried "
        "and the coverage record claims a book we do not have")
    opened = [e for e in rec.events if e[0] == "open_epochs"]
    assert opened and all(e[2] == "LEVELONE_OPTIONS" for e in opened), (
        f"an epoch was opened for a service the vendor refused: {opened}")


def test_the_refused_service_is_retried_on_the_next_slice(monkeypatch):
    """Retry is the whole point of keeping it out of the set."""
    rec = _Recorder(refuse_subscribe=("OPTIONS_BOOK",))
    ofs, _ = _wire(monkeypatch, rec)
    _plan(monkeypatch, ofs, ["A"])
    asyncio.run(ofs._apply_options_slice(object(), 0.0, "stream_start"))
    rec.refuse_sub.clear()                       # the vendor recovers
    rec.events.clear()
    _plan(monkeypatch, ofs, ["A"])               # same want-set, nothing rotated
    asyncio.run(ofs._apply_options_slice(object(), 900.0, "rotation"))

    retried = [e for e in rec.events if e[0] == "subscribe" and e[2] == "OPTIONS_BOOK"]
    assert retried, "the previously refused service was never retried"
    assert "A" in ofs._options_subscribed["OPTIONS_BOOK"], "the retry did not take effect"
    assert not [e for e in rec.events
                if e[0] == "subscribe" and e[2] == "LEVELONE_OPTIONS"], (
        "the already-subscribed service was re-subscribed — churn the vendor did not need")


def test_a_total_subscribe_failure_records_nothing(monkeypatch):
    """Neither service accepted: no epoch, no internal state, and it retries."""
    ofs, rec = _wire(monkeypatch, _Recorder(refuse_subscribe=("LEVELONE_OPTIONS",
                                                             "OPTIONS_BOOK")))
    _plan(monkeypatch, ofs, ["A"])
    asyncio.run(ofs._apply_options_slice(object(), 0.0, "stream_start"))
    assert "open_epochs" not in rec.kinds(), "an epoch was opened with no accepted service"
    for svc in ofs.OPTIONS_SERVICES:
        assert not ofs._options_subscribed[svc], f"{svc} recorded a subscription it never got"


def test_the_slice_record_shows_when_the_services_disagree(monkeypatch):
    """Partial state must be VISIBLE, not averaged into one total."""
    ofs, _ = _wire(monkeypatch, _Recorder(refuse_subscribe=("OPTIONS_BOOK",)))
    _plan(monkeypatch, ofs, ["A"])
    asyncio.run(ofs._apply_options_slice(object(), 0.0, "stream_start"))
    st = ofs.options_stream_status()
    assert st["subscribed_by_service"]["LEVELONE_OPTIONS"] == 1
    assert st["subscribed_by_service"]["OPTIONS_BOOK"] == 0
    assert st["services_in_agreement"] is False, (
        "the status claims the services agree while one is subscribed and the other is not")


def test_the_slice_record_makes_rotation_observable(wired, monkeypatch):
    """Frames arriving proves collection. Only this proves the ROTATION is advancing."""
    ofs, rec = wired
    _plan(monkeypatch, ofs, ["A"], slice_index=7)
    asyncio.run(ofs._apply_options_slice(object(), 0.0, "rotation"))
    st = ofs.options_stream_status()
    assert st.get("last_slice"), "options_stream_status exposes no slice record"
    assert st["last_slice"]["slice_index"] == 7
    assert "rotation_running" in st, "an operator cannot tell whether rotation is alive"


# ── the universe must be the ENROLLMENT ROSTER, not whatever has a fresh chain ──────────────
#
# The cohort walks a SORTED non-core list at start = (slice_index * k) % len(non_core), so the
# LENGTH of that list is load-bearing. This asked build_chains_for_selection() for the universe
# — "tickers whose newest chain snapshot is under 86,400s old" — a freshness-derived set that
# is recorded nowhere. MEASURED at one fixed instant: removing a single name moved the cohort
# from U000-U007 to U017-U024; adding one moved it to U040-U047. So one name's chain going
# stale reshuffled every other name's position, and the determinism replay depends on was a
# false claim.

def test_one_name_changing_shifts_the_whole_cohort():
    """The mechanism, kept as a measurement — it is why the universe must be governed."""
    pol = RotationPolicy()
    base = [f"U{i:03d}" for i in range(55)] + list(pol.core)
    t = 1_787_000_000.0
    full = rotation_cohort(base, t, pol)["rotating"]
    minus = rotation_cohort([x for x in base if x != "U000"], t, pol)["rotating"]
    assert full != minus, (
        "the fixture no longer reproduces the shift; if rotation_cohort became insensitive to "
        "roster length this guard is obsolete, but do not delete it without saying so")


def test_the_cohort_is_stable_when_only_chain_freshness_changes(monkeypatch):
    """THE FIX. Same roster, same instant, different fresh-chain sets -> identical cohort."""
    import order_flow_streaming as ofs
    import options_stream_subscription as sub

    roster = [f"U{i:03d}" for i in range(55)] + ["SPY", "QQQ", "IWM"]

    class _DB:
        def logging_universe_authoritative_tickers(self):
            return list(roster)

    monkeypatch.setattr("db.get_db", lambda: _DB(), raising=False)
    monkeypatch.setattr(ofs, "_subscribed_equity_syms", ["SPY"], raising=False)

    seen = []
    for stale in ([], ["U000"], ["U000", "U007", "U031"]):
        fresh = {t: (100.0, []) for t in roster if t not in stale}
        monkeypatch.setattr(sub, "build_chains_for_selection",
                            lambda tickers=None, **_k: (
                                {t: fresh[t] for t in (tickers or fresh) if t in fresh}),
                            raising=False)
        plan = ofs.options_desired_for_slice(1_787_000_000.0, equity_symbols=1)
        seen.append((tuple(plan["core"]), tuple(plan["rotating"])))

    assert len(set(seen)) == 1, (
        f"the cohort moved when only chain FRESHNESS changed: {seen} — a stale chain on one "
        f"name must be a recorded gap, not a reshuffle of every other name's turn")


def test_a_name_without_a_fresh_chain_is_recorded_as_a_gap(monkeypatch):
    """Absence must be stated, not inferred from thin data months later."""
    import order_flow_streaming as ofs
    import options_stream_subscription as sub

    roster = ["SPY", "QQQ", "IWM", "U001", "U002"]

    class _DB:
        def logging_universe_authoritative_tickers(self):
            return list(roster)

    monkeypatch.setattr("db.get_db", lambda: _DB(), raising=False)
    monkeypatch.setattr(ofs, "_subscribed_equity_syms", ["SPY"], raising=False)
    monkeypatch.setattr(sub, "build_chains_for_selection",
                        lambda tickers=None, **_k: {}, raising=False)
    plan = ofs.options_desired_for_slice(1_787_000_000.0, equity_symbols=1)
    assert any("no fresh chain" in n for n in plan["notes"]), (
        f"an underlying with no fresh chain produced no coverage-gap note: {plan['notes']}")


# ── the shared websocket ────────────────────────────────────────────────────────────────────
#
# `_resubscribe_to_ticker` drives level_one_equity / nasdaq_book / nyse_book subs on the SAME
# StreamClient under `_stream_resubscribe_lock`, and rewrites `_subscribed_equity_syms` AFTER
# those awaits. A rotation that took neither could interleave its unsubscribe/subscribe with a
# viewer's ticker switch on one socket, and could size the key budget from an equity count that
# changed mid-await. Options are additive; the equity/book path is what the console depends on.

def test_the_rotation_waits_for_the_equity_resubscribe_lock(wired, monkeypatch):
    """DRIVEN, not asserted: hold the lock and prove no vendor call escapes."""
    ofs, rec = wired
    _plan(monkeypatch, ofs, ["A"])

    async def scenario():
        lock = asyncio.Lock()
        monkeypatch.setattr(ofs, "_stream_resubscribe_lock", lock, raising=False)
        await lock.acquire()                       # a ticker switch is in flight
        task = asyncio.create_task(ofs._apply_options_slice(object(), 0.0, "rotation"))
        await asyncio.sleep(0.05)
        during = list(rec.events)                  # nothing may have happened yet
        lock.release()
        await task
        return during, list(rec.events)

    during, after = asyncio.run(scenario())
    assert during == [], (
        f"the rotation touched the shared socket while the equity resubscribe lock was held: "
        f"{during}")
    assert any(e[0] == "subscribe" for e in after), (
        "the rotation never proceeded after the lock was released — it would stall forever")


def test_the_budget_is_re_derived_under_the_lock(wired, monkeypatch):
    """A plan sized against a stale equity load must be TRIMMED, not sent.

    Sizing options against an equity count that changed mid-await is how a rotation tips the
    account past the vendor key limit and takes the equity stream down with it.
    """
    ofs, rec = wired
    import options_stream_subscription as sub

    _plan(monkeypatch, ofs, [f"S{i}" for i in range(50)])
    monkeypatch.setattr(ofs, "_stream_resubscribe_lock", None, raising=False)
    monkeypatch.setattr(sub, "contract_budget_from_key_limit",
                        lambda **_k: {"contracts_allowed": 5,
                                      "keys_available_for_options": 10}, raising=False)
    asyncio.run(ofs._apply_options_slice(object(), 0.0, "rotation"))
    subscribed = {s for e in rec.events if e[0] == "subscribe" for s in e[1]}  # distinct contracts
    assert len(subscribed) <= 5, (
        f"the rotation subscribed {len(subscribed)} contracts against a re-derived allowance of "
        f"5 — it would push the account past the key limit")


def test_a_null_lock_does_not_silently_mean_unsynchronised(wired, monkeypatch):
    """Outside the stream loop there is no shared socket; the slice must still complete."""
    ofs, rec = wired
    _plan(monkeypatch, ofs, ["A"])
    monkeypatch.setattr(ofs, "_stream_resubscribe_lock", None, raising=False)
    asyncio.run(ofs._apply_options_slice(object(), 0.0, "stream_start"))
    assert any(e[0] == "subscribe" for e in rec.events)


# ── the helper receipts, at the source ──────────────────────────────────────────────────────

def test_unsubscribe_options_reports_per_service_and_does_not_raise():
    """The contract the reconciler depends on: failure is in the receipt, never an exception."""
    import options_stream_subscription as sub

    class _Client:
        async def level_one_option_unsubs(self, _s):
            return None                                  # accepted

        async def options_book_unsubs(self, _s):
            raise RuntimeError("vendor said no")         # refused

    r = asyncio.run(sub.unsubscribe_options(_Client(), ["A"]))
    assert r["level_one"] is True, "an accepted unsubscribe was not reported True"
    assert r["book"] is False, "a refused unsubscribe was not reported False"
    assert any("options_book_unsubs" in e for e in r["errors"]), "the failure was not recorded"


def test_unsubscribe_options_flags_a_missing_method():
    import options_stream_subscription as sub

    class _Bare:
        async def level_one_option_unsubs(self, _s):
            return None

    r = asyncio.run(sub.unsubscribe_options(_Bare(), ["A"]))
    assert r["level_one"] is True and r["book"] is False
    assert any("no such method" in e for e in r["errors"])


# ── startup / teardown must not strand resources ────────────────────────────────────────────

def test_an_empty_initial_collection_stops_the_ingest_writer(monkeypatch):
    """A start that subscribes nothing must not leave the writer thread running forever."""
    import order_flow_streaming as ofs

    started, stopped = {"n": 0}, {"n": 0}

    class _Ingest:
        def start(self):
            started["n"] += 1

        def stop(self, timeout=None):
            stopped["n"] += 1
            return {"offered": 0, "written": 0, "dropped": 0}

        def queue_depth(self):
            return 0

        class stats:
            @staticmethod
            def snapshot():
                return {}

    monkeypatch.setenv("ED_OPTIONS_STREAM", "1")
    monkeypatch.setattr(ofs, "OptionsFrameIngest", None, raising=False)
    monkeypatch.setattr("calibration.options_stream_ingest.OptionsFrameIngest",
                        lambda *_a, **_k: _Ingest(), raising=False)
    monkeypatch.setattr(ofs, "_options_subscribed",
                        {s: set() for s in ofs.OPTIONS_SERVICES}, raising=False)

    async def _empty_slice(*_a, **_k):
        return {}

    monkeypatch.setattr(ofs, "_apply_options_slice", _empty_slice, raising=False)
    asyncio.run(ofs._start_options_collection(object()))
    assert started["n"] == 1, "the writer was never started (nothing to strand — test is moot)"
    assert stopped["n"] == 1, (
        "the ingest writer was left running after a start that subscribed nothing — an ingest "
        "with no producer, holding its queue and sqlite handle for the life of the process")


def test_teardown_closes_epochs_only_for_what_each_service_held(monkeypatch):
    """A shutdown must not write an end for an epoch that was never opened."""
    ofs, rec = _wire(monkeypatch, _Recorder())
    monkeypatch.setattr(ofs, "_options_subscribed",
                        {"LEVELONE_OPTIONS": {"A", "B"}, "OPTIONS_BOOK": {"A"}}, raising=False)
    monkeypatch.setattr(ofs, "_options_ingest", None, raising=False)
    ofs._stop_options_collection("stream_stop")
    closed = {(e[2], s) for e in rec.events if e[0] == "close_epochs" for s in e[1]}
    assert ("LEVELONE_OPTIONS", "A") in closed and ("LEVELONE_OPTIONS", "B") in closed
    assert ("OPTIONS_BOOK", "A") in closed
    assert ("OPTIONS_BOOK", "B") not in closed, (
        "teardown closed an OPTIONS_BOOK epoch for B, which that service never held")


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
