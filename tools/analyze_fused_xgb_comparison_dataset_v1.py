#!/usr/bin/env python3
"""
Row-loss funnel + per-horizon comparable counts (pred + fused + outcome_move).
Writes data/fused_xgb_comparison_dataset_analysis_v1.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from db import configure_sqlite_connection
from lstm_data import STREAM_5M_LOOKBACK
from ml_horizon import ML_HORIZON_SLUGS
from timeframe_config import CANONICAL_TIMEFRAME

# Strict prior v1 backfill shape (reference only — explains small-N bottleneck)
from tools.backfill_fusion_policy_columns_v1 import GOV_WHERE as STRICT_GOV_WHERE


def _policy_tickers(root: Path) -> list[str]:
    p = root / "data" / "ticker_readiness_matrix_v1.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    return sorted(
        r["ticker"]
        for r in data["tickers"]
        if r.get("final_readiness_verdict") == "READY_GLOBAL_STANDARD" and r.get("policy_status") == "POLICY_ELIGIBLE"
    )


def _one(c: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    return int(c.execute(sql, params).fetchone()[0])


def _sufficiency_class(n: int) -> str:
    if n >= 500:
        return "SUFFICIENT"
    if n >= 100:
        return "BORDERLINE"
    return "INSUFFICIENT"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "ed_console.db")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="analyze_fused_xgb_comparison_dataset_v1", write_capable=False)

    conn = sqlite3.connect(str(args.db.resolve()))
    configure_sqlite_connection(conn)

    tf = CANONICAL_TIMEFRAME
    prior = STREAM_5M_LOOKBACK

    lstm_sub = (
        f"(SELECT COUNT(*) FROM snapshots pr WHERE pr.ticker = snapshots.ticker "
        f"AND pr.timeframe = ? AND pr.ts_utc < snapshots.ts_utc) >= ?"
    )

    total = _one(conn, "SELECT COUNT(*) FROM snapshots")
    tf1m = _one(conn, "SELECT COUNT(*) FROM snapshots WHERE timeframe = ?", (tf,))
    lstm_eligible = _one(
        conn,
        f"SELECT COUNT(*) FROM snapshots WHERE timeframe = ? AND {lstm_sub}",
        (tf, tf, prior),
    )

    outcome_5c = _one(conn, "SELECT COUNT(*) FROM snapshots WHERE outcome_move_5c IS NOT NULL")
    all_7_move = _one(
        conn,
        "SELECT COUNT(*) FROM snapshots WHERE "
        + " AND ".join(f"outcome_move_{hz} IS NOT NULL" for hz in ML_HORIZON_SLUGS),
    )

    pred_5c = _one(conn, "SELECT COUNT(*) FROM snapshots WHERE pred_move_prob_5c IS NOT NULL")
    fused_5c = _one(conn, "SELECT COUNT(*) FROM snapshots WHERE fused_move_prob_5c IS NOT NULL")

    pred_any = _one(
        conn,
        "SELECT COUNT(*) FROM snapshots WHERE "
        + " OR ".join(f"pred_move_prob_{hz} IS NOT NULL" for hz in ML_HORIZON_SLUGS),
    )
    fused_any = _one(
        conn,
        "SELECT COUNT(*) FROM snapshots WHERE "
        + " OR ".join(f"fused_move_prob_{hz} IS NOT NULL" for hz in ML_HORIZON_SLUGS),
    )

    allowed = _policy_tickers(ROOT)
    ph = ",".join(["?"] * len(allowed))
    strict_params = tuple(allowed) + (tf, prior)
    strict_v1_shape = _one(
        conn,
        f"SELECT COUNT(*) FROM snapshots WHERE ticker IN ({ph}) AND {STRICT_GOV_WHERE}",
        strict_params,
    )

    all_7_move_and_lstm = _one(
        conn,
        f"SELECT COUNT(*) FROM snapshots WHERE timeframe = ? AND {lstm_sub} AND "
        + " AND ".join(f"outcome_move_{hz} IS NOT NULL" for hz in ML_HORIZON_SLUGS),
        (tf, tf, prior),
    )

    row_reduction = {
        "total_rows_snapshots": total,
        "after_timeframe_1m_only": tf1m,
        "after_lstm_causal_prior_ge_60": lstm_eligible,
        "after_outcome_move_5c_non_null": outcome_5c,
        "after_all_7_outcome_move_non_null": all_7_move,
        "after_all_7_outcome_move_and_lstm_eligible": all_7_move_and_lstm,
        "after_pred_move_prob_5c_non_null": pred_5c,
        "after_fused_move_prob_5c_non_null": fused_5c,
        "pred_move_any_horizon_non_null": pred_any,
        "fused_move_any_horizon_non_null": fused_any,
        "strict_policy_gov_movement_all_horizons_shape": strict_v1_shape,
        "interpretation": {
            "lstm_gate": "Causal replay needs >=60 prior 1m snapshots per ticker (STREAM_5M_LOOKBACK).",
            "strict_v1_bottleneck": "Policy tickers + full legacy GOV_WHERE + all outcome_move_* — shrinks eligible rows sharply.",
            "per_horizon_eval": "Comparable rows are counted per horizon; do not require all horizons at once.",
        },
    }

    per_hz: dict = {}
    for hz in ML_HORIZON_SLUGS:
        pm, fm, om = f"pred_move_prob_{hz}", f"fused_move_prob_{hz}", f"outcome_move_{hz}"
        triple = _one(
            conn,
            f"SELECT COUNT(*) FROM snapshots WHERE {pm} IS NOT NULL AND {fm} IS NOT NULL AND {om} IS NOT NULL",
        )
        nt = _one(conn, f"SELECT COUNT(DISTINCT ticker) FROM snapshots WHERE {pm} IS NOT NULL AND {fm} IS NOT NULL AND {om} IS NOT NULL")
        rng = conn.execute(
            f"SELECT MIN(ts_utc), MAX(ts_utc) FROM snapshots WHERE {pm} IS NOT NULL AND {fm} IS NOT NULL AND {om} IS NOT NULL"
        ).fetchone()
        per_hz[hz] = {
            "comparable_rows_pred_fused_outcome_move": triple,
            "distinct_tickers": nt,
            "ts_utc_min": rng[0],
            "ts_utc_max": rng[1],
            "sufficiency_class": _sufficiency_class(triple),
        }

    min_triple = min(per_hz[h]["comparable_rows_pred_fused_outcome_move"] for h in ML_HORIZON_SLUGS)

    backfill_expansion: dict[str, Any] = {"expanded_backfill_summary_path": str(ROOT / "data" / "fused_policy_backfill_expanded_summary_v1.json")}
    _bp = ROOT / "data" / "fused_policy_backfill_expanded_summary_v1.json"
    if _bp.is_file():
        try:
            backfill_expansion["expanded_backfill_summary"] = json.loads(_bp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            backfill_expansion["read_error"] = repr(e)

    # Verdict: strict statistical tier (500+) vs task ">> 55" meaningful minimum.
    all_sufficient = all(per_hz[h]["sufficiency_class"] == "SUFFICIENT" for h in ML_HORIZON_SLUGS)
    final_verdict_statistical = "PASS" if all_sufficient else "FAIL"
    final_verdict_meaningful_vs_55 = "PASS" if min_triple > 55 else "FAIL"

    out = {
        "db_path": str(args.db.resolve()),
        "ROW_REDUCTION_BREAKDOWN": row_reduction,
        "PER_HORIZON_ROW_COUNTS": per_hz,
        "SUFFICIENCY_CLASSIFICATION": {
            "thresholds": {"SUFFICIENT": ">=500", "BORDERLINE": "100-499", "INSUFFICIENT": "<100"},
            "min_comparable_rows_across_horizons": min_triple,
        },
        "BACKFILL_EXPANSION_RESULT": backfill_expansion,
        "FINAL_VERDICT": {
            "statistical_tier_ge_500_all_horizons": final_verdict_statistical,
            "meaningful_sample_gt_55_all_horizons": final_verdict_meaningful_vs_55,
            "note": "Use tools/backfill_fusion_policy_columns_expanded_v1.py without --limit (after comparable-yield pool) to approach max ~5–6k triple rows; runtime is bounded by per-row stack replay.",
        },
    }

    outp = ROOT / "data" / "fused_xgb_comparison_dataset_analysis_v1.json"
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps(out, indent=2, default=str))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
