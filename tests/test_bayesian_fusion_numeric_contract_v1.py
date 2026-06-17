"""FIND-BF-1..6 paired-fix — numeric_contract + triplet authority in bayesian_fusion."""

from __future__ import annotations

from types import SimpleNamespace


from bayesian_fusion import (
    DEFAULT_PRIORS,
    _bayesian_update,
    _model_dominant_class,
    _model_direction_triplet,
    _optional_support,
    fuse,
)


def test_model_direction_triplet_rejects_nan_probs():
    out = SimpleNamespace(
        available=True,
        prob_up=float("nan"),
        prob_down=0.3,
        prob_flat=0.2,
    )
    assert _model_direction_triplet(out) is None


def test_model_dominant_class_ignores_upstream_label():
    out = SimpleNamespace(
        available=True,
        dominant_class="up",
        prob_up=0.1,
        prob_down=0.7,
        prob_flat=0.2,
        continuation_support=0.3,
        reversal_support=0.2,
    )
    assert _model_dominant_class(out) == "down"


def test_optional_support_rejects_nan():
    out = SimpleNamespace(continuation_support=float("nan"))
    assert _optional_support(out, "continuation_support") is None


def test_bayesian_update_skips_nan_likelihood():
    priors = dict(DEFAULT_PRIORS)
    out = _bayesian_update(priors, [{"breakout": float("nan")}], [1.0])
    assert out == priors


def test_malformed_signal_layer_blend_env_still_fuses(monkeypatch, caplog):
    monkeypatch.setenv("ED_SIGNAL_LAYER_FUSION_BLEND", "not-a-float")
    regime = SimpleNamespace(primary="pinning", confidence="medium")
    rules = SimpleNamespace(signal="wait", conviction="medium")
    xgb = SimpleNamespace(
        available=True,
        prob_up=0.5,
        prob_down=0.3,
        prob_flat=0.2,
        dominant_class="up",
        confidence_label="medium",
        continuation_support=0.25,
        reversal_support=0.15,
    )
    lstm = SimpleNamespace(available=False)
    tr = SimpleNamespace(available=False)
    mc = SimpleNamespace(available=False)
    sl = {"meta.n_bars": 30, "direction_probs": {"up": 0.4, "down": 0.35, "flat": 0.25}}
    with caplog.at_level("DEBUG", logger="bayesian_fusion"):
        payload = fuse(regime, xgb, lstm, tr, mc, rules, signal_layer_v1=sl)
    assert payload.available is True
    assert "ED_SIGNAL_LAYER_FUSION_BLEND ignored" in caplog.text


def test_fuse_payload_dominant_direction_from_triplet():
    regime = SimpleNamespace(primary="breakout", confidence="high")
    rules = SimpleNamespace(signal="long", conviction="high")
    xgb = SimpleNamespace(
        available=True,
        prob_up=0.1,
        prob_down=0.7,
        prob_flat=0.2,
        dominant_class="up",
        confidence_label="high",
        continuation_support=0.4,
        reversal_support=0.2,
    )
    lstm = SimpleNamespace(available=False)
    tr = SimpleNamespace(available=False)
    mc = SimpleNamespace(available=False)
    payload = fuse(regime, xgb, lstm, tr, mc, rules)
    assert payload.available is True
    assert payload.dominant_direction == "down"


def test_fuse_evidence_xgb_uses_triplet_dominant_not_upstream_label():
    """OBS-BF-1: evidence summary must match triplet-derived direction, not dominant_class."""
    regime = SimpleNamespace(primary="breakout", confidence="high")
    rules = SimpleNamespace(signal="long", conviction="high")
    xgb = SimpleNamespace(
        available=True,
        prob_up=0.1,
        prob_down=0.7,
        prob_flat=0.2,
        dominant_class="up",
        confidence_label="high",
        continuation_support=0.4,
        reversal_support=0.2,
    )
    lstm = SimpleNamespace(available=False)
    tr = SimpleNamespace(available=False)
    mc = SimpleNamespace(available=False)
    payload = fuse(regime, xgb, lstm, tr, mc, rules)
    xgb_lines = [e for e in payload.evidence_summary if e.startswith("XGB:")]
    assert len(xgb_lines) == 1
    assert "XGB: down" in xgb_lines[0]
    assert "XGB: up" not in xgb_lines[0]
