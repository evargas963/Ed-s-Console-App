"""compute_exposures_by_strike's contract multiplier must come from the real chain
data, never a hardcoded/default multiplier -- a wrong default silently mis-scales
every exposure computed from that contract."""
from __future__ import annotations


from math_exposure_core import bucket_metric, compute_exposures_by_strike


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
    }
    base.update(overrides)
    return base


def test_exposures_use_schwab_multiplier_without_defaulting_to_100():
    exposures, diag = compute_exposures_by_strike([_contract()], spot=500.0)

    bucket = exposures[500.0]
    assert diag.contracts_used == 1
    assert bucket["call_oi_mult"] == 50.0
    assert bucket["call_delta"] == 25.0


def test_a_missing_multiplier_leaves_the_exposure_unknown_and_keeps_the_open_interest():
    """No silent 100: the contract's exposure is not known, its leg's sums are absent; its open
    interest and volume, which Schwab sent, are kept (M-14: the contract used to be dropped)."""
    ct = _contract()
    ct.pop("multiplier")

    exposures, diag = compute_exposures_by_strike([ct], spot=500.0)

    bucket = exposures[500.0]
    assert diag.contracts_used == 0
    assert diag.greeks_missing == 1
    assert bucket["call_oi"] == 10 and bucket["call_volume"] == 1
    for key in ("call_gex_1pct", "net_gex_1pct", "call_dex_dollars", "net_vanna", "call_oi_mult"):
        assert bucket_metric(bucket, key) is None, key


def test_exposures_preserve_missing_total_volume_instead_of_silent_zero():
    ct = _contract()
    ct.pop("totalVolume")

    exposures, diag = compute_exposures_by_strike([ct], spot=500.0)

    assert diag.contracts_used == 1
    assert exposures[500.0]["call_volume"] is None


def test_exposures_preserve_missing_open_interest_instead_of_silent_zero():
    ct = _contract()
    ct.pop("openInterest")

    exposures, diag = compute_exposures_by_strike([ct], spot=500.0)

    assert diag.contracts_used == 0
    assert exposures[500.0]["oi_unreported"] == 1
    assert exposures[500.0]["call_oi"] is None
    assert bucket_metric(exposures[500.0], "net_gex_1pct") is None

