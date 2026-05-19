"""Layer 5 canonical_contract chunk-1: gap-fill contract locks (see test_feature_contract_mvp.py)."""

from __future__ import annotations

import pytest

from features import canonical_contract as cc
from features.canonical_contract import (
    get_feature_spec,
    get_mvp_feature_names,
    get_mvp_field_semantics,
    validate_feature_contract_row,
)


def test_get_feature_spec_unknown_raises_key_error():
    with pytest.raises(KeyError, match="Unknown MVP feature"):
        get_feature_spec("unknown_field")


def test_get_mvp_field_semantics_unknown_raises_key_error():
    with pytest.raises(KeyError, match="Unknown MVP feature"):
        get_mvp_field_semantics("unknown_field")


def test_validate_rejects_non_numeric_string_for_spot():
    row = {k: None for k in get_mvp_feature_names()}
    row["price.spot"] = "garbage"  # type: ignore[assignment]
    ok, errs = validate_feature_contract_row(row)
    assert not ok
    assert any("price.spot" in e and "int, float" in e for e in errs)


def test_validate_rejects_uppercase_zone_without_normalization():
    row = {k: None for k in get_mvp_feature_names()}
    row["structure.zone"] = "PIN_BULL"
    ok, errs = validate_feature_contract_row(row)
    assert not ok
    assert any("normalized lowercase" in e for e in errs)


def test_validate_spread_zero_passes():
    row = {k: None for k in get_mvp_feature_names()}
    row["price.spread_pts"] = 0.0
    ok, errs = validate_feature_contract_row(row)
    assert ok, errs


def test_validate_all_none_row_passes():
    row = {k: None for k in get_mvp_feature_names()}
    ok, errs = validate_feature_contract_row(row)
    assert ok, errs


def test_mvp_specs_semantics_and_order_keys_aligned():
    spec_keys = set(cc._MVP_SPECS.keys())
    sem_keys = set(cc._MVP_FIELD_SEMANTICS.keys())
    order_keys = set(cc._MVP_FEATURE_ORDER)
    assert spec_keys == sem_keys == order_keys
    assert len(order_keys) == 10
