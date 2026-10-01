"""Chain net GEX$ / net DEX$: absence is None, never 0.0 and never raw units.

  * A book with no valid delta (or gamma) has no net DEX (or GEX), never 0.0.
  * A spot-built book whose gammas are all invalid is never reported in raw units as DEX$.
  * "dollarized" is stamped by the one producer (compute_exposures_by_strike) from whether spot
    was provided.
"""
from __future__ import annotations

from datetime import datetime

from math_exposure_core import (
    compute_exposures_by_strike,
)
from time_et import ET

SPOT = 500.0
#: the instant the hand-built contracts below are valued at: the morning of their expiry day
_NOW = datetime(2026, 9, 18, 10, 0, tzinfo=ET)


def _c(strike, typ, *, delta, gamma, oi=1000):
    # institutional-synthetic-ok: these tests MUST feed invalid greeks (NaN / None delta and
    # gamma) to prove absence stays None; a captured chain cannot be made invalid on demand.
    return {
        "strikePrice": strike, "putCall": typ, "daysToExpiration": 0, "delta": delta, "gamma": gamma,
        "openInterest": oi, "multiplier": 100, "expirationDate": "2026-09-18T20:00:00.000+00:00",
    }


def _book(contracts, spot=SPOT):
    ex, _ = compute_exposures_by_strike(contracts, spot=spot, now=_NOW)
    return ex, sorted(ex)


# ── T-01 / T-04 / M-06: per-strike bars and OI totals from the one producer ────

def test_unreported_oi_is_unknown_and_one_sided_oi_is_known():
    from math_exposure_core import book_total_oi, strike_total_oi
    ex, _ = _book([_c(500.0, "CALL", delta=0.5, gamma=0.02, oi=1000),      # one-sided: known
                   _c(510.0, "CALL", delta=0.4, gamma=0.02, oi=300),
                   _c(510.0, "PUT", delta=-0.4, gamma=0.02, oi=None)])     # OI not reported
    assert strike_total_oi(ex[500.0]) == 1000.0
    assert strike_total_oi(ex[510.0]) is None
    assert book_total_oi(ex) is None      # one unknown strike -> the book total is unknown


def test_per_strike_bars_are_dollar_gex_on_valid_gamma_only():
    from terrain_engine import _per_strike_rows
    cts = [_c(500.0, "CALL", delta=0.5, gamma=0.02),
           _c(510.0, "CALL", delta=0.5, gamma=float("nan"))]              # invalid gamma
    cts[0]["totalVolume"] = 0                                             # a REAL zero volume
    ex, _ = _book(cts)
    rows = _per_strike_rows(ex)
    assert [r[0] for r in rows] == [500.0]          # no bar for the invalid-gamma strike
    assert rows[0][2] == 0                          # reported zero stays zero
    ex2, _ = _book([_c(500.0, "CALL", delta=0.5, gamma=0.02)])
    assert _per_strike_rows(ex2)[0][2] is None
    ex3, _ = _book(cts, spot=None)
    assert _per_strike_rows(ex3) == []         # no spot -> no dollar bars, no raw ones


# ── max pain is PER EXPIRY (standard definition) -- the front expiry, labelled ────

def test_terrain_max_pain_uses_only_the_front_expiry():
    from math_levels import compute_max_pain
    from terrain_engine import compute_terrain

    def c(k, typ, oi, dte):
        ct = _c(k, typ, delta=0.5 if typ == "CALL" else -0.5, gamma=0.02, oi=oi)
        ct["daysToExpiration"] = dte
        if dte:
            ct["expirationDate"] = "2026-10-16T20:00:00.000+00:00"
        return ct

    front = [c(495.0, "PUT", 1000, 0), c(500.0, "CALL", 50, 0), c(500.0, "PUT", 50, 0),
             c(505.0, "CALL", 1000, 0)]
    # a later expiry with a very different distribution that would drag a POOLED max pain
    later = [c(520.0, "CALL", 90000, 30), c(530.0, "PUT", 90000, 30)]
    snap = compute_terrain("SPY", front + later, SPOT, now=_NOW)
    ex_front, _ = _book(front)
    assert snap.max_pain_dte == 0
    assert snap.max_pain == compute_max_pain(ex_front) == 500.0
    ex_all, _ = _book(front + later)
    assert compute_max_pain(ex_all) != snap.max_pain     # pooling would have moved it
