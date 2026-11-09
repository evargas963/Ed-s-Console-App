"""compute_pin_score must fail closed.

A strike whose open interest Schwab did not send has no open-interest share: the pin score reports
the missing open interest, never a negligible score.

Real data: CRWD's 2026-10-16 expiry captured 2026-10-07 10:38:40 ET (tests/real_chains.py), through
option_contract.read_chain and math_exposure_core.compute_exposures_by_strike. Induced (named): the
open interest taken out of the put at strike 270, as Schwab leaves a field out.
"""

from __future__ import annotations

from math_exposure_core import (
    compute_exposures_by_strike,
    strike_oi_legs,
    total_gex_dollars_at_strike,
)
from math_probabilities import compute_pin_score
from option_contract import read_chain
from tests.real_chains import CRWD


def test_pin_score_reports_missing_oi_instead_of_negligible():
    chain = [dict(ct) for ct in CRWD.chain]
    del next(c for c in chain if c["strikePrice"] == 270.0 and c["putCall"] == "PUT")[
        "openInterest"
    ]
    exposures = compute_exposures_by_strike(read_chain(chain), spot=CRWD.spot, now=CRWD.now)[0]
    assert strike_oi_legs(exposures[270.0]) is None  # its open-interest share is not known
    gex = total_gex_dollars_at_strike(
        compute_exposures_by_strike(read_chain(CRWD.chain), spot=CRWD.spot, now=CRWD.now)[0][270.0]
    )
    assert gex is not None and gex > 0
    assert compute_pin_score(gex, None) == {
        "raw": None,
        "normalized": None,
        "label": "missing_oi",
    }
