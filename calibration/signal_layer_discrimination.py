"""
Discrimination audit: canonical 1m signal_layer_v1 vs outcome_5c_pts and fusion spread.

Reads calibration_decision_log + price_bars_1m (BAR_ANCHOR_V1 — no future bars in features).

Usage:
  python -m calibration.signal_layer_discrimination [path/to/ed_console.db]
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from calibration.trust import TRUSTED_PREDICATE_SQL
from db import configure_sqlite_connection
from features.signal_layer_v1 import (
    compute_signal_layer_v1,
    flatten_numeric_features,
    layer_direction_policy,
    load_bars_before_decision,
)


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 10 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx < 1e-20 or vy < 1e-20:
        return None
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    return cov / math.sqrt(vx * vy)


def _rankdata(vals: list[float]) -> list[float]:
    """Average ranks for ties (0..n-1)."""
    indexed = sorted(enumerate(vals), key=lambda t: t[1])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(indexed):
        j = i
        while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        avg = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg
        i = j + 1
    return ranks


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 10:
        return None
    rx = _rankdata(xs)
    ry = _rankdata(ys)
    return _pearson(rx, ry)


def _mi_discrete(x: list[float], y: list[float], bins: int = 8) -> float | None:
    """Discrete MI (nats), x binned vs y quartiles; Laplace-smoothed joint."""
    if len(x) < 20:
        return None
    n = len(x)
    yq = sorted(y)
    q1 = yq[n // 4]
    q2 = yq[n // 2]
    q3 = yq[(3 * n) // 4]

    def ycat(v: float) -> int:
        if v <= q1:
            return 0
        if v <= q2:
            return 1
        if v <= q3:
            return 2
        return 3

    xmin, xmax = min(x), max(x)
    if abs(xmax - xmin) < 1e-18:
        return None
    width = (xmax - xmin) / float(bins) + 1e-18
    joint = [[1.0] * bins for _ in range(4)]  # Laplace +1
    py = [4.0] * 4
    px = [4.0] * bins
    for i in range(n):
        yi = ycat(y[i])
        xi = min(int((x[i] - xmin) / width), bins - 1)
        joint[yi][xi] += 1.0
        py[yi] += 1.0
        px[xi] += 1.0
    nt = n + 4 * bins
    mi = 0.0
    for yi in range(4):
        for xi in range(bins):
            pxy = joint[yi][xi] / nt
            px_ = px[xi] / nt
            py_ = py[yi] / nt
            if pxy <= 0 or px_ <= 0 or py_ <= 0:
                continue
            mi += pxy * math.log(pxy / (px_ * py_) + 1e-18)
    return mi


def run_discrimination(db_path: Path) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path))
    configure_sqlite_connection(conn)
    conn.row_factory = sqlite3.Row

    q = f"""
        SELECT id, ticker, decision_ts_utc, outcome_5c_pts, fusion_json, final_signal, raw_bundle_json
        FROM calibration_decision_log
        WHERE outcome_5c_pts IS NOT NULL AND ({TRUSTED_PREDICATE_SQL})
        ORDER BY id
    """
    rows = conn.execute(q).fetchall()
    y: list[float] = []
    layers: list[dict[str, Any]] = []
    fusion_probs: list[tuple[float, float, float]] = []
    fusion_n_present = 0
    fusion_n_missing = 0
    final_signals: list[str | None] = []
    layer_policies: list[str] = []

    for r in rows:
        pts = r["outcome_5c_pts"]
        if pts is None:
            continue
        y.append(float(pts))
        tkr = r["ticker"]
        ts = float(r["decision_ts_utc"])
        bars = load_bars_before_decision(conn, tkr, ts)
        layer = compute_signal_layer_v1(bars, decision_ts_utc=ts, inp=None)
        layers.append(layer)
        layer_policies.append(layer_direction_policy(layer))

        fj = r["fusion_json"]
        if fj:
            try:
                d = json.loads(fj)
                pu_raw = d.get("prob_up")
                pd_raw = d.get("prob_down")
                pf_raw = d.get("prob_flat")
                if pu_raw is not None and pd_raw is not None and pf_raw is not None:
                    fusion_probs.append((float(pu_raw), float(pd_raw), float(pf_raw)))
                    fusion_n_present += 1
                else:
                    fusion_n_missing += 1
            except Exception:
                fusion_n_missing += 1
        else:
            fusion_n_missing += 1

        fs = r["final_signal"]
        final_signals.append(fs if fs else None)

    conn.close()

    if not y:
        return {
            "n_rows": 0,
            "error": "no_trusted_rows_with_outcome_5c_pts",
        }

    # Univariate table
    keys: set[str] = set()
    for lay in layers:
        keys |= set(flatten_numeric_features(lay).keys())
    uni: list[dict[str, Any]] = []
    for k in sorted(keys):
        xs = []
        yy = []
        for i, lay in enumerate(layers):
            fv = flatten_numeric_features(lay)
            if k in fv:
                xs.append(fv[k])
                yy.append(y[i])
        if len(xs) < 15:
            continue
        pr = _pearson(xs, yy)
        sp = _spearman(xs, yy)
        mi = _mi_discrete(xs, yy)
        uni.append(
            {
                "feature": k,
                "n": len(xs),
                "pearson_r": pr,
                "spearman_r": sp,
                "mi_discrete": mi,
            }
        )
    uni.sort(key=lambda d: abs(d["pearson_r"] or 0.0), reverse=True)

    # Fusion spread (only rows with complete prob_up/down/flat triplets)
    if fusion_probs:
        means = [sum(t[i] for t in fusion_probs) / len(fusion_probs) for i in range(3)]
        stds = [
            math.sqrt(sum((t[i] - means[i]) ** 2 for t in fusion_probs) / max(len(fusion_probs) - 1, 1))
            for i in range(3)
        ]
        triplet_spread = float(sum(stds))
        fusion_near_flat = max(means) - min(means)
    else:
        means = [None, None, None]
        stds = [None, None, None]
        triplet_spread = None
        fusion_near_flat = None

    def _sig_dist(sigs: list[str | None]) -> dict[str, Any]:
        n = len(sigs)
        if n == 0:
            return {"long": None, "short": None, "wait": None, "missing": None}
        c = {"long": 0, "short": 0, "wait": 0, "missing": 0}
        for s in sigs:
            if s is None:
                c["missing"] += 1
                continue
            key = s.strip().lower()
            if key in c:
                c[key] += 1
            else:
                c["missing"] += 1
        return {k: round(100.0 * v / n, 2) for k, v in c.items()}

    return {
        "n_rows": len(y),
        "univariate": uni[:60],
        "top_10_pearson": uni[:10],
        "fusion_n_present_in_log": fusion_n_present,
        "fusion_n_missing_in_log": fusion_n_missing,
        "fusion_mean_p_up_down_flat": means,
        "fusion_std_p_up_down_flat": stds,
        "fusion_triplet_spread_l1": triplet_spread,
        "fusion_near_flat_max_min_gap": fusion_near_flat,
        "final_signal_pct": _sig_dist(final_signals),
        "layer_policy_pct": _sig_dist(layer_policies),
        "flags": {
            "fusion_triplet_near_collapse": (
                fusion_near_flat is not None and fusion_near_flat < 0.02
            ),
            "layer_policy_single_bucket": (
                len(set(layer_policies)) <= 1 if layer_policies else True
            ),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Signal layer discrimination audit")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="calibration.signal_layer_discrimination", write_capable=False)
    db = args.db
    if not db.is_file():
        print(json.dumps({"error": f"db not found: {db}", "binary_pass": False}, indent=2))
        return 2
    out = run_discrimination(db)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
