"""Schwab's Greeks are used exactly as Schwab sends them (math_exposure_core.greek_reported).

The one value not used as a number is Schwab's -999, its code for "no value" (on the Greek or on
the contract's volatility): that contract adds nothing and is counted in greeks_missing. A strike
where no contract carried a reported Greek has no value, never its 0.0 initialiser.
"""
from __future__ import annotations

import json
from pathlib import Path

from math_exposure_core import (
    MISSING_GREEK_SENTINEL,
    bucket_metric,
    compute_exposures_by_strike,
    exposure_books,
    greek_reported,
)
from server import project_gamma_surface

_FX = Path(__file__).resolve().parent / "fixtures"
SPOT = 100.0


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


def test_a_no_value_contract_adds_nothing_and_the_rest_of_the_strike_counts():
    none = _ct(100.0, "PUT", 700, iv=MISSING_GREEK_SENTINEL)
    call = _ct(100.0, "CALL", 500, gamma=0.04)
    exp, diag = compute_exposures_by_strike([none, call], spot=SPOT)
    assert bucket_metric(exp[100.0], "call_gamma") == 0.04 * 500 * 100
    assert bucket_metric(exp[100.0], "put_gamma") == 0.0     # the put leg carried no value
    assert diag.greeks_missing == 1


def test_real_spy_capture_is_used_as_schwab_sent_it():
    """tests/fixtures/real_spy_0dte_chain.json (SPY 2026-09-22 12:46 ET), as Schwab sent it:
    the in-the-money 764-766 calls report delta 1.0 / gamma 0.0 and count as reported; the
    773 strike's call and put gamma are Schwab's 0.245 times open interest."""
    fx = json.loads((_FX / "real_spy_0dte_chain.json").read_text(encoding="utf-8"))
    exp, diag = compute_exposures_by_strike(fx["chain"], spot=fx["spot"], require_oi=True)
    assert diag.greeks_missing == 0
    assert bucket_metric(exp[764.0], "call_delta") == 1.0 * 1685 * 100
    assert bucket_metric(exp[764.0], "call_gamma") == 0.0
    assert bucket_metric(exp[773.0], "call_gamma") == 0.245 * 9151 * 100
    assert bucket_metric(exp[773.0], "put_gamma") == 0.245 * 9368 * 100


def test_a_strike_no_greek_reached_is_blank_not_zero():
    exp, _ = compute_exposures_by_strike([_ct(100.0, "CALL", 500, iv=MISSING_GREEK_SENTINEL)], spot=SPOT)
    assert bucket_metric(exp[100.0], "net_gex_1pct") is None
    surface = project_gamma_surface([_ct(100.0, "CALL", 500, iv=MISSING_GREEK_SENTINEL)],
                                    exposure_books([_ct(100.0, "CALL", 500, iv=MISSING_GREEK_SENTINEL)], spot=SPOT))
    row = [r for r in surface["cells"] if r["strike"] == 100.0][0]
    assert row["gex"] == [None] and row["oi"] == [{"call": 500, "put": None}]


def test_genuine_balanced_zero_is_a_zero():
    call = _ct(100.0, "CALL", 500)
    put = _ct(100.0, "PUT", 500)
    exp, _ = compute_exposures_by_strike([call, put], spot=SPOT)
    assert bucket_metric(exp[100.0], "net_gex_1pct") == 0.0
    surface = project_gamma_surface([call, put], exposure_books([call, put], spot=SPOT))
    assert [r for r in surface["cells"] if r["strike"] == 100.0][0]["gex"] == [0]


def test_no_cell_is_ever_refilled_from_an_older_value():
    import inspect

    import db as db_mod
    import server
    src = inspect.getsource(server)
    for gone in ("_backfill_gex_cells_from_last_valid", "_LAST_VALID_GEX_CELLS",
                 "banked_morning_reference"):
        assert gone not in src, gone
    assert not hasattr(db_mod.EdDB, "load_gamma_surface_last_valid")
    assert not hasattr(db_mod.EdDB, "persist_gamma_surface_last_valid")
