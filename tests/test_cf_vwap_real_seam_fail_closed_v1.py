"""Real-seam fail-closed proof: _predict_xgb / _predict_lstm / composition.

# universal-scope-ok: authorization gate applies to every enrolled cf_vwap consumer.
# next-rth-ok: 2026-08-31 Monday.
# chart-intent-ok: ML authorization only; Chart not claimed Done.

These tests execute the serving entrypoints. They fail if the VWAP gate is
removed or if LSTM authorization falls back to merged_window[-1].vwap.
"""

from __future__ import annotations

from types import MappingProxyType

import pandas as pd
import pytest

from features.canonical_contract import get_mvp_feature_names
from features.inference_snapshot import build_inference_snapshot_v1_from_feature_row
from features.shared_sequence_context import SharedSequenceContext
from lstm_data import (
    CONFLUENCE_FEATURES,
    LSTM_ENCODER_SCHEMA_VERSION,
    STREAM_5M_LOOKBACK,
    encoded_width_1m,
    encoded_width_5m,
)


@pytest.fixture(autouse=True)
def _isolate_ablation_survivors_env(monkeypatch):
    monkeypatch.delenv("ED_APPLY_ABLATION_SURVIVORS", raising=False)
    monkeypatch.delenv("ED_ABLATION_DROP_GROUPS", raising=False)


def _inference_v1(*, spot: float = 500.0, as_of: float = 1_700_000_100.0) -> dict:
    feats = {k: None for k in get_mvp_feature_names()}
    feats["price.spot"] = spot
    feats["price.spread_pts"] = 0.02
    feats["structure.zone"] = "pin_bull"
    feats["structure.nearest_above_dist"] = 1.0
    feats["structure.nearest_below_dist"] = -1.0
    feats["structure.net_gamma"] = 0.0
    feats["anchor.vwap_side"] = "above"
    feats["anchor.vwap_dist_pts"] = 0.0
    return build_inference_snapshot_v1_from_feature_row(
        ticker="SPY",
        expiry=None,
        as_of_ts=as_of,
        features=feats,
    )


def _install_xgb(monkeypatch, *, feature_names: list[str]) -> None:
    import ml_predict as mp

    class _FakeXgb:
        n_features_in_ = 1

        def predict_proba(self, x):
            return [[0.2, 0.3, 0.5]]

    monkeypatch.setattr(mp, "_load_xgb", lambda _t: True)
    monkeypatch.setattr(
        mp,
        "_xgb_registry",
        {
            mp._model_registry_key("SPY"): {
                "model": _FakeXgb(),
                "meta": {"impute_medians": {}, "features": list(feature_names)},
                "feature_names": list(feature_names),
                "category_maps": {},
                "vol_medians": {},
            }
        },
    )
    monkeypatch.setattr(
        "ml_train.engineer_single_snapshot",
        lambda **_k: pd.DataFrame([[0.0]], columns=["f0"]),
    )


def _lstm_bar(ts_utc: float, *, spot: float = 500.0, vwap) -> dict:
    return {
        "ts_utc": ts_utc,
        "ticker": "SPY",
        "spot": spot,
        "spread": 0.02,
        "zone": "pin_bull",
        "nearest_above_dist": 1.0,
        "nearest_below_dist": -1.0,
        "net_gamma": 0.0,
        "vwap_side": "above",
        "vwap_dist_pts": 0.0,
        "absorption_score": None,
        "continuation_score": None,
        "candle_body_pts": 0.1,
        "candle_range_pts": 0.2,
        "dist_call_gamma_wall": 1.0,
        "dist_put_gamma_wall": -1.0,
        "dist_gamma_inflection": 0.0,
        "dist_delta_inflection": 0.0,
        "dist_call_oi_wall": 1.0,
        "dist_put_oi_wall": -1.0,
        "dist_call_vanna_wall": 1.0,
        "dist_put_vanna_wall": -1.0,
        "dist_call_oi_wall_pct": 0.01,
        "dist_put_oi_wall_pct": -0.01,
        "dist_call_vanna_wall_pct": 0.01,
        "dist_put_vanna_wall_pct": -0.01,
        "spy_chg_pct": 0.0,
        "qqq_chg_pct": 0.0,
        "iwm_chg_pct": 0.0,
        "vix_level": 18.0,
        "iv_level": 0.2,
        "vwap": vwap,
    }


def _lstm_checkpoint(*, consumes_cf_vwap: bool) -> dict:
    w5 = encoded_width_5m()
    w1 = encoded_width_1m()
    mask_conf = [True] * len(CONFLUENCE_FEATURES)
    if not consumes_cf_vwap:
        mask_conf[CONFLUENCE_FEATURES.index("cf_vwap_distance_pct")] = False
    return {
        "encoder_schema_version": LSTM_ENCODER_SCHEMA_VERSION,
        "encoder_width_5m_pre_mask": w5,
        "encoder_width_1m_pre_mask": w1,
        "mask_5m": [True] * w5,
        "mask_1m": [True] * w1,
        "mask_conf": mask_conf,
    }


class _FakeLstm:
    def __call__(self, _x1, _x5, _xc):
        import torch

        return torch.tensor([[0.2, 0.3, 0.5]])


def _install_lstm(monkeypatch, *, consumes_cf_vwap: bool) -> SharedSequenceContext:
    import ml_predict as mp

    # History rows carry a genuine older VWAP. The last row is still a prior
    # generation relative to the current snapshot (as_of exclusive).
    bars = [
        _lstm_bar(1_700_000_000.0 + i * 60.0, vwap=499.25)
        for i in range(STREAM_5M_LOOKBACK)
    ]
    ctx = SharedSequenceContext(
        as_of_ts=1_700_000_100.0,
        chron_snapshots=tuple(bars),
        lstm_merged_window=tuple(bars),
        lstm_merged_days=tuple(bars),
        n_fetch=len(bars),
        meta=MappingProxyType({}),
    )
    monkeypatch.setattr(mp, "_load_lstm", lambda _t: True)
    monkeypatch.setattr(
        mp,
        "_lstm_registry",
        {mp._model_registry_key("SPY"): (_FakeLstm(), _lstm_checkpoint(consumes_cf_vwap=consumes_cf_vwap))},
    )
    return ctx


def _predict_lstm_seam(snapshot_vwap, ctx: SharedSequenceContext):
    import ml_predict as mp

    return mp._predict_lstm(
        "SPY",
        object(),
        snapshot={"ticker": "SPY", "spot": 500.0, "vwap": snapshot_vwap},
        inference_snapshot_v1=_inference_v1(),
        parallel_runtime=True,
        shared_sequence_context=ctx,
    )


def test_xgb_requiring_cf_vwap_abstains_when_current_session_vwap_absent(monkeypatch):
    import ml_predict as mp

    _install_xgb(monkeypatch, feature_names=["cf_vwap_distance_pct"])
    out = mp._predict_xgb(
        _inference_v1(),
        "SPY",
        fusion_feature_overlay={"ticker": "SPY", "spot": 500.0, "vwap": None},
    )
    assert out is None


def test_xgb_requiring_cf_vwap_allows_genuine_zero_distance(monkeypatch):
    import ml_predict as mp

    _install_xgb(monkeypatch, feature_names=["cf_vwap_distance_pct"])
    out = mp._predict_xgb(
        _inference_v1(spot=500.0),
        "SPY",
        fusion_feature_overlay={"ticker": "SPY", "spot": 500.0, "vwap": 500.0},
    )
    assert out == {"up": 0.2, "down": 0.3, "flat": 0.5}


def test_xgb_without_cf_vwap_not_blocked_when_session_vwap_absent(monkeypatch):
    import ml_predict as mp

    _install_xgb(monkeypatch, feature_names=["vwap_dist_pts"])
    out = mp._predict_xgb(
        _inference_v1(),
        "SPY",
        fusion_feature_overlay={"ticker": "SPY", "spot": 500.0, "vwap": None},
    )
    assert out == {"up": 0.2, "down": 0.3, "flat": 0.5}


def test_lstm_consuming_cf_vwap_abstains_when_current_session_vwap_absent(monkeypatch):
    ctx = _install_lstm(monkeypatch, consumes_cf_vwap=True)
    assert ctx.lstm_merged_window[-1]["vwap"] == 499.25
    assert _predict_lstm_seam(None, ctx) is None


def test_lstm_consuming_cf_vwap_allows_genuine_zero_distance(monkeypatch):
    ctx = _install_lstm(monkeypatch, consumes_cf_vwap=True)
    out = _predict_lstm_seam(500.0, ctx)
    assert out is not None
    assert set(out) == {"up", "down", "flat"}
    assert abs(sum(out.values()) - 1.0) < 1e-3


def test_lstm_not_consuming_cf_vwap_not_blocked_when_session_vwap_absent(monkeypatch):
    ctx = _install_lstm(monkeypatch, consumes_cf_vwap=False)
    out = _predict_lstm_seam(None, ctx)
    assert out is not None
    assert set(out) == {"up", "down", "flat"}


def test_stale_merged_window_vwap_cannot_authorize_dependent_lstm(monkeypatch):
    """Current canonical snapshot VWAP is NULL; history last row has an older VWAP.

    merged_window[-1] is as_of-exclusive history, not the decision generation.
    A dependent LSTM must still abstain.
    """
    ctx = _install_lstm(monkeypatch, consumes_cf_vwap=True)
    assert ctx.lstm_merged_window[-1]["vwap"] is not None
    assert ctx.lstm_merged_window[-1]["vwap"] != 500.0
    assert _predict_lstm_seam(None, ctx) is None
    # Same fixture is capable of producing a directional leg when current VWAP is present.
    assert _predict_lstm_seam(500.0, ctx) is not None


def test_withheld_legs_cannot_be_reauthorized_through_composition_meta_fusion(monkeypatch):
    import ml_predict as mp

    _install_xgb(monkeypatch, feature_names=["cf_vwap_distance_pct"])
    ctx = _install_lstm(monkeypatch, consumes_cf_vwap=True)
    monkeypatch.setattr(
        mp,
        "_predict_transformer",
        lambda *_a, **_k: {"up": 0.4, "down": 0.3, "flat": 0.3},
    )
    monkeypatch.setattr(mp, "_load_meta", lambda _t: True)

    class _FakeMeta:
        n_features_in_ = 9

        def predict_proba(self, x):
            return [[0.15, 0.15, 0.70]]

    monkeypatch.setattr(
        mp,
        "_meta_registry",
        {mp._model_registry_key("SPY"): _FakeMeta()},
    )

    overlay = {"ticker": "SPY", "spot": 500.0, "vwap": None}
    bundle = mp.run_unified_stack_ml_once(
        overlay,
        "SPY",
        object(),
        inference_snapshot_v1=_inference_v1(),
        shared_sequence_context=ctx,
        meta_tabular_overlay=overlay,
    )

    assert bundle["fusion"]["xgb"] is None
    assert bundle["fusion"]["lstm"] is None
    assert bundle["model_outputs"]["xgb"]["available"] is False
    assert bundle["model_outputs"]["lstm"]["available"] is False
    assert bundle["model_outputs"]["xgb"]["up"] is None
    assert bundle["model_outputs"]["lstm"]["up"] is None
    assert bundle[mp.stack_probs_bundle_key()] is None

    comp = bundle["stack_probs_composition"]
    assert comp["complete"] is False
    assert "xgb" in comp["missing"]
    assert "lstm" in comp["missing"]

    withheld = {"up": 0.2, "down": 0.3, "flat": 0.5}
    assert mp._stack_probs(None, withheld, withheld) is None
    assert mp._stack_probs(withheld, None, withheld) is None
    assert mp._predict_meta("SPY", None, withheld, withheld) is None
    assert mp._predict_meta("SPY", withheld, None, withheld) is None
    assert mp._ensemble_parallel_probs("SPY", None, withheld, withheld) is None
    assert mp._ensemble_parallel_probs("SPY", withheld, None, withheld) is None
    assert mp._model_probs_to_fusion_out(None, "wait") is None
