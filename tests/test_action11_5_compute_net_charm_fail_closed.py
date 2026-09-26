"""Action 11.5: compute_net_charm fail-closed when no contracts contribute."""

from __future__ import annotations



def _charm_contract(**overrides) -> dict:
    # institutional-synthetic-ok: fail-closed charm test needs controlled contracts to
    # prove "unavailable when no contracts contribute".
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


def test_rc245_one_aggregate_is_priced_at_one_instant():
    """RC-245: every contract summed into a single published number must share ONE clock read.

    The loop used to call `time_to_expiry_years(..., now=None)` per contract, so each one
    re-read the clock and a 188-contract aggregate mixed instants that drifted across the
    loop — a single figure that did not describe a single moment. Proven by counting clock
    reads through the module's own resolution path, not by reading the source.
    """
    import math_exposure_core as mec

    reads = {"n": 0}
    real_now_et = __import__("time_et").now_et

    def _counting_now_et():
        reads["n"] += 1
        return real_now_et()

    import time_et

    orig = time_et.now_et
    time_et.now_et = _counting_now_et
    try:
        contracts = [
            _charm_contract(strikePrice=float(500 + i), putCall="CALL" if i % 2 else "PUT")
            for i in range(40)
        ]
        out = mec.compute_net_charm(contracts, 500.0, "2099-05-05")
    finally:
        time_et.now_et = orig

    assert out["contracts_used"] > 0, "fixture must actually exercise the loop"
    assert reads["n"] <= 1, (
        f"the clock was read {reads['n']} times for ONE aggregate — contracts summed into a "
        f"single number must be priced at a single instant (RC-245)"
    )


def test_rc245_time_to_expiry_is_resolved_once_per_distinct_expiry():
    """The invariant that was living inside the loop: T depends only on (expiry, now)."""
    import math_exposure_core as mec
    import time_et

    calls: list[str] = []
    orig = time_et.time_to_expiry_years

    def _counting_tte(exp, **kw):
        calls.append(str(exp))
        return orig(exp, **kw)

    time_et.time_to_expiry_years = _counting_tte
    try:
        contracts = [_charm_contract(strikePrice=float(500 + i)) for i in range(30)]
        out = mec.compute_net_charm(contracts, 500.0, "2099-05-05")
    finally:
        time_et.time_to_expiry_years = orig

    assert out["contracts_used"] > 0
    assert len(calls) <= len(set(calls)) or len(calls) <= 1, (
        f"time_to_expiry_years ran {len(calls)} times for {len(set(calls))} distinct "
        f"expiries — an invariant is being recomputed inside the loop (RC-245)"
    )












