"""Extended metrics for architecture comparison (calibration, stability, regime slices).

VIX evaluation regime cuts (low/mid/high) are an evaluation-domain authority calibrated against
PromotionPolicy.max_regime_balanced_accuracy_regression on the mid-VIX bucket. They are
deliberately distinct from the production runtime VIX tier authority in math_volatility
(vix_tier_token: 15/20/30 with four tiers low/normal/elevated/high) — different domain,
different bucket count, different consumer. Locked here as named constants so both functions
that bucket by VIX (regime_bucket_metrics, regime_conditional_calibration) share one source.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
from sklearn.metrics import balanced_accuracy_score, log_loss

# Eval-domain VIX regime cuts (NOT the runtime vix_tier_token 15/20/30 authority).
# Promotion policy mid-VIX balanced_accuracy regression gate is calibrated against these.
VIX_EVAL_REGIME_LOW_MAX: float = 16.0
VIX_EVAL_REGIME_MID_MAX: float = 24.0


def vix_eval_regime_token(vix: Any) -> str:
    """Single authority for eval-domain VIX bucketing: 'low' | 'mid' | 'high' | 'missing'.

    Returns 'missing' on None / non-numeric / NaN — consumers that need a numeric guard
    should branch on the token before computing slice metrics.
    """
    if vix is None:
        return "missing"
    try:
        v = float(vix)
    except (TypeError, ValueError):
        return "missing"
    if v != v:  # NaN
        return "missing"
    if v < VIX_EVAL_REGIME_LOW_MAX:
        return "low"
    if v < VIX_EVAL_REGIME_MID_MAX:
        return "mid"
    return "high"


def multiclass_brier_score(y_true: list[int], prob_rows: list[list[float]]) -> Optional[float]:
    if not y_true or not prob_rows or len(y_true) != len(prob_rows):
        return None
    Y = np.zeros((len(y_true), 3), dtype=np.float64)
    for i, y in enumerate(y_true):
        if 0 <= y < 3:
            Y[i, y] = 1.0
    P = np.asarray(prob_rows, dtype=np.float64)
    return float(np.mean(np.sum((P - Y) ** 2, axis=1)))


def half_split_log_loss_std(y_true: list[int], prob_rows: list[list[float]]) -> Optional[float]:
    """Std of log-loss on first vs second half (time-ordered rows) — stability proxy."""
    n = len(y_true)
    if n < 20 or len(prob_rows) != n:
        return None
    mid = n // 2
    y1, y2 = y_true[:mid], y_true[mid:]
    p1 = np.asarray(prob_rows[:mid], dtype=np.float64)
    p2 = np.asarray(prob_rows[mid:], dtype=np.float64)
    ll1 = float(log_loss(y1, p1, labels=[0, 1, 2]))
    ll2 = float(log_loss(y2, p2, labels=[0, 1, 2]))
    return float(np.std([ll1, ll2], ddof=0))


def regime_bucket_metrics(
    y_true: list[int],
    prob_rows: list[list[float]],
    rows_used: list[dict],
    *,
    min_support: int = 5,
) -> dict[str, Any]:
    """
    Per VIX bucket slice metrics from row ``vix_level``.

    - ``slice_accuracy``: plain argmax hit rate (majority-class dominated when skewed).
    - ``balanced_accuracy``: sklearn macro-recall (promotion_engine REGIME_MID_BUCKET_REGRESSION).
    """
    buckets: dict[str, list[tuple[int, int]]] = {"low": [], "mid": [], "high": [], "missing": []}
    for yt, pr, row in zip(y_true, prob_rows, rows_used):
        key = vix_eval_regime_token(row.get("vix_level"))
        pred = int(np.argmax(pr))
        buckets[key].append((yt, pred))

    out: dict[str, Any] = {}
    for name, pairs in buckets.items():
        if len(pairs) < min_support:
            out[name] = {
                "n": len(pairs),
                "slice_accuracy": None,
                "balanced_accuracy": None,
                "skipped_low_support": True,
            }
            continue
        ys = [a for a, _ in pairs]
        ps = [b for _, b in pairs]
        correct = sum(1 for a, b in zip(ys, ps) if a == b)
        out[name] = {
            "n": len(pairs),
            "slice_accuracy": float(correct / len(pairs)),
            "balanced_accuracy": float(balanced_accuracy_score(ys, ps)),
            "skipped_low_support": False,
        }
    return out


def confidence_reliability_proxy(prob_rows: list[list[float]], y_true: list[int]) -> dict[str, Any]:
    """Map max-prob 'confidence' bins to empirical hit rate (multiclass)."""
    if not prob_rows or len(prob_rows) != len(y_true):
        return {}
    edges = []
    hits = []
    for pr, yt in zip(prob_rows, y_true):
        p = np.asarray(pr, dtype=np.float64)
        pred = int(np.argmax(p))
        conf = float(np.max(p))
        edges.append(conf)
        hits.append(1.0 if pred == yt else 0.0)
    if len(edges) < 10:
        return {"confidence_hit_correlation": None, "mean_confidence": float(np.mean(edges))}
    c = float(np.corrcoef(edges, hits)[0, 1]) if np.std(edges) > 1e-9 else None
    return {
        "confidence_hit_correlation": c,
        "mean_confidence": float(np.mean(edges)),
    }


def expected_calibration_error_multiclass(
    y_true: list[int],
    prob_rows: list[list[float]],
    *,
    n_bins: int = 10,
) -> Optional[float]:
    """
    Top-predicted-class calibration: bin by max predicted probability, compare to empirical accuracy in bin.
    ECE = sum_b (n_b/n) * |acc_b - conf_b|.
    """
    if not y_true or len(y_true) != len(prob_rows) or len(y_true) < 10:
        return None
    confs: list[float] = []
    correct: list[float] = []
    for pr, yt in zip(prob_rows, y_true):
        p = np.asarray(pr, dtype=np.float64)
        pred = int(np.argmax(p))
        confs.append(float(np.max(p)))
        correct.append(1.0 if pred == yt else 0.0)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    n = len(y_true)
    for b in range(n_bins):
        lo, hi = edges[b], edges[b + 1]
        mask = [i for i, c in enumerate(confs) if (c >= lo if b == 0 else c > lo) and c <= hi]
        if not mask:
            continue
        nb = len(mask)
        acc_b = float(np.mean([correct[i] for i in mask]))
        conf_b = float(np.mean([confs[i] for i in mask]))
        ece += (nb / n) * abs(acc_b - conf_b)
    return float(ece)


def max_calibration_error_bins(
    y_true: list[int],
    prob_rows: list[list[float]],
    *,
    n_bins: int = 10,
) -> Optional[float]:
    """Max over bins of |accuracy - mean_confidence| (multiclass top-label calibration)."""
    if not y_true or len(y_true) != len(prob_rows) or len(y_true) < 10:
        return None
    confs = []
    correct = []
    for pr, yt in zip(prob_rows, y_true):
        p = np.asarray(pr, dtype=np.float64)
        pred = int(np.argmax(p))
        confs.append(float(np.max(p)))
        correct.append(1.0 if pred == yt else 0.0)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    mce: Optional[float] = None
    for b in range(n_bins):
        lo, hi = edges[b], edges[b + 1]
        mask = [i for i, c in enumerate(confs) if (c >= lo if b == 0 else c > lo) and c <= hi]
        if len(mask) < 3:
            continue
        acc_b = float(np.mean([correct[i] for i in mask]))
        conf_b = float(np.mean([confs[i] for i in mask]))
        gap = abs(acc_b - conf_b)
        mce = gap if mce is None else max(mce, gap)
    return mce


def reliability_bins_table(
    y_true: list[int],
    prob_rows: list[list[float]],
    *,
    n_bins: int = 10,
    min_bin_n: int = 3,
) -> list[dict[str, Any]]:
    """Calibration reliability table: bin by max probability."""
    out: list[dict[str, Any]] = []
    if not y_true or len(y_true) != len(prob_rows):
        return out
    confs: list[float] = []
    correct: list[float] = []
    for pr, yt in zip(prob_rows, y_true):
        p = np.asarray(pr, dtype=np.float64)
        pred = int(np.argmax(p))
        confs.append(float(np.max(p)))
        correct.append(1.0 if pred == yt else 0.0)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    for b in range(n_bins):
        lo, hi = edges[b], edges[b + 1]
        mask = [i for i, c in enumerate(confs) if (c >= lo if b == 0 else c > lo) and c <= hi]
        if len(mask) < min_bin_n:
            out.append(
                {
                    "bin_index": b,
                    "bin_lo": float(lo),
                    "bin_hi": float(hi),
                    "n": len(mask),
                    "mean_confidence": None,
                    "empirical_accuracy": None,
                    "calibration_gap": None,
                    "skipped_low_support": True,
                }
            )
            continue
        acc_b = float(np.mean([correct[i] for i in mask]))
        conf_b = float(np.mean([confs[i] for i in mask]))
        out.append(
            {
                "bin_index": b,
                "bin_lo": float(lo),
                "bin_hi": float(hi),
                "n": len(mask),
                "mean_confidence": conf_b,
                "empirical_accuracy": acc_b,
                "calibration_gap": float(acc_b - conf_b),
                "skipped_low_support": False,
            }
        )
    return out


def brier_decomposition_multiclass(
    y_true: list[int],
    prob_rows: list[list[float]],
) -> dict[str, Any]:
    """
    Multiclass Brier vs climatology (marginal class frequencies): skill summarizes calibration+resolution vs baseline.
    """
    if not y_true or len(y_true) != len(prob_rows):
        return {"brier_score": None, "reference_brier_climatology": None, "brier_skill_vs_climatology": None}
    n = len(y_true)
    Y = np.zeros((n, 3), dtype=np.float64)
    for i, y in enumerate(y_true):
        if 0 <= y < 3:
            Y[i, y] = 1.0
    P = np.asarray(prob_rows, dtype=np.float64)
    brier = float(np.mean(np.sum((P - Y) ** 2, axis=1)))
    p_bar = np.mean(Y, axis=0)
    ref_brier = float(np.sum(p_bar * (1.0 - p_bar)))
    skill = float(1.0 - brier / ref_brier) if ref_brier > 1e-12 else None
    return {
        "brier_score": brier,
        "reference_brier_climatology": ref_brier,
        "brier_skill_vs_climatology": skill,
    }


def overconfidence_diagnostics(y_true: list[int], prob_rows: list[list[float]]) -> dict[str, Any]:
    """Gap between mean max-probability and accuracy of argmax predictions."""
    if not y_true or len(y_true) != len(prob_rows):
        return {}
    confs = []
    hits = []
    for pr, yt in zip(prob_rows, y_true):
        p = np.asarray(pr, dtype=np.float64)
        pred = int(np.argmax(p))
        confs.append(float(np.max(p)))
        hits.append(1.0 if pred == yt else 0.0)
    mean_conf = float(np.mean(confs))
    mean_acc = float(np.mean(hits))
    return {
        "mean_max_probability": mean_conf,
        "argmax_accuracy": mean_acc,
        "overconfidence_index": float(mean_conf - mean_acc),
    }


def confidence_bucket_summaries(
    y_true: list[int],
    prob_rows: list[list[float]],
    *,
    n_buckets: int = 5,
) -> list[dict[str, Any]]:
    """Quantile buckets of confidence with empirical hit rate."""
    out: list[dict[str, Any]] = []
    if not y_true or len(y_true) != len(prob_rows) or len(y_true) < n_buckets * 3:
        return out
    rows = []
    for pr, yt in zip(prob_rows, y_true):
        p = np.asarray(pr, dtype=np.float64)
        pred = int(np.argmax(p))
        conf = float(np.max(p))
        rows.append((conf, 1.0 if pred == yt else 0.0))
    rows.sort(key=lambda x: x[0])
    n = len(rows)
    step = max(1, n // n_buckets)
    for b in range(n_buckets):
        lo = b * step
        hi = n if b == n_buckets - 1 else min(n, (b + 1) * step)
        chunk = rows[lo:hi]
        if not chunk:
            continue
        confs = [c for c, _ in chunk]
        hits = [h for _, h in chunk]
        out.append(
            {
                "bucket_index": b,
                "n": len(chunk),
                "mean_confidence": float(np.mean(confs)),
                "empirical_hit_rate": float(np.mean(hits)),
            }
        )
    return out


def _window_slices(n: int, n_windows: int) -> list[tuple[int, int]]:
    if n_windows < 2 or n < n_windows * 10:
        return []
    chunk = n // n_windows
    slices = []
    for w in range(n_windows):
        lo = w * chunk
        hi = n if w == n_windows - 1 else (w + 1) * chunk
        slices.append((lo, hi))
    return slices


def rolling_calibration_and_loss_stability(
    y_true: list[int],
    prob_rows: list[list[float]],
    *,
    n_windows: int = 3,
) -> dict[str, Any]:
    """
    Time-ordered rows: per-window ECE, log_loss, std across windows; degradation if last ECE >> first.
    """
    n = len(y_true)
    if n < 30 or len(prob_rows) != n:
        return {
            "n_windows": n_windows,
            "ece_by_window": [],
            "log_loss_by_window": [],
            "ece_cross_window_std": None,
            "calibration_degradation_flag": False,
            "insufficient_rows": True,
        }
    slices = _window_slices(n, n_windows)
    if not slices:
        return {
            "n_windows": n_windows,
            "ece_by_window": [],
            "log_loss_by_window": [],
            "ece_cross_window_std": None,
            "calibration_degradation_flag": False,
            "insufficient_rows": True,
        }
    eces = []
    lls = []
    for lo, hi in slices:
        yt_w = y_true[lo:hi]
        pr_w = prob_rows[lo:hi]
        ece = expected_calibration_error_multiclass(yt_w, pr_w, n_bins=8)
        if ece is None:
            continue
        ll = float(log_loss(yt_w, np.asarray(pr_w, dtype=np.float64), labels=[0, 1, 2]))
        eces.append({"lo": lo, "hi": hi, "ece": ece})
        lls.append({"lo": lo, "hi": hi, "log_loss": ll})
    std_ece = float(np.std([x["ece"] for x in eces], ddof=0)) if len(eces) >= 2 else None
    deg = False
    if len(eces) >= 2:
        first_e = eces[0]["ece"]
        last_e = eces[-1]["ece"]
        if first_e > 1e-9 and last_e > first_e * 1.35:
            deg = True
    return {
        "n_windows": n_windows,
        "ece_by_window": eces,
        "log_loss_by_window": lls,
        "ece_cross_window_std": std_ece,
        "calibration_degradation_flag": deg,
        "insufficient_rows": False,
    }


def regime_conditional_calibration(
    y_true: list[int],
    prob_rows: list[list[float]],
    rows_used: list[dict],
    *,
    min_support: int = 20,
) -> dict[str, Any]:
    """VIX-bucket conditional ECE (same buckets as regime_bucket_metrics)."""
    buckets: dict[str, tuple[list[int], list[list[float]]]] = {
        "low": ([], []),
        "mid": ([], []),
        "high": ([], []),
        "missing": ([], []),
    }
    for yt, pr, row in zip(y_true, prob_rows, rows_used):
        key = vix_eval_regime_token(row.get("vix_level"))
        yt_l, pr_l = buckets[key]
        yt_l.append(yt)
        pr_l.append(pr)

    out: dict[str, Any] = {}
    for name, (yt_l, pr_l) in buckets.items():
        if len(yt_l) < min_support:
            out[name] = {"n": len(yt_l), "ece": None, "skipped_low_support": True}
            continue
        ece = expected_calibration_error_multiclass(yt_l, pr_l, n_bins=8)
        out[name] = {
            "n": len(yt_l),
            "ece": ece,
            "skipped_low_support": False,
        }
    return out


def architecture_win_consistency_by_window(
    y_true: list[int],
    prob_parallel: list[list[float]],
    prob_cascade: list[list[float]],
    *,
    n_windows: int = 3,
) -> dict[str, Any]:
    """Per-window log_loss comparison (lower better); cascade win rate."""
    n = len(y_true)
    if (
        n < 30
        or len(prob_parallel) != n
        or len(prob_cascade) != n
    ):
        return {
            "cascade_log_loss_wins": 0,
            "windows_compared": 0,
            "cascade_win_rate_by_log_loss": None,
            "insufficient_rows": True,
        }
    slices = _window_slices(n, n_windows)
    if not slices:
        return {
            "cascade_log_loss_wins": 0,
            "windows_compared": 0,
            "cascade_win_rate_by_log_loss": None,
            "insufficient_rows": True,
        }
    wins = 0
    details = []
    for lo, hi in slices:
        yt = y_true[lo:hi]
        pp = np.asarray(prob_parallel[lo:hi], dtype=np.float64)
        cp = np.asarray(prob_cascade[lo:hi], dtype=np.float64)
        ll_p = float(log_loss(yt, pp, labels=[0, 1, 2]))
        ll_c = float(log_loss(yt, cp, labels=[0, 1, 2]))
        w = ll_c < ll_p
        if w:
            wins += 1
        details.append(
            {
                "lo": lo,
                "hi": hi,
                "parallel_log_loss": ll_p,
                "cascade_log_loss": ll_c,
                "cascade_wins_window": bool(w),
            }
        )
    nw = len(details)
    return {
        "cascade_log_loss_wins": wins,
        "windows_compared": nw,
        "cascade_win_rate_by_log_loss": float(wins / nw) if nw else None,
        "window_details": details,
        "insufficient_rows": False,
    }
