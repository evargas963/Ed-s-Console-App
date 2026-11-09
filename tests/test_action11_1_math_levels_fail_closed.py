"""math_levels fails closed on a chain whose open interest or multiplier is not known.

Real data: CRWD's 2026-10-16 expiry, every strike, captured 2026-10-07 10:38:40 ET
(tests/real_chains.py), read by the real reader (option_contract.read_chain) and summed per strike
by the real code (math_exposure_core.compute_exposures_by_strike). It holds one-sided strikes
(46.25: puts only) and strikes whose open interest Schwab sent as 0 on both sides (297.5).
Induced (named): one field taken out of one real contract, as Schwab leaves a field out.
"""

from __future__ import annotations

import collections

from math_exposure_core import compute_exposures_by_strike, key_level_strikes_with_oi
from math_levels import compute_max_pain
from option_contract import read_chain
from tests.real_chains import CRWD


def _exposures(chain: list[dict]) -> dict[float, dict]:
    return compute_exposures_by_strike(read_chain(chain), spot=CRWD.spot, now=CRWD.now)[0]


def _without(field: str, strike: float, side: str) -> list[dict]:
    """The real chain with `field` taken out of the `side` contract at `strike`."""
    chain = [dict(ct) for ct in CRWD.chain]
    ct = next(c for c in chain if c["strikePrice"] == strike and c["putCall"] == side)
    del ct[field]
    return chain


def _oi_mult_by_strike() -> dict[float, list[float]]:
    """Each strike's [call, put] open interest times multiplier, summed from Schwab's fields."""
    out: dict[float, list[float]] = collections.defaultdict(lambda: [0.0, 0.0])
    for ct in CRWD.chain:
        out[ct["strikePrice"]][ct["putCall"] == "PUT"] += ct["openInterest"] * ct["multiplier"]
    return out


def test_key_level_strikes_with_oi_counts_one_sided_and_skips_unknown():
    weights = _oi_mult_by_strike()
    known = sorted(k for k, (c, p) in weights.items() if c + p > 0)
    assert 46.25 in known and weights[46.25][0] == 0.0  # one-sided: counts (M-06)
    assert 297.5 not in known and weights[297.5] == [0.0, 0.0]  # known zero OI: excluded
    assert key_level_strikes_with_oi(_exposures(CRWD.chain)) == known
    # unknown OI: excluded
    unknown = _exposures(_without("openInterest", 100.0, "PUT"))
    assert key_level_strikes_with_oi(unknown) == [k for k in known if k != 100.0]


def test_compute_max_pain_ignores_strike_when_oi_present_but_mult_missing():
    # positive OI with no multiplier: the strike can't be weighed, so NO max pain -- it
    # used to be skipped, giving a max pain over part of the open interest (M-08)
    assert compute_max_pain(_exposures(_without("multiplier", 100.0, "CALL"))) is None


def test_compute_max_pain_skips_strike_with_only_one_oi_mult():
    """Every strike counts, a one-sided one too (M-08): max pain as its definition gives it.

    The settlement strike, among strikes with open interest, at which the in-the-money payout
    sum(max(0, S - K) * call OI * mult + max(0, K - S) * put OI * mult) is least; of equal
    pains the lowest strike. Worked out here from Schwab's fields.
    """
    weights = _oi_mult_by_strike()
    strikes = sorted(k for k, (c, p) in weights.items() if c + p > 0)

    def pain(s: float) -> float:
        return sum(
            max(0.0, s - k) * weights[k][0] + max(0.0, k - s) * weights[k][1] for k in strikes
        )

    want = min(strikes, key=pain)
    assert compute_max_pain(_exposures(CRWD.chain)) == want
