"""Layer 5 mvp_source_coercion chunk-1: FIND-MSC1 + direct coercion contract locks."""

from __future__ import annotations

import pytest

from features.mvp_source_coercion import (
    MvpFeatureSourceError,
    _require_mapping,
    read_liquidity_summary_subdict,
    read_optional_float,
    read_optional_vwap_side,
    read_optional_zone,
    strict_float_from_raw,
)


def test_read_optional_float_non_mapping_parent_raises():
    with pytest.raises(MvpFeatureSourceError, match="parent must be a Mapping"):
        read_optional_float(None, "spot", "price.spot")
    with pytest.raises(MvpFeatureSourceError, match="parent must be a Mapping"):
        read_optional_float("not a dict", "spot", "price.spot")
    with pytest.raises(MvpFeatureSourceError, match="parent must be a Mapping"):
        read_optional_float([], "spot", "price.spot")


def test_read_optional_zone_non_mapping_parent_raises():
    with pytest.raises(MvpFeatureSourceError, match="parent must be a Mapping"):
        read_optional_zone(None, "zone", "structure.zone")


def test_read_optional_vwap_side_non_mapping_parent_raises():
    with pytest.raises(MvpFeatureSourceError, match="parent must be a Mapping"):
        read_optional_vwap_side(None, "vwap_side", "anchor.vwap_side")


def test_read_liquidity_summary_subdict_non_mapping_raises():
    with pytest.raises(MvpFeatureSourceError, match="parent must be a Mapping"):
        read_liquidity_summary_subdict(None)  # type: ignore[arg-type]
    with pytest.raises(MvpFeatureSourceError, match="parent must be a Mapping"):
        read_liquidity_summary_subdict([])  # type: ignore[arg-type]


def test_require_mapping_returns_dict_unchanged():
    d = {"spot": 1.0}
    assert _require_mapping(d, "price.spot") is d


def test_strict_float_from_raw_rejects_bool_container_and_nan():
    with pytest.raises(MvpFeatureSourceError, match="bool"):
        strict_float_from_raw(True, "price.spot")
    with pytest.raises(MvpFeatureSourceError, match="invalid type"):
        strict_float_from_raw({"x": 1}, "price.spot")
    with pytest.raises(MvpFeatureSourceError, match="non-finite"):
        strict_float_from_raw(float("nan"), "price.spot")


def test_read_liquidity_summary_missing_key_returns_empty_dict():
    assert read_liquidity_summary_subdict({}) == {}
