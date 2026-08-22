"""Layer 5 db_feature_adapter chunk-1: adapter contract locks + MSC1 propagation."""

from __future__ import annotations

import pytest

from features.canonical_contract import get_mvp_feature_names
from features.db_feature_adapter import build_db_mvp_feature_row
from features.mvp_source_coercion import MvpFeatureSourceError


def _full_db_row() -> dict:
    return {
        "spot": 450.0,
        "spread": 0.02,
        "zone": "pin_bull",
        "nearest_above_dist": 1.5,
        "nearest_below_dist": -2.0,
        "net_gamma": 1e6,
        "vwap_side": "above",
        "vwap_dist_pts": 0.25,
        "range_imbalance_stall_score": 0.3,
        "range_imbalance_push_score": -0.1,
    }


def test_build_db_mvp_feature_row_empty_dict_all_none():
    row = build_db_mvp_feature_row({})
    assert list(row.keys()) == list(get_mvp_feature_names())
    assert all(v is None for v in row.values())


def test_build_db_mvp_feature_row_none_parent_raises():
    with pytest.raises(MvpFeatureSourceError, match="parent must be a Mapping"):
        build_db_mvp_feature_row(None)  # type: ignore[arg-type]


def test_build_db_mvp_feature_row_non_dict_parent_raises():
    with pytest.raises(MvpFeatureSourceError, match="parent must be a Mapping"):
        build_db_mvp_feature_row("not a dict")  # type: ignore[arg-type]


def test_build_db_mvp_feature_row_key_order_matches_contract():
    row = build_db_mvp_feature_row(_full_db_row())
    assert list(row.keys()) == list(get_mvp_feature_names())


def test_build_db_mvp_feature_row_invalid_column_raises():
    with pytest.raises(MvpFeatureSourceError, match="unparseable numeric"):
        build_db_mvp_feature_row({"spot": "garbage"})


def test_build_db_mvp_feature_row_negative_spread_withheld_not_invalid():
    """Stored crossed-quote spread must not abort sequence encode for the whole window."""
    row = build_db_mvp_feature_row({"spot": 450.0, "spread": -0.01})
    assert row["price.spread_pts"] is None


def test_build_db_mvp_feature_row_valid_mapping():
    snap = _full_db_row()
    row = build_db_mvp_feature_row(snap)
    assert row["price.spot"] == 450.0
    assert row["price.spread_pts"] == 0.02
    assert row["structure.zone"] == "pin_bull"
    assert row["structure.nearest_above_dist"] == 1.5
    assert row["structure.nearest_below_dist"] == -2.0
    assert row["structure.net_gamma"] == 1e6
    assert row["anchor.vwap_side"] == "above"
    assert row["anchor.vwap_dist_pts"] == 0.25
    assert row["liquidity.range_imbalance_stall_score"] == 0.3
    assert row["liquidity.range_imbalance_push_score"] == -0.1
