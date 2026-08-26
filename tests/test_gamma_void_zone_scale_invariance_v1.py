"""A void zone is GATED in the unit it is PUBLISHED in (option-chain fidelity, 2026-08-26).

THE DEFECT. `compute_gamma_void_zones` admitted a region on `zone_len >= min_width_strikes`
— a COUNT of consecutive strikes — and then published `lower`, `upper`, `width_pts` and
`dist_to_spot`, every one of which is a PRICE. A count only implies a distance if you assume
a strike increment, and that is precisely the core-ticker assumption this mission removes.

MEASURED over the 74 enrolled chains (production DB, 2026-08-26): the modal increment runs
from 0.22 to 30 points, so the SAME `min_width_strikes=2` admitted corridors from 0.130% of
spot ($SPX) to 46.168% (MTA) — 355x in the unit the caller reads. Running the real function
over those chains published 404 zones from 0.031% of spot (QQQ 599.78-600.00: a 0.22-point
"acceleration corridor") to 326% ($VIX 50-100 against a 15.32 spot).

These tests are scale-free by construction. No ticker, increment, or precision is named:
each builds the SAME void in strike-space at different increments and asserts the verdict
tracks price, not strike count.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from math_levels import compute_gamma_void_zones  # noqa: E402


def _chain(spot: float, increment: float, n: int = 41, void_at: tuple[int, int] = (18, 22)):
    """A chain with heavy OI/gamma everywhere except a contiguous void.

    The void is defined by strike INDEX, so the same structural hole can be rendered at any
    increment — which is the whole point: identical structure, different price width.
    """
    lo = spot - (n // 2) * increment
    out = {}
    for i in range(n):
        k = round(lo + i * increment, 4)
        in_void = void_at[0] <= i < void_at[1]
        oi = 2.0 if in_void else 5000.0
        gex = 1.0 if in_void else 1_000_000.0
        out[k] = {"call_oi": oi / 2, "put_oi": oi / 2, "net_gex_1pct": gex}
    return out


def _widths(zones):
    return sorted(z["width_pts"] for z in zones)


# ── the unit mismatch itself ────────────────────────────────────────────────────────────────

def test_the_same_strike_count_is_not_the_same_corridor():
    """THE ROOT CAUSE, stated as a measurement.

    Identical void — four consecutive strikes — at two increments. Under a COUNT gate both
    are admitted identically. They are not the same thing: one is a rounding artifact, the
    other is a fifth of the instrument.
    """
    dense = compute_gamma_void_zones(_chain(700.0, 0.25), 700.0, min_width_pct_of_spot=0.0)
    coarse = compute_gamma_void_zones(_chain(10.0, 2.50), 10.0, min_width_pct_of_spot=0.0)
    assert dense and coarse, "the fixture did not produce a void on both chains"
    dense_pct = dense[0]["width_pct_of_spot"]
    coarse_pct = coarse[0]["width_pct_of_spot"]
    assert coarse_pct > dense_pct * 50, (
        f"fixture is not exercising the spread: {dense_pct}% vs {coarse_pct}% — the point is "
        f"that one strike count means wildly different distances")


def test_a_sub_noise_corridor_is_not_published():
    """A corridor thinner than the gate cannot be an acceleration zone at any price level."""
    spot = 700.0
    zones = compute_gamma_void_zones(_chain(spot, 0.10), spot)
    assert not any(z["width_pct_of_spot"] < 0.10 for z in zones), (
        f"a corridor under the materiality gate was published: {zones}")


def test_the_gate_is_price_not_count():
    """Same structural void, same count, opposite verdicts — decided by price."""
    tiny = compute_gamma_void_zones(_chain(1000.0, 0.05), 1000.0)   # 4 strikes = 0.15 pts
    real = compute_gamma_void_zones(_chain(1000.0, 5.00), 1000.0)   # 4 strikes = 15 pts
    assert not tiny, f"a 0.015%-of-spot corridor survived a price gate: {tiny}"
    assert real, "a 1.5%-of-spot corridor was dropped — the gate is now too aggressive"


# ── deliver, never delete ───────────────────────────────────────────────────────────────────

def test_a_wide_real_void_is_kept_not_deleted():
    """The far-wing emptiness is REAL — the $VIX book truly has no OI between 50 and 100.

    Operator law: computed value gets a consumer; dropping features is not an audit outcome.
    The repair labels those zones, it does not silence them.
    """
    spot = 15.0
    zones = compute_gamma_void_zones(_chain(spot, 2.5, n=41, void_at=(30, 38)), spot)
    assert zones, "a genuine wide void was deleted rather than labelled"
    assert max(z["width_pct_of_spot"] for z in zones) > 50, (
        "the wide void lost its scale label, which is what makes keeping it safe")


def test_every_zone_carries_its_own_scale():
    """A consumer must be able to tell a near-spot corridor from a far wing without the ticker."""
    for spot, inc in ((7689.47, 5.0), (299.13, 1.0), (15.32, 2.5)):
        for z in compute_gamma_void_zones(_chain(spot, inc), spot):
            assert "width_pct_of_spot" in z, f"zone published without scale: {z}"
            assert abs(z["width_pct_of_spot"] - z["width_pts"] / spot * 100.0) < 0.01, (
                "width_pct_of_spot disagrees with width_pts — two computations of one width")


def test_no_chain_is_silenced_entirely_by_the_gate():
    """Across a wide sweep of scales, the gate must never take a chain's last zone."""
    for spot, inc in ((7689.0, 5.0), (766.9, 1.0), (299.1, 1.0), (37.4, 0.5),
                      (15.3, 2.5), (10.8, 2.5), (1238.1, 5.0)):
        assert compute_gamma_void_zones(_chain(spot, inc), spot), (
            f"spot={spot} inc={inc} lost every zone — the gate is deleting real structure")


# ── one emitter ─────────────────────────────────────────────────────────────────────────────

def test_the_end_of_chain_void_obeys_the_same_gate():
    """The two emission paths must not drift.

    Mid-chain and end-of-chain regions used to build the zone dict in two places, so the
    materiality gate would have had to be added twice to hold. This drives the END path
    specifically (the void runs to the last strike) and asserts it is gated identically.
    """
    spot = 1000.0
    end_void_tiny = _chain(spot, 0.05, n=41, void_at=(37, 41))
    end_void_real = _chain(spot, 5.00, n=41, void_at=(37, 41))
    assert not compute_gamma_void_zones(end_void_tiny, spot), (
        "the end-of-chain path published a sub-noise corridor — the paths have drifted")
    kept = compute_gamma_void_zones(end_void_real, spot)
    assert kept and all("width_pct_of_spot" in z for z in kept), (
        "the end-of-chain path emits zones without the scale field")


def test_zone_dict_is_built_in_exactly_one_place():
    """Structural: one emitter, or the gate can be half-applied again."""
    import ast

    src = (REPO / "math_levels.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "compute_gamma_void_zones")
    appends = [n for n in ast.walk(fn)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "append" and getattr(n.func.value, "id", "") == "zones"]
    assert len(appends) == 1, (
        f"{len(appends)} places construct a void zone; one computation means one emitter")
