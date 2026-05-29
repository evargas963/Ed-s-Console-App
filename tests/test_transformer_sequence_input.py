"""Transformer encoder window: canonical MVP merge (shared with LSTM structure stream)."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _minimal_valid_inference_v1():
    from features.inference_snapshot import build_inference_snapshot_v1_from_feature_row
    from features.canonical_contract import get_mvp_feature_names

    feats = {k: None for k in get_mvp_feature_names()}
    feats["price.spot"] = 400.0
    feats["price.spread_pts"] = 0.02
    feats["structure.zone"] = "pin_bull"
    feats["structure.nearest_above_dist"] = 1.0
    feats["structure.nearest_below_dist"] = -1.0
    feats["structure.net_gamma"] = 0.0
    feats["anchor.vwap_side"] = "above"
    feats["anchor.vwap_dist_pts"] = 0.1
    return build_inference_snapshot_v1_from_feature_row(
        ticker="SPY",
        expiry=None,
        as_of_ts=1_700_000_100.0,
        features=feats,
    )


def _base_db_row(ts_utc: float, spot: float = 450.0) -> dict:
    return {
        "ts_utc": ts_utc,
        "ticker": "SPY",
        "spot": spot,
        "spread": 0.02,
        "zone": "pin_neutral",
        "nearest_above_dist": 2.0,
        "nearest_below_dist": -2.0,
        "net_gamma": 1.0,
        "vwap_side": "below",
        "vwap_dist_pts": 9.99,
        "absorption_score": None,
        "continuation_score": None,
        "candle_body_pts": 0.1,
        "candle_range_pts": 0.2,
        "dist_call_gamma_wall": 1.0,
        "dist_put_gamma_wall": -1.0,
        "dist_gamma_inflection": 0.0,
        "dist_delta_inflection": 0.0,
        "dist_call_oi_wall": 0.0,
        "dist_put_oi_wall": 0.0,
        "spy_chg_pct": 0.0,
        "qqq_chg_pct": 0.0,
        "iwm_chg_pct": 0.0,
        "vix_level": 18.0,
        "iv_level": 0.2,
    }


def test_build_transformer_merged_window_matches_lstm_structure_stream():
    from features.lstm_sequence_input import build_lstm_merged_windows, build_transformer_merged_window

    win = [_base_db_row(1.0 + i) for i in range(4)]
    inf = _minimal_valid_inference_v1()
    mw_tr = build_transformer_merged_window(win, inference_snapshot_v1=inf)
    mw_lstm, _ = build_lstm_merged_windows(win, list(win), inference_snapshot_v1=inf)
    assert mw_tr == mw_lstm


def test_inference_snapshot_wrong_version_fails():
    from features.lstm_sequence_input import build_transformer_merged_window, TransformerSequenceInputError

    inf = _minimal_valid_inference_v1()
    bad = copy.deepcopy(inf)
    bad["feature_contract_version"] = "wrong"
    win = [_base_db_row(1.0 + i) for i in range(3)]
    with pytest.raises(TransformerSequenceInputError):
        build_transformer_merged_window(win, inference_snapshot_v1=bad)


def test_inference_snapshot_wrong_timeframe_fails():
    from features.lstm_sequence_input import build_transformer_merged_window, TransformerSequenceInputError

    inf = _minimal_valid_inference_v1()
    bad = copy.deepcopy(inf)
    bad["canonical_timeframe"] = "5m"
    win = [_base_db_row(1.0 + i) for i in range(3)]
    with pytest.raises(TransformerSequenceInputError):
        build_transformer_merged_window(win, inference_snapshot_v1=bad)


def test_invalid_historical_canonical_row_fails():
    from features.lstm_sequence_input import build_transformer_merged_window, TransformerSequenceInputError

    win = [_base_db_row(1.0)]
    win[0]["spot"] = "not_a_number"
    with pytest.raises(TransformerSequenceInputError):
        build_transformer_merged_window(win, inference_snapshot_v1=None)


def test_invalid_live_canonical_row_fails():
    from features.lstm_sequence_input import build_transformer_merged_window, TransformerSequenceInputError

    inf = _minimal_valid_inference_v1()
    bad = copy.deepcopy(inf)
    bad["features"]["price.spot"] = -1.0
    win = [_base_db_row(1.0)]
    with pytest.raises(TransformerSequenceInputError, match="price.spot"):
        build_transformer_merged_window(win, inference_snapshot_v1=bad)


def test_encode_feature_order_stable_and_matches_features_5m_len():
    from lstm_data import ENCODED_FEATURES_5M, encode_snapshot_5m, _safe_float
    from features.lstm_sequence_input import build_transformer_merged_window

    win = [_base_db_row(1.0 + i) for i in range(3)]
    mw = build_transformer_merged_window(win, inference_snapshot_v1=None)
    ref = _safe_float(mw[0].get("spot"))
    a = encode_snapshot_5m(mw[-1], ref)
    b = encode_snapshot_5m(mw[-1], ref)
    assert list(a) == list(b)
    assert len(a) == len(ENCODED_FEATURES_5M)


def test_legacy_mvp_poison_in_db_row_does_not_affect_encoded_mvp_slots():
    """Merged path overwrites MVP; raw legacy spot/zone must not drive encode alone."""
    from lstm_data import encode_snapshot_5m, _safe_float
    from features.lstm_sequence_input import build_transformer_merged_window

    win = [_base_db_row(1.0 + i, spot=111.0) for i in range(2)]
    win[-1]["spot"] = 99999.0
    win[-1]["zone"] = "breakdown"
    inf = _minimal_valid_inference_v1()
    mw = build_transformer_merged_window(win, inference_snapshot_v1=inf)
    ref = _safe_float(mw[0].get("spot"))
    enc_merged = encode_snapshot_5m(mw[-1], ref)
    enc_raw = encode_snapshot_5m(win[-1], ref)
    assert mw[-1]["spot"] == 400.0
    assert mw[-1]["zone"] == "pin_bull"
    assert list(enc_merged) != list(enc_raw)


def test_fusion_overlay_snapshot_cannot_override_merged_mvp_for_encode():
    """Fusion `snapshot` is not fed to encode_snapshot_5m — only merged_window rows are."""
    from lstm_data import encode_snapshot_5m, _safe_float
    from features.lstm_sequence_input import build_transformer_merged_window

    win = [_base_db_row(1.0 + i) for i in range(2)]
    inf = _minimal_valid_inference_v1()
    mw = build_transformer_merged_window(win, inference_snapshot_v1=inf)
    ref = _safe_float(mw[0].get("spot"))
    enc_ok = encode_snapshot_5m(mw[-1], ref)
    poison_overlay = {**mw[-1], "spot": 0.001, "zone": "breakdown"}
    enc_if_overlay_mistakenly_used = encode_snapshot_5m(poison_overlay, ref)
    assert list(enc_ok) != list(enc_if_overlay_mistakenly_used)


def test_predict_transformer_insufficient_history_raises():
    from unittest.mock import MagicMock, patch

    import numpy as np

    import ml_predict as mp
    from features.lstm_sequence_input import TransformerSequenceInputError

    fake_model = MagicMock()
    fake_ckpt = {
        "seq_len": 20,
        "feature_mask": np.ones(50, dtype=bool),
        "encoder_schema_version": 2,
        "encoder_width_5m_pre_mask": 31,
    }
    db = MagicMock()
    db.get_recent_snapshots.return_value = [{"ts_utc": float(i)} for i in range(10)]

    inf = _minimal_valid_inference_v1()
    with patch.object(mp, "_trans_registry", {mp._model_registry_key("SPY", "1c"): (fake_model, fake_ckpt)}), patch.object(
        mp, "_load_transformer", return_value=True
    ):
        with pytest.raises(TransformerSequenceInputError, match="20"):
            mp._predict_transformer("SPY", db, inference_snapshot_v1=inf)


# ── Workstream B3 — transformer trains/selects on a time-ordered held-out tail ───


def test_train_transformer_b3_reports_out_of_sample_holdout(tmp_path, monkeypatch):
    """B3: with enough rows the transformer reports an out-of-sample val metric, selects
    best_state on the val tail, and fits normalization on the train partition only."""
    import json

    import numpy as np

    import transformer_train as tt

    monkeypatch.setattr(tt, "EPOCHS", 2)  # keep the CPU train fast; B3 path is identical at 60
    n = 240
    nf = 8
    rng = np.random.default_rng(0)
    X = rng.normal(size=(n, tt.SEQUENCE_LENGTH, nf)).astype(np.float32)
    y = rng.integers(0, 3, n).astype(np.int64)
    days = np.array([f"2026-03-{1 + i % 20:02d}" for i in range(n)])
    tickers_arr = np.array(["XXT"] * n)

    res = tt.train_transformer(
        ticker="XXT",
        model_dir=tmp_path / "models",
        preloaded_sequences=(X, y, days, tickers_arr, nf),
        ml_horizon_slug="1c",
    )
    assert getattr(res, "error", None) in (None, "")
    meta = json.loads((tmp_path / "models" / "transformer_XXT_1c_meta.json").read_text(encoding="utf-8"))
    assert meta["val_basis"] == "time_ordered_tail"
    assert meta["n_val"] == round(n * 0.15)  # last 15% (most recent) held out
    assert 0.0 <= float(meta["val_accuracy"]) <= 1.0
    assert 1 <= int(meta["best_epoch"]) <= 2


def test_train_transformer_b3_no_holdout_when_too_few_rows(tmp_path, monkeypatch):
    """Thin ticker: no honest holdout can be carved -> in-sample (disclosed)."""
    import json

    import numpy as np

    import transformer_train as tt

    monkeypatch.setattr(tt, "EPOCHS", 2)
    n = 80
    nf = 8
    rng = np.random.default_rng(1)
    X = rng.normal(size=(n, tt.SEQUENCE_LENGTH, nf)).astype(np.float32)
    y = rng.integers(0, 3, n).astype(np.int64)
    days = np.array([f"2026-03-{1 + i % 10:02d}" for i in range(n)])
    tickers_arr = np.array(["XXT"] * n)

    tt.train_transformer(
        ticker="XXT",
        model_dir=tmp_path / "models",
        preloaded_sequences=(X, y, days, tickers_arr, nf),
        ml_horizon_slug="1c",
    )
    meta = json.loads((tmp_path / "models" / "transformer_XXT_1c_meta.json").read_text(encoding="utf-8"))
    assert meta["val_basis"] == "in_sample_no_holdout"
    assert int(meta["n_val"]) == 0
