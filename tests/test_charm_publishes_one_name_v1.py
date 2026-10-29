"""RC-302 — charm published one borrowed value under two names, and nothing read the second.

MEASURED. `compute_net_charm` returned the caller-supplied strike under BOTH `drift_toward`
and `gamma_pin`, on the success path and the error path, with an intermediate alias between
them. A `git ls-files`-scoped search for any reader of `charm["gamma_pin"]` returned ZERO.

So the second name carried no information and existed only to collide: `gamma_pin` is
simultaneously terrain's max-TOTAL-gamma strike over the wide multi-expiry book (Cursor
faucet conflict 1) and, here, the selected-expiry max-absolute-net-GEX strike that charm was
handed and did NOT compute (RC-292, RC-294). One identifier, two definitions, two chain
scopes — and one publisher with no audience.

Charm measures directional hedge DECAY. It does not compute a price attractor, so
`drift_toward` is a caller's label travelling through, and one name for it is one too many
only if nothing needs it at all.
"""

from __future__ import annotations

def test_the_two_pin_metrics_are_different_quantities():
    """RC-315: demonstrate the distinction the register describes, instead of describing it.

    RC-292 measured both at 775.0 on live SPY and warned that a coincidence reads as a
    contract. This builds a book where they SEPARATE, so the claim "these are two metrics"
    is executed rather than asserted — and so the register's wording cannot quietly drift
    back to treating them as one.

    It also pins what each one IS. `pick_pin_and_strength` maximises |call| + |put| GEX$: a
    gross CONCENTRATION, where the most hedging sits. `pick_net_gex_peak_strike` maximises
    |call - put|: where the SIGNED book leans. The first discards the sign, and the sign is
    what decides whether hedging at a strike stabilises or repels — which is why neither is
    a demonstrated magnet and why RC-315 withdrew the claim that one of them is.
    """
    from math_exposure_core import pick_net_gex_peak_strike, pick_pin_and_strength

    # RC-320: the PRODUCTION sign convention, verified against the real captured SPY chain
    # rather than assumed — `compute_exposures_by_strike` stores put_gex_1pct NONNEGATIVE
    # (14 positive buckets, 0 negative on that chain) and net = call - put. A first version
    # of this fixture used negative put values, which no producer emits, so it exercised the
    # pickers on data the repo cannot generate.
    #
    # 800: enormous and nearly BALANCED — the biggest gross concentration, tiny net.
    # 810: smaller book, entirely one-sided — the biggest signed-net peak.
    exposures = {
        800.0: {"call_gex_1pct": 9.0e9, "put_gex_1pct": 8.6e9, "net_gex_1pct": 0.4e9,
                "dollarized": True},
        810.0: {"call_gex_1pct": 4.0e9, "put_gex_1pct": 0.1e9, "net_gex_1pct": 3.9e9,
                "dollarized": True},
    }
    strikes = [800.0, 810.0]

    pin, strength = pick_pin_and_strength(exposures, strikes)
    peak = pick_net_gex_peak_strike(exposures, strikes)

    assert pin == 800.0, f"gross concentration is at 800 (17.6B vs 4.1B), got {pin}"
    assert peak == 810.0, f"signed-net peak is at 810 (3.9B vs 0.4B), got {peak}"
    assert pin != peak, (
        "the two metrics returned the same strike on a book built to separate them — "
        "if this ever passes trivially the fixture has stopped testing anything")
    assert strength is not None and 0.0 < strength <= 100.0, (
        f"strength_pct is the margin over the runner-up, got {strength}")
