"""
Issue 14 — per-horizon training eligibility independent of outcome_filled / other horizons.

Root cause was: ml_data_common.outcome_where_clause required outcome_filled=1, while db.fill_outcomes
only sets outcome_filled=1 when ALL OUTCOME_BAR_SPECS columns are populated — excluding rows that
already have valid outcome_1c (or 5c, etc.) before longer horizons have filled.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))






def test_row_counts_decoupled_sql_evidence():
    """Rows with partial backfill: outcome_1c set, outcome_filled=0 → included in new training filter only."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE snapshots_1m_normalized (
            ticker TEXT, timeframe TEXT, ts_utc REAL, ts_et TEXT,
            et_hour INTEGER, et_minute INTEGER,
            outcome_filled INTEGER,
            outcome_1c TEXT, outcome_5c TEXT, outcome_15c TEXT, outcome_60c TEXT
        )
        """
    )
    rows = [
        ("SPY", "1m", 1.0, "2026-01-02 10:00:00 ET", 10, 0, 0, "up", None, None, None),
        ("SPY", "1m", 2.0, "2026-01-02 10:01:00 ET", 10, 1, 0, "down", "up", None, None),
        ("SPY", "1m", 3.0, "2026-01-02 10:02:00 ET", 10, 2, 1, "flat", "flat", "up", "down"),
    ]
    conn.executemany(
        "INSERT INTO snapshots_1m_normalized VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    old_cnt = conn.execute(
        "SELECT COUNT(*) FROM snapshots_1m_normalized WHERE outcome_filled = 1 AND outcome_1c IS NOT NULL"
    ).fetchone()[0]
    new_1c = conn.execute(
        "SELECT COUNT(*) FROM snapshots_1m_normalized WHERE outcome_1c IS NOT NULL"
    ).fetchone()[0]
    new_5c = conn.execute(
        "SELECT COUNT(*) FROM snapshots_1m_normalized WHERE outcome_5c IS NOT NULL"
    ).fetchone()[0]
    conn.close()

    assert old_cnt == 1, "legacy filter should see only fully backfilled row"
    assert new_1c == 3, "1c training should use every row with outcome_1c"
    assert new_5c == 2, "5c training should use rows with outcome_5c only (subset)"








# ── D2 dual-label research registry locks (2026-07-06) ───────────────────────




# ── D2 matrix runner + scratch normalized-carry locks (2026-07-06) ───────────




