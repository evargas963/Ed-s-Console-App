"""FIND-CHARM-BY-STRIKE-V1 — per-strike dealer charm exposure and charm walls.

Charm-by-strike is standard institutional practice (SpotGamma / Unusual Whales /
VannaCharm publish it alongside GEX) and charm pressure is the mechanism attributed to
the end-of-day pin. We previously computed only a chain-level charm aggregate.

The analytic charm is verified against a FINITE-DIFFERENCE derivative of Black-Scholes
delta — an independent derivation, not a restatement of the same formula. That check
caught a sign inversion in the first draft before it shipped, which is exactly why the
verification is a test and not a one-off script.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from datetime import datetime
import time_et

from math_levels import bs_charm, compute_charm_by_strike, pick_charm_wall_strikes

_REAL_CHAIN = Path(__file__).parent / "fixtures" / "real_spy_0dte_chain_with_poison.json"


@pytest.fixture(autouse=True)
def _pin_now_to_fixture_session(monkeypatch):
    # Fixture is a REAL 0DTE SPY chain captured 2026-07-17; pin the clock to mid-session that
    # day so the canonical intraday time-to-expiry sees a live 0DTE, not an expired past date.
    monkeypatch.setattr(time_et, "now_et", lambda: datetime(2026, 7, 17, 10, 0, tzinfo=time_et.ET))


def _load_real_chain() -> tuple[list, float]:
    data = json.loads(_REAL_CHAIN.read_text(encoding="utf-8"))
    return data["chain"], float(data["spot"])


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_delta_call(s: float, k: float, t: float, sig: float, r: float = 0.0) -> float:
    d1 = (math.log(s / k) + (r + 0.5 * sig * sig) * t) / (sig * math.sqrt(t))
    return _norm_cdf(d1)


def test_bs_charm_matches_finite_difference_of_delta() -> None:
    """Independent check: charm IS dDelta/dt, so it must equal the numerical derivative."""
    cases = [
        (743.29, 745.0, 1 / 365, 0.15),
        (743.29, 740.0, 7 / 365, 0.18),
        (100.0, 100.0, 0.25, 0.20),
        (100.0, 110.0, 0.50, 0.25),
        (50.0, 45.0, 2 / 365, 0.35),
        (400.0, 420.0, 90 / 365, 0.22),
    ]
    for s, k, t, sig in cases:
        analytic = bs_charm(s, k, t, sig)
        assert analytic is not None
        h = t * 1e-5
        finite = (_bs_delta_call(s, k, t - h, sig) - _bs_delta_call(s, k, t + h, sig)) / (2 * h)
        assert abs(analytic - finite) / max(abs(finite), 1e-12) < 1e-4, (
            f"charm != dDelta/dt at S={s} K={k} T={t}: {analytic} vs {finite}"
        )


def test_bs_charm_refuses_degenerate_inputs() -> None:
    assert bs_charm(100.0, 100.0, 0.0, 0.20) is None      # expired
    assert bs_charm(100.0, 100.0, 0.02, 0.0) is None      # no vol
    assert bs_charm(0.0, 100.0, 0.02, 0.20) is None       # no spot


def test_charm_by_strike_on_real_chain_uses_dealer_convention() -> None:
    """net_charm must be call - put, matching the net-GEX dealer convention."""
    chain, spot = _load_real_chain()
    cbs = compute_charm_by_strike(chain, spot)
    assert cbs, "real chain must produce per-strike charm"
    for _k, b in cbs.items():
        assert math.isfinite(b["call_charm"])
        assert math.isfinite(b["put_charm"])
        assert abs(b["net_charm"] - (b["call_charm"] - b["put_charm"])) < 1e-6


def test_charm_walls_are_real_strikes_from_the_chain() -> None:
    chain, spot = _load_real_chain()
    cbs = compute_charm_by_strike(chain, spot)
    call_wall, put_wall = pick_charm_wall_strikes(cbs)
    strikes = set(cbs)
    assert call_wall is None or call_wall in strikes
    assert put_wall is None or put_wall in strikes


def test_charm_by_strike_fails_closed() -> None:
    assert compute_charm_by_strike([], 100.0) == {}
    assert compute_charm_by_strike(None, 100.0) == {}
    chain, _ = _load_real_chain()
    assert compute_charm_by_strike(chain, 0.0) == {}
    assert pick_charm_wall_strikes({}) == (None, None)
