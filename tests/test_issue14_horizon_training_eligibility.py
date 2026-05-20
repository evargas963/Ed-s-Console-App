"""
Issue 14 — per-horizon training eligibility independent of outcome_filled / other horizons.

Root cause was: ml_data_common.outcome_where_clause required outcome_filled=1, while db.fill_outcomes
only sets outcome_filled=1 when ALL OUTCOME_BAR_SPECS columns are populated — excluding rows that
already have valid outcome_1c (or 5c, etc.) while longer horizons are still pending.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))


def test_training_label_where_clause_per_horizon():
    from ml_data_common import training_label_where_clause, outcome_where_clause

    assert training_label_where_clause("outcome_1c") == "outcome_1c IS NOT NULL"
    assert training_label_where_clause("outcome_5c") == "outcome_5c IS NOT NULL"
    assert training_label_where_clause("outcome_15c") == "outcome_15c IS NOT NULL"
    assert training_label_where_clause("outcome_60c") == "outcome_60c IS NOT NULL"
    assert outcome_where_clause() == "outcome_1c IS NOT NULL"
    assert "outcome_filled" not in training_label_where_clause("outcome_1c").lower()
    assert "outcome_filled" not in outcome_where_clause().lower()


def test_training_label_unknown_column_raises():
    from ml_data_common import training_label_where_clause
    import pytest

    with pytest.raises(ValueError, match="unknown label"):
        training_label_where_clause("outcome_99c")


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


def test_ml_train_where_contract_matches_issue14():
    """load_data builds WHERE from training_label(TARGET_COL) — no outcome_filled."""
    from ml_train import TARGET_COL
    from ml_data_common import training_base_where_clause

    where = training_base_where_clause(TARGET_COL, include_ticker=False)
    assert "outcome_filled" not in where.lower()
    assert f"{TARGET_COL} IS NOT NULL" in where
    assert "et_hour" not in where


def test_lstm_sequence_source_rows_filtered_by_target_horizon_only():
    """LSTM sequence path: DB row gate = training_label(TARGET_HORIZON), same as per-sequence target key."""
    from lstm_data import TARGET_HORIZON
    from ml_data_common import training_label_where_clause

    frag = " AND " + training_label_where_clause(TARGET_HORIZON)
    assert frag.strip() == "AND outcome_1c IS NOT NULL"
    assert "outcome_filled" not in frag.lower()
    assert "outcome_5c" not in frag.lower()
    assert "outcome_15c" not in frag.lower()
    assert "outcome_60c" not in frag.lower()


def test_transformer_uses_same_lstm_extract_and_target():
    """Transformer sequences call extract_rth_snapshots with per-horizon label (no parallel completeness gate)."""
    import inspect

    import transformer_train

    src_prepare = inspect.getsource(transformer_train.prepare_transformer_data)
    assert "extract_rth_snapshots" in src_prepare
    assert "label_col" in src_prepare or "outcome_column" in src_prepare
    assert "target_column=" in src_prepare
    assert "outcome_filled" not in src_prepare

