#!/usr/bin/env python3

# DEPRECATED — 7-horizon era (pre Phase D3 schema drop).
# Targets retired outcome_3c/8c/13c columns; do not run against post-D3 databases.
# Relocated to tools/legacy/horizon_7/ for audit history only.
"""
Backfill snapshots.pred_1c_* from the same empirical histogram path as live inference
(prediction_engine._literal_empirical_horizon on outcome_1c).

Use after fixing persistence so historical rows match what would have been stored at insert time
(as_of_ts_utc = snapshot ts_utc).

Requires: zone, vwap_side, canonical timeframe 1m.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target

from db import EdDB
from prediction_engine import _literal_empirical_horizon, _tri_probs
from timeframe_config import CANONICAL_TIMEFRAME


def _process_rows(
    conn: sqlite3.Connection,
    edb: EdDB,
    rows: list,
    *,
    dry_run: bool,
) -> tuple[int, int, int]:
    """Returns (updated, skipped_insufficient, errors)."""
    updated = 0
    skipped_insufficient = 0
    errors = 0
    for r in rows:
        sid = int(r["snapshot_id"])
        ticker = str(r["ticker"] or "")
        zone = str(r["zone"] or "")
        vwap_side = str(r["vwap_side"] or "")
        nad = r["nearest_above_dist"]
        nbd = r["nearest_below_dist"]
        ts_utc = float(r["ts_utc"])

        try:
            similar = edb.get_similar_setups(
                ticker,
                CANONICAL_TIMEFRAME,
                zone,
                vwap_side,
                float(nad) if nad is not None else None,
                float(nbd) if nbd is not None else None,
                as_of_ts_utc=ts_utc,
            )
            probs, _src, _note, _n = _literal_empirical_horizon(similar, "outcome_1c", 1)
            u, d, f = _tri_probs(probs)
            if u is None:
                skipped_insufficient += 1
                continue
            if not dry_run:
                conn.execute(
                    """
                    UPDATE snapshots
                    SET pred_1c_up_prob = ?, pred_1c_down_prob = ?, pred_1c_flat_prob = ?
                    WHERE snapshot_id = ?
                    """,
                    (u, d, f, sid),
                )
            updated += 1
            if updated % 500 == 0 and not dry_run:
                conn.commit()
        except Exception:
            errors += 1
            if errors <= 5:
                traceback.print_exc()

    if not dry_run:
        conn.commit()
    return updated, skipped_insufficient, errors


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "ed_console.db")
    ap.add_argument("--limit", type=int, default=0, help="Max rows to process (0 = all eligible in one or more chunk passes)")
    ap.add_argument(
        "--chunk-size",
        type=int,
        default=0,
        help="When set with --limit 0, process eligible rows in chunks of this size until none remain (resumable). "
        "0 = single batch (fetch all matching rows at once). Recommended: 400–800 for large DBs.",
    )
    ap.add_argument("--dry-run", action="store_true", help="Compute only; no UPDATE")
    ap.add_argument(
        "--governed-only",
        action="store_true",
        help=(
            "Only rows matching governed 1m BAR_ANCHOR_V1 dataset (schema v3, full outcomes, "
            "price_bars_1m anchor). Same predicate as calibration/phase6 governed audits."
        ),
    )
    ap.add_argument(
        "--order-ts",
        choices=("asc", "desc"),
        default="desc",
        help="Process snapshots by ts_utc ascending (early history first) or descending (recent first; "
        "better empirical pools). Default: desc.",
    )
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    db_path = args.db.resolve()
    require_canonical_db_target(
        args,
        tool_name="backfill_pred_1c_snapshots_v1",
        write_capable=not args.dry_run,
    )

    edb = EdDB(db_path, allow_noncanonical=bool(getattr(args, "allow_noncanonical_db", False)))
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    gov_extra = ""
    if args.governed_only:
        gov_extra = """
          AND horizon_outcome_schema_version = 3
          AND outcome_1c IS NOT NULL AND outcome_3c IS NOT NULL AND outcome_5c IS NOT NULL
          AND outcome_8c IS NOT NULL AND outcome_13c IS NOT NULL AND outcome_15c IS NOT NULL
          AND outcome_60c IS NOT NULL
          AND EXISTS (
            SELECT 1 FROM price_bars_1m p
            WHERE p.ticker = snapshots.ticker AND p.bar_end_ts_utc <= snapshots.ts_utc
          )
        """
    base_sql = f"""
        SELECT snapshot_id, ticker, timeframe, zone, vwap_side,
               nearest_above_dist, nearest_below_dist, ts_utc
        FROM snapshots
        WHERE timeframe = ?
          AND pred_1c_up_prob IS NULL
          AND zone IS NOT NULL AND TRIM(zone) != ''
          AND vwap_side IS NOT NULL AND TRIM(vwap_side) != ''
          {gov_extra}
        ORDER BY ts_utc { "ASC" if args.order_ts == "asc" else "DESC" }
    """
    lim = args.limit if args.limit and args.limit > 0 else None
    chunk_size = int(args.chunk_size) if getattr(args, "chunk_size", 0) else 0

    total_scanned = 0
    updated = 0
    skipped_insufficient = 0
    errors = 0
    chunks_ran = 0

    if lim is not None:
        rows = conn.execute(base_sql + " LIMIT ?", (CANONICAL_TIMEFRAME, int(lim))).fetchall()
        total_scanned = len(rows)
        u, sk, er = _process_rows(conn, edb, rows, dry_run=args.dry_run)
        updated, skipped_insufficient, errors = u, sk, er
        chunks_ran = 1
    else:
        # One stable fetch: every eligible row is attempted exactly once (no re-query NULL loop).
        all_rows = conn.execute(base_sql, (CANONICAL_TIMEFRAME,)).fetchall()
        total_scanned = len(all_rows)
        if chunk_size > 0:
            for i in range(0, len(all_rows), chunk_size):
                batch = all_rows[i : i + chunk_size]
                chunks_ran += 1
                u, sk, er = _process_rows(conn, edb, batch, dry_run=args.dry_run)
                updated += u
                skipped_insufficient += sk
                errors += er
        else:
            chunks_ran = 1
            u, sk, er = _process_rows(conn, edb, all_rows, dry_run=args.dry_run)
            updated, skipped_insufficient, errors = u, sk, er

    conn.close()

    print(
        json.dumps(
            {
                "tool": "backfill_pred_1c_snapshots_v1",
                "db": str(db_path),
                "chunk_size": chunk_size,
                "chunks_ran": chunks_ran,
                "rows_scanned": total_scanned,
                "rows_updated_or_would_update": updated,
                "skipped_insufficient_labeled": skipped_insufficient,
                "errors": errors,
                "dry_run": bool(args.dry_run),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
