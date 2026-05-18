#!/usr/bin/env python3

# DEPRECATED — 7-horizon era (pre Phase D3 schema drop).
# Targets retired outcome_3c/8c/13c columns; do not run against post-D3 databases.
# Relocated to tools/legacy/horizon_7/ for audit history only.
"""
Post-remediation: governed coverage, null buckets, pred_1c sanity stats (JSON to stdout).
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target

# Same governed predicate as tools/_phase5_discrimination_audit_v1.py GOV_WHERE
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

# compute_probs() uses round(..., 3) per class; triple can deviate from 1.0 slightly (empirical contract).
TOL_SUM_STRICT = 1e-5
TOL_SUM_EMPIRICAL_ROUNDED = 0.002


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "ed_console.db")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="report_pred_1c_governed_remediation_v1", write_capable=False)

    db_path = args.db.resolve()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    n_gov = int(conn.execute(f"SELECT COUNT(*) FROM snapshots s WHERE {GOV_WHERE}").fetchone()[0])
    n_up = int(
        conn.execute(
            f"SELECT COUNT(*) FROM snapshots s WHERE {GOV_WHERE} AND s.pred_1c_up_prob IS NOT NULL"
        ).fetchone()[0]
    )
    n_triple = int(
        conn.execute(
            f"SELECT COUNT(*) FROM snapshots s WHERE {GOV_WHERE} "
            "AND s.pred_1c_up_prob IS NOT NULL AND s.pred_1c_down_prob IS NOT NULL "
            "AND s.pred_1c_flat_prob IS NOT NULL"
        ).fetchone()[0]
    )
    n_null = n_gov - n_up

    # Null reason buckets (governed + pred_1c still null)
    null_where = f"({GOV_WHERE}) AND s.pred_1c_up_prob IS NULL"

    n_missing_zone = int(
        conn.execute(
            f"SELECT COUNT(*) FROM snapshots s WHERE {null_where} AND (s.zone IS NULL OR TRIM(s.zone) = '')"
        ).fetchone()[0]
    )
    n_missing_vwap = int(
        conn.execute(
            f"SELECT COUNT(*) FROM snapshots s WHERE {null_where} AND (s.vwap_side IS NULL OR TRIM(s.vwap_side) = '')"
        ).fetchone()[0]
    )
    n_missing_zone_or_vwap = int(
        conn.execute(
            f"SELECT COUNT(*) FROM snapshots s WHERE {null_where} "
            "AND (s.zone IS NULL OR TRIM(s.zone) = '' OR s.vwap_side IS NULL OR TRIM(s.vwap_side) = '')"
        ).fetchone()[0]
    )
    # Governed + null + have zone+vwap => empirical pool insufficient after backfill attempt
    n_insufficient_pool = int(
        conn.execute(
            f"SELECT COUNT(*) FROM snapshots s WHERE {null_where} "
            "AND s.zone IS NOT NULL AND TRIM(s.zone) != '' "
            "AND s.vwap_side IS NOT NULL AND TRIM(s.vwap_side) != ''"
        ).fetchone()[0]
    )

    # Sanity on populated governed rows
    bad_nan = bad_inf = bad_neg = bad_sum_strict = bad_sum_empirical = 0
    max_dev = 0.0
    entropies: list[float] = []
    argmax_c = Counter()

    cur = conn.execute(
        f"""
        SELECT s.pred_1c_up_prob AS u, s.pred_1c_down_prob AS d, s.pred_1c_flat_prob AS f
        FROM snapshots s
        WHERE {GOV_WHERE}
          AND s.pred_1c_up_prob IS NOT NULL
          AND s.pred_1c_down_prob IS NOT NULL
          AND s.pred_1c_flat_prob IS NOT NULL
        """
    )
    for r in cur:
        u, d, f = float(r["u"]), float(r["d"]), float(r["f"])
        for x in (u, d, f):
            if math.isnan(x):
                bad_nan += 1
            if math.isinf(x):
                bad_inf += 1
            if x < 0:
                bad_neg += 1
        ssum = u + d + f
        dev = abs(ssum - 1.0)
        max_dev = max(max_dev, dev)
        if dev > TOL_SUM_STRICT:
            bad_sum_strict += 1
        if dev > TOL_SUM_EMPIRICAL_ROUNDED:
            bad_sum_empirical += 1
        # entropy (natural log), skip if zeros
        if u > 0 or d > 0 or f > 0:
            e = 0.0
            for p in (u, d, f):
                if p > 1e-18:
                    e -= p * math.log(p + 1e-18)
            entropies.append(e)
        m = max((u, "up"), (d, "down"), (f, "flat"), key=lambda t: t[0])[1]
        argmax_c[m] += 1

    mean_h = sum(entropies) / len(entropies) if entropies else None
    h_max = math.log(3.0)

    # Coverage by ticker (governed)
    by_ticker = conn.execute(
        f"""
        SELECT s.ticker AS t,
               COUNT(*) AS n_gov,
               SUM(CASE WHEN s.pred_1c_up_prob IS NOT NULL THEN 1 ELSE 0 END) AS n_pred
        FROM snapshots s
        WHERE {GOV_WHERE}
        GROUP BY s.ticker
        ORDER BY n_gov DESC
        """
    ).fetchall()

    # Time buckets: median ts split
    med_row = conn.execute(
        f"SELECT ts_utc FROM snapshots s WHERE {GOV_WHERE} ORDER BY ts_utc LIMIT 1 OFFSET (?)",
        (n_gov // 2,),
    ).fetchone()
    med_ts = float(med_row[0]) if med_row and n_gov > 0 else None
    n_recent = n_old = 0
    pred_recent = pred_old = 0
    if med_ts is not None:
        n_recent = int(
            conn.execute(
                f"SELECT COUNT(*) FROM snapshots s WHERE {GOV_WHERE} AND s.ts_utc >= ?",
                (med_ts,),
            ).fetchone()[0]
        )
        n_old = n_gov - n_recent
        pred_recent = int(
            conn.execute(
                f"SELECT COUNT(*) FROM snapshots s WHERE {GOV_WHERE} AND s.ts_utc >= ? "
                "AND s.pred_1c_up_prob IS NOT NULL",
                (med_ts,),
            ).fetchone()[0]
        )
        pred_old = n_up - pred_recent

    near_uniform = int(
        conn.execute(
            f"""
            SELECT COUNT(*) FROM snapshots s
            WHERE {GOV_WHERE}
              AND s.pred_1c_up_prob IS NOT NULL
              AND ABS(s.pred_1c_up_prob - 1.0/3) < 0.02
              AND ABS(s.pred_1c_down_prob - 1.0/3) < 0.02
              AND ABS(s.pred_1c_flat_prob - 1.0/3) < 0.02
            """
        ).fetchone()[0]
    )

    out = {
        "db_path": str(db_path),
        "governed_total": n_gov,
        "governed_pred_1c_up_nonnull": n_up,
        "governed_pred_1c_triple_nonnull": n_triple,
        "governed_pred_1c_null": n_null,
        "coverage_pct_pred_up": round(100.0 * n_up / n_gov, 6) if n_gov else None,
        "null_reason_counts": {
            "missing_zone_or_vwap_similarity_required": n_missing_zone_or_vwap,
            "insufficient_similar_set_labeled_pool": n_insufficient_pool,
            "note": "missing_zone_or_vwap is mutually exclusive with insufficient_pool for rows split; "
            "sum of buckets may exceed n_null if a row counts in both zone and vwap subqueries — use combined missing_zone_or_vwap.",
        },
        "sanity": {
            "populated_governed_triples_scanned": len(entropies),
            "bad_nan": bad_nan,
            "bad_inf": bad_inf,
            "bad_negative": bad_neg,
            "bad_sum_deviation_gt_tol_strict": bad_sum_strict,
            "bad_sum_deviation_gt_tol_empirical_rounded": bad_sum_empirical,
            "tol_sum_strict": TOL_SUM_STRICT,
            "tol_sum_empirical_rounded": TOL_SUM_EMPIRICAL_ROUNDED,
            "max_abs_sum_minus_1": round(max_dev, 10),
            "note": "Per-class rounding to 3 decimals in compute_probs causes |sum-1| up to ~0.001; use empirical tolerance for PASS.",
            "mean_entropy_nats": round(mean_h, 8) if mean_h is not None else None,
            "max_entropy_uniform_nats": round(h_max, 8),
            "argmax_direction_counts": dict(argmax_c),
            "near_uniform_third_third_third_count": near_uniform,
        },
        "coverage_by_ticker": [
            {
                "ticker": row["t"],
                "n_governed": row["n_gov"],
                "n_pred_1c": row["n_pred"],
                "pct": round(100.0 * row["n_pred"] / row["n_gov"], 4) if row["n_gov"] else None,
            }
            for row in by_ticker
        ],
        "time_split_median_ts_utc": med_ts,
        "coverage_recent_half_ts_gte_median": {
            "n_governed": n_recent,
            "n_pred_1c": pred_recent,
            "pct": round(100.0 * pred_recent / n_recent, 4) if n_recent else None,
        },
        "coverage_older_half_ts_lt_median": {
            "n_governed": n_old,
            "n_pred_1c": pred_old,
            "pct": round(100.0 * pred_old / n_old, 4) if n_old else None,
        },
    }
    print(json.dumps(out, indent=2))
    conn.close()


if __name__ == "__main__":
    main()
