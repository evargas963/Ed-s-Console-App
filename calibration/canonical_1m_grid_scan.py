#!/usr/bin/env python3
"""
Complete scan: BAR_ANCHOR_V1 snapshots vs canonical 1m grid coverage in price_bars_1m.

Batched for large DBs: loads bar_start sets per ticker; single pass for off-grid detection.
"""
from __future__ import annotations

import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from horizon_outcomes import (
    HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
    OUTCOME_BAR_SPECS,
    forward_bar_start_utc,
)
from app.domain.instrument_identity import ticker_storage_key
from timeframe_config import CANONICAL_TIMEFRAME

try:
    from db import configure_sqlite_connection
except Exception:

    def configure_sqlite_connection(conn, **kwargs):
        pass


@dataclass
class GridDefectScanResult:
    db_path: str
    tz_now_utc: float
    snapshots_bar_anchor_total: int = 0
    snapshots_in_outcome_window: int = 0
    trusted_calibration_joined: int = 0
    missing_anchor_snapshots: list[dict[str, Any]] = field(default_factory=list)
    missing_forward: list[dict[str, Any]] = field(default_factory=list)
    off_grid_price_bars_1m: int = 0
    off_grid_examples: list[dict[str, Any]] = field(default_factory=list)
    per_ticker_missing_forward: dict[str, int] = field(default_factory=dict)
    per_horizon_missing_forward: dict[str, int] = field(default_factory=dict)


def scan_db(db_path: Path, *, tz_now_utc: float | None = None) -> GridDefectScanResult:
    db_path = db_path.resolve()
    conn = sqlite3.connect(str(db_path), timeout=120.0)
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)

    if tz_now_utc is None:
        r = conn.execute("SELECT MAX(bar_end_ts_utc) AS m FROM price_bars_1m").fetchone()
        tz_now_utc = float(r["m"] or time.time())

    out = GridDefectScanResult(db_path=str(db_path), tz_now_utc=float(tz_now_utc))
    _max_m = max(s[2] for s in OUTCOME_BAR_SPECS)
    ts_cutoff = float(tz_now_utc) - float(_max_m) * 60.0 - 120.0

    out.snapshots_bar_anchor_total = int(
        conn.execute(
            """
            SELECT COUNT(*) FROM snapshots
            WHERE timeframe = ?
              AND COALESCE(horizon_outcome_schema_version, ?) = ?
            """,
            (CANONICAL_TIMEFRAME, HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1, HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1),
        ).fetchone()[0]
    )

    # bar_start sets per ticker (float -> True)
    bar_starts_by_ticker: dict[str, set[float]] = defaultdict(set)
    for r in conn.execute("SELECT ticker, bar_start_ts_utc FROM price_bars_1m"):
        bar_starts_by_ticker[r["ticker"]].add(float(r["bar_start_ts_utc"]))

    # Off-grid: stream without storing all in Python if possible — use SQL filter
    for r in conn.execute(
        """
        SELECT ticker, bar_start_ts_utc, bar_end_ts_utc
        FROM price_bars_1m
        WHERE ABS(bar_start_ts_utc - (ROUND(bar_start_ts_utc / 60.0) * 60.0)) > 0.05
        """
    ):
        out.off_grid_price_bars_1m += 1
        if len(out.off_grid_examples) < 30:
            out.off_grid_examples.append(
                {
                    "ticker": r["ticker"],
                    "bar_start_ts_utc": float(r["bar_start_ts_utc"]),
                    "bar_end_ts_utc": float(r["bar_end_ts_utc"]),
                }
            )

    # Preload max bar_end <= ts for anchor check: use bisect per ticker — too heavy.
    # Instead: for each ticker load sorted (bar_end_ts_utc, close) ... simplified:
    # missing anchor iff no row with bar_end <= ts — use MAX(bar_end) per query batched by ticker.

    bar_ends_by_ticker: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for r in conn.execute(
        "SELECT ticker, bar_end_ts_utc, close FROM price_bars_1m ORDER BY ticker, bar_end_ts_utc"
    ):
        bar_ends_by_ticker[r["ticker"]].append((float(r["bar_end_ts_utc"]), float(r["close"])))

    import bisect

    snaps = conn.execute(
        """
        SELECT snapshot_id, ticker, ts_utc, outcome_filled
        FROM snapshots
        WHERE timeframe = ?
          AND COALESCE(horizon_outcome_schema_version, ?) = ?
          AND ts_utc < ?
        """,
        (
            CANONICAL_TIMEFRAME,
            HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
            HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
            ts_cutoff,
        ),
    ).fetchall()

    out.snapshots_in_outcome_window = len(snaps)

    for r in snaps:
        snap_id = int(r["snapshot_id"])
        t_snap = float(r["ts_utc"])
        tkr = ticker_storage_key(r["ticker"])
        ends = bar_ends_by_ticker.get(tkr)
        if not ends:
            out.missing_anchor_snapshots.append(
                {"snapshot_id": snap_id, "ticker": tkr, "ts_utc": t_snap}
            )
            continue
        be_list = [x[0] for x in ends]
        idx = bisect.bisect_right(be_list, t_snap) - 1
        if idx < 0:
            out.missing_anchor_snapshots.append(
                {"snapshot_id": snap_id, "ticker": tkr, "ts_utc": t_snap}
            )
            continue

        bmap = bar_starts_by_ticker.get(tkr, frozenset())
        for odir, _opt, n_min in OUTCOME_BAR_SPECS:
            b_start = float(forward_bar_start_utc(t_snap, n_min))
            if t_snap + float(n_min) * 60.0 + 60.0 > float(tz_now_utc):
                continue
            if b_start not in bmap:
                rec = {
                    "snapshot_id": snap_id,
                    "ticker": tkr,
                    "ts_utc": t_snap,
                    "horizon": odir,
                    "n_minutes": n_min,
                    "required_bar_start_ts_utc": b_start,
                }
                out.missing_forward.append(rec)
                out.per_ticker_missing_forward[tkr] = out.per_ticker_missing_forward.get(tkr, 0) + 1
                out.per_horizon_missing_forward[odir] = out.per_horizon_missing_forward.get(odir, 0) + 1

    crows = conn.execute(
        """
        SELECT c.id, c.ticker, c.decision_ts_utc
        FROM calibration_decision_log c
        WHERE c.calibration_trust = 'trusted'
        """,
    ).fetchall()
    for c in crows:
        tkr = ticker_storage_key(c["ticker"])
        ts = float(c["decision_ts_utc"])
        s = conn.execute(
            """
            SELECT snapshot_id FROM snapshots
            WHERE ticker = ? AND timeframe = '1m' AND ts_utc = ?
            """,
            (tkr, ts),
        ).fetchone()
        if s is not None:
            out.trusted_calibration_joined += 1

    conn.close()
    return out


def result_to_dict(r: GridDefectScanResult) -> dict[str, Any]:
    return {
        "db_path": r.db_path,
        "tz_now_utc": r.tz_now_utc,
        "snapshots_bar_anchor_total": r.snapshots_bar_anchor_total,
        "snapshots_in_outcome_window": r.snapshots_in_outcome_window,
        "trusted_calibration_joined_exact_ts": r.trusted_calibration_joined,
        "missing_anchor_count": len(r.missing_anchor_snapshots),
        "missing_forward_bar_count": len(r.missing_forward),
        "off_grid_price_bars_1m": r.off_grid_price_bars_1m,
        "per_ticker_missing_forward": dict(sorted(r.per_ticker_missing_forward.items())),
        "per_horizon_missing_forward": dict(sorted(r.per_horizon_missing_forward.items())),
        "missing_anchor_examples": r.missing_anchor_snapshots[:50],
        "missing_forward_examples": r.missing_forward[:50],
        "off_grid_examples": r.off_grid_examples,
    }
