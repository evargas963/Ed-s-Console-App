"""META_XGB_TB_INGEST_V1 seams — session windows, mask-and-drop, purged folds.

Drives the real ingest functions; no mocks, no imputation anywhere.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from research.pilot_step3.data_loader import Bar1m
from research.pilot_step3.event_generation import PilotEvent
from research.pilot_step3.meta_xgb_tb_runner import (
    FEATURE_NAMES,
    CandidateRow,
    candidate_features,
    mask_and_drop,
    purged_session_folds,
)

ET = ZoneInfo("America/New_York")
REAL = "schwab_1m_accumulator_sqlite"


def _mk_bars(n=40, *, start=(10, 0), price=680.0, step=0.1):
    t0 = datetime(2026, 7, 22, *start, tzinfo=ET)
    out = []
    px = price
    for i in range(n):
        s = (t0 + timedelta(minutes=i)).timestamp()
        out.append(Bar1m(s, s + 60.0, px, px + 0.2, px - 0.2, px + step, 100.0, REAL))
        px += step
    return out


def _ev(i_sig):
    return PilotEvent(
        event_id=f"m-{i_sig}", signal_bar_index=i_sig, T_close_ts_utc=0.0, side="LONG",
        sma_fast=680.5, sma_slow=680.0, cusum_pos=2.6, cusum_neg=0.0, z_trigger=3.1,
        candidate_generator_id="meta_fixture",
    )


def test_features_are_complete_deep_in_session_and_masked_at_open():
    bars = _mk_bars()
    deep = candidate_features(bars, _ev(30), atr_t1=0.5, prev_session_close=679.0)
    assert set(deep.keys()) == set(FEATURE_NAMES)
    assert all(v is not None for v in deep.values())
    early = candidate_features(bars, _ev(3), atr_t1=0.5, prev_session_close=679.0)
    assert early["ret_15m_atr"] is None      # window would cross the open -> masked
    assert early["rv_15m_atr"] is None
    assert early["ret_5m_atr"] is None       # 5-bar window incomplete at index 3


def test_overnight_gap_is_named_feature_and_none_on_first_session():
    bars = _mk_bars()
    with_prev = candidate_features(bars, _ev(30), atr_t1=0.5, prev_session_close=679.0)
    assert abs(with_prev["overnight_gap_atr"] - (680.0 - 679.0) / 0.5) < 1e-9
    first = candidate_features(bars, _ev(30), atr_t1=0.5, prev_session_close=None)
    assert first["overnight_gap_atr"] is None


def test_missing_atr_masks_every_feature():
    bars = _mk_bars()
    out = candidate_features(bars, _ev(30), atr_t1=None, prev_session_close=679.0)
    assert all(v is None for v in out.values())


def test_mask_and_drop_is_absolute():
    good = CandidateRow(
        "2026-07-22", {name: 1.0 for name in FEATURE_NAMES}, 1, 5.0, None
    )
    holey = CandidateRow(
        "2026-07-22", {**{name: 1.0 for name in FEATURE_NAMES}, "rv_15m_atr": None}, 0, -4.0, None
    )
    unlabeled = CandidateRow(
        "2026-07-22", {name: 1.0 for name in FEATURE_NAMES}, None, None, "non_binary_TIMEOUT"
    )
    x, y, sessions, net, dropped = mask_and_drop([good, holey, unlabeled])
    assert len(x) == 1 and y == [1] and net == [5.0]
    assert dropped == 2
    assert all(all(v == v for v in row) for row in x)  # no NaN survives


def test_purged_folds_have_embargo_gap_and_no_overlap():
    days = [f"2026-06-{d:02d}" for d in range(1, 31)]
    folds = purged_session_folds(days, n_folds=5, embargo_sessions=1)
    assert folds
    for train, test in folds:
        assert set(train).isdisjoint(test)
        # embargo: the session immediately before the first test day is excluded
        gap_day = days[days.index(test[0]) - 1]
        assert gap_day not in train
        assert max(train) < min(test)
