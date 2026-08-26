"""A rejected greek must not arrive at the reader as a measured zero (RC-274 repair).

THE DEFECT, AND WHY THE EXISTING GUARD COULD NOT CATCH IT. `terrain_engine._per_strike_rows`
carries an explicit RC-274 guard: when both `net_gex_1pct` and the raw-gamma fallback are
absent it drops the strike rather than drawing a bar, because `float(g or 0.0)` "drew a bar at
zero — visually identical to a strike measured at flat gamma, on the surface used to read
where dealers are short". The guard was correct and it was UNREACHABLE. `_strike_bucket`
seeded `call_gamma`/`put_gamma`/`call_gex_1pct`/`put_gex_1pct` to 0.0 and the accumulators
only ever `+=` a valid contribution, so a strike whose every contract was rejected finalised
to `0.0 - 0.0 = 0.0`. The guard tested for None at a layer where None could no longer arrive.

MEASURED on the live XOM chain (production DB, 2026-08-26, 546 contracts / 66 strikes):
strike 144.0 genuinely measures net_gex_1pct = -29,470.7. Reject its 8 contracts' gamma by
any of the three real-world routes — None, the documented -999 Schwab sentinel, or the key
absent — and the panel rendered `[144.0, 0.0, 0]`.

THE REPAIR is the discipline `call_oi`/`put_oi` already used inline in the same function:
seed None, and let a number appear only when a measurement actually arrives.

These tests use REAL Schwab contract shape. The synthetic fixture is a controlled corruption
of it, which is the only way to prove EXACT exclusion.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from math_exposure_core import (  # noqa: E402
    MISSING_GREEK_SENTINEL,
    bucket_metric,
    compute_exposures_by_strike,
    total_gamma_raw_at_strike,
)
from terrain_engine import _per_strike_rows  # noqa: E402


def _ct(strike: float, side: str, gamma, oi: int = 1000):
    # institutional-synthetic-ok: proving that a REJECTED greek is distinguishable from a
    # MEASURED zero requires constructing the rejection; found real data cannot be made to
    # contain a controlled corruption of a known-good strike.
    return {"strikePrice": strike, "putCall": side, "openInterest": oi, "totalVolume": 5,
            "delta": 0.5 if side == "CALL" else -0.5, "gamma": gamma, "vega": 0.02,
            "volatility": 20.0, "multiplier": 100, "bidSize": 1, "askSize": 1,
            "daysToExpiration": 7, "expirationDate": "2026-09-18T00:00:00.000+00:00"}


REJECTIONS = [
    pytest.param(None, id="gamma_is_None"),
    pytest.param(MISSING_GREEK_SENTINEL, id="gamma_is_the_-999_sentinel"),
    pytest.param(-91965.237, id="gamma_is_vendor_garbage"),
]


# ── the distinction the whole repair exists to make ─────────────────────────────────────────

@pytest.mark.parametrize("bad_gamma", REJECTIONS)
def test_a_rejected_strike_is_not_a_measured_zero(bad_gamma):
    """THE CORE ASSERTION. Rejected and flat must not be the same value."""
    rejected, _ = compute_exposures_by_strike([_ct(100.0, "CALL", bad_gamma)], spot=100.0)
    assert bucket_metric(rejected.get(100.0, {}), "net_gex_1pct") is None, (
        "a strike with no usable gamma reported a number the reader cannot tell from a "
        "measurement")


def test_a_genuinely_flat_strike_still_reports_a_measured_zero():
    """THE OTHER HALF. None must mean absent — it must not swallow a real zero.

    Equal call and put gamma at one strike is a true, measured net of 0.0. If the repair
    turned that into None it would be deleting a real level, not preserving absence.
    """
    flat, _ = compute_exposures_by_strike(
        [_ct(100.0, "CALL", 0.05), _ct(100.0, "PUT", 0.05)], spot=100.0)
    v = bucket_metric(flat.get(100.0, {}), "net_gex_1pct")
    assert v == 0.0, f"a genuinely cancelling strike lost its measured zero: {v!r}"


def test_one_sided_strike_is_a_real_net_not_an_absence():
    """Calls with no puts is a true zero contribution on the missing side — a real net."""
    exp, _ = compute_exposures_by_strike([_ct(100.0, "CALL", 0.05)], spot=100.0)
    v = bucket_metric(exp.get(100.0, {}), "net_gex_1pct")
    assert v is not None and v > 0, (
        f"a call-only strike was treated as unmeasured instead of a real one-sided net: {v!r}")


# ── the guard is now reachable ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad_gamma", REJECTIONS)
def test_the_terrain_panel_drops_the_strike_instead_of_drawing_zero(bad_gamma):
    """The RC-274 guard fires — behaviour, not a code inspection."""
    contracts = [_ct(100.0, "CALL", bad_gamma), _ct(105.0, "CALL", 0.05)]
    exp, _ = compute_exposures_by_strike(contracts, spot=100.0)
    rows = _per_strike_rows(exp, contracts)
    drawn = [r for r in rows if abs(r[0] - 100.0) < 1e-9]
    assert not drawn, (
        f"the rejected strike was drawn as {drawn} — a bar at zero on the surface used to "
        f"read where dealers are short")
    assert any(abs(r[0] - 105.0) < 1e-9 for r in rows), (
        "the healthy neighbour was dropped too; the guard is over-firing")


def test_rejecting_one_strike_does_not_silence_its_neighbours():
    """Blast-radius control: absence is per-strike, never chain-wide."""
    contracts = [_ct(k, "CALL", (None if k == 100.0 else 0.05)) for k in (95.0, 100.0, 105.0)]
    exp, _ = compute_exposures_by_strike(contracts, spot=100.0)
    rows = _per_strike_rows(exp, contracts)
    assert sorted(r[0] for r in rows) == [95.0, 105.0], (
        f"expected exactly the two healthy strikes, got {rows}")


# ── the raw fallback must agree ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad_gamma", REJECTIONS)
def test_the_raw_gamma_fallback_reports_absence_too(bad_gamma):
    """The guard needs BOTH readers to say absent; one seeded zero re-opens the hole."""
    exp, _ = compute_exposures_by_strike([_ct(100.0, "CALL", bad_gamma)], spot=100.0)
    assert total_gamma_raw_at_strike(exp.get(100.0, {})) is None, (
        "the raw-gamma fallback still synthesises a zero, so the guard cannot fire")


def test_open_interest_survives_a_rejected_greek():
    """The contract is still REAL. Rejecting its gamma must not discard its OI."""
    exp, diag = compute_exposures_by_strike(
        [_ct(100.0, "PUT", -91965.237, oi=21605)], spot=100.0)
    assert exp[100.0].get("put_oi") == 21605.0, "OI was lost with the gamma"
    assert diag.greeks_missing >= 1, "the rejection was not reported in diagnostics"
