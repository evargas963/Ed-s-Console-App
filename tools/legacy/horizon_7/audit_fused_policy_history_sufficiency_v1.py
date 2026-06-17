#!/usr/bin/env python3

# DEPRECATED — 7-horizon era (pre Phase D3 schema drop).
# Targets retired outcome_3c/8c/13c columns; do not run against post-D3 databases.
# Relocated to tools/legacy/horizon_7/ for audit history only.
"""
Task 1: fused_* history sufficiency for fused vs XGB policy comparison.

Exits 0 always; inspect JSON for deficiency flags.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from db import configure_sqlite_connection
from ml_horizon import ML_HORIZON_SLUGS

GOV_WHERE = """
timeframe = '1m'
AND COALESCE(horizon_outcome_schema_version, 3) = 3
AND outcome_1c IS NOT NULL AND outcome_1c_pts IS NOT NULL
AND outcome_3c IS NOT NULL AND outcome_3c_pts IS NOT NULL
AND outcome_5c IS NOT NULL AND outcome_5c_pts IS NOT NULL
AND outcome_8c IS NOT NULL AND outcome_8c_pts IS NOT NULL
AND outcome_13c IS NOT NULL AND outcome_13c_pts IS NOT NULL
AND outcome_15c IS NOT NULL AND outcome_15c_pts IS NOT NULL
AND outcome_60c IS NOT NULL AND outcome_60c_pts IS NOT NULL
AND EXISTS (SELECT 1 FROM price_bars_1m p WHERE p.ticker = snapshots.ticker AND p.bar_end_ts_utc <= snapshots.ts_utc)
""".strip()


def _snapshot_columns(conn: sqlite3.Connection) -> set[str]:
    return {r[1] for r in conn.execute("PRAGMA table_info(snapshots)").fetchall()}


def main() -> int:
    ap = __import__("argparse").ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "ed_console.db")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="audit_fused_policy_history_sufficiency_v1", write_capable=False)

    readiness = json.loads((ROOT / "data" / "ticker_readiness_matrix_v1.json").read_text(encoding="utf-8"))
    allowed = sorted(
        r["ticker"]
        for r in readiness["tickers"]
        if r.get("final_readiness_verdict") == "READY_GLOBAL_STANDARD" and r.get("policy_status") == "POLICY_ELIGIBLE"
    )
    ph = ",".join(["?"] * len(allowed))

    conn = sqlite3.connect(str(args.db.resolve()))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    cols = _snapshot_columns(conn)

    hz0 = ML_HORIZON_SLUGS[0]
    fused_schema_ok = f"fused_move_prob_{hz0}" in cols
    out: dict = {
        "db_path": str(args.db.resolve()),
        "fused_columns_present": fused_schema_ok,
        "allowed_policy_tickers_n": len(allowed),
        "policy_ticker_domain": {"horizons": {}},
        "governed_GOV_WHERE_domain": {"horizons": {}},
    }

    if not fused_schema_ok:
        out["deficiency"] = (
            "snapshots table has no fused_* columns — run EdDB schema migration "
            "(instantiate db.EdDB(db_path) or apply db.py migrations) then populate via live logging or fusion replay/backfill."
        )
        out["sufficient_for_phase8_phase9_comparison"] = False
        outp = ROOT / "data" / "fused_policy_history_sufficiency_v1.json"
        outp.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(json.dumps(out, indent=2))
        conn.close()
        return 0

    for hz in ML_HORIZON_SLUGS:
        fm, fd, fc = f"fused_move_prob_{hz}", f"fused_dir_up_prob_{hz}", f"fused_confidence_{hz}"
        pm, pd = f"pred_move_prob_{hz}", f"pred_dir_up_prob_{hz}"
        q_base = f"SELECT COUNT(*) AS n FROM snapshots WHERE ticker IN ({ph}) AND outcome_move_{hz} IS NOT NULL"
        n_move_lab = conn.execute(q_base, allowed).fetchone()["n"]
        n_fused_m = conn.execute(q_base + f" AND {fm} IS NOT NULL", allowed).fetchone()["n"]
        n_pred_m = conn.execute(q_base + f" AND {pm} IS NOT NULL", allowed).fetchone()["n"]
        n_both_m = conn.execute(q_base + f" AND {fm} IS NOT NULL AND {pm} IS NOT NULL", allowed).fetchone()["n"]
        rng = conn.execute(
            f"SELECT MIN(ts_utc) AS mn, MAX(ts_utc) AS mx, COUNT(DISTINCT ticker) AS nt "
            f"FROM snapshots WHERE ticker IN ({ph}) AND outcome_move_{hz} IS NOT NULL AND {fm} IS NOT NULL",
            allowed,
        ).fetchone()
        n_fc = conn.execute(q_base + f" AND {fc} IS NOT NULL", allowed).fetchone()["n"]
        q_dir = (
            f"SELECT COUNT(*) AS n FROM snapshots WHERE ticker IN ({ph}) "
            f"AND outcome_dir_{hz} IS NOT NULL AND CAST(valid_dir_{hz} AS INTEGER)=1"
        )
        n_fused_d = conn.execute(q_dir + f" AND {fd} IS NOT NULL", allowed).fetchone()["n"]
        n_pred_d = conn.execute(q_dir + f" AND {pd} IS NOT NULL", allowed).fetchone()["n"]
        n_both_d = conn.execute(q_dir + f" AND {fd} IS NOT NULL AND {pd} IS NOT NULL", allowed).fetchone()["n"]

        out["policy_ticker_domain"]["horizons"][hz] = {
            "outcome_move_labeled_rows": n_move_lab,
            "fused_move_non_null": n_fused_m,
            "pred_move_non_null": n_pred_m,
            "both_move_non_null": n_both_m,
            "fused_confidence_non_null": n_fc,
            "fused_dir_non_null": n_fused_d,
            "pred_dir_non_null": n_pred_d,
            "both_dir_non_null": n_both_d,
            "fused_move_ts_min": rng["mn"],
            "fused_move_ts_max": rng["mx"],
            "fused_move_distinct_tickers": rng["nt"],
        }

        qg = f"SELECT COUNT(*) AS n FROM snapshots WHERE ticker IN ({ph}) AND {GOV_WHERE} AND outcome_move_{hz} IS NOT NULL"
        n_g = conn.execute(qg, allowed).fetchone()["n"]
        n_f = conn.execute(qg + f" AND {fm} IS NOT NULL", allowed).fetchone()["n"]
        n_p = conn.execute(qg + f" AND {pm} IS NOT NULL", allowed).fetchone()["n"]
        n_b = conn.execute(qg + f" AND {fm} IS NOT NULL AND {pm} IS NOT NULL", allowed).fetchone()["n"]
        out["governed_GOV_WHERE_domain"]["horizons"][hz] = {
            "governed_move_labeled": n_g,
            "fused_non_null": n_f,
            "pred_non_null": n_p,
            "both_non_null": n_b,
        }

    # Phase 8 uses min n>=50 per family:hz; stricter for policy
    min_fused = min(
        out["policy_ticker_domain"]["horizons"][h]["fused_move_non_null"] for h in ML_HORIZON_SLUGS
    )
    out["sufficient_for_phase8_phase9_comparison"] = bool(min_fused >= 50 and fused_schema_ok)
    if not out["sufficient_for_phase8_phase9_comparison"] and fused_schema_ok:
        out["deficiency"] = (
            f"min fused_move_non_null across horizons = {min_fused} "
            "(need live fused logging or replay to match pred coverage for fair comparison)"
        )

    conn.close()
    outp = ROOT / "data" / "fused_policy_history_sufficiency_v1.json"
    outp.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
