"""arch_competition.metrics fail-closed regime and confidence primitives (II, JJ)."""

from __future__ import annotations

from arch_competition.metrics import (
    confidence_reliability_proxy,
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
