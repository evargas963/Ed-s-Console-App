"""Tests for tools/replay_money_path_probe.py (pure helpers; no full DB replay in CI)."""
from __future__ import annotations

import datetime

from tools.replay_money_path_probe import (
    CLASS_REPLAY_DRIFT_FROM_LIVE_POLICY,
    CLASS_SIGNAL_EXPOSED,
    CLASS_SIGNAL_MISSING_DUE_TO_DATA,
    CLASS_SIGNAL_SUPPRESSED_BY_POLICY,
    classify_suppression_layer,
    classify_ticker_evidence,
    parse_date,
    rth_window_utc,
    ui_card_derivation,
)


def test_rth_window_june_16_2026():
    day = parse_date("2026-06-16")
    start, end = rth_window_utc(day)
    assert end > start
    et = datetime.timezone(datetime.timedelta(hours=-4))
    open_et = datetime.datetime.fromtimestamp(start, datetime.timezone.utc).astimezone(et)
    assert open_et.hour == 9 and open_et.minute == 30


def test_ui_card_derivation_tradeable_short():
    ui = ui_card_derivation("SHORT", True, "watch")
    assert ui["ALL_pill_direction"] == "SHORT"
    assert ui["ALL_pill_visual_state"] == "directional"
    assert ui["PLAN_pill_state"] == "WATCH"


def test_ui_card_derivation_not_tradeable_long_bias():
    ui = ui_card_derivation("LONG", False, "no_setup")
    assert ui["ALL_pill_direction"] == "FLAT"
    assert ui["PLAN_pill_state"] == "NO SETUP"


def test_classify_suppression_multi_horizon_alignment():
    layer = classify_suppression_layer(
        {
            "final_tradeable": False,
            "wait_reason": "fewer than 2 tradeable horizons align — ALL synthesis withheld",
            "fusion_available": True,
        }
    )
    assert layer == "multi_horizon_alignment"


def test_classify_ticker_evidence_sparse_data():
    tags = classify_ticker_evidence(
        {"normalized_rows_rth": 19},
        {"tradeable_windows": []},
        [{"final_tradeable": False, "suppression_layer": "multi_horizon_alignment"}],
    )
    assert CLASS_SIGNAL_MISSING_DUE_TO_DATA in tags
    assert CLASS_SIGNAL_SUPPRESSED_BY_POLICY in tags


def test_classify_ticker_evidence_live_tradeable():
    tags = classify_ticker_evidence(
        {"normalized_rows_rth": 368},
        {"tradeable_windows": [{"ts_utc": 1.0, "final_tradeable": True}]},
        [{"final_tradeable": True, "ts_utc": 1.0}],
    )
    assert CLASS_SIGNAL_EXPOSED in tags


def test_classify_ticker_evidence_replay_drift():
    tags = classify_ticker_evidence(
        {"normalized_rows_rth": 368},
        {"tradeable_windows": [{"ts_utc": 1.0, "final_tradeable": True}]},
        [{"final_tradeable": False, "replay_drift": True, "suppression_layer": "stack_vote_tie"}],
    )
    assert CLASS_REPLAY_DRIFT_FROM_LIVE_POLICY in tags
