#!/usr/bin/env python3
"""
Insert missing canonical 1m price_bars_1m rows required for BAR_ANCHOR_V1 horizon labels.

When history is ingested on an irregular sub-minute grid (e.g. 3m spacing stored in price_bars_1m),
forward_bar_start_utc(T, N) points at bar_start timestamps that have no row, so fill_outcomes
cannot set outcome_Nc. This repair adds **flat** 1m bars (O=H=L=C=carry-forward close, V=0) at
exact missing grid points so the existing bar-anchor contract can resolve without changing
horizon_outcomes semantics.

Usage:
  python -m calibration.repair_canonical_1m_bars_for_outcomes --db data/ed_console.db --snapshot-id 161097
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

from horizon_outcomes import OUTCOME_BAR_SPECS, forward_bar_start_utc

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from db_authority import is_canonical_db_path

try:
    from db import EdDB, configure_sqlite_connection
except ImportError as e:
    log.warning(
        "db.EdDB / configure_sqlite_connection not available — governed outcome refresh disabled: %s",
        e,
    )
    EdDB = None  # type: ignore[misc, assignment]

    def configure_sqlite_connection(conn, **kwargs):
        pass

from app.domain.instrument_identity import ticker_storage_key

from calibration.repair_canonical_1m_shared import GAP_FILL_CANONICAL_1M_GRID_V1, carry_basis_source_sql
from app.domain.time_et import is_collect_window_bar_end_ts_utc  # RC-183 collect-window law

GAP_FILL_SOURCE = GAP_FILL_CANONICAL_1M_GRID_V1


def _prev_close(conn: sqlite3.Connection, tkr: str, b_start: float) -> float | None:
    src_clause, src_params = carry_basis_source_sql()
    r = conn.execute(
        f"""
        SELECT close FROM price_bars_1m
        WHERE ticker = ? AND bar_start_ts_utc < ? AND {src_clause}
        ORDER BY bar_start_ts_utc DESC LIMIT 1
        """,
        (tkr, b_start, *src_params),
    ).fetchone()
    if r is None or r[0] is None:
        return None
    return float(r[0])


def repair_snapshot_horizon_bars(
    db_path: Path,
    *,
    snapshot_id: int,
    dry_run: bool = False,
) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path), timeout=120.0)
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)

    snap = conn.execute(
        "SELECT snapshot_id, ticker, ts_utc, timeframe FROM snapshots WHERE snapshot_id = ?",
        (snapshot_id,),
    ).fetchone()
    if snap is None:
        conn.close()
        return {"error": "snapshot_not_found", "snapshot_id": snapshot_id}

    if str(snap["timeframe"]) != "1m":
        conn.close()
        return {"error": "non_1m_snapshot", "timeframe": snap["timeframe"]}

    t_snap = float(snap["ts_utc"])
    raw_ticker = str(snap["ticker"])
    tkr = ticker_storage_key(raw_ticker)

    needed: set[float] = set()
    for _odir, _opt, n_min in OUTCOME_BAR_SPECS:
        needed.add(forward_bar_start_utc(t_snap, n_min))

    inserted: list[float] = []
    skipped_existing: list[float] = []
    skipped_outside_window: list[float] = []

    for b_start in sorted(needed):
        exists = conn.execute(
            "SELECT 1 FROM price_bars_1m WHERE ticker = ? AND bar_start_ts_utc = ? LIMIT 1",
            (tkr, b_start),
        ).fetchone()
        if exists:
            skipped_existing.append(b_start)
            continue
        # RC-183: never FABRICATE a carry bar outside the collect window — an outcome whose
        # forward anchor falls outside the law stays unresolved rather than resting on a fake bar.
        if not is_collect_window_bar_end_ts_utc(b_start + 60.0):
            skipped_outside_window.append(b_start)
            continue
        c = _prev_close(conn, tkr, b_start)
        if c is None:
            conn.close()
            return {
                "error": "no_prior_bar_for_carry",
                "bar_start": b_start,
                "ticker_key": tkr,
            }
        be = b_start + 60.0
        if not dry_run:
            conn.execute(
                """
                INSERT INTO price_bars_1m -- collect-window-ok: rows gated via is_collect_window_bar_end_ts_utc above (RC-183)
                  (ticker, bar_start_ts_utc, bar_end_ts_utc, open, high, low, close, volume, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, bar_start_ts_utc) DO UPDATE SET
                  bar_end_ts_utc = excluded.bar_end_ts_utc,
                  open = excluded.open,
                  high = excluded.high,
                  low = excluded.low,
                  close = excluded.close,
                  volume = excluded.volume,
                  source = excluded.source
                """,
                (tkr, b_start, be, c, c, c, c, 0.0, GAP_FILL_SOURCE),
            )
        inserted.append(b_start)

    refresh_n = 0
    if not inserted:
        refresh_status = "skipped_no_inserts"
        if not dry_run:
            conn.commit()
        conn.close()
    elif dry_run:
        refresh_status = "skipped_dry_run"
        conn.close()
    else:
        if EdDB is None:
            conn.rollback()
            conn.close()
            return {
                "error": "outcome_refresh_unavailable_eddb_import_failed",
                "snapshot_id": snapshot_id,
                "ticker": raw_ticker,
                "ticker_key": tkr,
                "planned_inserted_bar_starts": inserted,
                "governed_outcome_refresh_rows": 0,
                "governed_outcome_refresh_status": "skipped_eddb_unavailable",
                "note": "gap-fill inserts rolled back — governed outcome refresh requires db.EdDB",
            }
        conn.commit()
        conn.close()
        edb = EdDB(
            db_path,
            allow_noncanonical=not is_canonical_db_path(db_path.resolve()),
        )
        refresh_n = edb.refresh_governed_outcomes_for_mutated_bar_starts(tkr, set(inserted))
        refresh_status = "ok"

    return {
        "snapshot_id": snapshot_id,
        "ticker": raw_ticker,
        "ticker_key": tkr,
        "ts_utc": t_snap,
        "needed_bar_starts": sorted(needed),
        "inserted_bar_starts": inserted,
        "skipped_existing_bar_starts": skipped_existing,
        "skipped_outside_collect_window_bar_starts": skipped_outside_window,
        "dry_run": dry_run,
        "source_tag": GAP_FILL_SOURCE,
        "governed_outcome_refresh_rows": refresh_n,
        "governed_outcome_refresh_status": refresh_status,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--snapshot-id", type=int, required=True)
    ap.add_argument("--dry-run", action="store_true")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    if not args.db.is_file():
        print(f"DB not found: {args.db}", file=sys.stderr)
        return 1
    require_canonical_db_target(
        args,
        tool_name="calibration.repair_canonical_1m_bars_for_outcomes",
        write_capable=True,
    )
    import json

    out = repair_snapshot_horizon_bars(args.db, snapshot_id=args.snapshot_id, dry_run=args.dry_run)
    print(json.dumps(out, indent=2))
    return 1 if out.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
