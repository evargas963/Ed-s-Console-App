"""FIND-MLT-RTH-1: ml_train session clock features use time_et RTH authority."""

from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest

from ml_train import engineer_features, engineer_single_snapshot
from time_et import RTH_SESSION_MINUTES


def test_engineer_features_uses_rth_open_mins_authority() -> None:
    src = inspect.getsource(engineer_features)
    assert "RTH_OPEN_MINS" in src
    assert "RTH_SESSION_MINUTES" in src
    assert "570" not in src
    assert "390.0" not in src
    assert "(hrs - 9)" not in src


def test_engineer_single_snapshot_uses_rth_open_mins_authority() -> None:
    src = inspect.getsource(engineer_single_snapshot)
    assert "RTH_OPEN_MINS" in src
    assert "RTH_SESSION_MINUTES" in src
    assert "570" not in src
    assert "390.0" not in src


def test_session_clock_features_match_rth_constants() -> None:
    """10:00 ET → 30 min since open, progress 30/390."""
    ts = datetime(2026, 7, 7, 14, 0, tzinfo=timezone.utc).timestamp()
    import pandas as pd

    df = pd.DataFrame({"spot": [100.0], "ts_utc": [ts], "zone": ["pin_bull"]})
    X, names, _, _ = engineer_features(df)
    assert "minutes_since_open" in names
    assert X["minutes_since_open"].iloc[0] == pytest.approx(30.0)
    assert X["time_progress"].iloc[0] == pytest.approx(30.0 / float(RTH_SESSION_MINUTES))

    snap = engineer_single_snapshot(
        {"spot": 100.0, "et_hour": 10, "et_minute": 0, "zone": "pin_bull"},
        category_maps={"zone": {"pin_bull": 0}},
        feature_names=["minutes_since_open", "time_progress", "cat_zone"],
    )
    assert snap is not None
    assert snap["minutes_since_open"].iloc[0] == pytest.approx(30.0)
    assert snap["time_progress"].iloc[0] == pytest.approx(30.0 / float(RTH_SESSION_MINUTES))
