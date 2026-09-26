"""compute_net_charm/compute_gamma_void_zones/compute_pin_score must fail closed
(skip the contract) when openInterest/volatility is missing, never silently treat
a missing open-interest field as zero exposure."""
from __future__ import annotations

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








def test_pin_score_reports_missing_oi_instead_of_negligible():
    assert compute_pin_score(10_000.0, None) == {"raw": None, "normalized": None, "label": "missing_oi"}
