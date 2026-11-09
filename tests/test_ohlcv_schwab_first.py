"""Missing exposure buckets read as absent, not zero.

Real data: CRWD's 2026-10-16 expiry captured 2026-10-07 10:38:40 ET (tests/real_chains.py), through
option_contract.read_chain and math_exposure_core.compute_exposures_by_strike. Strike 297.5: open
interest Schwab sent as 0 on both sides, a net GEX of exactly 0. Induced (named): the open interest
taken out of one real contract, as Schwab leaves a field out.
"""

from __future__ import annotations

from math_exposure_core import bucket_metric, compute_exposures_by_strike, net_gex_dollars_at_strike
from option_contract import read_chain
from tests.real_chains import CRWD


def _bucket(chain: list[dict], strike: float) -> dict:
    exposures = compute_exposures_by_strike(read_chain(chain), spot=CRWD.spot, now=CRWD.now)[0]
    return exposures[strike]


def test_bucket_metric_missing_returns_none_not_zero():
    assert bucket_metric({}, "net_gex_1pct") is None
    assert net_gex_dollars_at_strike({}) is None
    chain = [dict(ct) for ct in CRWD.chain]
    del next(c for c in chain if c["strikePrice"] == 100.0 and c["putCall"] == "CALL")[
        "openInterest"
    ]
    assert bucket_metric(_bucket(chain, 100.0), "net_gex_1pct") is None
    assert net_gex_dollars_at_strike(_bucket(chain, 100.0)) is None
    zero = [ct["openInterest"] for ct in CRWD.chain if ct["strikePrice"] == 297.5]
    assert zero == [0, 0]
    assert bucket_metric(_bucket(CRWD.chain, 297.5), "net_gex_1pct") == 0.0
