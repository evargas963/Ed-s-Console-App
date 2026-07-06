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



# ── D2 dual-label research registry locks (2026-07-06) ───────────────────────


def test_tb_research_labels_registered_additively_only():
    """D2 (operator-approved): outcome_tb_{hz} label columns are accepted by the
    training loaders for SCRATCH-DB research runs — additively. Production
    defaults and the production outcome writer must be untouched:
      - DEFAULT_TRAINING_LABEL_COLUMN stays outcome_1c
      - OUTCOME_BAR_SPECS (production writer) carries no TB columns
      - TB registry is exactly the four research columns
    """
    from horizon_outcomes import OUTCOME_BAR_SPECS, TB_RESEARCH_LABEL_COLUMNS
    from ml_data_common import training_label_where_clause
    from ml_horizon import DEFAULT_TRAINING_LABEL_COLUMN

    assert DEFAULT_TRAINING_LABEL_COLUMN == "outcome_1c", (
        "production default training label changed — D2 must be additive-only"
    )
    assert TB_RESEARCH_LABEL_COLUMNS == {
        "outcome_tb_1c": 1, "outcome_tb_5c": 5,
        "outcome_tb_15c": 15, "outcome_tb_60c": 60,
    }
    for col in TB_RESEARCH_LABEL_COLUMNS:
        assert training_label_where_clause(col) == f"{col} IS NOT NULL"
    writer_cols = {s[0] for s in OUTCOME_BAR_SPECS} | {s[1] for s in OUTCOME_BAR_SPECS}
    assert not any("tb" in c.split("_") for c in writer_cols), (
        "TB columns leaked into the production outcome writer specs"
    )


def test_tb_label_core_policies():
    """D2 generator core (pure function): PT/SL touch, ambiguous close-side with
    tag, vertical flat, and session-truncation flag — the approved policies."""
    from tools.research.d2_build_dual_label_scratch_db import tb_label_for_window

    bars_up = [(1.0, 105.0, 99.5, 104.0)]
    assert tb_label_for_window(100.0, bars_up, 2.0, 5) == ("up", "pt_up", 0)
    bars_dn = [(1.0, 100.4, 95.0, 96.0)]
    assert tb_label_for_window(100.0, bars_dn, 2.0, 5) == ("down", "sl_down", 0)
    # ambiguous: both barriers inside one bar -> close side + 'ambiguous'
    bars_amb_up = [(1.0, 103.0, 97.0, 101.0)]
    assert tb_label_for_window(100.0, bars_amb_up, 2.0, 5) == ("up", "ambiguous", 0)
    bars_amb_dn = [(1.0, 103.0, 97.0, 99.0)]
    assert tb_label_for_window(100.0, bars_amb_dn, 2.0, 5) == ("down", "ambiguous", 0)
    # vertical: full window, no touch -> flat, not truncated
    quiet = [(float(i), 100.5, 99.5, 100.1) for i in range(5)]
    assert tb_label_for_window(100.0, quiet, 2.0, 5) == ("flat", "vertical", 0)
    # truncated: session cut the window short with no touch -> flat + truncated flag
    short = quiet[:3]
    assert tb_label_for_window(100.0, short, 2.0, 5) == ("flat", "vertical_truncated", 1)
    # first-touch order: barrier hit in bar 2 wins over later bars
    seq = [(1.0, 100.5, 99.5, 100.2), (2.0, 102.5, 99.8, 102.2), (3.0, 100.0, 95.0, 96.0)]
    assert tb_label_for_window(100.0, seq, 2.0, 5) == ("up", "pt_up", 0)


def test_d2_builder_opens_production_read_only():
    """The scratch builder must open the source DB via sqlite URI mode=ro —
    production mutation impossible by construction."""
    src = (ROOT / "tools" / "research" / "d2_build_dual_label_scratch_db.py").read_text(
        encoding="utf-8"
    )
    assert "?mode=ro" in src and "uri=True" in src, (
        "d2 scratch builder no longer opens the production DB read-only"
    )
