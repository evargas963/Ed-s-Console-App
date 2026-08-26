"""OPTION-CHAIN SCALE INVARIANCE — a measurement must not change meaning with the strike step.

THE FAMILY. The option-chain path carried several constants expressed in ABSOLUTE DOLLARS or in
STRIKE COUNTS, applied across instruments whose ladders differ by a factor of twenty ($0.50 on
XRT/CDE/CIFR, $10 on FN/STRL, $5 on AEIS/MU). Under one name they measured different things per
ticker, and on the widest ladders some measured nothing at all. This is the same class as the
display defect: a rule that is right on SPY/QQQ/IWM and wrong elsewhere.

Every case below was found by adversarial audit, confirmed against the production database, and
is asserted here on LADDER GEOMETRY rather than on a specific ticker, so a new optionable symbol
of any spacing is covered without being named.

Nothing here infers dealer ownership, aggressor side, or intent.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _ladder(spot: float, step: float, n_side: int = 8, gex_slope: float = 1.0) -> dict:
    """A per-strike exposures map with a KNOWN linear GEX slope.

    institutional-synthetic-ok: this fixes the ladder GEOMETRY so scale-invariance is testable
    at all — the whole point is comparing the same shape at different steps. No market claim is
    derived from it; the real-data evidence lives in the docstrings and the commit.
    """
    out: dict[float, dict] = {}
    for i in range(-n_side, n_side + 1):
        k = round(spot + i * step, 4)
        out[k] = {"net_gex_1pct": gex_slope * (k - spot)}
    return out


# ── compute_gamma_gradient: the sample must follow the ladder ───────────────────────────────

@pytest.mark.parametrize("step", [0.5, 1.0, 2.5, 5.0, 10.0, 25.0])
def test_gamma_gradient_is_computable_on_every_ladder(step: float):
    """A $10 ladder cannot place a strike inside an absolute +/-$5 window on BOTH sides.

    MEASURED before the fix, production DB, last 10 days: AEIS 21/21 NULL, FN 21/21, STRL 21/21
    — 100%. The metric simply did not exist for wide-ladder instruments, and nothing said so.
    """
    from math_probabilities import compute_gamma_gradient

    spot = 400.0
    g = compute_gamma_gradient(_ladder(spot, step), spot)
    assert g is not None, (
        f"gradient is None on a ${step} ladder — the sample is still tied to a dollar constant "
        f"instead of the instrument's own strikes")


def test_gamma_gradient_recovers_the_true_slope_regardless_of_step():
    """THE INVARIANT. A ladder built with slope 1.0 must measure ~1.0 at ANY step.

    The old divisor was the WINDOW (a fixed 2 * 5.0), not the distance actually sampled, so the
    reported slope was scaled by an arbitrary factor per ticker — MU got one strike per side,
    truly $5 apart, divided by 10, reporting half the real slope.
    """
    from math_probabilities import compute_gamma_gradient

    spot = 400.0
    for step in (0.5, 1.0, 2.5, 5.0, 10.0, 25.0):
        g = compute_gamma_gradient(_ladder(spot, step, gex_slope=1.0), spot)
        assert g == pytest.approx(1.0, rel=1e-6), (
            f"${step} ladder reports slope {g}, not 1.0 — the divisor is not the distance "
            f"actually sampled, so gradients are not comparable across instruments")


def test_gamma_gradient_samples_a_strike_count_not_a_price_window():
    """Coverage must not balloon on a dense ladder.

    With the old absolute window, a $0.50 step put ~20 strikes inside +/-$5 — CIFR's window
    spanned +/-31% of spot — so "near spot" meant the whole neighbourhood there and two strikes
    elsewhere.
    """
    import inspect

    from math_probabilities import GRADIENT_STRIKES_PER_SIDE, compute_gamma_gradient

    # Check the SIGNATURE, not the source text: the docstring names the old parameter when
    # explaining what it got wrong, and a substring match on that would fail on correct code.
    assert "window_pts" not in inspect.signature(compute_gamma_gradient).parameters, (
        "the absolute dollar window parameter is back")
    assert GRADIENT_STRIKES_PER_SIDE >= 1

    # A dense ladder must not reach further than the requested strike count.
    spot = 20.0
    dense = _ladder(spot, 0.5, n_side=40, gex_slope=1.0)
    assert compute_gamma_gradient(dense, spot, strikes_per_side=2) == pytest.approx(1.0, rel=1e-6)


def test_gamma_gradient_absence_stays_absence():
    """One-sided or empty books report None, never a fabricated flat slope."""
    from math_probabilities import compute_gamma_gradient

    spot = 100.0
    assert compute_gamma_gradient({}, spot) is None
    one_sided = {95.0: {"net_gex_1pct": 1.0}, 90.0: {"net_gex_1pct": 2.0}}
    assert compute_gamma_gradient(one_sided, spot) is None, (
        "a book with no strike above spot must not report a slope")
    assert compute_gamma_gradient(_ladder(spot, 1.0), 0) is None
    assert compute_gamma_gradient(_ladder(spot, 1.0), None) is None


def test_gamma_gradient_sign_follows_the_book_not_the_ladder():
    """Direction must be a property of the exposures, identical at every step."""
    from math_probabilities import compute_gamma_gradient

    spot = 400.0
    for step in (0.5, 2.5, 10.0):
        up = compute_gamma_gradient(_ladder(spot, step, gex_slope=+1.0), spot)
        dn = compute_gamma_gradient(_ladder(spot, step, gex_slope=-1.0), spot)
        assert up > 0 > dn, f"${step} ladder disagrees about direction: up={up} down={dn}"
