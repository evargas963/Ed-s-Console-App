"""Layer 5 training_cache.py fail-closed fingerprint and cache-load guards."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from training_cache import (
    _normalize_data_fp,
    compute_feature_cache_key,
    load_lstm_feature_cache,
    xgb_meta_content_sha256,
)
from features.training_canonical_input import training_canonical_lineage_header


def test_normalize_data_fp_distinguishes_missing_row_count_from_zero():
    assert _normalize_data_fp({"row_count": 0}) != _normalize_data_fp({})
    assert _normalize_data_fp({"row_count": 0})["row_count"] == 0
    assert _normalize_data_fp({}).get("row_count") is None


def test_feature_cache_key_differs_when_row_count_missing_vs_zero():
    base = {
        "min_ts_utc": 1.0,
        "max_ts_utc": 2.0,
        "table": "snapshots_1m_normalized",
        "timeframe": "1m",
    }
    code_fp = "abc"
    k_missing = compute_feature_cache_key("SPY", base, code_fp, target_column="outcome_5c")
    k_zero = compute_feature_cache_key(
        "SPY", {**base, "row_count": 0}, code_fp, target_column="outcome_5c"
    )
    assert k_missing != k_zero


def test_xgb_meta_content_sha256_missing_paths_do_not_collide_to_empty():
    a = Path("/tmp/nonexistent_xgb_meta_a.json")
    b = Path("/tmp/nonexistent_xgb_meta_b.json")
    assert xgb_meta_content_sha256(a) != xgb_meta_content_sha256(b)
    assert xgb_meta_content_sha256(a).startswith("MISSING:")


def test_load_lstm_feature_cache_rejects_missing_feature_dimensions(tmp_path: Path):
    from lstm_data import LSTMDataset

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    X = np.zeros((2, 1), dtype=np.float32)
    y = np.array([0, 1], dtype=np.int64)
    np.savez_compressed(
        cache_dir / "lstm_tensors.npz",
        X_5m=X,
        X_1m=X,
        X_conf=X,
        y=y,
    )
    meta = {
        "tickers": ["SPY"],
        "timestamps": [1.0, 2.0],
        "days": ["2026-05-05"],
        **training_canonical_lineage_header(),
    }
    (cache_dir / "lstm_dataset_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    data_fp = {
        "table": "snapshots_1m_normalized",
        "timeframe": "1m",
        "ticker": "SPY",
        "min_ts_utc": 1.0,
        "max_ts_utc": 2.0,
        "row_count": 2,
    }
    feature_key = "test_key"
    identity = {
        "ticker": "SPY",
        "feature_cache_key": feature_key,
        "data_fingerprint": data_fp,
        **training_canonical_lineage_header(),
    }
    (cache_dir / "feature_cache_identity.json").write_text(
        json.dumps(identity), encoding="utf-8"
    )

    assert (
        load_lstm_feature_cache(cache_dir, "SPY", data_fp, feature_key) is None
    )


def test_load_lstm_feature_cache_accepts_valid_meta(tmp_path: Path):
    cache_dir = tmp_path / "cache2"
    cache_dir.mkdir()
    X = np.zeros((2, 3), dtype=np.float32)
    y = np.array([0, 1], dtype=np.int64)
    np.savez_compressed(
        cache_dir / "lstm_tensors.npz",
        X_5m=X,
        X_1m=X,
        X_conf=X,
        y=y,
    )
    meta = {
        "tickers": ["SPY"],
        "timestamps": [1.0, 2.0],
        "days": ["2026-05-05"],
        "n_features_5m": 3,
        "n_features_1m": 3,
        "n_confluence": 3,
        "n_samples": 2,
        **training_canonical_lineage_header(),
    }
    (cache_dir / "lstm_dataset_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    data_fp = {
        "table": "snapshots_1m_normalized",
        "timeframe": "1m",
        "ticker": "SPY",
        "min_ts_utc": 1.0,
        "max_ts_utc": 2.0,
        "row_count": 2,
    }
    feature_key = "test_key2"
    identity = {
        "ticker": "SPY",
        "feature_cache_key": feature_key,
        "data_fingerprint": data_fp,
        **training_canonical_lineage_header(),
    }
    (cache_dir / "feature_cache_identity.json").write_text(
        json.dumps(identity), encoding="utf-8"
    )

    ds = load_lstm_feature_cache(cache_dir, "SPY", data_fp, feature_key)
    assert ds is not None
    assert ds.n_features_5m == 3
