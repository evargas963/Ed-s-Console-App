"""Max pain is withheld when the chain cannot weigh every strike.

Real data: CRWD's 2026-10-16 expiry, every strike, captured 2026-10-07 10:38:40 ET
(tests/real_chains.py), through option_contract.read_chain and
math_exposure_core.compute_exposures_by_strike. Induced (named): fields taken out of real
contracts, as Schwab leaves a field out.
"""

from math_exposure_core import compute_exposures_by_strike
from math_levels import compute_max_pain
from option_contract import read_chain
from tests.real_chains import CRWD


def _exposures(chain: list[dict]) -> dict[float, dict]:
    return compute_exposures_by_strike(read_chain(chain), spot=CRWD.spot, now=CRWD.now)[0]


def test_compute_max_pain_returns_none_for_sparse_chain():
    assert compute_max_pain({}) is None
    # one strike with open interest (a one-sided strike, calls only): no grid to settle over
    one = [ct for ct in CRWD.chain if ct["strikePrice"] == 315.0]
    assert [ct["openInterest"] > 0 for ct in one] == [True, False]
    assert compute_max_pain(_exposures(one)) is None


def test_compute_max_pain_skips_strikes_with_missing_multiplier():
    # a strike with call open interest and no multiplier: never a synthetic *100 (dbf6e9e) and no
    # longer skipped either (M-08, 2026-09-24) -- a max pain that leaves out real OI is withheld.
    chain = [dict(ct) for ct in CRWD.chain]
    ct = next(c for c in chain if c["strikePrice"] == 315.0 and c["putCall"] == "CALL")
    assert ct["putCall"] == "CALL" and ct["openInterest"] > 0
    del ct["multiplier"]
    assert compute_max_pain(_exposures(chain)) is None
