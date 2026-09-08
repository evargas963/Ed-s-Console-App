"""Hermetic contracts for pred_1c persistence and the legacy audit wiring."""

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


def test_phase5_audit_module_defines_governed_pred_1c_metric() -> None:
    source = (
        ROOT / "tools" / "legacy" / "horizon_7" / "_phase5_discrimination_audit_v1.py"
    ).read_text(encoding="utf-8")
    assert '"governed_rows_with_pred_1c_nonnull": n_gov_pred1c,' in source
    assert "s.pred_1c_up_prob IS NOT NULL" in source
