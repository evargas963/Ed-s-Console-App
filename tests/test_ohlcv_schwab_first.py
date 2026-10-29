"""Missing exposure buckets read as absent, not zero."""

from __future__ import annotations

from math_exposure_core import bucket_metric, net_gex_dollars_at_strike


def test_bucket_metric_missing_returns_none_not_zero():
    assert bucket_metric({}, "net_gex_1pct") is None
    assert net_gex_dollars_at_strike({}) is None
    assert bucket_metric({"net_gex_1pct": 0.0}, "net_gex_1pct") == 0.0


