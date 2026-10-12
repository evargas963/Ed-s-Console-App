"""Schwab's Greeks are used exactly as Schwab sends them (math_exposure_core.greek_reported).

The one value not used as a number is Schwab's -999, its code for "no value" (on the Greek or on
the contract's volatility): that contract adds nothing and is counted in greeks_missing. A strike
where no contract carried a reported Greek has no value, never its 0.0 initialiser.
"""
from __future__ import annotations

from datetime import datetime

from math_exposure_core import (
    MISSING_GREEK_SENTINEL,
    bucket_metric,
    compute_exposures_by_strike,
    exposure_books,
    greek_reported,
)
from server import project_gamma_surface
from tests.real_chains import SPY_0DTE
from time_et import ET

SPOT = 100.0
#: the hand-built contracts below (expiring 2026-10-01, a date Schwab's /markets answers) are
#: valued the day before their expiry
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=ET)


def _ct(strike: float, side: str, oi, *, gamma=0.04, delta=0.5, iv=20.0):
    # institutional-synthetic-ok: each case needs one exactly-controlled field
    return {
        "strikePrice": strike, "putCall": side, "openInterest": oi, "multiplier": 100.0,
        "delta": delta if side == "CALL" else -abs(delta), "gamma": gamma, "vega": 0.01,
        "volatility": iv, "totalVolume": 0, "expirationDate": "2026-10-01T20:00:00.000+00:00",
    }


def test_every_value_schwab_sends_is_used_as_sent():
    for g in (0.0, 0.001, 0.04, 5.274, -91965.237):
        assert greek_reported(g, iv=20.0)
    assert greek_reported(1.0, iv=61.39) and greek_reported(1.001, iv=20.0)


def test_schwabs_no_value_code_is_not_a_number():
    assert not greek_reported(MISSING_GREEK_SENTINEL, iv=20.0)
    assert not greek_reported(0.04, iv=MISSING_GREEK_SENTINEL)
    assert not greek_reported(None, iv=20.0)


def test_a_no_value_contract_leaves_its_leg_and_the_strikes_net_unknown():
    """A put with open interest and no value: the put leg's sums and the strike's net are not
    known (the call's GEX is not the strike's net); the call leg stands. Open interest 0 adds a
    known 0 whatever its Greeks."""
    none = _ct(100.0, "PUT", 700, iv=MISSING_GREEK_SENTINEL)
    call = _ct(100.0, "CALL", 500, gamma=0.04)
    exp, diag = compute_exposures_by_strike([none, call], spot=SPOT, now=NOW)
    assert bucket_metric(exp[100.0], "call_gamma") == 0.04 * 500 * 100
    assert bucket_metric(exp[100.0], "put_gamma") is None
    for net in ("net_gex_1pct", "net_dex_dollars", "net_vanna"):
        assert bucket_metric(exp[100.0], net) is None, net
    assert diag.greeks_missing == 1
    no_oi = _ct(100.0, "PUT", 0, iv=MISSING_GREEK_SENTINEL)
    exp, _ = compute_exposures_by_strike([no_oi, call], spot=SPOT, now=NOW)
    assert bucket_metric(exp[100.0], "net_gex_1pct") == bucket_metric(exp[100.0], "call_gex_1pct")


def test_real_spy_capture_is_used_as_schwab_sent_it():
    """SPY's same-day chain of 2026-10-07 12:32 ET (tests/real_chains.py), as Schwab sent it,
    valued at its capture: the in-the-money 767-769 calls report delta 1 / gamma 0 and count as
    reported; the 777 strike's call and put gamma are Schwab's own times open interest."""
    exp, diag = compute_exposures_by_strike(SPY_0DTE.chain, spot=SPY_0DTE.spot, now=SPY_0DTE.now)
    assert diag.greeks_missing == 0
    assert bucket_metric(exp[767.0], "call_delta") == 1 * 1091 * 100.0
    assert bucket_metric(exp[767.0], "call_gamma") == 0.0
    assert bucket_metric(exp[777.0], "call_gamma") == 0.18283389 * 2898 * 100.0
    assert bucket_metric(exp[777.0], "put_gamma") == 0.18262005 * 7656 * 100.0


def test_a_strike_no_greek_reached_is_blank_not_zero():
    exp, _ = compute_exposures_by_strike([_ct(100.0, "CALL", 500, iv=MISSING_GREEK_SENTINEL)], spot=SPOT, now=NOW)
    assert bucket_metric(exp[100.0], "net_gex_1pct") is None
    surface = project_gamma_surface([_ct(100.0, "CALL", 500, iv=MISSING_GREEK_SENTINEL)],
                                    exposure_books([_ct(100.0, "CALL", 500, iv=MISSING_GREEK_SENTINEL)], spot=SPOT,
                                                   now=NOW))
    row = [r for r in surface["cells"] if r["strike"] == 100.0][0]
    # no put is listed at the strike: its OI is the call's 500 (strike_oi_legs, the one reader)
    assert row["gex"] == [None] and row["oi"] == [{"call": 500, "put": 0, "total": 500}]


def test_genuine_balanced_zero_is_a_zero():
    call = _ct(100.0, "CALL", 500)
    put = _ct(100.0, "PUT", 500)
    exp, _ = compute_exposures_by_strike([call, put], spot=SPOT, now=NOW)
    assert bucket_metric(exp[100.0], "net_gex_1pct") == 0.0
    surface = project_gamma_surface([call, put], exposure_books([call, put], spot=SPOT, now=NOW))
    assert [r for r in surface["cells"] if r["strike"] == 100.0][0]["gex"] == [0]
