"""Smoke tests: institutional behavior scores + news module import."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def test_liquidity_behavior_scores():
    from institutional_behavior import compute_liquidity_behavior_row

    d = compute_liquidity_behavior_row(
        spot=500.0,
        candle_open=500.0,
        candle_high=500.4,
        candle_low=499.9,
        candle_close=500.05,
        candle_volume=120_000,
        flow_imbalance=0.62,
        net_gamma=1e6,
        atr=1.2,
        candle_range_pts=0.5,
        candle_body_pts=0.05,
        order_flow_score=55.0,
    )
    assert "absorption_score" in d and "continuation_score" in d
    assert 0.0 <= d["absorption_score"] <= 1.0
    assert 0.0 <= d["continuation_score"] <= 1.0
    assert d["behavior_label"] in ("absorption_heavy", "continuation_heavy", "balanced")


def test_article_datetime_parse():
    from datetime import datetime

    from news_sentiment import _parse_article_datetime

    from time_et import ET as et  # noqa: F401
    ts = int(datetime(2026, 3, 1, 10, 0, 0, tzinfo=et).timestamp())
    d = _parse_article_datetime(ts)
    assert d is not None and d.year == 2026
    assert _parse_article_datetime(str(ts)) is not None


def test_headline_impact():
    from news_sentiment import classify_headline_impact

    assert classify_headline_impact("FDA approval for drug candidate") == "MEDIUM"
    assert classify_headline_impact("Tariff and sanction announced on imports") == "HIGH"
    assert classify_headline_impact("Company renews office lease") == "LOW"


def test_snapshot_row_has_context_fields():
    from db import SnapshotRow

    assert "sentiment_composite" in SnapshotRow.__dataclass_fields__
    assert "absorption_score" in SnapshotRow.__dataclass_fields__


if __name__ == "__main__":
    test_liquidity_behavior_scores()
    test_article_datetime_parse()
    test_headline_impact()
    test_snapshot_row_has_context_fields()
    print("context_layer: ok")
