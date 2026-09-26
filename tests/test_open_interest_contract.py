"""compute_net_charm/compute_gamma_void_zones/compute_pin_score must fail closed
(skip the contract) when openInterest/volatility is missing, never silently treat
a missing open-interest field as zero exposure."""
from __future__ import annotations

from math_probabilities import compute_pin_score










def test_pin_score_reports_missing_oi_instead_of_negligible():
    assert compute_pin_score(10_000.0, None) == {"raw": None, "normalized": None, "label": "missing_oi"}
