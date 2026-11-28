"""Max pain is withheld when the chain cannot weigh every strike.

Real data: CRWD's 2026-10-16 expiry, every strike, captured 2026-10-07 10:38:40 ET
(tests/real_chains.py), through option_contract.read_chain and
math_exposure_core.compute_exposures_by_strike. Induced (named): fields taken out of real
contracts, as Schwab leaves a field out.
"""

from calc.math_levels import compute_max_pain
from tests.real_chains import CRWD, crwd_exposures


def test_compute_max_pain_returns_none_for_sparse_chain():
    assert compute_max_pain({}) is None
    # one strike with open interest (a one-sided strike, calls only): no grid to settle over
    one = [ct for ct in CRWD.chain if ct["strikePrice"] == 315.0]
    assert [ct["openInterest"] > 0 for ct in one] == [True, False]
    assert compute_max_pain(crwd_exposures(one)) is None


def test_compute_max_pain_is_withheld_with_a_strike_whose_open_interest_was_not_sent():
    """Induced: the 315 call's openInterest taken out, as Schwab leaves a field out.

    The whole chain weighs every strike's open interest; with one strike's not known, max pain
    over part of it would be a number of ours, so it is "-".
    """
    assert compute_max_pain(crwd_exposures(CRWD.chain)) is not None
    unsent = [
        {k: v for k, v in ct.items() if k != "openInterest"}
        if ct["strikePrice"] == 315.0 and ct["putCall"] == "CALL"
        else ct
        for ct in CRWD.chain
    ]
    assert compute_max_pain(crwd_exposures(unsent)) is None
