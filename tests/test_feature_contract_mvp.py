"""
MVP canonical feature contract, live/DB adapters, inference snapshot, gap report.
"""
from __future__ import annotations

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












