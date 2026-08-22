"""RC-455: range×imbalance stall/push is not microstructure absorption."""
from __future__ import annotations

from features.db_feature_adapter import build_db_mvp_feature_row
from institutional_behavior import (
    LEGACY_ABSORPTION_SEMANTIC_ERA,
    RANGE_IMBALANCE_SEMANTIC_ERA,
    compute_liquidity_behavior_row,
)


def test_doji_with_imbalance_is_stall_only():
    d = compute_liquidity_behavior_row(
        high=101.0,
        low=100.0,
        open_=100.5,
        close=100.5,
        volume=10_000,
        flow_imbalance=0.80,
        order_flow_score=99.0,
        net_gamma=1e9,
    )
    assert d["range_imbalance_stall_score"] == 0.80
    assert d["range_imbalance_push_score"] == 0.0
    assert d["range_imbalance_label"] == "stall_heavy"
    assert d["absorption_score"] is None
    assert d["continuation_score"] is None
    assert d["legacy_absorption_quarantined"] is True
    assert d["semantic_era"] == RANGE_IMBALANCE_SEMANTIC_ERA
    assert d["legacy_absorption_semantic_era"] == LEGACY_ABSORPTION_SEMANTIC_ERA


def test_full_body_with_imbalance_is_push_only():
    d = compute_liquidity_behavior_row(
        high=101.0,
        low=100.0,
        open_=100.0,
        close=101.0,
        volume=10_000,
        flow_imbalance=-0.50,
    )
    assert d["range_imbalance_push_score"] == 0.50
    assert d["range_imbalance_stall_score"] == 0.0
    assert d["range_imbalance_label"] == "push_heavy"


def test_retired_composite_and_gamma_do_not_change_score():
    a = compute_liquidity_behavior_row(
        high=101.0, low=100.0, open_=100.2, close=100.8, volume=1.0, flow_imbalance=0.4
    )
    b = compute_liquidity_behavior_row(
        high=101.0,
        low=100.0,
        open_=100.2,
        close=100.8,
        volume=9_999_999,
        flow_imbalance=0.4,
        order_flow_score=100.0,
        net_gamma=-1e12,
    )
    assert a["range_imbalance_stall_score"] == b["range_imbalance_stall_score"]
    assert a["range_imbalance_push_score"] == b["range_imbalance_push_score"]


def test_missing_ohlc_fails_closed():
    d = compute_liquidity_behavior_row(flow_imbalance=0.9)
    assert d["range_imbalance_stall_score"] is None
    assert d["range_imbalance_push_score"] is None
    assert d["range_imbalance_label"] is None


def test_no_magic_constant_tokens_in_producer_source():
    from pathlib import Path

    src = Path("institutional_behavior.py").read_text(encoding="utf-8")
    body = src.split('"""', 2)[-1] if '"""' in src else src
    for tok in (
        "0.52",
        "0.48",
        "1.15",
        "0.85",
        "0.0012",
        "900",
        "1.25",
        "/18",
        "1.08",
        "0.92",
        "1.06",
        "0.94",
        "0.12",
    ):
        assert tok not in body, tok


def test_historical_absorption_columns_do_not_map_into_new_features():
    row = build_db_mvp_feature_row(
        {
            "spot": 450.0,
            "spread": 0.02,
            "zone": "pin_bull",
            "nearest_above_dist": 1.5,
            "nearest_below_dist": -2.0,
            "net_gamma": 1e6,
            "vwap_side": "above",
            "vwap_dist_pts": 0.25,
            "absorption_score": 0.99,
            "continuation_score": 0.88,
        }
    )
    assert row["liquidity.range_imbalance_stall_score"] is None
    assert row["liquidity.range_imbalance_push_score"] is None


def test_new_db_columns_map_when_present():
    row = build_db_mvp_feature_row(
        {
            "range_imbalance_stall_score": 0.25,
            "range_imbalance_push_score": 0.40,
        }
    )
    assert row["liquidity.range_imbalance_stall_score"] == 0.25
    assert row["liquidity.range_imbalance_push_score"] == 0.40
