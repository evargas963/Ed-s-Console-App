"""LSTM sequence input: canonical MVP merge + InferenceSnapshotV1 live bar."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _isolate_ablation_survivors_env(monkeypatch):
    """Encoder cone tests must not inherit operator shell ED_APPLY_ABLATION_SURVIVORS=1."""
    monkeypatch.delenv("ED_APPLY_ABLATION_SURVIVORS", raising=False)
    monkeypatch.delenv("ED_ABLATION_DROP_GROUPS", raising=False)
    try:
        from arch_competition import stack_bundle_eval_v1 as sbe

        sbe._ablation_drop_snapshot_columns_cached.cache_clear()
        sbe.ablated_drop_group_ids_for_model_horizon.cache_clear()
        sbe.ablated_drop_members_for_model_horizon.cache_clear()
    except Exception:
        pass


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


def test_merge_strips_legacy_mvp_and_uses_canonical():
    from features.lstm_sequence_input import merge_db_row_with_canonical_mvp
    from features.canonical_contract import get_mvp_feature_names

    db = _base_db_row(1.0, spot=999.0)
    cf = {k: None for k in get_mvp_feature_names()}
    cf["price.spot"] = 450.0
    cf["price.spread_pts"] = 0.02
    cf["structure.zone"] = "pin_bull"
    cf["structure.nearest_above_dist"] = 1.0
    cf["structure.nearest_below_dist"] = -1.0
    cf["structure.net_gamma"] = 0.0
    cf["anchor.vwap_side"] = "above"
    cf["anchor.vwap_dist_pts"] = 0.1
    m = merge_db_row_with_canonical_mvp(db, cf)
    assert m["spot"] == 450.0
    assert m["zone"] == "pin_bull"
    assert m["vwap_side"] == "above"
    assert m["candle_body_pts"] == 0.1


def test_encode_snapshot_dimensions_match_features_lists():
    from lstm_data import (
        encode_snapshot_5m,
        encode_snapshot_1m,
        ENCODED_FEATURES_5M,
        ENCODED_FEATURES_1M,
        encoded_width_5m,
        encoded_width_1m,
    )
    from features.canonical_contract import get_mvp_feature_names

    cf = {k: None for k in get_mvp_feature_names()}
    cf["price.spot"] = 450.0
    cf["price.spread_pts"] = 0.02
    cf["structure.zone"] = "pin_bull"
    cf["structure.nearest_above_dist"] = 1.0
    cf["structure.nearest_below_dist"] = -1.0
    cf["structure.net_gamma"] = 0.0
    cf["anchor.vwap_side"] = "above"
    cf["anchor.vwap_dist_pts"] = 0.1
    db = _base_db_row(1.0)
    from features.lstm_sequence_input import merge_db_row_with_canonical_mvp

    merged = merge_db_row_with_canonical_mvp(db, cf)
    v5 = encode_snapshot_5m(merged, 450.0)
    v1 = encode_snapshot_1m(merged, 450.0)
    assert len(v5) == len(ENCODED_FEATURES_5M) == encoded_width_5m()
    assert len(v1) == len(ENCODED_FEATURES_1M) == encoded_width_1m()


def test_null_weighted_push_null_becomes_zero_in_tabular_encoder():
    """NULL spy_weighted_push → 0.0 in Stage 2 tabular encoder (no __present channel)."""
    from lstm_data import ENCODED_FEATURES_5M, encode_snapshot_5m

    row = _base_db_row(1.0)
    row["spy_weighted_push"] = None
    vec = encode_snapshot_5m(row, 450.0)
    idx = ENCODED_FEATURES_5M.index("spy_weighted_push")
    assert vec[idx] == 0.0


def test_weighted_push_present_in_tabular_encoder():
    from lstm_data import ENCODED_FEATURES_5M, encode_snapshot_5m

    row = _base_db_row(1.0)
    row["qqq_weighted_push"] = 0.42
    vec = encode_snapshot_5m(row, 450.0)
    idx = ENCODED_FEATURES_5M.index("qqq_weighted_push")
    assert vec[idx] == 0.42


def test_lstm_checkpoint_encoder_schema_guard():
    from lstm_data import (
        assert_lstm_encoder_checkpoint_compatible,
        LSTM_ENCODER_SCHEMA_VERSION,
        encoded_width_5m,
        encoded_width_1m,
    )

    assert_lstm_encoder_checkpoint_compatible(
        {
            "encoder_schema_version": LSTM_ENCODER_SCHEMA_VERSION,
            "encoder_width_5m_pre_mask": encoded_width_5m(),
            "encoder_width_1m_pre_mask": encoded_width_1m(),
        }
    )
    with pytest.raises(ValueError, match="encoder schema"):
        assert_lstm_encoder_checkpoint_compatible({"encoder_schema_version": 1})
    assert_lstm_encoder_checkpoint_compatible(
        {
            "encoder_schema_version": 2,
            "encoder_width_5m_pre_mask": 31,
            "encoder_width_1m_pre_mask": 16,
        }
    )


def test_inference_snapshot_wrong_version_fails():
    from features.lstm_sequence_input import build_lstm_merged_windows, LstmSequenceInputError

    inf = _minimal_valid_inference_v1()
    bad = copy.deepcopy(inf)
    bad["feature_contract_version"] = "wrong"
    win = [_base_db_row(1.0 + i) for i in range(3)]
    days = list(win)
    with pytest.raises(LstmSequenceInputError):
        build_lstm_merged_windows(win, days, inference_snapshot_v1=bad)


def test_inference_snapshot_wrong_timeframe_fails():
    from features.lstm_sequence_input import build_lstm_merged_windows, LstmSequenceInputError

    inf = _minimal_valid_inference_v1()
    bad = copy.deepcopy(inf)
    bad["canonical_timeframe"] = "5m"
    win = [_base_db_row(1.0 + i) for i in range(3)]
    days = list(win)
    with pytest.raises(LstmSequenceInputError):
        build_lstm_merged_windows(win, days, inference_snapshot_v1=bad)


def test_invalid_db_row_mvp_source_fails():
    from features.lstm_sequence_input import build_lstm_merged_windows, LstmSequenceInputError

    win = [_base_db_row(1.0)]
    win[0]["spot"] = "not_a_number"
    with pytest.raises(LstmSequenceInputError):
        build_lstm_merged_windows(win, list(win), inference_snapshot_v1=None)


def test_live_bar_overrides_db_mvp_with_inference_snapshot():
    from features.lstm_sequence_input import build_lstm_merged_windows

    inf = _minimal_valid_inference_v1()
    win = [_base_db_row(1.0 + i, spot=100.0) for i in range(3)]
    win[-1]["ts_utc"] = 1_700_000_100.0
    days = list(win)
    mw, md = build_lstm_merged_windows(win, days, inference_snapshot_v1=inf)
    assert mw[-1]["spot"] == 400.0
    assert mw[0]["spot"] == 100.0


def test_invalid_live_canonical_row_fails():
    from features.lstm_sequence_input import build_lstm_merged_windows, LstmSequenceInputError

    inf = _minimal_valid_inference_v1()
    bad = copy.deepcopy(inf)
    bad["features"]["price.spot"] = -1.0
    win = [_base_db_row(1.0)]
    with pytest.raises(LstmSequenceInputError, match="price.spot"):
        build_lstm_merged_windows(win, list(win), inference_snapshot_v1=bad)


def test_legacy_mvp_values_in_db_row_do_not_affect_merged_when_canonical_differs():
    """Poisoned legacy spot/zone must not survive merge — canonical wins."""
    from features.lstm_sequence_input import merge_db_row_with_canonical_mvp
    from features.canonical_contract import get_mvp_feature_names

    db = _base_db_row(1.0, spot=1.0)
    db["zone"] = "breakdown"
    cf = {k: None for k in get_mvp_feature_names()}
    cf["price.spot"] = 450.0
    cf["price.spread_pts"] = 0.02
    cf["structure.zone"] = "pin_bull"
    cf["structure.nearest_above_dist"] = 1.0
    cf["structure.nearest_below_dist"] = -1.0
    cf["structure.net_gamma"] = 0.0
    cf["anchor.vwap_side"] = "above"
    cf["anchor.vwap_dist_pts"] = 0.1
    m = merge_db_row_with_canonical_mvp(db, cf)
    assert m["spot"] == 450.0
    assert m["zone"] == "pin_bull"


# ── Workstream B3 — LSTM trains/selects on a time-ordered held-out tail ──────────


def _synthetic_lstm_dataset(n: int, seed: int = 0):
    import numpy as np

    from lstm_data import LSTMDataset, STREAM_1M_LOOKBACK, STREAM_5M_LOOKBACK

    rng = np.random.default_rng(seed)
    f5, f1, fc = 6, 5, 4
    return LSTMDataset(
        X_5m=rng.normal(size=(n, STREAM_5M_LOOKBACK, f5)).astype(np.float32),
        X_1m=rng.normal(size=(n, STREAM_1M_LOOKBACK, f1)).astype(np.float32),
        X_conf=rng.normal(size=(n, fc)).astype(np.float32),
        y=rng.integers(0, 3, n).astype(np.int64),
        tickers=["XXT"] * n,
        timestamps=[f"2026-03-{1 + i % 20:02d} 10:30:00" for i in range(n)],
        days=[f"2026-03-{1 + i % 20:02d}" for i in range(n)],
        ml_horizon_slug="1c",
        n_samples=n,
    )


def test_extract_rth_snapshots_hoists_imports_outside_row_loop():
    """Regression: per-row import + ablation manifest re-read hung 40-session extract for 40+ min."""
    import ast
    import inspect

    from lstm_data import extract_rth_snapshots

    tree = ast.parse(inspect.getsource(extract_rth_snapshots))
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        if not (
            isinstance(node.target, ast.Name)
            and node.target.id == "row"
        ):
            continue
        for child in ast.walk(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                raise AssertionError(
                    "extract_rth_snapshots must not import inside the row loop"
                )


def test_build_lstm_dataset_uses_end_idx_minus_one_for_confluence(monkeypatch):
    """Regression: snapshots.index(current) inside the slide loop is O(n²) and hung 40-session builds."""
    from lstm_data import STREAM_5M_LOOKBACK, build_lstm_dataset, compute_confluence_features

    seen: list[int] = []
    real_conf = compute_confluence_features

    def _spy_conf(snaps, idx):
        seen.append(idx)
        return real_conf(snaps, idx)

    n_snaps = STREAM_5M_LOOKBACK + 5
    day_snaps = [{"ts_utc": float(i), "spot": 100.0 + i * 0.01, "outcome_5c": "up"} for i in range(n_snaps)]
    for s in day_snaps:
        s["ts_et"] = "2026-01-02 10:00:00"

    monkeypatch.setattr("lstm_data.compute_confluence_features", _spy_conf)
    monkeypatch.setattr(
        "lstm_data.extract_rth_snapshots",
        lambda *a, **k: {"2026-01-02": day_snaps},
    )
    monkeypatch.setattr(
        "features.training_canonical_input.training_snapshot_for_sequence_encode",
        lambda snap: snap,
    )
    from lstm_data import encoded_width_5m, encoded_width_1m

    monkeypatch.setattr(
        "features.lstm_sequence_input.encode_lstm_structure_sequence_bar",
        lambda merged, ref: [0.0] * encoded_width_5m(),
    )
    monkeypatch.setattr(
        "features.lstm_sequence_input.encode_lstm_micro_sequence_bar",
        lambda merged, ref: [0.0] * encoded_width_1m(),
    )

    ds = build_lstm_dataset(["SPY"], require_outcome=True, ml_horizon_slug="5c")
    assert ds.n_samples == 5
    assert seen == list(range(STREAM_5M_LOOKBACK - 1, n_snaps - 1))


def test_train_lstm_b3_reports_out_of_sample_holdout(tmp_path, monkeypatch):
    """B3: LSTM reports an out-of-sample val metric, selects best_state on the val tail, and
    fits normalization on the train partition only."""
    import json

    import lstm_model as lm

    monkeypatch.setattr(lm, "EPOCHS", 2)
    n = 240
    ds = _synthetic_lstm_dataset(n)
    lm.train_lstm(dataset=ds, ticker="XXT", model_dir=tmp_path / "models", ml_horizon_slug="1c")
    meta = json.loads((tmp_path / "models" / "lstm_XXT_1c_meta.json").read_text(encoding="utf-8"))
    assert meta["val_basis"] == "time_ordered_tail"
    assert meta["n_val"] == round(n * 0.15)
    assert 0.0 <= float(meta["val_accuracy"]) <= 1.0
    assert 1 <= int(meta["best_epoch"]) <= 2


def test_train_lstm_b3_no_holdout_when_too_few_rows(tmp_path, monkeypatch):
    """Thin ticker: no honest holdout -> in-sample (disclosed)."""
    import json

    import lstm_model as lm

    monkeypatch.setattr(lm, "EPOCHS", 2)
    ds = _synthetic_lstm_dataset(80, seed=1)
    lm.train_lstm(dataset=ds, ticker="XXT", model_dir=tmp_path / "models", ml_horizon_slug="1c")
    meta = json.loads((tmp_path / "models" / "lstm_XXT_1c_meta.json").read_text(encoding="utf-8"))
    assert meta["val_basis"] == "in_sample_no_holdout"
    assert int(meta["n_val"]) == 0
