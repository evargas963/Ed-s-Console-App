"""arch_competition.metrics fail-closed regime and confidence primitives (II, JJ)."""

from __future__ import annotations




def _rows_and_probs(*, vix_levels: list[float | None], n: int = 12):
    y_true = [0] * n
    prob_rows = [[0.7, 0.2, 0.1]] * n
    rows_used = [{"vix_level": v} for v in vix_levels]
    return y_true, prob_rows, rows_used


















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
                         encoding="utf-8", errors="replace", timeout=300)
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
