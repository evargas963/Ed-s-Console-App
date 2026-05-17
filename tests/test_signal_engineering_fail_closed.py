"""signal_engineering filters and JSON parsing."""

from __future__ import annotations

import logging

import pytest

from calibration.signal_engineering import (
    _lj,
    filter_alignment_not_unusable,
    filter_vix_bucket_set,
    filter_vol_known,
)


def test_lj_uses_parse_json_mapping_warns_on_corrupt(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    out = _lj("{bad", context="signal_engineering:test")
    assert out == {}
    assert any("unparseable" in r.message for r in caplog.records)


def test_filter_alignment_excludes_missing_and_unknown() -> None:
    assert filter_alignment_not_unusable({"_features": {"alignment_state": "__missing__"}}) is False
    assert filter_alignment_not_unusable({"_features": {"alignment_state": "UNKNOWN"}}) is False
    assert filter_alignment_not_unusable({"_features": {"alignment_state": "ALIGNED"}}) is True
    assert filter_alignment_not_unusable({}) is False


def test_filter_vol_known_uses_axis_sentinel() -> None:
    assert filter_vol_known({"vol_regime": None}) is False
    assert filter_vol_known({"vol_regime": "unknown"}) is False
    assert filter_vol_known({"vol_regime": "elevated"}) is True


def test_filter_vix_bucket_set_uses_axis_sentinel() -> None:
    assert filter_vix_bucket_set({"vix_bucket": None}) is False
    assert filter_vix_bucket_set({"vix_bucket": ""}) is False
    assert filter_vix_bucket_set({"vix_bucket": "unknown"}) is False
    assert filter_vix_bucket_set({"vix_bucket": "low"}) is True
