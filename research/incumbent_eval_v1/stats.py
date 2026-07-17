"""Pure statistics for incumbent_eval_v1 (no DB, no I/O — fully unit-testable).

Implements exactly the metrics frozen in prereg_v1.json:
multiclass MCC (Gorodkin), balanced accuracy, accuracy, multiclass log loss,
trivial baselines (always_flat / majority / persistence), day-block bootstrap
CI + p-value for MCC, within-cell shuffle control, and Holm-Bonferroni.
"""

from __future__ import annotations

import math
import random
from typing import Any, Optional, Sequence

CLASSES = ("up", "down", "flat")
_PROB_CLIP_MIN = 1e-6


def confusion_matrix(preds: Sequence[str], truths: Sequence[str]) -> dict[str, dict[str, int]]:
    cm = {p: {t: 0 for t in CLASSES} for p in CLASSES}
    for p, t in zip(preds, truths):
        cm[p][t] += 1
    return cm


def mcc_multiclass(cm: dict[str, dict[str, int]]) -> Optional[float]:
    """Gorodkin multiclass Matthews correlation; None when degenerate
    (all predictions one class or all truths one class)."""
    n = sum(cm[p][t] for p in CLASSES for t in CLASSES)
    if n == 0:
        return None
    pred_dist = {p: sum(cm[p][t] for t in CLASSES) for p in CLASSES}
    truth_dist = {t: sum(cm[p][t] for p in CLASSES) for t in CLASSES}
    hits = sum(cm[c][c] for c in CLASSES)
    corr = hits * n - sum(pred_dist[c] * truth_dist[c] for c in CLASSES)
    den_p = n * n - sum(pred_dist[c] ** 2 for c in CLASSES)
    den_t = n * n - sum(truth_dist[c] ** 2 for c in CLASSES)
    if den_p <= 0 or den_t <= 0:
        return None
    return corr / math.sqrt(den_p * den_t)


def balanced_accuracy(cm: dict[str, dict[str, int]]) -> Optional[float]:
    """Mean per-class recall over classes present in truth."""
    recalls = []
    for c in CLASSES:
        support = sum(cm[p][c] for p in CLASSES)
        if support:
            recalls.append(cm[c][c] / support)
    return (sum(recalls) / len(recalls)) if recalls else None


def accuracy(cm: dict[str, dict[str, int]]) -> Optional[float]:
    n = sum(cm[p][t] for p in CLASSES for t in CLASSES)
    return (sum(cm[c][c] for c in CLASSES) / n) if n else None


def multiclass_log_loss(prob_rows: Sequence[dict[str, float]], truths: Sequence[str]) -> Optional[float]:
    """Mean NLL of the probability assigned to the realized class."""
    total = 0.0
    n = 0
    for probs, truth in zip(prob_rows, truths):
        p = probs.get(f"prob_{truth}")
        if p is None or not math.isfinite(float(p)):
            continue
        total += -math.log(max(min(float(p), 1.0), _PROB_CLIP_MIN))
        n += 1
    return (total / n) if n else None


def baseline_accuracies(preds_ignored: Sequence[str], truths: Sequence[str]) -> dict[str, Optional[float]]:
    """Trivial baselines scored on the same truth sequence (time-ordered).

    persistence predicts row i's truth as row i-1's truth (first row unscored).
    Honesty note: with ~1-minute decision cadence and (N+1)-minute label spans,
    row i-1's label is NOT fully resolved at row i's decision time, so this is
    a look-ahead-ADVANTAGED baseline — a deliberately hard bar. always_flat and
    majority_class are likewise in-sample rates, not causal strategies. Losing
    to them is disqualifying; beating them is necessary, not sufficient.
    """
    n = len(truths)
    if n == 0:
        return {"always_flat": None, "majority_class": None, "persistence": None}
    counts = {c: truths.count(c) for c in CLASSES}
    always_flat = counts["flat"] / n
    majority = max(counts.values()) / n
    if n > 1:
        hits = sum(1 for i in range(1, n) if truths[i] == truths[i - 1])
        persistence: Optional[float] = hits / (n - 1)
    else:
        persistence = None
    return {"always_flat": always_flat, "majority_class": majority, "persistence": persistence}


def day_block_bootstrap_mcc(
    preds: Sequence[str],
    truths: Sequence[str],
    et_dates: Sequence[str],
    *,
    n_boot: int,
    seed: int,
) -> dict[str, Any]:
    """Bootstrap over whole ET dates (preserving intra-day serial dependence).

    Returns the 95% percentile CI of MCC and a two-sided bootstrap p-value for
    MCC != 0 (2 * min(P(boot<=0), P(boot>=0)), floored at 2/n_boot).
    """
    by_day: dict[str, list[int]] = {}
    for i, d in enumerate(et_dates):
        by_day.setdefault(d, []).append(i)
    days = sorted(by_day)
    if len(days) < 2:
        return {"ci95": None, "p_value": None, "n_days": len(days), "n_boot": 0}
    rng = random.Random(seed)
    stats: list[float] = []
    for _ in range(n_boot):
        sample_days = [days[rng.randrange(len(days))] for _ in range(len(days))]
        idx = [i for d in sample_days for i in by_day[d]]
        m = mcc_multiclass(confusion_matrix([preds[i] for i in idx], [truths[i] for i in idx]))
        if m is not None:
            stats.append(m)
    if len(stats) < max(50, n_boot // 2):
        # Degenerate resamples dominate — CI would be fabricated.
        return {"ci95": None, "p_value": None, "n_days": len(days), "n_boot": len(stats)}
    stats.sort()

    def _pct(q: float) -> float:
        return stats[min(len(stats) - 1, max(0, int(q * (len(stats) - 1))))]

    n_le = sum(1 for s in stats if s <= 0.0)
    n_ge = sum(1 for s in stats if s >= 0.0)
    p = 2.0 * min(n_le, n_ge) / len(stats)
    return {
        "ci95": [_pct(0.025), _pct(0.975)],
        "p_value": max(p, 2.0 / len(stats)),
        "n_days": len(days),
        "n_boot": len(stats),
    }


def shuffle_control_mcc(
    preds: Sequence[str],
    truths: Sequence[str],
    *,
    n_shuffles: int,
    seed: int,
) -> dict[str, Any]:
    """Within-cell truth permutation null. The observed pipeline is honest when
    this null is centered at ~0; quantiles let the runner flag artifacts."""
    rng = random.Random(seed)
    truths_l = list(truths)
    nulls: list[float] = []
    for _ in range(n_shuffles):
        rng.shuffle(truths_l)
        m = mcc_multiclass(confusion_matrix(preds, truths_l))
        if m is not None:
            nulls.append(m)
    if not nulls:
        return {"null_mean": None, "null_q025": None, "null_q975": None, "n_shuffles": 0}
    nulls.sort()

    def _pct(q: float) -> float:
        return nulls[min(len(nulls) - 1, max(0, int(q * (len(nulls) - 1))))]

    return {
        "null_mean": sum(nulls) / len(nulls),
        "null_q025": _pct(0.025),
        "null_q975": _pct(0.975),
        "n_shuffles": len(nulls),
    }


def holm_bonferroni(p_values: dict[str, Optional[float]], alpha: float = 0.05) -> dict[str, dict[str, Any]]:
    """Holm step-down FWER control over the declared family.

    Cells with p None (under-sampled / degenerate) are excluded from the
    ordering but still reported with significant=None.
    """
    testable = sorted(
        ((k, v) for k, v in p_values.items() if v is not None), key=lambda kv: kv[1]
    )
    m = len(testable)
    out: dict[str, dict[str, Any]] = {
        k: {"p_raw": v, "p_adjusted": None, "significant": None} for k, v in p_values.items()
    }
    running_max = 0.0
    rejecting = True
    for rank, (k, p) in enumerate(testable):
        adj = min(1.0, (m - rank) * p)
        running_max = max(running_max, adj)
        out[k]["p_adjusted"] = running_max
        if rejecting and running_max < alpha:
            out[k]["significant"] = True
        else:
            rejecting = False
            out[k]["significant"] = False
    return out
