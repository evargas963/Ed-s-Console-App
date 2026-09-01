"""call_engine chunk-1: I-01 contract when canonical/fusion/mh_policy are absent."""

from __future__ import annotations

from types import SimpleNamespace

from call_engine import compute_call
from signal_types import PredictiveCard, RulesCard, SignalInput, CanonicalForecast
from tests.mvp_test_fixtures import minimal_mvp_features


def _strong_long_stack_input() -> SignalInput:
    return SignalInput(
        ticker="SPY",
        timeframe="1m",
        expiry=None,
        dte=None,
        spot=450.0,
        candle_open=449.5,
        candle_high=450.2,
        candle_low=449.3,
        candle_close=450.0,
        candle_direction="up",
        candle_body_pts=0.5,
        candle_range_pts=0.9,
        vwap=449.8,
        vwap_side="above",
        vwap_dist_pts=0.2,
        zone="breakout",
        prev_zone="pin_bull",
        zone_since_bars=5,
        zone_since_bars_1m=5,
        zone_since_bars_5m=1,
        call_gamma_wall=460.0,
        put_gamma_wall=440.0,
        call_delta_wall=None,
        put_delta_wall=None,
        gamma_inflection=None,
        delta_inflection=None,
        call_oi_wall=None,
        put_oi_wall=None,
        call_vanna_wall=None,
        put_vanna_wall=None,
        pin_width_pts=2.0,
        dist_call_gamma_wall=10.0,
        dist_put_gamma_wall=-10.0,
        dist_call_delta_wall=None,
        dist_put_delta_wall=None,
        dist_gamma_inflection=None,
        dist_delta_inflection=None,
        dist_call_oi_wall=None,
        dist_put_oi_wall=None,
        dist_call_vanna_wall=None,
        dist_put_vanna_wall=None,
        nearest_above_name="CGW",
        nearest_above_val=460.0,
        nearest_above_dist=10.0,
        nearest_below_name="PGW",
        nearest_below_val=440.0,
        nearest_below_dist=10.0,
        net_gamma=1000.0,
        net_delta=800.0,
        net_vanna=None,
        charm_net=None,
        charm_direction="buying",
        charm_drift_toward=450.0,
        charm_magnitude="moderate",
        dex_magnitude="moderate",
        iv_level=0.15,
        iv_direction="flat",
        realized_vol=None,
        atr=1.5,
        put_call_oi_ratio=0.9,
        oi_center=None,
        recent_crosses=[],
        ceiling_tests_today=0,
        floor_tests_today=0,
        spy_chg_pct=0.8,
        qqq_chg_pct=0.9,
        iwm_chg_pct=0.7,
        spy_weighted_push=0.5,
        qqq_weighted_push=0.5,
        iwm_weighted_push=0.5,
        vix_level=18.0,
        mins_to_close=240.0,
        em_upper=452.0,
        em_lower=448.0,
        order_flow_score=0.5,
        order_flow_direction="bullish",
        order_flow_readiness="green",
    )


def test_compute_call_missing_upstreams_forces_wait_not_sized_trade():
    """Stack may lean long, but missing canonical provenance must not emit a sized trade."""
    rules = RulesCard(
        headline="Stack lean",
        headline_1m="",
        detail="",
        zone_label="UP",
        zone_color="#166534",
        signal="long",
        conviction="high",
        alerts=[],
        micro=SimpleNamespace(
            regime="TREND_UP",
            structure_support=449.0,
            structure_resist=451.5,
            bos=None,
            sweeps=[],
            last_sweep=None,
        ),
    )
    pred = PredictiveCard(
        headline="Lean up",
        prediction_dir="up",
        prediction_target=455.0,
        historical_5c_dominant_dir="up",
        historical_5c_dominant_prob=0.7,
        empirical_confidence="high",
        forward_direction="flat",
        forward_prob_up=1.0 / 3.0,
        forward_prob_down=1.0 / 3.0,
        forward_prob_flat=1.0 / 3.0,
        forward_confidence="low",
        forward_provenance="missing",
        samples_used=0,
        model_note="",
        timeframe_reads={},
        up_prob_5c=0.7,
        down_prob_5c=0.15,
        flat_prob_5c=0.15,
    )

    call = compute_call(
        _strong_long_stack_input(),
        rules,
        pred,
        regime=None,
        fusion=None,
        vol_regime=None,
        canonical=None,
        mvp_features=minimal_mvp_features(zone="breakout"),
        mh_policy=None,
    )

    assert call.signal == "wait"
    assert call.r_units == 0.0
    assert call.execution_mode == "NO_TRADE"
    assert call.wait_blocker is not None
    assert call.wait_blocker.get("provenance") == "missing_canonical_fallback"
    # TEST_SYSTEM_REHAB_V2: was `call.signal not in ("long","short") or not
    # call.validation_passed` -- line 147 above already asserts `call.signal ==
    # "wait"`, which makes `signal not in ("long","short")` unconditionally true, so
    # this could never fail regardless of `validation_passed`. Line 147 already
    # covers "not in (long, short)"; dropped as dead weight rather than kept as a
    # tautology.


def _phase3_rules_long():
    return RulesCard(
        headline="Micro long",
        headline_1m="",
        detail="",
        zone_label="UP",
        zone_color="#166534",
        signal="long",
        conviction="low",
        alerts=[],
        micro=SimpleNamespace(
            regime="TREND_UP",
            structure_support=449.0,
            structure_resist=451.5,
            bos=None,
            sweeps=[],
            last_sweep=None,
            is_compressing=False,
            compression_bars=0,
        ),
    )


def _phase3_canonical():
    return CanonicalForecast(
        direction="up",
        probability_up=0.62,
        probability_down=0.20,
        probability_flat=0.18,
        confidence="medium",
        provenance="bayesian_fusion",
    )


def _phase3_pred_bullish_all_horizons():
    return PredictiveCard(
        headline="Bullish",
        prediction_dir="up",
        prediction_target=455.0,
        historical_5c_dominant_dir="up",
        historical_5c_dominant_prob=0.62,
        empirical_confidence="medium",
        forward_direction="up",
        forward_prob_up=0.62,
        forward_prob_down=0.20,
        forward_prob_flat=0.18,
        forward_confidence="medium",
        forward_provenance="bayesian_fusion",
        samples_used=100,
        model_note="",
        timeframe_reads={},
        up_prob_1c=0.62, down_prob_1c=0.20, flat_prob_1c=0.18,
        up_prob_5c=0.64, down_prob_5c=0.18, flat_prob_5c=0.18,
        up_prob_15c=0.66, down_prob_15c=0.17, flat_prob_15c=0.17,
        up_prob_60c=0.60, down_prob_60c=0.22, flat_prob_60c=0.18,
        horizon_directional_authorized={
            "1c": True, "5c": True, "15c": True, "60c": True,
        },
    )


def _phase3_vol_regime():
    return SimpleNamespace(
        vol_regime="normal",
        trade_permissive=True,
        conviction_multiplier=1.0,
        risk_multiplier=1.0,
        breakout_bias=0.6,
        reversal_bias=0.5,
    )


def test_call_all_pool_promotes_over_tape_wait():
    """Phase 3: ALL tradeable + tape below threshold → directional from ALL only."""
    from multi_horizon_decision import compute_multi_horizon_synthesis

    inp = _strong_long_stack_input()
    inp.order_flow_direction = "neutral"
    inp.spy_chg_pct = 0.01
    inp.qqq_chg_pct = 0.01
    inp.iwm_chg_pct = 0.01
    inp.spy_weighted_push = 0.0
    inp.qqq_weighted_push = 0.0
    inp.iwm_weighted_push = 0.0
    inp.net_delta = 50.0
    inp.zone = "pin_bull"

    canonical = _phase3_canonical()
    pred = _phase3_pred_bullish_all_horizons()
    mh_policy = compute_multi_horizon_synthesis(inp, pred, canonical)
    assert mh_policy.final_tradeable_decision is True
    assert mh_policy.final_bias == "long"

    call = compute_call(
        inp,
        _phase3_rules_long(),
        pred,
        regime=SimpleNamespace(primary="unknown", confidence="low"),
        fusion=None,
        vol_regime=_phase3_vol_regime(),
        canonical=canonical,
        mvp_features=minimal_mvp_features(zone="pin_bull"),
        mh_policy=mh_policy,
    )
    assert call.signal == "long", (
        f"expected ALL-promoted long; got {call.signal!r} blocker={call.wait_blocker!r}"
    )
    # TEST_SYSTEM_REHAB_V2: was `"ALL consolidated promoted" in call.headline or
    # call.signal == "long"` -- the line above already asserts signal == "long", so
    # the second arm made this unconditionally true regardless of the headline text,
    # the actual property this line claims to check (directional from ALL only).
    assert "ALL consolidated promoted" in call.headline, (
        f"headline must attribute the decision to ALL-pool promotion; got {call.headline!r}")


def test_call_all_pool_vetoes_tape_only_directional():
    """Phase 3: tape reaches threshold but ALL pooled evidence is WAIT → forced wait."""
    from multi_horizon_decision import compute_multi_horizon_synthesis

    inp = _strong_long_stack_input()
    canonical = _phase3_canonical()
    pred = PredictiveCard(
        headline="Flat",
        prediction_dir="flat",
        prediction_target=None,
        historical_5c_dominant_dir="flat",
        historical_5c_dominant_prob=0.34,
        empirical_confidence="low",
        forward_direction="flat",
        forward_prob_up=1.0 / 3.0,
        forward_prob_down=1.0 / 3.0,
        forward_prob_flat=1.0 / 3.0,
        forward_confidence="low",
        forward_provenance="bayesian_fusion",
        samples_used=100,
        model_note="",
        timeframe_reads={},
        up_prob_1c=0.34, down_prob_1c=0.33, flat_prob_1c=0.33,
        up_prob_5c=0.34, down_prob_5c=0.33, flat_prob_5c=0.33,
        up_prob_15c=0.34, down_prob_15c=0.33, flat_prob_15c=0.33,
        up_prob_60c=0.34, down_prob_60c=0.33, flat_prob_60c=0.33,
    )
    mh_policy = compute_multi_horizon_synthesis(inp, pred, canonical)
    assert mh_policy.final_tradeable_decision is False

    call = compute_call(
        inp,
        _phase3_rules_long(),
        pred,
        regime=SimpleNamespace(primary="trend_continuation", confidence="medium"),
        fusion=None,
        vol_regime=_phase3_vol_regime(),
        canonical=canonical,
        mvp_features=minimal_mvp_features(zone="breakout"),
        mh_policy=mh_policy,
    )
    assert call.signal == "wait"
    assert call.wait_blocker is not None
    assert call.wait_blocker.get("reason") == "multi_horizon_policy"


def test_call_all_pool_wait_non_tradable_canonical_provenance():
    """Phase 3: ALL tradeable but canonical provenance not tradable → canonical_provenance blocker."""
    from multi_horizon_decision import compute_multi_horizon_synthesis

    inp = _strong_long_stack_input()
    canonical = _phase3_canonical()
    canonical = CanonicalForecast(
        direction=canonical.direction,
        probability_up=canonical.probability_up,
        probability_down=canonical.probability_down,
        probability_flat=canonical.probability_flat,
        confidence=canonical.confidence,
        provenance="uniform_max_entropy",
    )
    pred = _phase3_pred_bullish_all_horizons()
    mh_policy = compute_multi_horizon_synthesis(inp, pred, canonical)
    assert mh_policy.final_tradeable_decision is True

    call = compute_call(
        inp,
        _phase3_rules_long(),
        pred,
        regime=SimpleNamespace(primary="unknown", confidence="low"),
        fusion=None,
        vol_regime=_phase3_vol_regime(),
        canonical=canonical,
        mvp_features=minimal_mvp_features(zone="breakout"),
        mh_policy=mh_policy,
    )
    assert call.signal == "wait"
    assert call.wait_blocker is not None
    assert call.wait_blocker.get("reason") == "canonical_provenance"
    assert call.wait_blocker.get("reason") != "stack"


def test_the_charm_note_does_not_credit_time_decay_with_a_price_target():
    """RC-313: the Call card sentence, EXECUTED.

    It read "Time decay pushing dealers to {dir} toward {strike}". Charm measured the
    direction; it did NOT measure the strike. `charm_drift_toward` is
    pick_net_gex_peak_strike over the SELECTED expiry, republished unchanged (RC-292/RC-302),
    and RC-295 already deleted the identical claim from the pinning score while leaving this
    sentence — which makes the same assertion to a reader who has no score to check it
    against. Both measured quantities must still reach the operator; only the causal claim
    between them goes.
    """
    from call_engine import _greek_notes

    inp = SimpleNamespace(net_gamma=None, charm_direction="selling",
                          charm_drift_toward=772.5, iv_direction=None, vix_level=None)
    notes = [n for n in _greek_notes(inp) if "772.5" in n or "decay" in n.lower()]
    assert len(notes) == 1, f"expected exactly one charm note, got {notes}"
    note = notes[0]

    assert "772.50" in note, "the strike stopped reaching the operator"
    assert "selling" in note, "charm's own measured direction stopped reaching the operator"
    assert "toward" not in note.lower(), (
        f"the note still points time decay at a price target it did not measure: {note!r}")
    assert "pushing dealers to" not in note, f"the RC-313 wording is back: {note!r}"
    assert "net-gex peak" in note.lower(), (
        f"the note does not say WHICH quantity the strike is: {note!r}")
    assert "expiry" in note.lower(), (
        f"the note does not say the strike is selected-expiry scoped: {note!r}")

    # Absence stays absent: no direction or no strike means no sentence at all.
    for missing in ({"charm_direction": None}, {"charm_drift_toward": None}):
        fields = {"net_gamma": None, "charm_direction": "selling",
                  "charm_drift_toward": 772.5, "iv_direction": None, "vix_level": None}
        fields.update(missing)
        partial = SimpleNamespace(**fields)
        assert not [n for n in _greek_notes(partial) if "772.5" in n or "decay" in n.lower()], (
            f"a charm note was emitted with {missing} — half a claim is still a claim")


def test_call_stack_uses_all_consolidated_not_fusion_multi_horizon_slots():
    """Phase 3 mechanical: stack vote keys are 8-wide with single all_consolidated ML slot."""
    import inspect

    import call_engine as ce

    assert ce.CONFLUENCE_TOTAL_SOURCES == 8
    src = inspect.getsource(ce.compute_call)
    assert '"all_consolidated":' in src
    idx = src.index("stack_votes = {")
    block = src[idx : idx + 700]
    assert '"fusion"' not in block
    assert '"multi_horizon"' not in block
