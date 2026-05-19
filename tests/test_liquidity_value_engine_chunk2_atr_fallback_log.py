"""liquidity_value_engine chunk-2: FIND-LVE1 — log when ATR clustering degrades to percent."""

from __future__ import annotations

import logging

import pytest

from liquidity_models import PlaybookConfig
from liquidity_value_engine import cluster_price_levels_into_zones


def test_atr_mode_logs_when_atr_value_unavailable(caplog: pytest.LogCaptureFixture):
    config = PlaybookConfig(clustering_mode="atr")
    levels = [(100.0, "PDH"), (100.05, "POC")]
    with caplog.at_level(logging.INFO, logger="liquidity_value_engine"):
        cluster_price_levels_into_zones(levels, 100.0, config, atr_value=None)
    assert any(
        "atr_value unavailable, falling back to percent threshold" in r.message
        for r in caplog.records
    )


def test_atr_mode_no_fallback_log_when_atr_present(caplog: pytest.LogCaptureFixture):
    config = PlaybookConfig(clustering_mode="atr")
    levels = [(100.0, "PDH"), (100.2, "POC")]
    with caplog.at_level(logging.INFO, logger="liquidity_value_engine"):
        cluster_price_levels_into_zones(levels, 100.0, config, atr_value=1.0)
    assert not any("falling back to percent threshold" in r.message for r in caplog.records)


def test_percent_mode_does_not_emit_atr_fallback_log(caplog: pytest.LogCaptureFixture):
    config = PlaybookConfig(clustering_mode="percent")
    levels = [(100.0, "PDH"), (100.05, "POC")]
    with caplog.at_level(logging.INFO, logger="liquidity_value_engine"):
        cluster_price_levels_into_zones(levels, 100.0, config, atr_value=None)
    assert not any("falling back to percent threshold" in r.message for r in caplog.records)
