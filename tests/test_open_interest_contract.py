"""compute_net_charm/compute_gamma_void_zones/compute_pin_score must fail closed
(skip the contract) when openInterest/volatility is missing, never silently treat
a missing open-interest field as zero exposure."""
from __future__ import annotations

from math_exposure_core import compute_net_charm
from math_levels import compute_gamma_void_zones
from math_probabilities import compute_pin_score


def _charm_contract(**overrides) -> dict:
    # institutional-synthetic-ok: fail-closed charm tests remove openInterest/volatility
    # to prove the contract is skipped (not silently zeroed); needs controlled input.
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


def test_net_charm_skips_contract_missing_schwab_open_interest():
    ct = _charm_contract()
    ct.pop("openInterest")

    out = compute_net_charm([ct], 500.0, "2099-05-05")

    assert out["contracts_used"] == 0
    assert out["net_charm_daily"] is None
    assert out["charm_direction"] is None
    assert out["charm_magnitude"] is None


def test_net_charm_skips_contract_missing_schwab_volatility():
    ct = _charm_contract()
    ct.pop("volatility")

    out = compute_net_charm([ct], 500.0, "2099-05-05")

    assert out["contracts_used"] == 0
    assert out["charm_direction"] is None


def test_gamma_void_does_not_classify_missing_oi_as_low_oi():
    exposures = {
        495.0: {"call_gamma": 0.0, "put_gamma": 0.0, "net_gex_1pct": 1.0, "call_oi": None, "put_oi": None},
        500.0: {"call_gamma": 0.0, "put_gamma": 0.0, "net_gex_1pct": 10.0, "call_oi": 100.0, "put_oi": 100.0},
        505.0: {"call_gamma": 0.0, "put_gamma": 0.0, "net_gex_1pct": 1.0, "call_oi": None, "put_oi": None},
    }

    assert compute_gamma_void_zones(exposures, spot=500.0, min_width_strikes=1) == []


def test_pin_score_reports_missing_oi_instead_of_negligible():
    assert compute_pin_score(10_000.0, None) == {"raw": None, "normalized": None, "label": "missing_oi"}
