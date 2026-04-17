#!/usr/bin/env python3
"""Load move/dir heads per horizon; one inference row per governed ticker. Exit 1 on null or error."""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from db import configure_sqlite_connection
from features.inference_snapshot import build_inference_snapshot_v1_from_db_row
from ml_horizon import ML_HORIZON_SLUGS, normalize_ml_horizon_slug
import ml_predict
from ml_predict import _predict_xgb_movement_heads, reset_ml_infer_horizon_slug, set_ml_infer_horizon_slug

GOV = (
    "timeframe='1m' AND COALESCE(horizon_outcome_schema_version,3)=3 "
    "AND outcome_1c IS NOT NULL AND outcome_60c IS NOT NULL"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "ed_console.db")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="smoke_movement_heads_inference_v1", write_capable=False)

    conn = sqlite3.connect(str(args.db.resolve()))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    tickers = sorted({r[0] for r in conn.execute(f"SELECT DISTINCT ticker FROM snapshots WHERE {GOV}")})
    ml_predict._xgb_movehead_registry.clear()
    horizons = [normalize_ml_horizon_slug(h) for h in ML_HORIZON_SLUGS]
    for tkr in tickers:
        r = conn.execute(
            f"SELECT * FROM snapshots WHERE ticker=? AND {GOV} LIMIT 1",
            (tkr,),
        ).fetchone()
        if not r:
            print("FAIL no row", tkr)
            return 1
        d = dict(r)
        if d.get("spread") is not None and float(d["spread"]) < 0:
            d["spread"] = abs(float(d["spread"]))
        try:
            inf = build_inference_snapshot_v1_from_db_row(
                ticker=tkr, expiry=d.get("expiry"), as_of_ts=float(d["ts_utc"]), db_row=d
            )
        except Exception as e:
            print("FAIL build_inference", tkr, e)
            return 1
        for hz in horizons:
            tok = set_ml_infer_horizon_slug(hz)
            try:
                p = _predict_xgb_movement_heads(inf, tkr, None)
            finally:
                reset_ml_infer_horizon_slug(tok)
            pm = p.get(f"pred_move_prob_{hz}")
            pu = p.get(f"pred_dir_up_prob_{hz}")
            if pm is None or pu is None:
                print("FAIL null pred", tkr, hz, "move", pm, "dir", pu)
                return 1
            for k, v in p.items():
                if hz in k and v is not None and (v < 0 or v > 1):
                    print("FAIL bad prob", tkr, hz, k, v)
                    return 1
    conn.close()
    print("OK", len(tickers), "tickers", len(horizons), "horizons")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
