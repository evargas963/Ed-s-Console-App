"""call_engine Layer 5 chunk-2C: CE1/CE2/CE9 audit-trail log emission."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import patch


import call_engine as ce
from signal_types import CanonicalForecast, PredictiveCard, RulesCard
from tests.mvp_test_fixtures import minimal_mvp_features
from tests.test_call_engine_chunk1_fail_closed import _strong_long_stack_input


def _rules_long() -> RulesCard:
    return RulesCard(
        headline="trend",
        headline_1m="trend",
        detail="",
        zone_label="BREAKOUT",
        zone_color="#0f0",
        signal="long",
        conviction="high",
        alerts=[],
        micro=None,
    )


def _pred() -> PredictiveCard:
    return PredictiveCard(
        headline="",
        prediction_dir="up",
        prediction_target=None,
        historical_5c_dominant_dir="up",
        historical_5c_dominant_prob=0.6,
        empirical_confidence="medium",
        forward_direction="up",
        forward_prob_up=0.6,
        forward_prob_down=0.2,
        forward_prob_flat=0.2,
        forward_confidence="high",
        forward_provenance="fusion",
        samples_used=10,
        model_note="",
        timeframe_reads={},
        up_prob_5c=0.7,
        down_prob_5c=0.15,
        flat_prob_5c=0.15,
    )


def _canonical(*, confidence: str = "high") -> CanonicalForecast:
    return CanonicalForecast(
        direction="up",
        probability_up=0.6,
        probability_down=0.2,
        probability_flat=0.2,
        confidence=confidence,
        provenance="fusion",
    )


def test_ce1_stop_distance_logs_when_session_time_missing(caplog):
    inp = SimpleNamespace(spot=450.0, et_hour=None, et_minute=None, vix_level=20.0)
    with caplog.at_level(logging.DEBUG, logger="call_engine"):
        ce._stop_distance(inp)
    assert any("et_hour/et_minute missing" in r.message for r in caplog.records)


def test_ce2_conviction_logs_invalid_confidence_substitution(caplog):
    canonical = _canonical(confidence="not_a_tier")
    with caplog.at_level(logging.DEBUG, logger="call_engine"):
        ce._conviction_from_canonical_forecast(
            canonical,
            pred_agrees=True,
            final_signal="long",
        )
    assert any("invalid confidence" in r.message for r in caplog.records)


def test_ce2_conviction_logs_dominant_probability_fallback(caplog):
    canonical = _canonical()

    def _boom():
        raise TypeError("bad triplet")

    canonical.dominant_probability = _boom  # type: ignore[method-assign]
    with caplog.at_level(logging.DEBUG, logger="call_engine"):
        ce._conviction_from_canonical_forecast(
            canonical,
            pred_agrees=True,
            final_signal="long",
        )
    assert any("dominant_probability unavailable" in r.message for r in caplog.records)


def test_ce9_call_readiness_failure_logs_warning(caplog):
    inp = _strong_long_stack_input()
    fusion = SimpleNamespace(
        available=True,
        fusion_dominant_direction="up",
        dominant_direction="up",
        model_agreement=0.8,
        n_sources_active=3,
        fusion_confidence="high",
        mc_available=False,
    )
    vol = SimpleNamespace(
        vol_regime="normal",
        trade_permissive=True,
        conviction_multiplier=1.0,
        risk_multiplier=1.0,
        breakout_bias=0.6,
        reversal_bias=0.5,
    )
    with patch(
        "setup_readiness.compute_call_readiness",
        side_effect=RuntimeError("readiness module broken"),
    ):
        with caplog.at_level(logging.WARNING, logger="call_engine"):
            ce.compute_call(
                inp,
                _rules_long(),
                _pred(),
                regime=SimpleNamespace(primary="trend_continuation", confidence="medium"),
                fusion=fusion,
                vol_regime=vol,
                canonical=_canonical(),
                mvp_features=minimal_mvp_features(zone="breakout"),
                mh_policy=None,
            )
    assert any(r.levelname == "WARNING" and "call_readiness:" in r.message for r in caplog.records)


def test_ce9_put_readiness_failure_logs_warning(caplog):
    inp = _strong_long_stack_input()
    fusion = SimpleNamespace(
        available=True,
        fusion_dominant_direction="up",
        dominant_direction="up",
        model_agreement=0.8,
        n_sources_active=3,
        fusion_confidence="high",
        mc_available=False,
    )
    vol = SimpleNamespace(
        vol_regime="normal",
        trade_permissive=True,
        conviction_multiplier=1.0,
        risk_multiplier=1.0,
        breakout_bias=0.6,
        reversal_bias=0.5,
    )
    with patch(
        "setup_readiness.compute_call_readiness",
        return_value={
            "readiness_score": 50,
            "call_state": "WAIT",
            "forecast_state": "dormant",
            "reasons": [],
            "missing_conditions": [],
            "component_scores": {},
        },
    ), patch(
        "setup_readiness.compute_put_readiness",
        side_effect=RuntimeError("put readiness module broken"),
    ):
        with caplog.at_level(logging.WARNING, logger="call_engine"):
            ce.compute_call(
                inp,
                _rules_long(),
                _pred(),
                regime=SimpleNamespace(primary="trend_continuation", confidence="medium"),
                fusion=fusion,
                vol_regime=vol,
                canonical=_canonical(),
                mvp_features=minimal_mvp_features(zone="breakout"),
                mh_policy=None,
            )
    assert any(r.levelname == "WARNING" and "put_readiness:" in r.message for r in caplog.records)


def test_build_call_headlines_mh_promotion_visible():
    headline, reasoning = ce._build_call_headlines(
        final_signal="long",
        conviction="low",
        trade_type="trend_continuation",
        entry=450.0,
        stop=448.0,
        target=452.0,
        target2=None,
        confluence_count=1,
        confluence_total=8,
        confluence_detail="all_consolidated promoted directional",
        micro_regime="unknown",
        rules=_rules_long(),
        pred=_pred(),
        pred_agrees=False,
        fusion=None,
        wait_blocker=None,
        mh_promoted_directional=True,
    )
    assert "ALL consolidated promoted over tape WAIT" in headline
    assert "ALL consolidated pooled consensus promoted" in reasoning
    assert "conviction floored to low" in reasoning


# ═══ RC-338: readiness scoring policy has ONE computation authority ═══════════════════════
#
# compute_call_readiness and compute_put_readiness each carried a private copy of every
# point table, the probability bands (0.60/0.56/0.52), the state thresholds (80/50) and
# the forecast thresholds (65/40). Neither delegated to the other; the numbers agreed by
# authorship coincidence, and a one-sided edit would silently diverge the CALL and PUT
# chips. The policy now lives ONLY in setup_readiness.score_readiness; the side functions
# classify inputs into tiers and pick wording. These tests are the recurrence lock: they
# detect the EXISTENCE of a second scoring authority, not merely output divergence.

import ast as _ast
import inspect as _inspect
import re as _re

import setup_readiness as _sr


def _side_source_no_docstring(fn) -> str:
    tree = _ast.parse(_inspect.getsource(fn))
    f = tree.body[0]
    if f.body and isinstance(f.body[0], _ast.Expr) and isinstance(f.body[0].value, _ast.Constant):
        f.body = f.body[1:]
    return _ast.unparse(f)


def test_rc338_no_scoring_literals_in_either_side_function():
    """A side function that re-encodes any band, threshold, point value or state string
    is a second producer of the readiness policy — regardless of whether its numbers
    currently match the canonical ones."""
    banned = ("0.60", "0.56", "0.52", ">= 80", ">= 50", ">= 65", ">= 40",
              "'ACTIVE'", '"ACTIVE"', "'WATCH'", '"WATCH"')
    for fn in (_sr.compute_call_readiness, _sr.compute_put_readiness):
        src = _side_source_no_docstring(fn)
        for tok in banned:
            assert tok not in src, (
                f"{fn.__name__} carries scoring literal {tok!r} — a second readiness "
                f"policy authority (RC-338)")
        assert not _re.search(r"\b\w+_score\s*=", src), (
            f"{fn.__name__} computes a component score locally instead of delegating")
        assert "score_readiness(" in src, f"{fn.__name__} does not delegate to the authority"


def test_rc338_policy_constants_defined_exactly_once():
    src = _inspect.getsource(_sr)
    assert src.count("READINESS_PROB_BANDS = ") == 1
    assert src.count("READINESS_ACTIVE_MIN = ") == 1
    assert src.count("READINESS_WATCH_MIN = ") == 1


def test_rc338_both_sides_deliver_the_authoritys_result(monkeypatch):
    """Origin proof: an impossible sentinel from the authority must surface unaltered
    through BOTH side functions. A side that recomputes or adjusts any scored field
    shows a non-sentinel value here."""
    sentinel = {
        "call_state": "SENTINEL_STATE", "forecast_state": "sentinel_fc",
        "readiness_score": 12345, "prob_band": "strong",
        "component_scores": {"trend_score": 1, "structure_score": 2, "level_score": 3,
                             "probability_score": 4, "confluence_score": 5,
                             "validation_score": 6},
    }
    monkeypatch.setattr(_sr, "score_readiness", lambda **kw: dict(sentinel))
    for fn in (_sr.compute_call_readiness, _sr.compute_put_readiness):
        out = fn({})
        assert out["readiness_score"] == 12345, f"{fn.__name__} altered the authority's score"
        assert out["call_state"] == "SENTINEL_STATE"
        assert out["forecast_state"] == "sentinel_fc"
        assert "prob_band" not in out


def test_rc338_state_and_forecast_boundaries_from_the_one_authority():
    def total(**kw):
        return _sr.score_readiness(**kw)

    cases = [
        # (tiers..., expected_total, state, forecast)
        (dict(trend_tier="weak", structure_tier="confirmed", level_tier="near",
              direction_matches=True, prob=0.40, confluence_tier="mixed",
              validation_passed=False), 49, "WAIT", "forming"),
        (dict(trend_tier="aligned", structure_tier="forming", level_tier="unknown",
              direction_matches=True, prob=0.40, confluence_tier="mixed",
              validation_passed=False), 50, "WATCH", "forming"),
        (dict(trend_tier="aligned", structure_tier="forming", level_tier="trigger",
              direction_matches=True, prob=0.52, confluence_tier="weak",
              validation_passed=False), 64, "WATCH", "forming"),
        (dict(trend_tier="aligned", structure_tier="forming", level_tier="near",
              direction_matches=True, prob=0.56, confluence_tier="mixed",
              validation_passed=False), 65, "WATCH", "near_trigger"),
        (dict(trend_tier="aligned", structure_tier="confirmed", level_tier="near",
              direction_matches=True, prob=0.52, confluence_tier="mixed",
              validation_passed=True), 79, "WATCH", "near_trigger"),
        (dict(trend_tier="aligned", structure_tier="confirmed", level_tier="trigger",
              direction_matches=True, prob=0.60, confluence_tier="weak",
              validation_passed=False), 80, "ACTIVE", "active"),
        (dict(trend_tier="weak", structure_tier="forming", level_tier="near",
              direction_matches=False, prob=0.99, confluence_tier="mixed",
              validation_passed=False), 39, "WAIT", "dormant"),
        (dict(trend_tier="weak", structure_tier="forming", level_tier="unknown",
              direction_matches=False, prob=0.99, confluence_tier="weak",
              validation_passed=True), 40, "WAIT", "forming"),
    ]
    for kw, want_total, want_state, want_fc in cases:
        got = total(**kw)
        assert got["readiness_score"] == want_total, (kw, got["readiness_score"])
        assert got["call_state"] == want_state, (want_total, got["call_state"])
        assert got["forecast_state"] == want_fc, (want_total, got["forecast_state"])

    # Probability band boundaries, from the one authority.
    for prob, pts in ((0.60, 15), (0.5999, 11), (0.56, 11), (0.5599, 7), (0.52, 7), (0.5199, 3)):
        got = total(trend_tier="weak", structure_tier="none", level_tier="unknown",
                    direction_matches=True, prob=prob, confluence_tier="weak",
                    validation_passed=False)
        assert got["component_scores"]["probability_score"] == pts, (prob, got)
    got = total(trend_tier="weak", structure_tier="none", level_tier="unknown",
                direction_matches=False, prob=0.99, confluence_tier="weak",
                validation_passed=False)
    assert got["component_scores"]["probability_score"] == 1


def test_rc338_call_and_put_sides_score_identically_for_mirrored_inputs():
    call_max = _sr.compute_call_readiness({
        "regime": "bull", "trend": "up", "structure_confirmation": "reclaim",
        "prediction_direction": "up", "prediction_dominant_prob": 0.61,
        "confluence_read": "strong", "validation_passed": True, "breakout_ready": True,
    })
    put_max = _sr.compute_put_readiness({
        "regime": "bear", "trend": "down", "structure_confirmation": "lower high",
        "prediction_direction": "down", "prediction_dominant_prob": 0.61,
        "confluence_read": "strong", "validation_passed": True, "breakdown_ready": True,
    })
    assert call_max["readiness_score"] == put_max["readiness_score"] == 100
    assert call_max["call_state"] == put_max["call_state"] == "ACTIVE"
    assert call_max["component_scores"] == put_max["component_scores"]

    call_empty = _sr.compute_call_readiness({})
    put_empty = _sr.compute_put_readiness({})
    assert call_empty["readiness_score"] == put_empty["readiness_score"] == 23
    assert call_empty["call_state"] == put_empty["call_state"] == "WAIT"
    assert call_empty["forecast_state"] == put_empty["forecast_state"] == "dormant"
    assert call_empty["component_scores"] == put_empty["component_scores"]

    # Output schema unchanged for consumers (call_engine.py:1970 / :2014).
    for out in (call_max, put_max, call_empty, put_empty):
        assert set(out) == {"call_state", "forecast_state", "readiness_score",
                            "reasons", "missing_conditions", "component_scores"}
