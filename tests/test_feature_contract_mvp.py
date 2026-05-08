"""
MVP canonical feature contract, live/DB adapters, inference snapshot, gap report.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_contract_mvp_names_unique_and_specs_complete():
    from features.canonical_contract import (
        CANONICAL_FEATURE_TIMEFRAME,
        CANONICAL_FEATURE_CONTRACT_VERSION,
        get_mvp_feature_names,
        get_feature_spec,
        get_mvp_field_semantics,
    )

    assert CANONICAL_FEATURE_TIMEFRAME == "1m"
    assert CANONICAL_FEATURE_CONTRACT_VERSION == "v1_1m_mvp"
    names = list(get_mvp_feature_names())
    assert len(names) == len(set(names))
    for n in names:
        spec = get_feature_spec(n)
        assert spec["canonical_name"] == n
        for key in (
            "dtype",
            "missing_semantics",
            "source_category",
            "live_supported",
            "db_supported",
            "training_supported",
            "inference_supported",
        ):
            assert key in spec
        sem = get_mvp_field_semantics(n)
        for k in ("missing", "invalid", "valid"):
            assert k in sem and sem[k].strip()


def test_live_db_keys_identical_to_canonical_list():
    from features.live_feature_adapter import build_live_mvp_feature_row
    from features.db_feature_adapter import build_db_mvp_feature_row
    from features.canonical_contract import get_mvp_feature_names

    base_live = {
        "spot": 450.0,
        "spread": 0.0002,
        "spread_pts": 0.02,
        "zone": "pin_bull",
        "nearest_above_dist": 1.5,
        "nearest_below_dist": -2.0,
        "net_gamma": 1e6,
        "vwap_side": "above",
        "dist_to_vwap_pts": 0.25,
        "liquidity_summary": {"absorption_score": 0.3, "continuation_score": -0.1},
    }
    base_db = {
        "spot": 450.0,
        "spread": 0.02,
        "zone": "pin_bull",
        "nearest_above_dist": 1.5,
        "nearest_below_dist": -2.0,
        "net_gamma": 1e6,
        "vwap_side": "above",
        "vwap_dist_pts": 0.25,
        "absorption_score": 0.3,
        "continuation_score": -0.1,
    }
    lv = build_live_mvp_feature_row(base_live)
    db = build_db_mvp_feature_row(base_db)
    canon = list(get_mvp_feature_names())
    assert list(lv.keys()) == canon
    assert list(db.keys()) == canon


def test_live_adapter_ignores_spot_anchors_duplicate():
    from features.live_feature_adapter import build_live_mvp_feature_row
    from features.canonical_contract import validate_feature_contract_row

    payload = {
        "spot": 450.0,
        "spread": 0.0002,
        "spread_pts": 0.02,
        "zone": "pin_bull",
        "nearest_above_dist": 1.5,
        "nearest_below_dist": -2.0,
        "net_gamma": 1e6,
        "vwap_side": "above",
        "dist_to_vwap_pts": 0.25,
        "liquidity_summary": {"absorption_score": 0.3, "continuation_score": -0.1},
        "spot_anchors": {"vwap_side": "below", "dist_to_vwap_pts": 999.0},
    }
    row = build_live_mvp_feature_row(payload)
    assert row["anchor.vwap_side"] == "above"
    assert row["anchor.vwap_dist_pts"] == 0.25
    ok, errs = validate_feature_contract_row(row)
    assert ok, errs


def test_db_adapter_validates():
    from features.db_feature_adapter import build_db_mvp_feature_row
    from features.canonical_contract import validate_feature_contract_row

    snap = {
        "spot": 450.0,
        "spread": 0.02,
        "zone": "pin_bull",
        "nearest_above_dist": 1.5,
        "nearest_below_dist": -2.0,
        "net_gamma": 1e6,
        "vwap_side": "above",
        "vwap_dist_pts": 0.25,
        "absorption_score": 0.3,
        "continuation_score": -0.1,
    }
    row = build_db_mvp_feature_row(snap)
    ok, errs = validate_feature_contract_row(row)
    assert ok, errs


def test_cross_path_parity_and_uppercase_normalization():
    from features.live_feature_adapter import build_live_mvp_feature_row
    from features.db_feature_adapter import build_db_mvp_feature_row
    from features.canonical_contract import get_mvp_feature_names

    live = {
        "spot": 100.0,
        "spread": 0.0005,
        "spread_pts": 0.05,
        "zone": "PIN_NEUTRAL",
        "nearest_above_dist": 0.5,
        "nearest_below_dist": -0.5,
        "net_gamma": 1.0,
        "vwap_side": "Below",
        "dist_to_vwap_pts": -0.1,
        "liquidity_summary": {"absorption_score": 0.2, "continuation_score": 0.3},
    }
    db = {
        "spot": 100.0,
        "spread": 0.05,
        "zone": "pin_neutral",
        "nearest_above_dist": 0.5,
        "nearest_below_dist": -0.5,
        "net_gamma": 1.0,
        "vwap_side": "below",
        "vwap_dist_pts": -0.1,
        "absorption_score": 0.2,
        "continuation_score": 0.3,
    }
    a = build_live_mvp_feature_row(live)
    b = build_db_mvp_feature_row(db)
    assert list(a.keys()) == list(get_mvp_feature_names())
    assert a == b
    assert a["structure.zone"] == "pin_neutral"
    assert a["anchor.vwap_side"] == "below"


def test_live_adapter_uses_spread_pts_not_fractional_spread_for_canonical_points():
    from features.live_feature_adapter import build_live_mvp_feature_row

    row = build_live_mvp_feature_row({
        "spot": 100.0,
        "spread": 0.0005,
        "spread_pts": 0.05,
        "liquidity_summary": {},
    })

    assert row["price.spread_pts"] == 0.05


def test_validate_rejects_extra_keys():
    from features.canonical_contract import validate_feature_contract_row, get_mvp_feature_names

    row = {k: None for k in get_mvp_feature_names()}
    row["extra.bad"] = 1  # type: ignore[index]
    ok, errs = validate_feature_contract_row(row)
    assert not ok
    assert any("extra" in e for e in errs)


def test_validate_rejects_missing_keys():
    from features.canonical_contract import validate_feature_contract_row

    ok, errs = validate_feature_contract_row({"price.spot": 1.0})
    assert not ok
    assert any("missing" in e for e in errs)


def test_validate_rejects_wrong_key_order():
    from features.canonical_contract import validate_feature_contract_row, get_mvp_feature_names

    # Valid values but wrong insertion order
    names = list(get_mvp_feature_names())
    row = {k: None for k in reversed(names)}
    ok, errs = validate_feature_contract_row(row)
    assert not ok
    assert any("order" in e.lower() for e in errs)


def test_validate_rejects_bool_as_float():
    from features.canonical_contract import validate_feature_contract_row, get_mvp_feature_names

    row = {k: None for k in get_mvp_feature_names()}
    row["price.spot"] = True  # type: ignore[assignment]
    ok, errs = validate_feature_contract_row(row)
    assert not ok
    assert any("bool" in e.lower() for e in errs)


def test_validate_rejects_nan_and_inf():
    from features.canonical_contract import validate_feature_contract_row, get_mvp_feature_names

    row = {k: None for k in get_mvp_feature_names()}
    row["price.spot"] = float("nan")
    ok, errs = validate_feature_contract_row(row)
    assert not ok
    assert any("finite" in e.lower() or "nan" in e.lower() for e in errs)

    row = {k: None for k in get_mvp_feature_names()}
    row["structure.net_gamma"] = float("inf")
    ok, errs = validate_feature_contract_row(row)
    assert not ok


def test_validate_rejects_invalid_zone_enum():
    from features.canonical_contract import validate_feature_contract_row, get_mvp_feature_names

    row = {k: None for k in get_mvp_feature_names()}
    row["structure.zone"] = "not_a_zone"
    ok, errs = validate_feature_contract_row(row)
    assert not ok
    assert any("structure.zone" in e for e in errs)


def test_validate_rejects_invalid_vwap_side():
    from features.canonical_contract import validate_feature_contract_row, get_mvp_feature_names

    row = {k: None for k in get_mvp_feature_names()}
    row["anchor.vwap_side"] = "sideways"
    ok, errs = validate_feature_contract_row(row)
    assert not ok


def test_validate_rejects_empty_string_categorical():
    from features.canonical_contract import validate_feature_contract_row, get_mvp_feature_names

    row = {k: None for k in get_mvp_feature_names()}
    row["structure.zone"] = "   "
    ok, errs = validate_feature_contract_row(row)
    assert not ok


def test_validate_spot_nonpositive_rejected():
    from features.canonical_contract import validate_feature_contract_row, get_mvp_feature_names

    row = {k: None for k in get_mvp_feature_names()}
    row["price.spot"] = 0.0
    ok, errs = validate_feature_contract_row(row)
    assert not ok

    row = {k: None for k in get_mvp_feature_names()}
    row["price.spot"] = -1.0
    ok, errs = validate_feature_contract_row(row)
    assert not ok


def test_validate_spread_negative_rejected():
    from features.canonical_contract import validate_feature_contract_row, get_mvp_feature_names

    row = {k: None for k in get_mvp_feature_names()}
    row["price.spread_pts"] = -0.01
    ok, errs = validate_feature_contract_row(row)
    assert not ok


def test_signed_distances_allowed():
    from features.canonical_contract import validate_feature_contract_row, get_mvp_feature_names

    row = {k: None for k in get_mvp_feature_names()}
    row["structure.nearest_below_dist"] = -3.0
    row["structure.nearest_above_dist"] = 2.0
    ok, errs = validate_feature_contract_row(row)
    assert ok, errs


def test_inference_snapshot_v1_metadata_and_quality():
    from features.inference_snapshot import build_inference_snapshot_v1
    from features.canonical_contract import (
        validate_feature_contract_row,
        CANONICAL_FEATURE_CONTRACT_VERSION,
        CANONICAL_FEATURE_TIMEFRAME,
        INFERENCE_SNAPSHOT_SOURCE_LIVE_L1,
    )

    l1 = {
        "spot": 400.0,
        "spread": 0.01,
        "zone": "breakout",
        "nearest_above_dist": 2.0,
        "nearest_below_dist": -1.0,
        "net_gamma": 0.5,
        "vwap_side": "above",
        "dist_to_vwap_pts": 0.4,
        "liquidity_summary": {"absorption_score": None, "continuation_score": 0.1},
        "as_of_ts": 1700000000.0,
    }
    snap = build_inference_snapshot_v1(
        ticker="SPY",
        expiry=None,
        as_of_ts=None,
        l1_payload=l1,
    )
    assert snap["snapshot_type"] == "InferenceSnapshotV1"
    assert snap["feature_contract_version"] == CANONICAL_FEATURE_CONTRACT_VERSION
    assert snap["canonical_timeframe"] == CANONICAL_FEATURE_TIMEFRAME
    assert snap["source"] == INFERENCE_SNAPSHOT_SOURCE_LIVE_L1
    assert snap["ticker"] == "SPY"
    assert snap["as_of_ts"] == 1700000000.0
    fq = snap["feature_quality"]
    assert fq["present_count"] + fq["missing_count"] == 10
    assert len(fq["missing_fields"]) == fq["missing_count"]
    ok, _ = validate_feature_contract_row(snap["features"])
    assert ok


def test_inference_snapshot_v1_ignores_server_build_ts_for_as_of_ts():
    """D-S017-03: ingestion wall clock must not become InferenceSnapshotV1.as_of_ts."""
    from features.inference_snapshot import build_inference_snapshot_v1

    l1 = {
        "spot": 400.0,
        "spread": 0.01,
        "zone": "breakout",
        "nearest_above_dist": 2.0,
        "nearest_below_dist": -1.0,
        "net_gamma": 0.5,
        "vwap_side": "above",
        "dist_to_vwap_pts": 0.4,
        "liquidity_summary": {"absorption_score": None, "continuation_score": 0.1},
        "_server_build_ts": 9_999_999_999.0,
    }
    snap = build_inference_snapshot_v1(
        ticker="SPY",
        expiry=None,
        as_of_ts=None,
        l1_payload=l1,
    )
    assert snap["as_of_ts"] is None


def test_inference_snapshot_rejects_invalid_features():
    from features.inference_snapshot import build_inference_snapshot_v1

    with pytest.raises(ValueError, match="Invalid MVP feature row"):
        build_inference_snapshot_v1(
            ticker="SPY",
            expiry=None,
            as_of_ts=1.0,
            l1_payload={
                "spot": -1.0,
                "spread": 0.0,
                "zone": "pin_bull",
                "nearest_above_dist": None,
                "nearest_below_dist": None,
                "net_gamma": None,
                "vwap_side": "above",
                "dist_to_vwap_pts": None,
                "liquidity_summary": {},
            },
        )


def test_gap_report_structure():
    from features.feature_gap_report import compare_live_and_db_feature_support

    r = compare_live_and_db_feature_support()
    assert r["contract_version"] == "v1_1m_mvp"
    assert len(r["features"]) == 10
    assert all("chosen_live_source" in x for x in r["features"])


def test_validate_rejects_nan_in_canonical_row():
    from features.canonical_contract import validate_feature_contract_row, get_mvp_feature_names

    row = {k: None for k in get_mvp_feature_names()}
    row["liquidity.absorption_score"] = float("nan")
    ok, errs = validate_feature_contract_row(row)
    assert not ok


@pytest.mark.parametrize(
    "bad_spot",
    ["abc", "not_a_number", {}, [], [1.0]],
)
def test_live_adapter_invalid_spot_never_becomes_none(bad_spot):
    from features.live_feature_adapter import build_live_mvp_feature_row
    from features.mvp_source_coercion import MvpFeatureSourceError

    payload = {
        "spot": bad_spot,
        "spread": 0.02,
        "zone": "pin_bull",
        "nearest_above_dist": 1.0,
        "nearest_below_dist": -1.0,
        "net_gamma": 0.0,
        "vwap_side": "above",
        "dist_to_vwap_pts": 0.1,
        "liquidity_summary": {},
    }
    with pytest.raises(MvpFeatureSourceError):
        build_live_mvp_feature_row(payload)


@pytest.mark.parametrize(
    "bad_spot",
    ["abc", "not_a_number", {}, [], [1.0]],
)
def test_db_adapter_invalid_spot_never_becomes_none(bad_spot):
    from features.db_feature_adapter import build_db_mvp_feature_row
    from features.mvp_source_coercion import MvpFeatureSourceError

    snap = {
        "spot": bad_spot,
        "spread": 0.02,
        "zone": "pin_bull",
        "nearest_above_dist": 1.0,
        "nearest_below_dist": -1.0,
        "net_gamma": 0.0,
        "vwap_side": "above",
        "vwap_dist_pts": 0.1,
        "absorption_score": None,
        "continuation_score": None,
    }
    with pytest.raises(MvpFeatureSourceError):
        build_db_mvp_feature_row(snap)


def test_live_liquidity_summary_non_dict_raises():
    from features.live_feature_adapter import build_live_mvp_feature_row
    from features.mvp_source_coercion import MvpFeatureSourceError

    base = {
        "spot": 1.0,
        "spread": 0.02,
        "zone": "pin_bull",
        "nearest_above_dist": 1.0,
        "nearest_below_dist": -1.0,
        "net_gamma": 0.0,
        "vwap_side": "above",
        "dist_to_vwap_pts": 0.1,
    }
    for bad in ([], {}, 1, "x"):
        p = {**base, "liquidity_summary": bad}
        if bad == {}:
            build_live_mvp_feature_row(p)
            continue
        with pytest.raises(MvpFeatureSourceError):
            build_live_mvp_feature_row(p)


def test_live_nested_liquidity_invalid_numeric_raises():
    from features.live_feature_adapter import build_live_mvp_feature_row
    from features.mvp_source_coercion import MvpFeatureSourceError

    base = {
        "spot": 1.0,
        "spread": 0.02,
        "zone": "pin_bull",
        "nearest_above_dist": 1.0,
        "nearest_below_dist": -1.0,
        "net_gamma": 0.0,
        "vwap_side": "above",
        "dist_to_vwap_pts": 0.1,
        "liquidity_summary": {"absorption_score": "nope", "continuation_score": 0.1},
    }
    with pytest.raises(MvpFeatureSourceError):
        build_live_mvp_feature_row(base)


def test_live_adapter_invalid_zone_present_raises_not_missing():
    from features.live_feature_adapter import build_live_mvp_feature_row
    from features.mvp_source_coercion import MvpFeatureSourceError

    payload = {
        "spot": 1.0,
        "spread": 0.02,
        "zone": "not_a_zone",
        "nearest_above_dist": 1.0,
        "nearest_below_dist": -1.0,
        "net_gamma": 0.0,
        "vwap_side": "above",
        "dist_to_vwap_pts": 0.1,
        "liquidity_summary": {},
    }
    with pytest.raises(MvpFeatureSourceError, match="not in locked vocabulary"):
        build_live_mvp_feature_row(payload)


def test_adapter_present_nan_raises_not_none():
    from features.live_feature_adapter import build_live_mvp_feature_row
    from features.mvp_source_coercion import MvpFeatureSourceError

    payload = {
        "spot": float("nan"),
        "spread": 0.02,
        "zone": "pin_bull",
        "nearest_above_dist": 1.0,
        "nearest_below_dist": -1.0,
        "net_gamma": 0.0,
        "vwap_side": "above",
        "dist_to_vwap_pts": 0.1,
        "liquidity_summary": {},
    }
    with pytest.raises(MvpFeatureSourceError):
        build_live_mvp_feature_row(payload)


def test_inference_snapshot_raises_on_invalid_l1_coercion():
    from features.inference_snapshot import build_inference_snapshot_v1
    from features.mvp_source_coercion import MvpFeatureSourceError

    with pytest.raises(MvpFeatureSourceError):
        build_inference_snapshot_v1(
            ticker="SPY",
            expiry=None,
            as_of_ts=1.0,
            l1_payload={
                "spot": "not_a_number",
                "spread": 0.0,
                "zone": "pin_bull",
                "nearest_above_dist": None,
                "nearest_below_dist": None,
                "net_gamma": None,
                "vwap_side": "above",
                "dist_to_vwap_pts": None,
                "liquidity_summary": {},
            },
        )


def test_semantic_parity_controlled_fixtures():
    from features.semantic_parity import assert_live_db_canonicalization_equivalent

    live = {
        "spot": 450.0,
        "spread": 0.0002,
        "spread_pts": 0.02,
        "zone": "pin_bull",
        "nearest_above_dist": 1.5,
        "nearest_below_dist": -2.0,
        "net_gamma": 1e6,
        "vwap_side": "above",
        "dist_to_vwap_pts": 0.25,
        "liquidity_summary": {"absorption_score": 0.3, "continuation_score": -0.1},
    }
    db = {
        "spot": 450.0,
        "spread": 0.02,
        "zone": "pin_bull",
        "nearest_above_dist": 1.5,
        "nearest_below_dist": -2.0,
        "net_gamma": 1e6,
        "vwap_side": "above",
        "vwap_dist_pts": 0.25,
        "absorption_score": 0.3,
        "continuation_score": -0.1,
    }
    assert_live_db_canonicalization_equivalent(live, db)
