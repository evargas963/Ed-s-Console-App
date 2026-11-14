"""Max pain is withheld when the chain cannot weigh every strike.

Real data: CRWD's 2026-10-16 expiry, every strike, captured 2026-10-07 10:38:40 ET
(tests/real_chains.py), through option_contract.read_chain and
math_exposure_core.compute_exposures_by_strike. Induced (named): fields taken out of real
contracts, as Schwab leaves a field out.
"""

from math_levels import compute_max_pain
from tests.real_chains import CRWD, crwd_exposures


def test_compute_max_pain_returns_none_for_sparse_chain():
    assert compute_max_pain({}) is None
    # one strike with open interest (a one-sided strike, calls only): no grid to settle over
    one = [ct for ct in CRWD.chain if ct["strikePrice"] == 315.0]
    assert [ct["openInterest"] > 0 for ct in one] == [True, False]
    assert compute_max_pain(crwd_exposures(one)) is None
