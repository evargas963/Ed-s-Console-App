"""
No-fallback lock repair (2026-09-17, FB-01105 + 3 JSON-registry siblings unreachable by the
discovery scanner): tools/repair_validation_counts_v1.py's diagnostic counts used SQL-level
default-on-NULL comparisons for outcome_filled and horizon_outcome_schema_version throughout,
including a whole third comparison line explicitly labeled by that shape whose value was always
mathematically just the sum of the two bare-comparison lines above it (outcome_filled IS NULL
and outcome_filled = 0 are disjoint). Simplified every query to a bare comparison and derived
the redundant comparison line in Python instead of issuing a fourth SQL-level default-on-NULL
query.
"""
from __future__ import annotations

import sqlite3
import sys

from db import EdDB, configure_sqlite_connection
from horizon_outcomes import HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1


def test_no_coalesce_left_in_source():
    import inspect

    from tools import repair_validation_counts_v1 as mod

    src = inspect.getsource(mod)
    assert "COALESCE" not in src


def test_main_runs_end_to_end_against_real_db_and_prints_derived_sum(
    tmp_path, monkeypatch, capsys
):
    db_path = tmp_path / "rvc.db"
    _ = EdDB(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    conn.execute(
        """
        INSERT INTO snapshots (
            ticker, timeframe, ts_utc, ts_et, spot, zone,
            horizon_outcome_schema_version, outcome_filled, outcome_1c
        )
        VALUES ('SPY', '1m', 1_900_000_100.0, 'et', 100.0, 'pin_neutral', ?, 0, NULL)
        """,
        (HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,),
    )
    conn.commit()
    conn.close()

    from tools import repair_validation_counts_v1 as mod

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "repair_validation_counts_v1.py",
            "--db",
            str(db_path),
            "--allow-noncanonical-db",
        ],
    )
    mod.main()
    out = capsys.readouterr().out
    assert "pin_neutral outcome_filled IS NULL: 0" in out
    assert "pin_neutral outcome_filled = 0: 1" in out
    assert "pin_neutral outcome_filled unrecorded-or-zero (IS NULL + =0): 1" in out
