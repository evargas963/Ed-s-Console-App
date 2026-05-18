"""
Shared helpers for movement-target Phase 5 / 6 / 6.5 evaluation (binary heads).

Inference contract (documented): Option 1 — when XGB movement heads are loaded, direction
probabilities are emitted for all scored rows (same feature row as training). Evaluation of
outcome_dir_{H} uses only rows with valid_dir_{H}=1; move head uses all rows with move labels.
"""
from __future__ import annotations

import math
import random
import statistics
from collections import Counter
from typing import Any

HORIZONS_MV = ("1c", "5c", "15c", "60c")


def col_move(hz: str) -> str:
    return f"outcome_move_{hz}"


def col_dir(hz: str) -> str:
    return f"outcome_dir_{hz}"


def col_valid_dir(hz: str) -> str:
    return f"valid_dir_{hz}"


def pred_move_keys(hz: str) -> tuple[str, str, str, str]:
    """Canonical, legacy move prob column names."""
    return (
        f"pred_move_prob_{hz}",
        f"pred_no_move_prob_{hz}",
        f"pred_{hz}_move_prob",
        f"pred_{hz}_no_move_prob",
    )


def pred_dir_keys(hz: str) -> tuple[str, str, str, str]:
    """Canonical, legacy dir prob column names."""
    return (
        f"pred_dir_up_prob_{hz}",
        f"pred_dir_down_prob_{hz}",
        f"pred_{hz}_dir_up_prob",
        f"pred_{hz}_dir_down_prob",
    )


def rget_float(row: Any, *names: str) -> float | None:
    for k in names:
        try:
            v = row[k]
        except (KeyError, IndexError, TypeError):
            continue
        if v is None:
            continue
        try:
            x = float(v)
            if math.isnan(x) or math.isinf(x):
                return None
            return x
        except (TypeError, ValueError):
            continue
    return None


def binary_baselines_move(ys: list[int]) -> dict[str, Any]:
    """ys: 1=move, 0=no_move."""
    n = len(ys)
    if n == 0:
        return {"n": 0}
    ctr = Counter(ys)
    maj = ctr.most_common(1)[0][0]
    acc_maj = sum(1 for y in ys if y == maj) / n
    acc_always_move = sum(1 for y in ys if y == 1) / n
    acc_always_nomove = sum(1 for y in ys if y == 0) / n
    rnd_accs: list[float] = []
    for t in range(20):
        rng = random.Random(42 + t * 9973)
        rnd_accs.append(sum(1 for y in ys if rng.randint(0, 1) == y) / n)
    return {
        "prior_majority_class": "move" if maj == 1 else "no_move",
        "prior_majority_accuracy": round(acc_maj, 6),
        "always_move_accuracy": round(acc_always_move, 6),
        "always_no_move_accuracy": round(acc_always_nomove, 6),
        "random_accuracy_mean": round(sum(rnd_accs) / len(rnd_accs), 6),
    }


def binary_baselines_dir(y_up: list[int]) -> dict[str, Any]:
    """y_up: 1=up, 0=down on conditional sample."""
    n = len(y_up)
    if n == 0:
        return {"n": 0}
    p_up = sum(y_up) / n
    ctr = Counter(y_up)
    maj = ctr.most_common(1)[0][0]
    acc_maj = sum(1 for y in y_up if y == maj) / n
    rnd_accs: list[float] = []
    for t in range(20):
        rng = random.Random(42 + t * 9973)
        rnd_accs.append(sum(1 for y in y_up if int(rng.random() < 0.5) == y) / n)
    return {
        "conditional_majority_accuracy": round(acc_maj, 6),
        "majority_class_up": maj == 1,
        "always_up_accuracy": round(p_up, 6),
        "always_down_accuracy": round(1.0 - p_up, 6),
        "random_accuracy_mean": round(sum(rnd_accs) / len(rnd_accs), 6),
    }


def binary_classification_report(y_true: list[int], y_pred: list[int]) -> dict[str, Any]:
    """y_true / y_pred in {0,1}; positive class = 1."""
    assert len(y_true) == len(y_pred)
    tp = sum(1 for a, b in zip(y_true, y_pred) if a == 1 and b == 1)
    tn = sum(1 for a, b in zip(y_true, y_pred) if a == 0 and b == 0)
    fp = sum(1 for a, b in zip(y_true, y_pred) if a == 0 and b == 1)
    fn = sum(1 for a, b in zip(y_true, y_pred) if a == 1 and b == 0)
    n = tp + tn + fp + fn
    acc = (tp + tn) / n if n else float("nan")
    rec_pos = tp / (tp + fn) if (tp + fn) else float("nan")
    rec_neg = tn / (tn + fp) if (tn + fp) else float("nan")
    return {
        "n": n,
        "accuracy": round(acc, 6),
        "recall_positive": round(rec_pos, 6),
        "recall_negative": round(rec_neg, 6),
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
    }


def decile_accuracy_monotonicity(scores: list[float], correct: list[int]) -> dict[str, Any]:
    """Higher score = more confident. Spearman-like proxy on decile accuracies."""
    if len(scores) != len(correct) or len(scores) < 30:
        return {"note": "insufficient_for_deciles", "spearman_proxy": None}
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    n = len(scores)
    decile_stats: list[dict[str, Any]] = []
    for d in range(10):
        a = (d * n) // 10
        b = ((d + 1) * n) // 10 if d < 9 else n
        idxs = order[a:b]
        if not idxs:
            continue
        cor = sum(correct[i] for i in idxs) / len(idxs)
        decile_stats.append(
            {
                "decile": d + 1,
                "n": len(idxs),
                "score_min": round(min(scores[i] for i in idxs), 6),
                "score_max": round(max(scores[i] for i in idxs), 6),
                "accuracy": round(cor, 6),
            }
        )
    if len(decile_stats) < 3:
        return {"deciles": decile_stats, "spearman_proxy": None}
    accs = [ds["accuracy"] for ds in decile_stats]
    x = list(range(len(accs)))
    mx, my = statistics.fmean(x), statistics.fmean(accs)
    num = sum((x[i] - mx) * (accs[i] - my) for i in range(len(x)))
    denx = sum((x[i] - mx) ** 2 for i in range(len(x)))
    deny = sum((accs[i] - my) ** 2 for i in range(len(x)))
    sp = num / math.sqrt(denx * deny) if denx > 0 and deny > 0 else float("nan")
    return {"deciles": decile_stats, "spearman_proxy": round(sp, 6) if sp == sp else None}


def logloss_bin(y: int, p: float) -> float:
    p = min(1.0 - 1e-9, max(1e-9, float(p)))
    if y == 1:
        return -math.log(p)
    return -math.log(1.0 - p)
