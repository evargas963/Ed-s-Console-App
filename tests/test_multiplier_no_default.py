"""compute_exposures_by_strike's contract multiplier must come from the real chain
data, never a hardcoded/default multiplier -- a wrong default silently mis-scales
every exposure computed from that contract."""
from __future__ import annotations


from datetime import datetime

from math_exposure_core import compute_exposures_by_strike
from time_et import ET

#: the instant the hand-built contract below is valued at: three days before it expires
_NOW = datetime(2026, 9, 15, 12, 0, tzinfo=ET)


def _contract(**overrides):
    # institutional-synthetic-ok: fail-closed tests deliberately remove/alter single
    # fields (multiplier, openInterest, bidSize, totalVolume) to prove no-silent-default
    # behavior; such malformed contracts cannot be sourced from real data.
    base = {
        "strikePrice": 500.0,
        "putCall": "CALL",
        "openInterest": 10,
        "totalVolume": 1,
        "bidSize": 1,
        "askSize": 1,
        "delta": 0.5,
        "gamma": 0.1,
        "vega": 0.02,
        "volatility": 20.0,
        "multiplier": 5,
        "expirationDate": "2026-09-18T20:00:00.000+00:00",
    }
    base.update(overrides)
    return base


def test_exposures_use_schwab_multiplier_without_defaulting_to_100():
    exposures, diag = compute_exposures_by_strike([_contract()], spot=500.0, now=_NOW)

    bucket = exposures[500.0]
    assert diag.contracts_used == 1
    assert bucket["call_oi_mult"] == 50.0
    assert bucket["call_delta"] == 25.0


def test_exposures_skip_missing_multiplier_instead_of_silent_100_default():
    ct = _contract()
    ct.pop("multiplier")

    exposures, diag = compute_exposures_by_strike([ct], spot=500.0, now=_NOW)

    assert exposures == {}
    assert diag.contracts_used == 0
    assert diag.greeks_missing == 1


def test_exposures_preserve_missing_total_volume_instead_of_silent_zero():
    ct = _contract()
    ct.pop("totalVolume")

    exposures, diag = compute_exposures_by_strike([ct], spot=500.0, now=_NOW)

    assert diag.contracts_used == 1
    assert exposures[500.0]["call_volume"] is None


def test_exposures_preserve_missing_open_interest_instead_of_silent_zero():
    ct = _contract()
    ct.pop("openInterest")

    exposures, diag = compute_exposures_by_strike([ct], spot=500.0, now=_NOW)

    assert diag.contracts_used == 0
    assert exposures[500.0]["oi_unreported"] == 1
    assert exposures[500.0]["call_oi"] is None
    assert exposures[500.0]["has_oi"] is False

