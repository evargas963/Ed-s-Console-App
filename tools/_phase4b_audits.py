#!/usr/bin/env python3
"""Phase 4B: leakage, duplicates, bar order, chain samples — stdout JSON."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from horizon_outcomes import forward_bar_start_utc  # noqa: E402

DB = ROOT / "data" / "ed_console.db"


def main() -> None:
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    out: dict = {}

    # --- STEP 4 duplicates ---
    dup_sn = conn.execute(
        """
        SELECT ticker, timeframe, ts_utc, COUNT(*) AS c
        FROM snapshots
        GROUP BY ticker, timeframe, ts_utc
        HAVING c > 1
        """
    ).fetchall()
    out["duplicate_snapshot_keys"] = len(dup_sn)
    out["duplicate_snapshot_sample"] = [dict(r) for r in dup_sn[:20]]

    dup_bars = conn.execute(
        """
        SELECT ticker, bar_start_ts_utc, COUNT(*) AS c
        FROM price_bars_1m
        GROUP BY ticker, bar_start_ts_utc
        HAVING c > 1
        """
    ).fetchall()
    out["duplicate_price_bars_1m_keys"] = len(dup_bars)

    # --- Bar ordering: bar_end != bar_start + 60 ---
    bad_len = conn.execute(
        """
        SELECT COUNT(*) AS n FROM price_bars_1m
        WHERE ABS(bar_end_ts_utc - bar_start_ts_utc - 60.0) > 0.05
        """
    ).fetchone()["n"]
    out["bars_bad_length_60s"] = int(bad_len)

    # Overlap: same ticker, overlapping [start,end) intervals
    overlap = conn.execute(
        """
        SELECT COUNT(*) AS n FROM price_bars_1m p1
        JOIN price_bars_1m p2
          ON p1.ticker = p2.ticker AND p1.bar_start_ts_utc < p2.bar_start_ts_utc
         AND p1.bar_end_ts_utc > p2.bar_start_ts_utc
        """
    ).fetchone()["n"]
    out["overlapping_bar_intervals"] = int(overlap)

    # --- STEP 1 leakage: outcome forward bar_start strictly after decision minute for 5c ---
    # For each filled snapshot, verify: forward_bar_start_utc(T, N) >= floor(T/60)*60 + N*60
    # and bar_start used for label has bar_end = bar_start + 60 > T (bar "complete" after T for forward)
    leaks = []
    rows = conn.execute(
        """
        SELECT snapshot_id, ticker, ts_utc, outcome_5c, outcome_5c_pts
        FROM snapshots
        WHERE timeframe = '1m' AND outcome_5c IS NOT NULL
        ORDER BY RANDOM()
        LIMIT 25
        """
    ).fetchall()
    for r in rows:
        t = float(r["ts_utc"])
        tkr = r["ticker"]
        b5 = float(forward_bar_start_utc(t, 5))
        row_bar = conn.execute(
            """
            SELECT bar_start_ts_utc, bar_end_ts_utc, close
            FROM price_bars_1m
            WHERE ticker = ? AND bar_start_ts_utc = ?
            """,
            (tkr, b5),
        ).fetchone()
        # Leakage if forward bar_end <= ts_utc (label uses bar that hasn't completed after T)
        if row_bar is None:
            leaks.append({"snapshot_id": r["snapshot_id"], "reason": "missing_forward_bar_row", "ticker": tkr})
            continue
        be = float(row_bar["bar_end_ts_utc"])
        if be <= t:
            leaks.append(
                {
                    "snapshot_id": r["snapshot_id"],
                    "reason": "forward_bar_end_not_after_ts",
                    "ts_utc": t,
                    "bar_end": be,
                }
            )
    out["leakage_samples_checked"] = len(rows)
    out["leakage_violations"] = leaks

    # --- STEP 7 chain: 15 rows with anchor + 5c forward ---
    chain = []
    rows2 = conn.execute(
        """
        SELECT snapshot_id, ticker, ts_utc, outcome_1c, outcome_5c, outcome_60c
        FROM snapshots
        WHERE timeframe = '1m' AND outcome_5c IS NOT NULL
        ORDER BY RANDOM()
        LIMIT 15
        """
    ).fetchall()
    for r in rows2:
        t = float(r["ts_utc"])
        tkr = r["ticker"]
        anch = conn.execute(
            """
            SELECT bar_end_ts_utc, close
            FROM price_bars_1m
            WHERE ticker = ? AND bar_end_ts_utc <= ?
            ORDER BY bar_end_ts_utc DESC
            LIMIT 1
            """,
            (tkr, t),
        ).fetchone()
        b5s = float(forward_bar_start_utc(t, 5))
        fwd = conn.execute(
            """
            SELECT bar_start_ts_utc, bar_end_ts_utc, close
            FROM price_bars_1m WHERE ticker = ? AND bar_start_ts_utc = ?
            """,
            (tkr, b5s),
        ).fetchone()
        chain.append(
            {
                "snapshot_id": int(r["snapshot_id"]),
                "ticker": tkr,
                "ts_utc": t,
                "anchor_bar_end": float(anch["bar_end_ts_utc"]) if anch else None,
                "anchor_close": float(anch["close"]) if anch else None,
                "forward_5c_bar_start": b5s,
                "forward_5c_close": float(fwd["close"]) if fwd else None,
                "outcome_5c": r["outcome_5c"],
            }
        )
    out["chain_samples"] = chain

    conn.close()
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
