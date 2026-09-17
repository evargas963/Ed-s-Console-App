"""Hermetic contracts for pred_1c persistence.

No-fallback lock repair (2026-09-17, operator point 12, "prove zero ... test
references" for the tools/legacy/horizon_7/ deletion): this file used to also pin
tools/legacy/horizon_7/_phase5_discrimination_audit_v1.py's source text (a deprecated,
"DEPRECATED -- 7-horizon era... do not run against post-D3 databases" module that was
deleted along with the rest of that directory). That test was never updated when the
directory was deleted, so it had been failing with FileNotFoundError ever since --
found only now because point 12 required actually running the tests that reference the
deletion, rather than trusting a prior "zero references" claim. Confirmed via repo-wide
grep that `governed_rows_with_pred_1c_nonnull` and the audited query shape have no
other definition or consumer anywhere in the current codebase (the deprecated metric
was genuinely retired, not relocated), so the test was deleted rather than repointed --
there is nothing left to test it against. This file's real schema-contract test
(unaffected, was passing throughout) is unchanged below.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def test_snapshots_table_accepts_pred_1c_triple_minimal_insert(tmp_path: Path) -> None:
    from db import EdDB

    db = EdDB(tmp_path / "p1c.db", allow_noncanonical=True)
    with db._connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
              ticker, timeframe, ts_utc, ts_et, spot, zone, vwap_side,
              pred_1c_up_prob, pred_1c_down_prob, pred_1c_flat_prob,
              horizon_outcome_schema_version
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            ("SPY", "1m", 1_777_000_000.0, "test_et", 500.0, "pin_neutral",
             "above", 0.31, 0.41, 0.28, 3),
        )
        snapshot_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        row = conn.execute(
            "SELECT pred_1c_up_prob, pred_1c_down_prob, pred_1c_flat_prob "
            "FROM snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
    assert row is not None
    assert tuple(row) == pytest.approx((0.31, 0.41, 0.28))
