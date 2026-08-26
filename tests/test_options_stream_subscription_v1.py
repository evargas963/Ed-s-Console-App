"""OPTIONS FLOW — contract selection must be deterministic, bounded, and FAIR across underlyings.

REGRESSION THIS PINS (found by measurement, not review): the first selection filled the ceiling one
underlying at a time in alphabetical order. On five real chains that produced AAPL/IWM/NVDA taking
all 240 slots while SPY and QQQ got ZERO — the two most important underlyings silently absent
because of their initials. A ceiling must degrade DEPTH, never delete whole underlyings.

Nothing here infers dealer ownership, inventory sign, aggressor side or opening/closing intent;
these tests are about which symbols get streamed and how the bound behaves.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from options_stream_subscription import (
    MAX_STREAMED_CONTRACTS,
    SelectionPolicy,
    select_contracts,
    subscribe_options,
)


def _chain(root: str, spot: float, n_strikes: int = 40, expiries: int = 4) -> list[dict]:
    """Synthetic chain shaped like the vendor's per-contract dicts.

    institutional-synthetic-ok: this tests SELECTION GEOMETRY (ordering, fairness, bounds), which
    needs controlled strike/expiry counts per underlying; no market claim is derived from it.
    """
    out = []
    for e in range(expiries):
        exp = f"2026-09-{e + 1:02d}T20:00:00.000+00:00"
        for i in range(n_strikes):
            strike = round(spot - (n_strikes // 2) + i, 2)
            for side in ("CALL", "PUT"):
                out.append({
                    "symbol": f"{root:<6}2609{e + 1:02d}{'C' if side == 'CALL' else 'P'}"
                              f"{int(strike * 1000):08d}",
                    "strikePrice": strike, "putCall": side, "expirationDate": exp,
                })
    return out


def test_selection_is_deterministic():
    chains = {"SPY": (600.0, _chain("SPY", 600.0)), "QQQ": (500.0, _chain("QQQ", 500.0))}
    a = select_contracts(chains)
    b = select_contracts(chains)
    assert a.symbols == b.symbols and a.symbols, "same inputs must give the same ordered selection"


def test_ceiling_is_honoured():
    chains = {f"T{i}": (100.0, _chain(f"T{i}", 100.0)) for i in range(6)}
    res = select_contracts(chains, SelectionPolicy(strikes_per_side=30, expiries=8, max_contracts=57))
    assert len(res.symbols) <= 57, "hard ceiling breached"
    assert res.truncated and res.notes, "truncation must be reported, never silent"


def test_no_underlying_is_starved_by_the_ceiling():
    """THE REGRESSION. Alphabetically-late underlyings must still be represented."""
    roots = ["AAPL", "IWM", "NVDA", "QQQ", "SPY", "TSLA"]
    chains = {r: (100.0 + i, _chain(r, 100.0 + i)) for i, r in enumerate(roots)}
    res = select_contracts(chains, SelectionPolicy(max_contracts=60))
    assert len(res.symbols) == 60
    for r in roots:
        assert res.per_underlying.get(r, 0) > 0, (
            f"{r} received ZERO contracts — the ceiling deleted an underlying instead of "
            f"reducing depth: {res.per_underlying}")
    counts = sorted(res.per_underlying.values())
    assert counts[-1] - counts[0] <= 1, (
        f"allocation is not fair; depths differ by more than one: {res.per_underlying}")


def test_missing_spot_is_skipped_not_guessed():
    chains = {"SPY": (None, _chain("SPY", 600.0)), "QQQ": (500.0, _chain("QQQ", 500.0))}
    res = select_contracts(chains)
    assert not any(s.startswith("SPY") for s in res.symbols), "no centre must mean no selection"
    assert any("SPY" in n and "spot" in n for n in res.notes), "the skip must be explained"


def test_both_sides_of_spot_and_both_option_sides_are_selected():
    chains = {"SPY": (600.0, _chain("SPY", 600.0))}
    res = select_contracts(chains, SelectionPolicy(strikes_per_side=4, expiries=1,
                                                   max_contracts=MAX_STREAMED_CONTRACTS))
    assert any("C" in s[6:] for s in res.symbols) and any("P" in s[6:] for s in res.symbols), \
        "a flow product needs both calls and puts"


def test_level_one_requests_the_COMPLETE_field_surface_not_a_default():
    """The foundation's whole premise: native truth is not lost because today's code under-asked."""
    class _Fields:
        @staticmethod
        def all_fields():
            return list(range(56))

    class _Client:
        LevelOneOptionFields = _Fields

        def __init__(self):
            self.fields_seen = None
            self.book_syms = None

        async def level_one_option_subs(self, syms, fields=None):
            self.fields_seen = fields

        async def options_book_subs(self, syms):
            self.book_syms = syms

    c = _Client()
    receipt = asyncio.run(subscribe_options(c, ["SPY   260826C00600000"]))
    assert receipt["level_one"]["fields_requested"] == 56, (
        "LEVELONE_OPTIONS must request every entitled field, not a library default subset")
    assert c.fields_seen is not None and len(c.fields_seen) == 56
    assert receipt["book"]["symbols"] == 1
    assert not receipt["errors"]


def test_subscribe_fails_soft_without_a_client():
    receipt = asyncio.run(subscribe_options(None, ["SPY   260826C00600000"]))
    assert receipt["errors"], "a missing client must be reported, never silently succeed"


# ── ROTATION: universal coverage when the budget cannot hold everything at once ──────────────
# Measured against the real enrolled universe (58 underlyings, 238-contract budget): without
# rotation every underlying gets 4-5 contracts, which proves a pipeline and describes no flow.
# With rotation SPY/QQQ/IWM hold 39 each continuously and each non-core underlying gets 14 in
# its turn, with a full cycle over all 55 non-core in 7 slices (1.8 h).

def _universe(n: int = 58) -> list[str]:
    from options_stream_subscription import CORE_UNDERLYINGS
    return list(CORE_UNDERLYINGS) + [f"U{i:03d}" for i in range(n - len(CORE_UNDERLYINGS))]


def test_core_underlyings_are_never_rotated_out():
    """SPY/QQQ/IWM carry the money path. A gap in their options history is a gap in the record
    for terrain, models and every decision built on them."""
    from options_stream_subscription import CORE_UNDERLYINGS, RotationPolicy, rotation_cohort

    pol, u = RotationPolicy(), _universe()
    for s in range(40):
        c = rotation_cohort(u, s * pol.slice_seconds, pol)
        for core in CORE_UNDERLYINGS:
            assert core in c["eligible"], f"{core} was rotated out in slice {s}"


def test_every_non_core_underlying_is_covered_within_one_cycle():
    """Rotation must GUARANTEE a turn, not merely tend towards one. An underlying that can be
    skipped indefinitely is starved on a longer timescale — the same defect as alphabetical
    ceiling-filling, just harder to notice."""
    from options_stream_subscription import RotationPolicy, rotation_cohort

    pol, u = RotationPolicy(), _universe()
    first = rotation_cohort(u, 0.0, pol)
    seen: set[str] = set()
    for s in range(first["full_cycle_slices"]):
        seen.update(rotation_cohort(u, s * pol.slice_seconds, pol)["rotating"])
    assert len(seen) == first["non_core_total"], (
        f"only {len(seen)} of {first['non_core_total']} non-core underlyings got a turn in a "
        f"full cycle — some are starved on the rotation timescale")


def test_rotation_is_deterministic_from_the_clock_alone():
    """Replay must be able to reconstruct which underlyings were eligible at a past instant
    without stored scheduler state. Two calls inside one slice must agree, and the boundary must
    actually move the cohort."""
    from options_stream_subscription import RotationPolicy, rotation_cohort

    pol, u = RotationPolicy(), _universe()
    # ALIGN to a slice boundary. An arbitrary epoch sits mid-slice, so "base + slice_seconds - 1"
    # would cross into the next slice and the test would fail on correct code — which is exactly
    # what a first run of this did.
    base = (1_787_000_000 // pol.slice_seconds) * pol.slice_seconds
    a = rotation_cohort(u, base, pol)
    b = rotation_cohort(u, base + pol.slice_seconds - 1, pol)
    c = rotation_cohort(u, base + pol.slice_seconds, pol)
    assert a["eligible"] == b["eligible"], "cohort changed inside a single slice"
    assert a["rotating"] != c["rotating"], "cohort did not advance across a slice boundary"


def test_rotation_buys_real_depth_rather_than_reshuffling_slivers():
    """The whole justification. If a rotating underlying's depth were no better than the
    everything-at-once split, rotation would add gaps for nothing."""
    from options_stream_subscription import RotationPolicy, rotation_cohort, split_budget

    pol, u = RotationPolicy(), _universe()
    budget = 238
    flat_depth = budget // len(u)
    c = rotation_cohort(u, 0.0, pol)
    sp = split_budget(budget, len(c["core"]), len(c["rotating"]), pol)
    core_depth = sp["core"] // max(1, len(c["core"]))
    rot_depth = sp["rotating"] // max(1, len(c["rotating"]))

    assert rot_depth > flat_depth * 2, (
        f"rotating depth {rot_depth} is not materially better than the flat split "
        f"{flat_depth} — the coverage gaps rotation introduces would buy nothing")
    assert core_depth > flat_depth * 4, (
        f"core depth {core_depth} vs flat {flat_depth}: the money path is not getting the "
        f"continuous depth that justifies reserving budget for it")
    assert sp["core"] + sp["rotating"] == budget, "the budget split loses or invents contracts"
