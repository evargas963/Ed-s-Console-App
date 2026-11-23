"""Institutional consistency: dollar GEX pickers and aggregates."""

from calc.math_exposure_core import (
    bucket_metric_abs,
    compute_exposures_by_strike,
    exposures_have_dollar_gex,
    net_gex_dollars_at_strike,
    pick_absolute_gamma_strike,
    pick_key_delta_strike,
    pick_volatility_point_strikes,
)
from calc.terrain_engine import (
    OPTION_LEVELS,
    SAME_DAY_LEVELS,
    TERRAIN_SCHEMA_VERSION,
    compute_terrain,
    price_relations,
)
from option_contract import read_chain
from push import confluence as push_confluence
from tests.real_chains import SPY_0DTE
from time_et import sessions

_SPY = read_chain(SPY_0DTE.chain)


def _dollarized_exposures():
    # Real captured SPY 0DTE chain (tests/real_chains.py, 2026-10-07 12:32 ET), valued at its
    # capture — level invariants must hold on real data.
    exposures, _ = compute_exposures_by_strike(
        _SPY, spot=SPY_0DTE.spot, now=SPY_0DTE.now, sessions=sessions()
    )
    return exposures, SPY_0DTE.spot


def test_exposures_are_dollarized():
    exposures, _ = _dollarized_exposures()
    assert exposures_have_dollar_gex(exposures)


def test_pin_fails_closed_without_dollarized_gex():
    """No dollarized book -> None; a raw-gamma fallback would silently change basis."""
    # the refusal path needs an un-dollarized bucket on purpose.
    raw_only = {700.0: {"net_gamma": 5.0, "call_gamma": 3.0, "put_gamma": 2.0}}
    assert pick_absolute_gamma_strike(raw_only) is None


def test_key_delta_strike_is_the_total_dex_argmax_on_real_chain():
    exposures, _ = _dollarized_exposures()
    strikes = sorted(exposures.keys())
    kds = pick_key_delta_strike(exposures)
    assert kds is not None

    # Independent recompute: no other strike may carry more total |DEX$|.
    def total_dex(s):
        b = exposures[s]
        c = bucket_metric_abs(b, "call_dex_dollars")
        p = bucket_metric_abs(b, "put_dex_dollars")
        return -1.0 if c is None or p is None else c + p

    best = max(strikes, key=total_dex)
    assert kds == round(best, 2)


def test_key_delta_strike_fails_closed_without_dollarization():
    # OI-only buckets (no DEX$ fields) must return None, never a raw-unit rank.
    exposures = {100.0: {"call_oi": 500, "put_oi": 400}}
    assert pick_key_delta_strike(exposures) is None


def test_volatility_points_are_signed_extremes_on_real_chain():
    exposures, _ = _dollarized_exposures()
    strikes = sorted(exposures.keys())
    hvp, lvp = pick_volatility_point_strikes(exposures)
    signed = {s: net_gex_dollars_at_strike(exposures[s]) for s in strikes}
    signed = {s: v for s, v in signed.items() if v is not None}
    negatives = {s: v for s, v in signed.items() if v < 0}
    positives = {s: v for s, v in signed.items() if v > 0}
    if negatives:
        assert hvp == round(min(negatives, key=negatives.get), 2)
    else:
        assert hvp is None
    if positives:
        assert lvp == round(max(positives, key=positives.get), 2)
    else:
        assert lvp is None
    # The real SPY chain has positive pockets — LVP must exist there.
    assert lvp is not None


def test_terrain_snapshot_v2_carries_net_gex_and_new_levels():
    """Real seam: compute_terrain (the terrain panel's producer) on the real SPY chain.

    It must serve net_gex_at_spot and the new levels agreeing with their pickers — the UI
    renders these fields directly.
    """
    held = sessions()
    snap = compute_terrain("SPY", _SPY, SPY_0DTE.spot, now=SPY_0DTE.now, sessions=held)
    d = (
        snap.to_dict() | price_relations(snap.to_dict(), SPY_0DTE.spot).to_dict()
    )  # as the terrain panel sends it
    # v3 (RC-292): gamma_pin* renamed absolute_gamma_*; + pin_candidate(+blockers). v4: the five
    # values no code read deleted (rr_25d, zero_dte_gamma_share_pct, vanna_agg, the wall ranges).
    # The v2 fields this test locks are all still carried.
    # v5: net_gex_peak deleted (it always equalled hvp or lvp). v6: the pin read on open interest,
    # its four gate inputs deleted. v7: the flip's chain-coverage confidence deleted.
    assert TERRAIN_SCHEMA_VERSION == 7 and d["schema_version"] == 7
    assert "confidence" not in d
    for fld in (
        "net_gex_at_spot",
        "key_delta_strike",
        "hvp",
        "lvp",
        "absolute_gamma_strike",
        "pin_candidate",
    ):
        assert fld in d, fld + " missing from terrain payload"
    assert "gamma_pin" not in d, "the retired gamma_pin key returned to the terrain payload"
    assert d["net_gex_at_spot"] is not None, "the chain must price (valued at its capture)"
    exposures, _ = compute_exposures_by_strike(
        _SPY, spot=SPY_0DTE.spot, now=SPY_0DTE.now, sessions=held
    )
    assert d["key_delta_strike"] == pick_key_delta_strike(exposures)
    assert (d["hvp"], d["lvp"]) == pick_volatility_point_strikes(exposures)


def test_the_net_gamma_peaks_are_served_under_names_that_say_what_they_are():
    """Each list that names a level calls the two by what they hold, and each has its pill."""
    for levels in (SAME_DAY_LEVELS, OPTION_LEVELS):
        named = dict(levels)
        assert (named["hvp"], named["lvp"]) == ("Gamma Net Negative", "Gamma Net Positive")
    # one list names the levels: the same-day levels are its own entries, in its order
    assert [level for level in OPTION_LEVELS if level in SAME_DAY_LEVELS] == list(SAME_DAY_LEVELS)
    assert {key for key, _label in OPTION_LEVELS} - {key for key, _label in SAME_DAY_LEVELS} == {
        "max_pain",
        "pin_candidate",
    }
    # each level's pill is its own name, but the two net GEX strikes', whose sign is a sign
    pills = {
        label: push_confluence._option_abbrev(label, same_day=False) for _k, label in OPTION_LEVELS
    }
    assert pills == {label: label for _k, label in OPTION_LEVELS} | {
        "Gamma Net Negative": "Gamma Net −",
        "Gamma Net Positive": "Gamma Net +",
    }
    assert push_confluence._option_abbrev("Gamma Net Negative", same_day=False) == "Gamma Net −"
    assert push_confluence._option_abbrev("Gamma Net Positive", same_day=True) == "0DTE Gamma Net +"


def test_volatility_points_one_sided_chain_returns_none_side():
    # every gamma reported, as each bucket the producer builds counts its unreported ones
    reported = {"call_gamma_unreported": 0, "put_gamma_unreported": 0}
    exposures = {
        100.0: {
            "net_gex_1pct": 5_000_000.0,
            "call_gex_1pct": 5_000_000.0,
            "dollarized": True,
            **reported,
        },
        105.0: {
            "net_gex_1pct": 9_000_000.0,
            "call_gex_1pct": 9_000_000.0,
            "dollarized": True,
            **reported,
        },
    }
    hvp, lvp = pick_volatility_point_strikes(exposures)
    assert hvp is None  # no negative pocket anywhere
    assert lvp == 105.0  # most positive, signed — not magnitude
