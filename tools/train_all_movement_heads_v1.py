#!/usr/bin/env python3
"""
Train all movement (dir + move) XGB heads per ticker and horizon into models/active/{TICKER}/.

Uses ml_train.train_ticker with existing feature pipeline. Skips combinations with insufficient rows.

  python tools/train_all_movement_heads_v1.py --db data/ed_console.db
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from ml_horizon import ML_HORIZON_SLUGS, directional_label_column, move_label_column, normalize_ml_horizon_slug
from ml_train import (
    TARGET_MODE_DIR,
    TARGET_MODE_MOVE,
    load_data,
    train_ticker,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("train_movement")

MIN_ROWS_DIR = 80
MIN_ROWS_MOVE = 80


def _tickers(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT ticker FROM snapshots_1m_normalized ORDER BY ticker"
    ).fetchall()
    return [str(r[0]).strip().upper() for r in rows if r[0]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "ed_console.db")
    ap.add_argument("--min-rows-dir", type=int, default=MIN_ROWS_DIR)
    ap.add_argument("--min-rows-move", type=int, default=MIN_ROWS_MOVE)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="train_all_movement_heads_v1", write_capable=True)

    dbp = str(args.db.resolve())
    conn = sqlite3.connect(dbp)
    tickers = _tickers(conn)
    conn.close()
    log.info("tickers=%s", tickers)

    report: dict = {"db": dbp, "started": time.time(), "results": [], "errors": []}
    horizons = [normalize_ml_horizon_slug(h) for h in ML_HORIZON_SLUGS]

    for tkr in tickers:
        out_dir = ROOT / "models" / "active" / tkr
        out_dir.mkdir(parents=True, exist_ok=True)
        for hz in horizons:
            for mode, min_r, label_fn, tm in (
                ("dir", args.min_rows_dir, directional_label_column, TARGET_MODE_DIR),
                ("move", args.min_rows_move, move_label_column, TARGET_MODE_MOVE),
            ):
                lc = label_fn(hz)
                try:
                    df = load_data(dbp, ticker=tkr, ml_horizon_slug=hz, label_column=lc)
                except Exception as e:
                    report["errors"].append({"ticker": tkr, "hz": hz, "mode": mode, "phase": "load", "err": str(e)})
                    continue
                if len(df) < min_r:
                    report["results"].append(
                        {
                            "ticker": tkr,
                            "horizon": hz,
                            "mode": mode,
                            "status": "SKIP_LOW_N",
                            "n": len(df),
                        }
                    )
                    continue
                try:
                    train_ticker(
                        ticker=tkr,
                        df=df,
                        model_dir=out_dir,
                        nan_threshold=0.35,
                        skip_sanity=True,
                        show_importance=False,
                        compare=False,
                        evaluate_only=False,
                        ml_horizon_slug=hz,
                        target_mode=tm,
                    )
                    report["results"].append(
                        {"ticker": tkr, "horizon": hz, "mode": mode, "status": "OK", "n": len(df)}
                    )
                    log.info("OK %s %s %s n=%s", tkr, hz, mode, len(df))
                except Exception as e:
                    report["errors"].append(
                        {
                            "ticker": tkr,
                            "hz": hz,
                            "mode": mode,
                            "err": str(e),
                            "trace": traceback.format_exc(),
                        }
                    )
                    log.warning("FAIL %s %s %s: %s", tkr, hz, mode, e)

    report["finished"] = time.time()
    report["elapsed_s"] = round(report["finished"] - report["started"], 3)
    outp = ROOT / "data" / "train_all_movement_heads_v1_report.json"
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"elapsed_s": report["elapsed_s"], "errors": len(report["errors"]), "wrote": str(outp)}, indent=2))
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
