"""Action 11.5: compute_net_charm fail-closed when no contracts contribute."""

from __future__ import annotations

from math_exposure_core import compute_net_charm


def _charm_contract(**overrides) -> dict:
    base = {
        "expirationDate": "2099-05-05",
        "putCall": "CALL",
        "strikePrice": 500.0,
        "gamma": 0.1,
        "delta": 0.5,
        "volatility": 20.0,
        "openInterest": 100.0,
        "multiplier": 100.0,
        "daysToExpiration": 1,
    }
    base.update(overrides)
    return base


def test_net_charm_unavailable_when_no_contracts_match():
    out = compute_net_charm([], 500.0, "2099-05-05")
    assert out["contracts_used"] == 0
    assert out["charm_direction"] is None
    assert out["charm_magnitude"] is None
    assert out["net_charm_daily"] is None


def test_net_charm_emits_magnitude_when_contracts_used():
    out = compute_net_charm([_charm_contract()], 500.0, "2099-05-05")
    assert out["contracts_used"] > 0
    assert out["charm_direction"] in ("buying", "selling", "neutral")
    assert out["charm_magnitude"] in ("large", "moderate", "small", "negligible")
