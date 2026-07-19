"""FIND-GAMMA-FLIP-METHOD-V1 — canonical gamma profile (hypothetical-spot recompute).

Proven 2026-07-19 on a real SPY reference chain that the cumulative-sum method does NOT
reproduce the published profile (corr 0.086, never crosses zero, 2.19e9 divergence).
Only recomputing every contract's gamma at each candidate price reproduces the published
flip. These tests run on a REAL captured Schwab chain, never a hand-built one.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from math_levels import (
    GAMMA_FLIP_NARROW,
    GAMMA_FLIP_UNAVAILABLE,
    bs_gamma,
    compute_gamma_flip_v2,
    compute_gamma_profile,
    gamma_at_price,
    gamma_flip_from_profile,
)

_REAL_CHAIN = Path(__file__).parent / "fixtures" / "real_spy_0dte_chain_with_poison.json"


def _load_real_chain() -> tuple[list, float]:
    data = json.loads(_REAL_CHAIN.read_text(encoding="utf-8"))
    return data["chain"], float(data["spot"])


def test_bs_gamma_peaks_at_the_money() -> None:
    """Gamma must peak ATM and vanish far OTM — the shape the whole profile depends on."""
    atm = bs_gamma(100.0, 100.0, 0.02, 0.20)
    otm = bs_gamma(100.0, 130.0, 0.02, 0.20)
    assert atm is not None and otm is not None
    assert atm > otm
    assert bs_gamma(100.0, 100.0, 0.0, 0.20) is None      # expired -> refuse
    assert bs_gamma(100.0, 100.0, 0.02, 0.0) is None      # no vol -> refuse


def test_profile_on_real_chain_is_finite_and_spans_spot() -> None:
    chain, spot = _load_real_chain()
    prof = compute_gamma_profile(chain, spot, span_pct=0.15, steps=120)
    assert len(prof) == 121
    assert all(math.isfinite(v) for _, v in prof)
    prices = [p for p, _ in prof]
    assert prices[0] < spot < prices[-1]
    assert prices == sorted(prices)


def test_profile_uses_dealer_sign_convention() -> None:
    """Calls add, puts subtract: an all-call book must be positive at every price."""
    chain, spot = _load_real_chain()
    calls = [c for c in chain if str(c.get("putCall", "")).upper().startswith("C")]
    assert calls, "fixture must contain calls"
    prof = compute_gamma_profile(calls, spot, span_pct=0.10, steps=40)
    assert prof and all(v >= 0 for _, v in prof)


def test_flip_is_interpolated_within_the_profile_span() -> None:
    chain, spot = _load_real_chain()
    prof = compute_gamma_profile(chain, spot, span_pct=0.15, steps=240)
    flip = gamma_flip_from_profile(prof)
    if flip is not None:
        assert prof[0][0] <= flip <= prof[-1][0]


def test_flip_returns_none_when_no_zero_crossing() -> None:
    assert gamma_flip_from_profile([(100.0, 5.0), (101.0, 7.0)]) is None
    assert gamma_flip_from_profile([]) is None


def test_narrow_chain_flip_is_reported_low_confidence() -> None:
    """The live 20-strike chain spans only ~+/-1.3%; its flip must never be served as
    trustworthy (measured error vs full-chain reference: 770.35 vs 745.61)."""
    chain, spot = _load_real_chain()
    flip, confidence, diag = compute_gamma_flip_v2(chain, spot)
    assert confidence == GAMMA_FLIP_NARROW
    assert diag["span_below_pct"] < 0.05 or diag["span_above_pct"] < 0.05
    assert diag["n_strikes"] > 0 and diag["strike_lo"] < diag["strike_hi"]


def test_flip_v2_fails_closed_without_inputs() -> None:
    for contracts, spot in (([], 100.0), (None, 100.0), ([{"strikePrice": 100}], 0.0)):
        flip, confidence, _diag = compute_gamma_flip_v2(contracts, spot)
        assert flip is None and confidence == GAMMA_FLIP_UNAVAILABLE

def test_regime_is_defined_even_when_the_profile_never_crosses_zero() -> None:
    """RC-11: no zero-crossing means no FLIP LEVEL, never an unknown regime.

    A chain whose dealer gamma holds one sign at every price has an unambiguous regime --
    arguably more certain than one with a flip beside spot. Before this was corrected, 20
    of 51 live tickers reported UNAVAILABLE while their gamma was uniformly signed.
    """
    chain, spot = _load_real_chain()
    prof = compute_gamma_profile(chain, spot)
    assert prof, "real chain must produce a profile"

    at_spot = gamma_at_price(prof, spot)
    assert at_spot is not None and math.isfinite(at_spot)

    # interpolation must sit inside the bracketing profile values
    pts = sorted(prof)
    below = [v for x, v in pts if x <= spot]
    above = [v for x, v in pts if x >= spot]
    if below and above:
        lo, hi = min(below[-1], above[0]), max(below[-1], above[0])
        assert lo - 1e-6 <= at_spot <= hi + 1e-6

    # a strictly one-signed profile yields no flip but still reports a usable verdict
    assert gamma_flip_from_profile([(100.0, 5.0), (101.0, 7.0)]) is None
    assert gamma_at_price([(100.0, 5.0), (101.0, 7.0)], 100.5) == 6.0


def test_gamma_at_price_clamps_outside_the_profile() -> None:
    prof = [(100.0, -2.0), (110.0, 4.0)]
    assert gamma_at_price(prof, 50.0) == -2.0     # below the profile -> first value
    assert gamma_at_price(prof, 500.0) == 4.0     # above -> last value
    assert gamma_at_price([], 100.0) is None
    assert gamma_at_price(prof, None) is None
