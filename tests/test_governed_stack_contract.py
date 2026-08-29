from types import SimpleNamespace

import pytest

from governed_stack_contract import (
    classify_stack_health,
    mc_model_direction_inputs,
    mc_team_should_fail_closed,
    unified_stack_team_can_authorize,
    wall_clock_minutes_to_mc_bars,
)


def test_wall_clock_minutes_to_mc_bars_true_wallclock():
    """Display-only 5m/15m EFE/EAE must request TRUE wall-clock bars, not slug integers.

    With monte_carlo.BAR_MINUTES=5: 5 min -> 1 bar, 15 min -> 3 bars. Using the slug
    integer (5c->5 bars) would be 25 minutes — the over-simulation bug this helper exists
    to prevent.
    """
    from monte_carlo import BAR_MINUTES

    assert wall_clock_minutes_to_mc_bars(5) == 5 // int(BAR_MINUTES)
    assert wall_clock_minutes_to_mc_bars(15) == 15 // int(BAR_MINUTES)
    if int(BAR_MINUTES) == 5:
        assert wall_clock_minutes_to_mc_bars(5) == 1
        assert wall_clock_minutes_to_mc_bars(15) == 3


def test_wall_clock_minutes_to_mc_bars_rejects_non_multiple_and_nonpositive():
    from monte_carlo import BAR_MINUTES

    with pytest.raises(ValueError):
        wall_clock_minutes_to_mc_bars(0)
    with pytest.raises(ValueError):
        wall_clock_minutes_to_mc_bars(-5)
    if int(BAR_MINUTES) == 5:
        # 1-minute forecast is NOT representable while BAR_MINUTES=5 (needs the alignment fix)
        with pytest.raises(ValueError):
            wall_clock_minutes_to_mc_bars(1)


# ── BAR_MINUTES sizing alignment (minimal-guidance lane, 2026-07-08) ─────────


def test_bar_minutes_aligns_slug_horizon_to_wall_clock_minutes():
    """FIX lock: for EVERY governed horizon slug (authority list, no literals),
    the MC bars requested by the live stack path equal the slug's wall-clock
    minutes — simulated forward time == 1-minute label horizon. Pre-fix
    (BAR_MINUTES=5) this was 5x over-horizon: 5c requested 5 bars = 25 minutes,
    and those over-horizon mc_eae/mc_efe fed compute_position_size."""
    from governed_stack_contract import GOVERNED_STACK_HORIZONS, horizon_slug_to_mc_bars
    from monte_carlo import BAR_MINUTES

    assert int(BAR_MINUTES) == 1
    for slug in GOVERNED_STACK_HORIZONS:
        minutes = int(str(slug).rstrip("c"))
        assert horizon_slug_to_mc_bars(slug) * int(BAR_MINUTES) == minutes, slug


def test_bar_minutes_one_makes_slug_and_wall_clock_maps_converge():
    """With BAR_MINUTES=1 the slug map and the wall-clock map agree for every
    governed horizon — the two code paths can no longer diverge in units."""
    from governed_stack_contract import (
        GOVERNED_STACK_HORIZONS,
        horizon_slug_to_mc_bars,
    )

    for slug in GOVERNED_STACK_HORIZONS:
        minutes = int(str(slug).rstrip("c"))
        assert horizon_slug_to_mc_bars(slug) == wall_clock_minutes_to_mc_bars(minutes), slug


def test_one_minute_wall_clock_now_representable():
    """Pre-fix this raised ValueError ('not representable while BAR_MINUTES=5')."""
    assert wall_clock_minutes_to_mc_bars(1) == 1


def test_default_horizon_removed_and_horizon_bars_required():
    """DEFAULT_HORIZON=13 was dead (every live caller passes horizon_bars) and
    misleading (commented '~1hr' under the 5-minute reading; 13 minutes under
    the aligned reading). Removed: a silent default cannot reintroduce a unit
    mistake — omitting horizon_bars is now a loud TypeError."""
    import inspect

    import monte_carlo

    assert not hasattr(monte_carlo, "DEFAULT_HORIZON")
    sig = inspect.signature(monte_carlo.simulate)
    assert sig.parameters["horizon_bars"].default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        monte_carlo.simulate(spot=500.0, iv=0.2)  # no horizon_bars -> loud failure


def test_mc_inputs_from_stack_probs():
    x = SimpleNamespace(available=True, prob_up=0.6, prob_down=0.2, prob_flat=0.2)
    u, d, c, avail, src = mc_model_direction_inputs(
        xgb_out=x,
        lstm_out=SimpleNamespace(available=False),
        transformer_out=SimpleNamespace(available=False),
        stack_probs={"up": 0.5, "down": 0.3, "flat": 0.2},
    )
    assert abs(u - 0.5) < 1e-9
    assert abs(d - 0.3) < 1e-9
    assert src == "stack_probs_meta_or_weighted"
    assert c in ("high", "medium", "low")
    assert avail["xgboost"] is True


def test_mc_inputs_uniform_when_no_signal():
    fb = SimpleNamespace(available=False, prob_up=0.33, prob_down=0.33, prob_flat=0.34)
    u, d, c, avail, src = mc_model_direction_inputs(
        xgb_out=fb,
        lstm_out=fb,
        transformer_out=fb,
        stack_probs=None,
    )
    assert abs(u - 1 / 3) < 1e-9
    assert abs(d - 1 / 3) < 1e-9
    assert c == "low"
    assert src == "uniform_no_stack_tri_class_signal"


def test_display_wall_clock_mc_excursions_fail_closed_without_iv():
    from signals import _compute_display_wall_clock_mc_excursions

    inp = SimpleNamespace(ticker="SPY", iv_level=None)
    out = _compute_display_wall_clock_mc_excursions(
        inp,
        regime=None,
        mc_spot_ctx={"spot": 500.0},
        mc_context_error=None,
        xgb_out=None,
        lstm_out=None,
        transformer_out=None,
        ml_bundle={},
    )
    assert out == {
        "mc_efe_5m": None,
        "mc_eae_5m": None,
        "mc_efe_15m": None,
        "mc_eae_15m": None,
    }


def test_display_wall_clock_mc_excursions_populates_5m_15m():
    from signals import _compute_display_wall_clock_mc_excursions
    from governed_stack_contract import wall_clock_minutes_to_mc_bars

    inp = SimpleNamespace(ticker="SPY", iv_level=0.18)
    fb = SimpleNamespace(available=False, prob_up=0.33, prob_down=0.33, prob_flat=0.34)
    out = _compute_display_wall_clock_mc_excursions(
        inp,
        regime=SimpleNamespace(primary="pinning", confidence="high"),
        mc_spot_ctx={"spot": 450.0, "realized_vol": 0.15, "atr": 1.5},
        mc_context_error=None,
        xgb_out=fb,
        lstm_out=fb,
        transformer_out=fb,
        ml_bundle={},
    )
    # Wall-clock invariant is unit-independent: N minutes -> N / BAR_MINUTES bars
    # (was 5->1, 15->3 under BAR_MINUTES=5; identity under the =1 alignment).
    from monte_carlo import BAR_MINUTES

    assert wall_clock_minutes_to_mc_bars(5) == 5 // int(BAR_MINUTES)
    assert wall_clock_minutes_to_mc_bars(15) == 15 // int(BAR_MINUTES)
    assert out["mc_efe_5m"] is not None and out["mc_eae_5m"] is not None
    assert out["mc_efe_15m"] is not None and out["mc_eae_15m"] is not None
    assert out["mc_efe_15m"] >= out["mc_efe_5m"]
    assert out["mc_eae_15m"] >= out["mc_eae_5m"]


def test_derive_stack_layers_scored_meta_when_stack_probs_feed_mc():
    from bayesian_fusion import FusionPayload
    from governed_stack_contract import derive_stack_layers_scored
    from ml_predict import stack_probs_bundle_key

    x = SimpleNamespace(available=True, prob_up=0.5, prob_down=0.3, prob_flat=0.2)
    mc = SimpleNamespace(available=True)
    regime = SimpleNamespace(primary="trend", confidence=0.8)
    spk = stack_probs_bundle_key()
    bundle = {
        spk: {"up": 0.5, "down": 0.3, "flat": 0.2},
        "mc_stack_probability_source": "stack_probs_meta_or_weighted",
        # META is credited only when the APPROVED composition actually ran. The source string alone
        # is not evidence — mc_model_direction_inputs returns it for any complete triplet, including
        # the 5c weighted blend for which zero meta_*_5c.pkl exists.
        "stack_probs_composition": {
            "horizon": "1c", "required": ["xgb", "lstm", "transformer"],
            "produced": ["xgb", "lstm", "transformer"], "missing": [], "collapsed": [],
            "contract_compliant": True, "contract_issues": [], "complete": True,
        },
    }
    fusion = FusionPayload(
        available=True,
        prob_up=0.4,
        prob_down=0.35,
        prob_flat=0.25,
        n_sources_available=3,
        n_sources_active=3,
    )
    layers = derive_stack_layers_scored(
        xgb_out=x,
        lstm_out=x,
        transformer_out=x,
        mc_out=mc,
        ml_bundle=bundle,
        regime=regime,
        fusion_payload=fusion,
    )
    assert layers == [
        "xgb",
        "lstm",
        "transformer",
        "meta",
        "monte_carlo",
        "regime",
        "fusion",
    ]


def test_derive_stack_layers_scored_omits_meta_without_stack_probs():
    from bayesian_fusion import FusionPayload
    from governed_stack_contract import derive_stack_layers_scored

    x = SimpleNamespace(available=True, prob_up=0.5, prob_down=0.3, prob_flat=0.2)
    mc = SimpleNamespace(available=False)
    regime = SimpleNamespace(primary="trend", confidence=0.8)
    fusion = FusionPayload(
        available=True,
        prob_up=0.4,
        prob_down=0.35,
        prob_flat=0.25,
        n_sources_available=1,
        n_sources_active=1,
    )
    layers = derive_stack_layers_scored(
        xgb_out=x,
        lstm_out=SimpleNamespace(available=False),
        transformer_out=SimpleNamespace(available=False),
        mc_out=mc,
        ml_bundle={"mc_stack_probability_source": "average_available_ml_layers"},
        regime=regime,
        fusion_payload=fusion,
    )
    assert "meta" not in layers
    assert "xgb" in layers
    assert "fusion" in layers


def test_unified_stack_team_requires_the_complete_approved_composition():
    """Authorization is COMPOSITION-based, not shape-based: the approved composition (owned by
    active_bundle_contract) must have produced the triplet. One surviving leg is not a stack, even
    though _weighted_average_partial renormalises it into a complete-looking up/down/flat dict."""
    ok = SimpleNamespace(available=True, prob_up=0.5, prob_down=0.3, prob_flat=0.2)
    bad = SimpleNamespace(available=False, prob_up=0.33, prob_down=0.33, prob_flat=0.34)
    partial = {
        "horizon": "1c", "required": ["xgb", "lstm", "transformer"], "produced": ["xgb"],
        "missing": ["lstm", "transformer"], "collapsed": [], "contract_compliant": True,
        "contract_issues": [], "complete": False,
    }
    team_ok, reason = unified_stack_team_can_authorize(
        xgb_out=ok,
        lstm_out=bad,
        transformer_out=bad,
        stack_probs={"up": 0.5, "down": 0.3, "flat": 0.2},
        stack_probs_composition=partial,
    )
    assert team_ok is False
    assert "composition_incomplete" in reason


def test_mc_team_fail_closed_when_stack_incomplete():
    assert mc_team_should_fail_closed(False, "stack_probs_meta_or_weighted") is True
    assert mc_team_should_fail_closed(True, "uniform_no_stack_tri_class_signal") is True


def test_classify_stack_health_no_partial_or_degraded():
    assert classify_stack_health(
        fusion_available=True,
        mc_available=True,
        n_ml_layers_available=1,
        unified_stack_team_ok=False,
    ) == "INVALID"
    assert classify_stack_health(
        fusion_available=True,
        mc_available=False,
        n_ml_layers_available=3,
        unified_stack_team_ok=True,
    ) == "INVALID"
    assert classify_stack_health(
        fusion_available=True,
        mc_available=True,
        n_ml_layers_available=3,
        unified_stack_team_ok=True,
    ) == "FULL"
