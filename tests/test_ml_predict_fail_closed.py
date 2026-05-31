"""Fail-closed contracts for ml_predict model-probability → fusion/UI conversion."""
from __future__ import annotations

import ml_predict as mp


def test_require_direction_probability_triplet_none_input():
    assert mp._require_direction_probability_triplet(None) is None


def test_require_direction_probability_triplet_missing_key():
    assert mp._require_direction_probability_triplet({"up": 0.5, "down": 0.3}) is None
    assert mp._require_direction_probability_triplet({"up": 0.5, "flat": 0.2}) is None


def test_require_direction_probability_triplet_complete():
    tri = mp._require_direction_probability_triplet({"up": 0.5, "down": 0.3, "flat": 0.2})
    assert tri == (0.5, 0.3, 0.2)


def test_model_probs_to_fusion_out_fail_closed_on_partial_dict():
    assert mp._model_probs_to_fusion_out({"up": 0.5, "down": 0.3}, "wait") is None


def test_model_probs_to_fusion_out_available_on_complete_dict():
    out = mp._model_probs_to_fusion_out(
        {"up": 0.5, "down": 0.3, "flat": 0.2},
        "long",
    )
    assert out is not None
    assert out["available"] is True
    assert out["prob_up"] == 0.5
    assert out["prob_down"] == 0.3
    assert out["prob_flat"] == 0.2
    assert out["dominant_class"] == "up"
    assert out["continuation_support"] == 0.5
    assert out["reversal_support"] == 0.3


def test_model_probs_to_fusion_out_none_input():
    assert mp._model_probs_to_fusion_out(None, "wait") is None


def test_model_probs_to_ui_output_fail_closed_on_partial_dict():
    out = mp._model_probs_to_ui_output({"up": 0.5, "down": 0.3}, approved=True)
    assert out["available"] is False
    assert out["dominant"] is None
    assert out["approved"] is False


def test_model_probs_to_ui_output_available_on_complete_dict():
    out = mp._model_probs_to_ui_output(
        {"up": 0.5, "down": 0.3, "flat": 0.2},
        approved=True,
    )
    assert out["available"] is True
    assert out["dominant"] == "up"
    assert out["up"] == 0.5
    assert out["down"] == 0.3
    assert out["flat"] == 0.2
    assert out["approved"] is True


def test_model_probs_to_ui_output_none_input():
    out = mp._model_probs_to_ui_output(None, approved=True)
    assert out["available"] is False


def test_parallel_base_stack_complete_requires_all_legs():
    tri = {"up": 0.4, "down": 0.3, "flat": 0.3}
    assert mp._parallel_base_stack_complete(tri, tri, tri) is True
    assert mp._parallel_base_stack_complete(tri, tri, None) is False
    assert mp._parallel_base_stack_complete(tri, {"up": 0.5}, tri) is False


def test_weighted_average_fail_closed_on_partial_stack():
    tri = {"up": 0.4, "down": 0.3, "flat": 0.3}
    assert mp._weighted_average("SPY", tri, tri, None) is None


def test_stack_probs_fail_closed_on_partial_stack():
    tri = {"up": 0.4, "down": 0.3, "flat": 0.3}
    assert mp._stack_probs(tri, tri, None) is None


def test_ensemble_parallel_probs_fail_closed_on_partial_stack():
    tri = {"up": 0.4, "down": 0.3, "flat": 0.3}
    assert mp._ensemble_parallel_probs("SPY", tri, None, tri) is None


# ── CLOSEOUT #3 — fusion meta<bases: collapsed-base exclusion in the combiner ──────────
import json

import pytest


def test_weighted_average_backcompat_identical_without_collapse():
    """No collapse flags => the prior fixed 0.40/0.35/0.25 weighting, byte-identical."""
    xgb = {"up": 0.8, "down": 0.1, "flat": 0.1}
    lstm = {"up": 0.2, "down": 0.5, "flat": 0.3}
    tr = {"up": 0.1, "down": 0.2, "flat": 0.7}
    got = mp._weighted_average("SPY", xgb, lstm, tr)
    exp = {
        "up": round(0.8 * 0.40 + 0.2 * 0.35 + 0.1 * 0.25, 4),
        "down": round(0.1 * 0.40 + 0.5 * 0.35 + 0.2 * 0.25, 4),
        "flat": round(0.1 * 0.40 + 0.3 * 0.35 + 0.7 * 0.25, 4),
    }
    assert got == exp


def test_weighted_average_drops_collapsed_base_and_renormalizes():
    """A collapsed (confident all-flat) XGB is excluded; LSTM/TR weights re-normalize."""
    xgb = {"up": 0.8, "down": 0.1, "flat": 0.1}  # confident — must NOT pull the result up
    lstm = {"up": 0.2, "down": 0.5, "flat": 0.3}
    tr = {"up": 0.1, "down": 0.2, "flat": 0.7}
    got = mp._weighted_average("SPY", xgb, lstm, tr, collapsed={"xgb"})
    wl, wt = 0.35 / 0.60, 0.25 / 0.60
    assert got["up"] == pytest.approx(round(0.2 * wl + 0.1 * wt, 4))
    assert got["down"] == pytest.approx(round(0.5 * wl + 0.2 * wt, 4))
    assert got["flat"] == pytest.approx(round(0.3 * wl + 0.7 * wt, 4))
    assert got["up"] < 0.2  # XGB's 0.8 up did not leak in


def test_weighted_average_all_collapsed_returns_uniform():
    tri = {"up": 0.4, "down": 0.3, "flat": 0.3}
    got = mp._weighted_average("SPY", tri, tri, tri, collapsed={"xgb", "lstm", "transformer"})
    assert got == mp._UNIFORM_PROBS


def test_read_base_collapse_flags(tmp_path):
    for base, flag in (("xgb", True), ("lstm", False), ("transformer", True)):
        (tmp_path / f"{base}_SPY_1c_meta.json").write_text(
            json.dumps({"val_single_class_collapse": flag}), encoding="utf-8"
        )
    assert mp.read_base_collapse_flags(tmp_path, "SPY", "1c") == {"xgb", "transformer"}


def test_read_base_collapse_flags_missing_and_bad_json(tmp_path):
    # only xgb present + flagged; lstm absent; transformer unreadable -> only xgb
    (tmp_path / "xgb_SPY_1c_meta.json").write_text(
        json.dumps({"val_single_class_collapse": True}), encoding="utf-8"
    )
    (tmp_path / "transformer_SPY_1c_meta.json").write_text("{not json", encoding="utf-8")
    assert mp.read_base_collapse_flags(tmp_path, "SPY", "1c") == {"xgb"}


def test_ensemble_all_collapsed_returns_uniform(monkeypatch):
    tri = {"up": 0.4, "down": 0.3, "flat": 0.3}
    monkeypatch.setattr(mp, "_active_base_collapse_flags", lambda t: {"xgb", "lstm", "transformer"})
    got = mp._ensemble_parallel_probs("SPY", tri, tri, tri)
    assert got == mp._UNIFORM_PROBS


def test_ensemble_backcompat_no_collapse_uses_weighted_average(monkeypatch):
    """No collapse + no meta => falls to the unchanged weighted average."""
    xgb = {"up": 0.8, "down": 0.1, "flat": 0.1}
    lstm = {"up": 0.2, "down": 0.5, "flat": 0.3}
    tr = {"up": 0.1, "down": 0.2, "flat": 0.7}
    monkeypatch.setattr(mp, "_active_base_collapse_flags", lambda t: set())
    monkeypatch.setattr(mp, "_predict_meta", lambda *a, **k: None)
    assert mp._ensemble_parallel_probs("SPY", xgb, lstm, tr) == mp._weighted_average("SPY", xgb, lstm, tr)
