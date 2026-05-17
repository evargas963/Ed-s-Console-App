"""arch_competition.metrics fail-closed regime and confidence primitives (II, JJ)."""

from __future__ import annotations

import pytest
from sklearn.metrics import balanced_accuracy_score

from arch_competition.metrics import (
    confidence_reliability_proxy,
    max_calibration_error_bins,
    regime_bucket_metrics,
)


def _rows_and_probs(*, vix_levels: list[float | None], n: int = 12):
    y_true = [0] * n
    prob_rows = [[0.7, 0.2, 0.1]] * n
    rows_used = [{"vix_level": v} for v in vix_levels]
    return y_true, prob_rows, rows_used


def test_regime_bucket_metrics_missing_vix_separate_from_mid():
    y, probs, rows = _rows_and_probs(
        vix_levels=[None] * 6 + [18.0] * 6,
        n=12,
    )
    out = regime_bucket_metrics(y, probs, rows, min_support=3)
    assert out["missing"]["n"] == 6
    assert out["mid"]["n"] == 6
    assert out["low"]["n"] == 0
    assert out["high"]["n"] == 0


def test_regime_slice_accuracy_differs_from_balanced_accuracy_on_skew():
    """slice_accuracy is plain hit rate; balanced_accuracy is sklearn macro-recall."""
    n = 10
    y_true = [2] * 8 + [0] * 2
    prob_rows = [[0.05, 0.05, 0.9]] * n
    rows_used = [{"vix_level": 18.0}] * n
    out = regime_bucket_metrics(y_true, prob_rows, rows_used, min_support=5)
    mid = out["mid"]
    ps = [2] * n
    assert mid["slice_accuracy"] == pytest.approx(0.8)
    assert mid["balanced_accuracy"] == pytest.approx(float(balanced_accuracy_score(y_true, ps)))
    assert mid["balanced_accuracy"] < mid["slice_accuracy"]


def test_mce_none_when_no_bin_qualifies():
    y = list(range(10))
    confs = [0.4 + i * 0.06 for i in range(10)]
    probs = [[c, (1.0 - c) / 2.0, (1.0 - c) / 2.0] for c in confs]
    assert max_calibration_error_bins(y, probs, n_bins=10) is None


def test_confidence_reliability_proxy_none_when_insufficient_samples():
    y = [0, 1, 2, 0, 1]
    probs = [[0.7, 0.2, 0.1]] * 5
    out = confidence_reliability_proxy(probs, y)
    assert out["confidence_hit_correlation"] is None
    assert "mean_confidence" in out


def test_confidence_reliability_proxy_none_when_confidence_constant():
    y = [0] * 12
    probs = [[0.5, 0.25, 0.25]] * 12
    out = confidence_reliability_proxy(probs, y)
    assert out["confidence_hit_correlation"] is None


def test_promotion_blocks_when_confidence_correlation_withheld():
    from arch_competition.promotion_engine import decide_promotion
    from tests.test_arch_competition_eval_promotion import _promotable_manifest

    m = _promotable_manifest()
    for arch in ("parallel", "cascade"):
        m["confidence_reliability_summary"]["by_architecture"][arch]["confidence_hit_correlation"] = None
    rec = decide_promotion(m)
    assert rec["would_promote_challenger"] is False
    codes = [x["code"] for x in rec["blocked_promotion_flags"]]
    assert "MISSING_CONFIDENCE_RELIABILITY_METRIC" in codes
