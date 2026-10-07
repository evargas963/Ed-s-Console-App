"""Every producer keeps the full number (operator 2026-10-07: no rounding of a calculated result;
only the screen formats a number for display). Each test runs the producer on a real captured
Schwab chain, valued at the chain's own capture time (passed in, never a patched clock), and
asserts the result is the computation's full value, not one cut to a few decimals.

Real data: SPY's 0DTE chain of 2026-09-22 12:46 ET (tests/fixtures/real_spy_0dte_chain.json, 20
strikes, 764-783) and CRWD's chain of 2026-09-02 (tests/fixtures/real_crwd_complete_chain_quarter.json).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import time_et
from math_exposure_core import compute_exposures_by_strike, compute_net_vanna
from math_levels import GAMMA_FLIP_NARROW, compute_gamma_flip_v2, compute_gamma_profile

FX = Path(__file__).resolve().parent / "fixtures"


def test_the_flip_is_the_profiles_full_zero_crossing():
    """SPY's 20-strike 0DTE chain: the flip is the interpolated zero crossing of the gamma
    profile in full (it was cut to 771.9), inside the delivered strikes; the verdict is NARROW
    because 20 strikes span only ~+/-1.3% of spot, with both span flags False."""
    data = json.loads((FX / "real_spy_0dte_chain.json").read_text(encoding="utf-8"))
    chain, spot = data["chain"], float(data["spot"])
    now = datetime(2026, 9, 22, 12, 46, tzinfo=time_et.ET)
    flip, confidence, diag = compute_gamma_flip_v2(
        chain, spot, profile=compute_gamma_profile(chain, spot, now=now))
    assert confidence == GAMMA_FLIP_NARROW
    assert flip == 771.8964751646467
    assert (diag["strike_lo"], diag["strike_hi"]) == (764.0, 783.0)
    assert diag["span_below_pct"] == (spot - 764.0) / spot and diag["span_above_pct"] == (783.0 - spot) / spot
    assert diag["covers_regime_span"] is False and diag["covers_level_span"] is False


def test_net_vanna_is_the_books_full_sum():
    """RC-362: net vanna = sum of call vanna - sum of put vanna, shares per vol point, and that
    times spot in dollars -- in full (they were cut to two decimals); None on an empty or
    valueless book or no spot."""
    fx = json.loads((FX / "real_crwd_complete_chain_quarter.json").read_text(encoding="utf-8"))
    book, _ = compute_exposures_by_strike(fx["chain"], spot=fx["spot"],
                                          now=datetime(2026, 9, 2, 10, 5, tzinfo=time_et.ET))
    want = sum(b["call_vanna"] for b in book.values()) - sum(b["put_vanna"] for b in book.values())
    out = compute_net_vanna(book, 800.0)
    assert want != round(want, 2), "the book's sum has more than two decimals"
    assert out == {"net_vanna_shares_per_volpt": want, "net_vanna_dollars_per_volpt": want * 800.0}
    assert compute_net_vanna({}, 800.0) is None
    assert compute_net_vanna(book, None) is None
    assert compute_net_vanna({700.0: {"other": 1}}, 800.0) is None
