"""Regression: engineer_features must not mutate read-only NumPy views (CI / pandas map path)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import ml_train
from ml_train import _mutable_float_ndarray, engineer_features, tabular_training_feature_names


def _volume_ratio_probe_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                **ml_train.probe_training_feature_row(),
                "candle_volume": 1000.0,
                "ts_utc": 1.0,
            },
            {
                **ml_train.probe_training_feature_row(),
                "candle_volume": 2000.0,
                "ts_utc": 2.0,
                "net_gamma": 2.0,
            },
        ]
    )


def test_mutable_float_ndarray_copies_readonly_input() -> None:
    ro = np.array([100.0, 0.0, np.nan], dtype=float)
    ro.flags.writeable = False
    out = _mutable_float_ndarray(ro)
    assert out.flags.writeable
    out[1] = np.nan
    assert np.isnan(out[1])


def test_engineer_features_with_candle_volume_does_not_raise() -> None:
    df = _volume_ratio_probe_df()
    X, names, _, _ = engineer_features(df)
    assert "volume_ratio" in names
    assert "candle_volume_log" in names
    assert np.isfinite(X["volume_ratio"].iloc[0])


def test_engineer_features_readonly_map_numpy_path(monkeypatch) -> None:
    """Simulate pandas map().to_numpy() returning a read-only float array."""
    df = _volume_ratio_probe_df()
    real_to_numpy = pd.Series.to_numpy

    def to_numpy_readonly(self, *args, **kwargs):
        if kwargs.get("dtype") is float or (args and args[0] is float):
            arr = real_to_numpy(self, *args, **kwargs)
            ro = np.array(arr, copy=False)
            ro.flags.writeable = False
            return ro
        return real_to_numpy(self, *args, **kwargs)

    monkeypatch.setattr(pd.Series, "to_numpy", to_numpy_readonly)
    X, names, _, _ = engineer_features(df)
    assert "volume_ratio" in names


def test_tabular_training_feature_names_refresh_path() -> None:
    ml_train._TABULAR_TRAINING_FEATURE_NAMES = None
    names = tabular_training_feature_names()
    assert names
    assert isinstance(names, list)


def test_registered_ml_columns_import_path() -> None:
    from tools.build_feature_assignment_matrix_v2 import _registered_ml_columns

    cols = _registered_ml_columns()
    assert isinstance(cols, dict)
    assert cols
