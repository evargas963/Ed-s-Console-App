"""FIND-MLT-RTH-1: ml_train session clock features use time_et RTH authority."""

from __future__ import annotations

import inspect
from datetime import datetime, timezone

import numpy as np
import pytest

from ml_train import engineer_features, engineer_single_snapshot
from time_et import RTH_SESSION_MINUTES


def test_session_time_kernel_uses_rth_authority_and_builders_delegate() -> None:
    """RC-339 relocation of the SAME guarantee: session-clock math must use the time_et
    RTH constants and never hardcode 570/390 — and since the math now lives in ONE kernel
    (fk_session_time_features), the constants are asserted THERE, while both builders are
    required to delegate to it rather than carry clock math of their own."""
    from ml_train import fk_session_time_features

    ksrc = inspect.getsource(fk_session_time_features)
    assert "RTH_OPEN_MINS" in ksrc
    assert "RTH_SESSION_MINUTES" in ksrc
    assert "570" not in ksrc
    assert "390.0" not in ksrc

    for fn in (engineer_features, engineer_single_snapshot):
        src = inspect.getsource(fn)
        assert "fk_session_time_features" in src, f"{fn.__name__} does not delegate"
        assert "570" not in src
        assert "390.0" not in src
        assert "(hrs - 9)" not in src


def test_session_clock_features_match_rth_constants() -> None:
    """10:00 ET → 30 min since open, progress 30/390."""
    ts = datetime(2026, 7, 7, 14, 0, tzinfo=timezone.utc).timestamp()
    import pandas as pd

    df = pd.DataFrame({"spot": [100.0], "ts_utc": [ts], "zone": ["pin_bull"]})
    X, names, _, _ = engineer_features(df)
    assert "minutes_since_open" in names
    assert X["minutes_since_open"].iloc[0] == pytest.approx(30.0)
    assert X["time_progress"].iloc[0] == pytest.approx(30.0 / float(RTH_SESSION_MINUTES))

    # RC-336: the serve builder takes its clock from ts_utc, the same authority training
    # uses — never from the stored et_hour/et_minute columns. This call used to supply only
    # the stored clock and expect 30.0, which is precisely the fallback that made serving
    # disagree with training whenever ts_utc was absent (measured: 15 divergences, including
    # a stale stored clock yielding a confident minutes_since_open = 0.0). The RTH-constant
    # arithmetic under test is unchanged; only the clock source is now stated.
    snap = engineer_single_snapshot(
        {"spot": 100.0, "ts_utc": ts, "et_hour": 10, "et_minute": 0, "zone": "pin_bull"},
        category_maps={"zone": {"pin_bull": 0}},
        feature_names=["minutes_since_open", "time_progress", "cat_zone"],
    )
    assert snap is not None
    assert snap["minutes_since_open"].iloc[0] == pytest.approx(30.0)
    assert snap["time_progress"].iloc[0] == pytest.approx(30.0 / float(RTH_SESSION_MINUTES))

    # A STALE stored clock must not move the answer — ts_utc is the only authority.
    stale = engineer_single_snapshot(
        {"spot": 100.0, "ts_utc": ts, "et_hour": 3, "et_minute": 17, "zone": "pin_bull"},
        category_maps={"zone": {"pin_bull": 0}},
        feature_names=["minutes_since_open", "time_progress", "cat_zone"],
    )
    assert stale["minutes_since_open"].iloc[0] == pytest.approx(30.0), (
        "a stale stored et_hour changed the serve clock — ts_utc must be the only authority")

    # NO canonical clock means ABSENT, matching what engineer_features emits, not a number
    # manufactured from the stored columns.
    noclock = engineer_single_snapshot(
        {"spot": 100.0, "et_hour": 10, "et_minute": 0, "zone": "pin_bull"},
        category_maps={"zone": {"pin_bull": 0}},
        feature_names=["minutes_since_open", "time_progress", "cat_zone"],
    )
    assert np.isnan(noclock["minutes_since_open"].iloc[0]), (
        "serve fabricated a session clock from stored et_hour with no ts_utc (RC-336)")
    assert np.isnan(noclock["time_progress"].iloc[0])
