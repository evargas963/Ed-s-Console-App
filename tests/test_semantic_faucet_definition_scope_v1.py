"""One published level name, one metric: on a real book where max total gamma and max |net
GEX| fall on different strikes, each terrain name carries its own metric, and the pin claim
is published only through its qualification gates."""

from __future__ import annotations

import pytest

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

FIXTURE = REPO / "tests" / "fixtures" / "real_spy_0dte_chain.json"


@pytest.fixture(autouse=True)
def _at_capture(pin_clock):
    """real_spy_0dte_chain.json was captured 2026-09-22 12:46 ET."""
    return pin_clock(2026, 9, 22, 12, 46)

def _fixture_book():
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return fx["chain"], float(fx["spot"])


def test_definitions_diverge_on_the_real_book_so_a_miswire_cannot_hide():
    """Premise: the two pin-shaped definitions disagree on this chain (773 vs 775; SPY 2026-09-22 12:46 ET).

    RC-292 measured live SPY where they AGREED (775 == 775) and named the coincidence the
    finding: nothing could tell two definitions apart. This fixture is the book where they
    split, so every name-to-metric wiring below is checked against a number the other
    metric cannot produce.
    """
    from math_exposure_core import (
        compute_exposures_by_strike,
        pick_net_gex_peak_strike,
        pick_pin_and_strength,
    )
    from math_exposure_core import key_level_strikes_with_gamma

    chain, spot = _fixture_book()
    ex, _ = compute_exposures_by_strike(chain, spot=spot)
    ks = key_level_strikes_with_gamma(ex) or sorted(ex)
    total_leader, _strength = pick_pin_and_strength(ex, ks)
    net_leader = pick_net_gex_peak_strike(ex, ks)
    assert total_leader is not None and net_leader is not None
    assert total_leader != net_leader, (
        "the fixture no longer separates max-total-gamma from max-|net-GEX| — replace it "
        "with a book where the definitions diverge or every wiring check below is blind")
    assert (total_leader, net_leader) == (773.0, 775.0), (
        "the measured split (773 vs 775) no longer reproduces on this fixture")


def test_terrain_names_carry_their_declared_definitions():
    """absolute_gamma_strike ≡ pick_pin_and_strength; net_gex_peak ≡
    pick_net_gex_peak_strike — same book, same strikes, ONE faucet per definition."""
    from math_exposure_core import (
        compute_exposures_by_strike,
        pick_net_gex_peak_strike,
        pick_pin_and_strength,
    )
    from math_exposure_core import key_level_strikes_with_gamma
    from terrain_engine import compute_terrain

    chain, spot = _fixture_book()
    snap = compute_terrain("SPY", chain, spot)
    ex, _ = compute_exposures_by_strike(chain, spot=spot)
    ks = key_level_strikes_with_gamma(ex) or sorted(ex)
    assert snap.absolute_gamma_strike == pick_pin_and_strength(ex, ks)[0]
    assert snap.net_gex_peak == pick_net_gex_peak_strike(ex, ks)
    # the cross-wire that RC-292 could never see: each name now refuses the other metric
    assert snap.absolute_gamma_strike != snap.net_gex_peak
    d = snap.to_dict()
    assert d["absolute_gamma_strike"] == snap.absolute_gamma_strike
    assert d["net_gex_peak"] == snap.net_gex_peak
    assert "gamma_pin" not in d, "the retired two-definition name returned to the payload"


def test_pin_candidate_is_published_only_through_the_qualification_gates():
    """RC-292 operator disposition, executed: every gate flips the claim off; all five
    passing publishes the strike; the real fixture withholds with named blockers."""
    from terrain_engine import compute_terrain, qualify_pin_candidate

    passing = dict(
        spot=100.0, absolute_gamma_strike=100.2, absolute_gamma_strength_pct=15.0,
        absolute_gamma_gex_dollars=60_000.0, absolute_gamma_oi=3_000.0,
        book_oi_total=10_000.0, net_gex_at_spot=5.0, front_dte=0.0,
    )
    strike, blockers = qualify_pin_candidate(**passing)
    assert (strike, blockers) == (100.2, [])
    for gate, patch in (
        ("regime", {"net_gex_at_spot": -5.0}),
        ("proximity", {"absolute_gamma_strike": 102.0}),
        ("dte", {"front_dte": 3.0}),
        ("liquidity", {"absolute_gamma_oi": 1.0}),
        ("completeness", {"book_oi_total": None}),
    ):
        strike, blockers = qualify_pin_candidate(**{**passing, **patch})
        assert strike is None and gate in blockers, (
            f"the {gate} gate did not withhold the pin claim: blockers={blockers}")
    # The real book, valued at its capture (2026-09-22 12:46 ET): gamma at spot is +$2.41B, so
    # the regime gate passes and liquidity withholds the claim -- WITH its reason. (Until
    # 2026-09-27 this expected ["regime", "liquidity"]: the fixture had expired, gamma at spot
    # read None, and the test had locked in the expired answer.)
    chain, spot = _fixture_book()
    snap = compute_terrain("SPY", chain, spot)
    assert snap.net_gex_at_spot is not None and snap.net_gex_at_spot > 0
    assert snap.pin_candidate is None
    assert snap.pin_candidate_blockers == ["liquidity"]
    assert snap.absolute_gamma_strike is not None, (
        "withholding the CLAIM must never delete the measured concentration (deliver, "
        "never delete)")
