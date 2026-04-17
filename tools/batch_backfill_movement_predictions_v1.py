#!/usr/bin/env python3
"""
Batch backfill: movement + direction XGB head probabilities for all governed 1m snapshots.

Uses InferenceSnapshotV1 from DB rows and ml_predict._predict_xgb_movement_heads per horizon.
This path is **XGB head inference only** (no LSTM/Transformer, no Monte Carlo, no Bayesian fusion)
and therefore is **not** the governed live stack defined in signals.compute_signals
(base → MC → fusion → policy). Offline policy scripts that read these DB columns are not
fusion-authoritative until a fusion-backed persistence path exists.

  python tools/batch_backfill_movement_predictions_v1.py --db data/ed_console.db
"""
from __future__ import annotations

import argparse
import bisect
import json
import logging
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from db import configure_sqlite_connection
from features.inference_snapshot import build_inference_snapshot_v1_from_db_row
from instrument_identity import ticker_storage_key
from ml_horizon import ML_HORIZON_SLUGS, normalize_ml_horizon_slug
import ml_predict
from ml_predict import _predict_xgb_movement_heads, reset_ml_infer_horizon_slug, set_ml_infer_horizon_slug

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("batch_movement")

GOV_SQL = """
SELECT * FROM snapshots
WHERE timeframe = '1m'
  AND COALESCE(horizon_outcome_schema_version, 3) = 3
  AND outcome_1c IS NOT NULL AND outcome_1c_pts IS NOT NULL
  AND outcome_3c IS NOT NULL AND outcome_3c_pts IS NOT NULL
  AND outcome_5c IS NOT NULL AND outcome_5c_pts IS NOT NULL
  AND outcome_8c IS NOT NULL AND outcome_8c_pts IS NOT NULL
  AND outcome_13c IS NOT NULL AND outcome_13c_pts IS NOT NULL
  AND outcome_15c IS NOT NULL AND outcome_15c_pts IS NOT NULL
  AND outcome_60c IS NOT NULL AND outcome_60c_pts IS NOT NULL
ORDER BY ticker, ts_utc
"""


def _load_bar_ends(conn: sqlite3.Connection) -> dict[str, list[float]]:
    by_t: dict[str, list[float]] = defaultdict(list)
    for r in conn.execute("SELECT ticker, bar_end_ts_utc FROM price_bars_1m ORDER BY ticker, bar_end_ts_utc"):
        by_t[r["ticker"]].append(float(r["bar_end_ts_utc"]))
    return dict(by_t)


def _has_anchor(bar_ends: dict[str, list[float]], ticker: str, ts: float) -> bool:
    t = ticker_storage_key(ticker)
    ends = bar_ends.get(t)
    if not ends:
        return False
    i = bisect.bisect_right(ends, float(ts)) - 1
    return i >= 0


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _sanitize_snapshot_dict_for_mvp(d: dict[str, Any]) -> dict[str, Any]:
    """Coerce DB quirks so build_db_mvp_feature_row passes (spread must be >= 0 when present)."""
    out = dict(d)
    sp = out.get("spread")
    if sp is not None:
        try:
            v = float(sp)
            if v < 0:
                out["spread"] = abs(v)
        except (TypeError, ValueError):
            pass
    return out


def _pred_columns_for_horizon(hz: str) -> list[str]:
    return [
        f"pred_move_prob_{hz}",
        f"pred_no_move_prob_{hz}",
        f"pred_dir_up_prob_{hz}",
        f"pred_dir_down_prob_{hz}",
        f"pred_{hz}_move_prob",
        f"pred_{hz}_no_move_prob",
        f"pred_{hz}_dir_up_prob",
        f"pred_{hz}_dir_down_prob",
    ]


def _infer_row_movement_all_horizons(
    d: dict[str, Any],
    horizons: tuple[str, ...],
    *,
    max_attempts: int = 3,
) -> dict[str, float | None]:
    """Returns flat dict of column -> value for all horizons (None for missing)."""
    ticker = str(d["ticker"])
    out: dict[str, float | None] = {}
    for hz in horizons:
        for c in _pred_columns_for_horizon(hz):
            out[c] = None

    d = _sanitize_snapshot_dict_for_mvp(d)
    try:
        inf = build_inference_snapshot_v1_from_db_row(
            ticker=ticker,
            expiry=d.get("expiry"),
            as_of_ts=float(d["ts_utc"]),
            db_row=d,
        )
    except Exception as e:
        log.warning("build_inference_snapshot failed snapshot_id=%s ticker=%s: %s", d.get("snapshot_id"), ticker, e)
        return out

    for hz in horizons:
        hz = normalize_ml_horizon_slug(hz)
        tok = set_ml_infer_horizon_slug(hz)
        preds: dict[str, float] = {}
        try:
            for attempt in range(max_attempts):
                try:
                    preds = _predict_xgb_movement_heads(inf, ticker, None)
                    break
                except Exception as e:
                    if attempt == max_attempts - 1:
                        log.debug("movehead predict fail snapshot_id=%s hz=%s: %s", d.get("snapshot_id"), hz, e)
                    else:
                        time.sleep(0.05 * (attempt + 1))
        finally:
            reset_ml_infer_horizon_slug(tok)
        keys = _pred_columns_for_horizon(hz)
        for c in keys:
            v = preds.get(c)
            if v is not None:
                out[c] = float(v)

    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "ed_console.db")
    ap.add_argument("--commit-every", type=int, default=80)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit-rows", type=int, default=0, help="0 = no limit")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(
        args, tool_name="batch_backfill_movement_predictions_v1", write_capable=not args.dry_run
    )

    dbp = args.db.resolve()
    if not dbp.is_file():
        log.error("missing db %s", dbp)
        return 2

    horizons = tuple(normalize_ml_horizon_slug(h) for h in ML_HORIZON_SLUGS)
    all_cols: list[str] = []
    for hz in horizons:
        all_cols.extend(_pred_columns_for_horizon(hz))

    ml_predict._xgb_movehead_registry.clear()

    conn = sqlite3.connect(str(dbp))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    bar_ends = _load_bar_ends(conn)

    rows = []
    for r in conn.execute(GOV_SQL):
        if _has_anchor(bar_ends, r["ticker"], float(r["ts_utc"])):
            rows.append(r)
    log.info("governed_with_anchor=%s", len(rows))

    if args.limit_rows > 0:
        rows = rows[: args.limit_rows]

    stats = defaultdict(int)
    t0 = time.time()
    buf: list[tuple] = []

    set_sql = ", ".join(f"{c} = ?" for c in all_cols)
    upd_sql = f"UPDATE snapshots SET {set_sql} WHERE snapshot_id = ?"

    def flush() -> None:
        if args.dry_run or not buf:
            return
        conn.execute("BEGIN IMMEDIATE")
        try:
            for vals in buf:
                conn.execute(upd_sql, vals)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        buf.clear()

    for i, r in enumerate(rows):
        d = _row_to_dict(r)
        sid = d.get("snapshot_id")
        merged = _infer_row_movement_all_horizons(d, horizons)
        # Build tuple in all_cols order
        vals = []
        ok_move = True
        ok_dir = True
        for hz in horizons:
            pm = merged.get(f"pred_move_prob_{hz}")
            pu = merged.get(f"pred_dir_up_prob_{hz}")
            if pm is None:
                ok_move = False
            if pu is None:
                ok_dir = False
        for c in all_cols:
            v = merged.get(c)
            vals.append(v)
        vals.append(sid)
        if all(merged.get(c) is None for c in all_cols):
            stats["rows_all_null_preds"] += 1
            stats["rows_processed"] += 1
            continue
        buf.append(tuple(vals))
        if ok_move:
            stats["row_move_ok"] += 1
        if ok_dir:
            stats["row_dir_ok"] += 1
        stats["rows_processed"] += 1

        if len(buf) >= args.commit_every:
            flush()
            log.info("progress %s/%s elapsed_s=%.1f", i + 1, len(rows), time.time() - t0)

    flush()
    conn.close()

    rep = {
        "db": str(dbp),
        "dry_run": args.dry_run,
        "horizons": list(horizons),
        "stats": dict(stats),
        "elapsed_s": round(time.time() - t0, 3),
    }
    outj = ROOT / "data" / "batch_backfill_movement_predictions_v1_report.json"
    outj.parent.mkdir(parents=True, exist_ok=True)
    outj.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print(json.dumps(rep, indent=2))
    log.info("wrote %s", outj)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
