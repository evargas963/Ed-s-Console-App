"""v2_decision.post_trade_attribution must build and persist an attribution record
carrying every required key, and load recent records back correctly -- a dropped
key would silently break the post-trade audit trail this record exists to provide."""
from __future__ import annotations

import pytest

from v2_decision.post_trade_attribution import (
    POST_TRADE_ATTRIBUTION_REQUIRED_KEYS,
    append_post_trade_attribution_record,
    build_post_trade_attribution_record,
    load_recent_post_trade_attribution_records,
    post_trade_attribution_log_path,
)


def _trade_row() -> dict:
    return {
        "architecture_type": "parallel",
        "ticker": "SPY",
        "signal_time": "2026-05-05T14:30:00Z",
        "entry_time": "2026-05-05T14:31:00Z",
        "exit_time": "2026-05-05T14:46:00Z",
        "right": "CALL",
        "strike": 500.0,
        "expiry": "2026-05-05",
        "contract_symbol": "SPY260505C00500000",
        "entry_price": 1.25,
        "exit_price": 1.55,
        "contracts": 1,
        "multiplier": 100,
        "pnl_dollars": 30.0,
        "pnl_percent": 24.0,
        "exit_reason": "target_hit",
        "hold_bars": 15,
        "skipped_flag": False,
        "skipped_reason": None,
        "snapshot_id_entry": 101,
        "snapshot_id_exit": 116,
        "pricing_entry_rule": "entry_price = ask",
        "pricing_exit_rule": "exit_price = bid",
        "path_model_used": "underlying_1m_ohlc",
        "same_bar_stop_target_conflict_flag": False,
        "same_bar_resolution_rule": None,
    }


def test_post_trade_attribution_record_has_required_v2_20_5_blocks():
    """Contract: Framework v2.0 §20.5 - close-out attribution record is structured."""
    record = build_post_trade_attribution_record(ticker="SPY", trade_row=_trade_row())

    assert POST_TRADE_ATTRIBUTION_REQUIRED_KEYS.issubset(record.keys())
    assert record["schema_version"] == "1"
    assert record["record_type"] == "v2_post_trade_attribution_close_out"
    for block in (
        "close_out_record",
        "signal_contribution",
        "execution_shortfall",
        "portfolio_allocation",
        "lifecycle_action",
        "tax_impact",
        "regime_context",
        "reason_code_outcome",
        "feedback",
    ):
        assert isinstance(record[block], dict)


def test_trade_log_row_maps_to_close_out_and_reason_code_fields():
    """Contract: realized contract evaluator rows can seed v2 close-out records."""
    record = build_post_trade_attribution_record(ticker="SPY", trade_row=_trade_row())

    close_out = record["close_out_record"]
    assert close_out["ticker"] == "SPY"
    assert close_out["expression_profile_id"] == "A2"
    assert close_out["contract_symbol"] == "SPY260505C00500000"
    assert close_out["pnl_dollars"] == 30.0
    assert close_out["snapshot_id_entry"] == 101
    assert close_out["snapshot_id_exit"] == 116

    assert record["reason_code_outcome"]["exit_reason"] == "target_hit"
    assert record["reason_code_outcome"]["primary_outcome_code"] == "target_hit"
    assert record["lifecycle_action"]["hold_bars"] == 15


def test_post_trade_attribution_append_and_load_jsonl(tmp_path):
    """Contract: scaffold is log-only append JSONL, not DB-bound."""
    record = build_post_trade_attribution_record(ticker="SPY", trade_row=_trade_row())

    path = append_post_trade_attribution_record(tmp_path, record)
    loaded = load_recent_post_trade_attribution_records(tmp_path)

    assert path == post_trade_attribution_log_path(tmp_path)
    assert path.is_file()
    assert loaded == [record]


def test_post_trade_attribution_rejects_missing_required_key(tmp_path):
    record = build_post_trade_attribution_record(ticker="SPY", trade_row=_trade_row())
    record.pop("feedback")

    with pytest.raises(ValueError, match="missing keys"):
        append_post_trade_attribution_record(tmp_path, record)


def test_post_trade_attribution_feedback_is_log_only_no_learning():
    """Contract: initial §20.5 scaffold must not feed calibration, lifecycle, or refit."""
    record = build_post_trade_attribution_record(ticker="SPY", trade_row=_trade_row())

    assert record["feedback"]["status"] == "log_only_no_learning"
    assert record["feedback"]["feeds_calibration"] is False
    assert record["feedback"]["feeds_execution_model"] is False
    assert record["feedback"]["feeds_lifecycle_policy"] is False
    assert record["feedback"]["feeds_refit"] is False
