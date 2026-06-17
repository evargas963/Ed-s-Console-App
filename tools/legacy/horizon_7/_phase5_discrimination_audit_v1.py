#!/usr/bin/env python3

# DEPRECATED — 7-horizon era (pre Phase D3 schema drop).
# Targets retired outcome_3c/8c/13c columns; do not run against post-D3 databases.
# Relocated to tools/legacy/horizon_7/ for audit history only.
"""Phase 5 — Discrimination audit (governed 1m schema v3, valid bar anchor)."""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

DEFAULT_DB = ROOT / "data" / "ed_console.db"

GOV_WHERE = """
s.timeframe = '1m'
AND s.horizon_outcome_schema_version = 3
AND EXISTS (
  SELECT 1 FROM price_bars_1m p
  WHERE p.ticker = s.ticker AND p.bar_end_ts_utc <= s.ts_utc
)
AND s.outcome_1c IS NOT NULL AND s.outcome_3c IS NOT NULL AND s.outcome_5c IS NOT NULL
AND s.outcome_8c IS NOT NULL AND s.outcome_13c IS NOT NULL AND s.outcome_15c IS NOT NULL
AND s.outcome_60c IS NOT NULL
"""

HORIZONS = ["1c", "3c", "5c", "8c", "13c", "15c", "60c"]
OUTCOME_COL = {h: f"outcome_{h}" for h in HORIZONS}
PTS_COL = {h: f"outcome_{h}_pts" for h in HORIZONS}
PRED_PREFIX = {h: f"pred_{h}" for h in HORIZONS}


def _entropy3(pu: float, pd: float, pf: float) -> float:
    s = 0.0
    for p in (pu, pd, pf):
        if p > 1e-18:
            s -= p * math.log(p + 1e-18)
    return s


def _argmax3(pu: float, pd: float, pf: float) -> str:
    m = max(pu, pd, pf)
    if pu == m:
        return "up"
    if pd == m:
        return "down"
    return "flat"


def _wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (float("nan"), float("nan"))
    p = successes / n
    denom = 1 + z**2 / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _chi2_independence(table: list[list[int]]) -> tuple[float, int]:
    """Pearson chi-square; table[r][c]. Returns (chi2, df)."""
    rows = len(table)
    cols = len(table[0]) if rows else 0
    n = sum(sum(row) for row in table)
    if n == 0:
        return (0.0, 0)
    row_s = [sum(table[r][c] for c in range(cols)) for r in range(rows)]
    col_s = [sum(table[r][c] for r in range(rows)) for c in range(cols)]
    chi2 = 0.0
    for r in range(rows):
        for c in range(cols):
            e = row_s[r] * col_s[c] / n
            if e > 0:
                o = table[r][c]
                chi2 += (o - e) ** 2 / e
    df = (rows - 1) * (cols - 1)
    return (chi2, df)


def _chi2_sf(chi2: float, df: int) -> float | None:
    """Survival function P(X > chi2) for chi-square(df); mpmath-free approximation."""
    try:
        from scipy.stats import chi2 as chi2_dist  # type: ignore

        return float(chi2_dist.sf(chi2, df))
    except Exception:
        return None


def _z_test_binomial_vs_p0(x: int, n: int, p0: float) -> tuple[float, float]:
    """One-sample z: p_hat vs fixed baseline p0; two-sided normal p-value."""
    if n <= 0 or p0 <= 0 or p0 >= 1:
        return (float("nan"), float("nan"))
    p_hat = x / n
    se = math.sqrt(p0 * (1.0 - p0) / n)
    if se < 1e-18:
        return (0.0, 1.0)
    z = (p_hat - p0) / se
    try:
        from scipy.stats import norm  # type: ignore

        pval = float(2 * (1 - norm.cdf(abs(z))))
    except Exception:
        from statistics import NormalDist

        pval = float(2 * (1 - NormalDist().cdf(abs(z))))
    return (z, pval)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args()
    db_path = args.db.resolve()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    n_gov = int(conn.execute(f"SELECT COUNT(*) AS n FROM snapshots s WHERE {GOV_WHERE}").fetchone()["n"])
    n_gov_pred1c = int(
        conn.execute(
            f"SELECT COUNT(*) AS n FROM snapshots s WHERE {GOV_WHERE} AND s.pred_1c_up_prob IS NOT NULL"
        ).fetchone()["n"]
    )

    # Step 1 — baseline on full governed set
    oc_cols = ", ".join(OUTCOME_COL[h] for h in HORIZONS)
    rows_all = conn.execute(
        f"""
        SELECT {oc_cols}
        FROM snapshots s
        WHERE {GOV_WHERE}
        """
    ).fetchall()

    def baseline_for_col(col: str) -> dict[str, Any]:
        ctr = Counter((r[col] or "NULL") for r in rows_all)
        tot = len(rows_all)
        out: dict[str, Any] = {"n": tot, "counts": dict(ctr)}
        for k in ("up", "down", "flat"):
            out[f"pct_{k}"] = round(100.0 * ctr.get(k, 0) / tot, 6) if tot else None
        return out

    baseline = {h: baseline_for_col(OUTCOME_COL[h]) for h in HORIZONS}

    # Per-horizon prediction analysis
    pred_cols = ", ".join(
        f"s.pred_{h}_up_prob, s.pred_{h}_down_prob, s.pred_{h}_flat_prob" for h in HORIZONS
    )
    extra = "s.ticker, s.market_session, s.regime_primary, s.realized_vol, " + pred_cols + ", " + oc_cols
    extra += ", " + ", ".join(PTS_COL[h] for h in HORIZONS)
    extra += ", s.pred_confidence"

    rows_p = conn.execute(
        f"""
        SELECT {extra}
        FROM snapshots s
        WHERE {GOV_WHERE}
        """
    ).fetchall()

    per_h: dict[str, Any] = {}

    for h in HORIZONS:
        pu_k, pd_k, pf_k = f"pred_{h}_up_prob", f"pred_{h}_down_prob", f"pred_{h}_flat_prob"
        ocol, pcol = OUTCOME_COL[h], PTS_COL[h]

        sub = [r for r in rows_p if r[pu_k] is not None and r[pd_k] is not None and r[pf_k] is not None]
        n_pred = len(sub)
        if n_pred == 0:
            per_h[h] = {
                "n_governed_with_predictions": 0,
                "note": "no_non_null_pred_probs_in_governed_set",
            }
            continue

        entropies = []
        max_probs = []
        pred_classes = []
        outcomes = []
        pts_list = []
        conf_labels: list[str] = []

        for r in sub:
            pu, pd, pf = float(r[pu_k]), float(r[pd_k]), float(r[pf_k])
            sm = pu + pd + pf
            if sm > 0:
                pu, pd, pf = pu / sm, pd / sm, pf / sm
            pc = _argmax3(pu, pd, pf)
            entropies.append(_entropy3(pu, pd, pf))
            max_probs.append(max(pu, pd, pf))
            pred_classes.append(pc)
            outcomes.append(str(r[ocol] or "NULL"))
            pv = r[pcol]
            pts_list.append(float(pv) if pv is not None else float("nan"))
            conf_labels.append(str(r["pred_confidence"] or "NULL"))

        ctr_p = Counter(pred_classes)
        totp = n_pred
        pred_dist = {k: {"n": ctr_p[k], "pct": round(100.0 * ctr_p[k] / totp, 6)} for k in ("up", "down", "flat")}
        conf_ctr = Counter(conf_labels)
        pred_confidence_distribution = {k: {"n": conf_ctr[k], "pct": round(100.0 * conf_ctr[k] / totp, 6)} for k in sorted(conf_ctr.keys())}

        mean_h = statistics.fmean(entropies)
        # max entropy log(3) for 3-class
        h_max = math.log(3)
        var_maxp = statistics.pvariance(max_probs) if len(max_probs) > 1 else 0.0
        near_uniform = sum(1 for m in max_probs if m < 0.34)

        # Collapse: dominant predicted class share
        top_share = ctr_p.most_common(1)[0][1] / totp if ctr_p else 0.0

        # Conditional outcome rates
        cond: dict[str, Any] = {}
        bl = baseline[h]
        for pcl in ("up", "down", "flat"):
            idxs = [i for i, p in enumerate(pred_classes) if p == pcl]
            if not idxs:
                cond[pcl] = {"n": 0}
                continue
            co = Counter(outcomes[i] for i in idxs)
            nn = len(idxs)
            cond[pcl] = {
                "n": nn,
                "pct_actual_up": round(100.0 * co.get("up", 0) / nn, 6),
                "pct_actual_down": round(100.0 * co.get("down", 0) / nn, 6),
                "pct_actual_flat": round(100.0 * co.get("flat", 0) / nn, 6),
            }
        # Uplift vs baseline (percentage points)
        p_base_up = float(bl["pct_up"]) / 100.0
        p_base_dn = float(bl["pct_down"]) / 100.0
        p_base_fl = float(bl["pct_flat"]) / 100.0
        for pcl in ("up", "down", "flat"):
            if cond[pcl].get("n", 0) == 0:
                continue
            nn = cond[pcl]["n"]
            co = Counter(outcomes[i] for i in range(len(outcomes)) if pred_classes[i] == pcl)
            cond[pcl]["uplift_vs_baseline_up_pp"] = round(100.0 * (co.get("up", 0) / nn - p_base_up), 6)
            cond[pcl]["uplift_vs_baseline_down_pp"] = round(100.0 * (co.get("down", 0) / nn - p_base_dn), 6)
            cond[pcl]["uplift_vs_baseline_flat_pp"] = round(100.0 * (co.get("flat", 0) / nn - p_base_fl), 6)

        # 3x3 table predicted x actual
        labels = ["up", "down", "flat"]
        tab = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
        pi = {lab: i for i, lab in enumerate(labels)}
        for i in range(len(pred_classes)):
            if pred_classes[i] in pi and outcomes[i] in pi:
                tab[pi[pred_classes[i]]][pi[outcomes[i]]] += 1
        chi2, df = _chi2_independence(tab)
        p_chi = _chi2_sf(chi2, df)

        # Accuracy (exact match)
        correct = sum(1 for i in range(len(pred_classes)) if pred_classes[i] == outcomes[i])
        acc = correct / n_pred

        # Quantile bins by max_probs (deciles)
        order = sorted(range(len(max_probs)), key=lambda i: max_probs[i])
        decile_stats: list[dict[str, Any]] = []
        for d in range(10):
            a = (d * n_pred) // 10
            b = ((d + 1) * n_pred) // 10 if d < 9 else n_pred
            idxs = order[a:b]
            if not idxs:
                continue
            cor = sum(1 for i in idxs if pred_classes[i] == outcomes[i])
            decile_stats.append(
                {
                    "decile": d + 1,
                    "n": len(idxs),
                    "max_prob_min": round(min(max_probs[i] for i in idxs), 6),
                    "max_prob_max": round(max(max_probs[i] for i in idxs), 6),
                    "accuracy": round(cor / len(idxs), 6),
                }
            )

        # Monotonicity: Spearman-like check — correlation of decile index vs accuracy
        if len(decile_stats) >= 3:
            accs = [ds["accuracy"] for ds in decile_stats]
            x = list(range(len(accs)))
            mx = statistics.fmean(x)
            my = statistics.fmean(accs)
            num = sum((x[i] - mx) * (accs[i] - my) for i in range(len(x)))
            denx = sum((x[i] - mx) ** 2 for i in range(len(x)))
            deny = sum((accs[i] - my) ** 2 for i in range(len(x)))
            spearman_proxy = num / math.sqrt(denx * deny) if denx > 0 and deny > 0 else float("nan")
        else:
            spearman_proxy = float("nan")

        # EV per pred class (mean pts)
        ev: dict[str, Any] = {}
        for pcl in ("up", "down", "flat"):
            idxs = [i for i, p in enumerate(pred_classes) if p == pcl]
            if not idxs:
                ev[pcl] = {"n": 0}
                continue
            ptsv = [pts_list[i] for i in idxs if not math.isnan(pts_list[i])]
            ev[pcl] = {
                "n": len(idxs),
                "n_pts_non_null": len(ptsv),
                "mean_pts": round(statistics.fmean(ptsv), 8) if ptsv else None,
                "win_rate_up": round(sum(1 for i in idxs if outcomes[i] == "up") / len(idxs), 6),
            }

        # Slices: ticker (min 200 rows), session, rv bucket
        def rv_bucket(rv: Any) -> str:
            if rv is None:
                return "rv_null"
            x = float(rv)
            if x < 0.05:
                return "rv_lt_0.05"
            if x < 0.15:
                return "rv_0.05_0.15"
            if x < 0.35:
                return "rv_0.15_0.35"
            return "rv_ge_0.35"

        slice_acc: dict[str, Any] = {}
        tickers = defaultdict(list)
        for i, r in enumerate(sub):
            tickers[r["ticker"]].append(i)
        tkr_ok = {t: ix for t, ix in tickers.items() if len(ix) >= 200}
        slice_acc["tickers_min_200_rows"] = {
            t: round(
                sum(1 for i in tickers[t] if pred_classes[i] == outcomes[i]) / len(tickers[t]),
                6,
            )
            for t in sorted(tkr_ok.keys())
        }
        sess = defaultdict(list)
        for i, r in enumerate(sub):
            sess[str(r["market_session"] or "unknown")].append(i)
        slice_acc["market_session"] = {
            s: round(sum(1 for i in sess[s] if pred_classes[i] == outcomes[i]) / len(sess[s]), 6)
            for s in sorted(sess.keys())
        }
        rvb = defaultdict(list)
        for i, r in enumerate(sub):
            rvb[rv_bucket(r["realized_vol"])].append(i)
        slice_acc["realized_vol_bucket"] = {
            b: round(sum(1 for i in rvb[b] if pred_classes[i] == outcomes[i]) / len(rvb[b]), 6)
            for b in sorted(rvb.keys())
        }

        # Statsig: one-sample z — among pred=up rows, is P(actual=up) different from baseline P(up)?
        idx_up = [i for i in range(len(pred_classes)) if pred_classes[i] == "up"]
        if idx_up:
            x_up_hit = sum(1 for i in idx_up if outcomes[i] == "up")
            z1, p1 = _z_test_binomial_vs_p0(x_up_hit, len(idx_up), p_base_up)
        else:
            z1, p1 = (float("nan"), float("nan"))
        idx_dn = [i for i in range(len(pred_classes)) if pred_classes[i] == "down"]
        if idx_dn:
            x_dn_hit = sum(1 for i in idx_dn if outcomes[i] == "down")
            z_dn, p_dn = _z_test_binomial_vs_p0(x_dn_hit, len(idx_dn), p_base_dn)
        else:
            z_dn, p_dn = (float("nan"), float("nan"))
        idx_fl = [i for i in range(len(pred_classes)) if pred_classes[i] == "flat"]
        if idx_fl:
            x_fl_hit = sum(1 for i in idx_fl if outcomes[i] == "flat")
            z_fl, p_fl = _z_test_binomial_vs_p0(x_fl_hit, len(idx_fl), p_base_fl)
        else:
            z_fl, p_fl = (float("nan"), float("nan"))

        per_h[h] = {
            "n_governed_with_predictions": n_pred,
            "prediction_distribution": pred_dist,
            "pred_confidence_label_distribution": pred_confidence_distribution,
            "mean_entropy_nats": round(mean_h, 8),
            "max_entropy_nats_log3": round(h_max, 8),
            "entropy_ratio_to_uniform": round(mean_h / h_max, 6) if h_max > 0 else None,
            "variance_max_probability": round(var_maxp, 8),
            "n_max_prob_below_0_34_near_uniform_heuristic": near_uniform,
            "pct_max_prob_below_0_34": round(100.0 * near_uniform / n_pred, 6),
            "dominant_predicted_class_share": round(top_share, 6),
            "collapse_heuristic": {
                "always_long": top_share > 0.95 and ctr_p.most_common(1)[0][0] == "up",
                "always_flat": top_share > 0.95 and ctr_p.most_common(1)[0][0] == "flat",
                "near_uniform_frac": round(100.0 * near_uniform / n_pred, 6),
            },
            "overall_accuracy_vs_outcome": round(acc, 6),
            "conditional_outcomes_given_predicted": cond,
            "chi_square_pred_x_actual": {"chi2": round(chi2, 6), "df": df, "p_value": p_chi},
            "decile_by_max_probability_accuracy": decile_stats,
            "decile_accuracy_vs_rank_correlation_proxy": round(spearman_proxy, 6)
            if spearman_proxy == spearman_proxy
            else None,
            "expected_value_by_predicted_class": ev,
            "slice_accuracy": slice_acc,
            "ztest_predicted_class_hit_rate_vs_baseline": {
                "pred_up_vs_baseline_up_rate": {"z": z1, "p_value_two_sided": p1},
                "pred_down_vs_baseline_down_rate": {"z": z_dn, "p_value_two_sided": p_dn},
                "pred_flat_vs_baseline_flat_rate": {"z": z_fl, "p_value_two_sided": p_fl},
            },
            "wilson_95ci_overall_accuracy": {
                "successes": correct,
                "n": n_pred,
                "lo": _wilson_ci(correct, n_pred)[0],
                "hi": _wilson_ci(correct, n_pred)[1],
            },
        }

    conn.close()

    notes = [
        "Analysis uses stored snapshot columns pred_*_up_prob/down_prob/flat_prob only (not re-simulated pipeline).",
    ]
    if n_gov_pred1c == 0:
        notes.insert(
            0,
            "pred_1c_* columns are NULL for all governed rows in this DB — no empirical 1c probabilities persisted.",
        )
    out = {
        "db_path": str(db_path),
        "governed_row_count": n_gov,
        "governed_rows_with_pred_1c_nonnull": n_gov_pred1c,
        "governed_where_sql_fragment": " ".join(GOV_WHERE.split()),
        "step1_baseline_outcome_distribution_by_horizon": baseline,
        "steps_2_through_8_by_horizon_with_predictions": per_h,
        "notes": notes,
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
