"""arch_competition.metrics fail-closed regime and confidence primitives (II, JJ)."""

from __future__ import annotations

import pytest
from sklearn.metrics import balanced_accuracy_score

from arch_competition.metrics import (
    VIX_EVAL_REGIME_LOW_MAX,
    VIX_EVAL_REGIME_MID_MAX,
    confidence_reliability_proxy,
    max_calibration_error_bins,
    regime_bucket_metrics,
    regime_conditional_calibration,
    vix_eval_regime_token,
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


def test_vix_eval_regime_cuts_are_16_and_24():
    """Eval-domain authority constants — distinct from runtime vix_tier_token (15/20/30)."""
    assert VIX_EVAL_REGIME_LOW_MAX == 16.0
    assert VIX_EVAL_REGIME_MID_MAX == 24.0


@pytest.mark.parametrize(
    "vix,expected",
    [
        (None, "missing"),
        (float("nan"), "missing"),
        ("not-a-number", "missing"),
        (5.0, "low"),
        (15.99, "low"),
        (16.0, "mid"),
        (23.99, "mid"),
        (24.0, "high"),
        (50.0, "high"),
    ],
)
def test_vix_eval_regime_token_canonical_cuts(vix, expected):
    assert vix_eval_regime_token(vix) == expected


def test_regime_bucket_and_conditional_share_same_cuts():
    """Both VIX-bucketing functions must agree on the boundary at 16 and 24."""
    y = [0] * 12
    probs = [[0.7, 0.2, 0.1]] * 12
    # 4 rows at exactly the low/mid boundary, 4 at mid/high boundary, 4 'high'
    rows = (
        [{"vix_level": 15.99}] * 4
        + [{"vix_level": 16.0}] * 4
        + [{"vix_level": 24.0}] * 4
    )
    rb = regime_bucket_metrics(y, probs, rows, min_support=3)
    rc = regime_conditional_calibration(y, probs, rows, min_support=3)
    assert rb["low"]["n"] == 4
    assert rb["mid"]["n"] == 4
    assert rb["high"]["n"] == 4
    assert rc["low"]["n"] == 4
    assert rc["mid"]["n"] == 4
    assert rc["high"]["n"] == 4


def test_single_authority_no_duplicate_thresholds_in_metrics():
    """Lock the refactor: both bucket functions must reference vix_eval_regime_token, not inline 16/24."""
    import inspect

    from arch_competition.metrics import regime_bucket_metrics as rb_fn
    from arch_competition.metrics import regime_conditional_calibration as rc_fn

    for fn in (rb_fn, rc_fn):
        src = inspect.getsource(fn)
        assert "vix_eval_regime_token" in src, f"{fn.__name__} must delegate to authority"
        # No re-inlined literal cuts
        assert "vf < 16" not in src
        assert "vf < 24" not in src
        assert "< 16" not in src
        assert "< 24" not in src


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


def test_rc247_importing_metrics_does_not_drag_sklearn_in():
    """RC-247: a trading console must not load an ML EVALUATION library to serve a quote.

    arch_competition/__init__ re-exports eval_runner -> metrics, and the live console reaches
    that package for calibration helpers — so a module-level `from sklearn.metrics import ...`
    cost every boot 8.66s of sklearn plus 1.65s of scipy (MEASURED in fresh processes; server
    boot 17.89s -> 6.61s once made lazy). This asserts the import boundary, in a SUBPROCESS so
    the ambient test session's own imports cannot mask the regression.
    """
    import subprocess
    import sys
    from pathlib import Path

    repo = str(Path(__file__).resolve().parent.parent)
    code = (
        "import sys; sys.path.insert(0, r'%s');"
        "import arch_competition.metrics as m;"
        "print('sklearn' in sys.modules, 'scipy' in sys.modules)" % repo
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         timeout=300)
    assert out.returncode == 0, out.stderr[-400:]
    assert out.stdout.strip() == "False False", (
        f"importing arch_competition.metrics pulled sklearn/scipy: {out.stdout.strip()!r} — "
        f"the boot tax is back (RC-247)"
    )


def test_rc247_the_scoring_functions_still_work_through_the_lazy_accessor():
    """Laziness must not mean absence: the three scoring paths still compute."""
    from arch_competition.metrics import half_split_log_loss_std

    y = [0, 1, 2] * 10
    probs = [[0.5, 0.3, 0.2] if v == 0 else [0.2, 0.5, 0.3] if v == 1 else [0.3, 0.2, 0.5]
             for v in y]
    out = half_split_log_loss_std(y, probs)
    assert out is not None and out >= 0.0, "the lazy sklearn accessor did not deliver log_loss"
