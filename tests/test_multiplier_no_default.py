from __future__ import annotations

import json

from backfill_flow_imbalance import _contracts_from_chain_json
from math_exposure_core import compute_exposures_by_strike


def _contract(**overrides):
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
    assert bucket["call_oi_dollars"] == 25_000.0
    assert bucket["call_delta"] == 25.0


def test_exposures_skip_missing_multiplier_instead_of_silent_100_default():
    ct = _contract()
    ct.pop("multiplier")

    exposures, diag = compute_exposures_by_strike([ct], spot=500.0)

    assert exposures == {}
    assert diag.contracts_used == 0
    assert diag.greeks_missing == 1


def test_exposures_preserve_missing_total_volume_instead_of_silent_zero():
    ct = _contract()
    ct.pop("totalVolume")

    exposures, diag = compute_exposures_by_strike([ct], spot=500.0)

    assert diag.contracts_used == 1
    assert exposures[500.0]["call_volume"] is None


def test_exposures_preserve_missing_open_interest_instead_of_silent_zero():
    ct = _contract()
    ct.pop("openInterest")

    exposures, diag = compute_exposures_by_strike([ct], spot=500.0, require_oi=False)

    assert diag.contracts_used == 1
    assert exposures[500.0]["call_oi"] is None
    assert exposures[500.0]["call_oi_mult"] == 0.0


def test_exposures_skip_missing_bidsize_instead_of_coercing_schwab_none_to_zero():
    ct = _contract()
    ct.pop("bidSize")

    exposures, diag = compute_exposures_by_strike([ct], spot=500.0)

    assert diag.contracts_used == 1
    assert exposures[500.0]["call_bid_size"] == 0.0


def test_flow_backfill_normalizer_does_not_default_missing_multiplier_to_100():
    raw = json.dumps([_contract(multiplier=5), {k: v for k, v in _contract().items() if k != "multiplier"}])

    rows = _contracts_from_chain_json(raw)

    assert rows[0]["multiplier"] == 5.0
    assert rows[1]["multiplier"] is None
