"""tools/apply_row_retention_v1.py — proves the FIFO cutoff logic is correct, dry-run
never writes, batching covers every eligible row, and the table allowlist genuinely
refuses snapshots/model_execution_identities (or any other table), not just by
convention."""
from __future__ import annotations

import sqlite3

import pytest

from tools.apply_row_retention_v1 import ALLOWED_TABLES, apply_retention

_NOW = 2_000_000.0
_DAY = 86400.0


def _make_db(tmp_path, table: str, rows: list[tuple]) -> str:
    db_path = tmp_path / "ret.db"
    con = sqlite3.connect(str(db_path))
    con.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY, ts_utc REAL NOT NULL)')
    con.executemany(f'INSERT INTO "{table}" (id, ts_utc) VALUES (?, ?)', rows)
    con.commit()
    con.close()
    return str(db_path)


def _count(db_path: str, table: str) -> int:
    con = sqlite3.connect(db_path)
    try:
        return con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    finally:
        con.close()


@pytest.mark.parametrize("table", sorted(ALLOWED_TABLES))
def test_dry_run_counts_old_rows_without_deleting(tmp_path, table):
    rows = [(1, _NOW - 40 * _DAY), (2, _NOW - 20 * _DAY), (3, _NOW - 1 * _DAY)]
    db_path = _make_db(tmp_path, table, rows)
    result = apply_retention(db_path, table=table, ts_column="ts_utc",
                              retention_days=30, now_ts=_NOW, dry_run=True)
    assert result["rows_affected"] == 1   # only row 1 (40 days old) is past a 30-day cutoff
    assert _count(db_path, table) == 3, "dry-run must not delete anything"


@pytest.mark.parametrize("table", sorted(ALLOWED_TABLES))
def test_execute_deletes_exactly_the_rows_past_the_cutoff(tmp_path, table):
    rows = [(1, _NOW - 40 * _DAY), (2, _NOW - 20 * _DAY), (3, _NOW - 1 * _DAY)]
    db_path = _make_db(tmp_path, table, rows)
    result = apply_retention(db_path, table=table, ts_column="ts_utc",
                              retention_days=30, now_ts=_NOW, dry_run=False)
    assert result["rows_affected"] == 1
    assert _count(db_path, table) == 2

    con = sqlite3.connect(db_path)
    try:
        remaining_ids = {r[0] for r in con.execute(f'SELECT id FROM "{table}"').fetchall()}
    finally:
        con.close()
    assert remaining_ids == {2, 3}


def test_batching_covers_every_eligible_row_across_multiple_batches(tmp_path):
    table = "complete_chain_captures"
    rows = [(i, _NOW - 40 * _DAY) for i in range(25)] + [(1000, _NOW - 1 * _DAY)]
    db_path = _make_db(tmp_path, table, rows)
    result = apply_retention(db_path, table=table, ts_column="ts_utc",
                              retention_days=30, now_ts=_NOW, batch_size=7, dry_run=False)
    assert result["rows_affected"] == 25
    assert result["batches_run"] == 4   # ceil(25/7)
    assert _count(db_path, table) == 1


def test_refuses_snapshots_even_if_caller_asks(tmp_path):
    db_path = _make_db(tmp_path, "snapshots", [(1, _NOW - 400 * _DAY)])
    with pytest.raises(ValueError, match="snapshots"):
        apply_retention(db_path, table="snapshots", ts_column="ts_utc",
                         retention_days=30, now_ts=_NOW, dry_run=False)
    assert _count(db_path, "snapshots") == 1, "refused table must be completely untouched"


def test_refuses_model_execution_identities_even_if_caller_asks(tmp_path):
    db_path = _make_db(tmp_path, "model_execution_identities", [(1, _NOW - 400 * _DAY)])
    with pytest.raises(ValueError, match="model_execution_identities"):
        apply_retention(db_path, table="model_execution_identities", ts_column="ts_utc",
                         retention_days=30, now_ts=_NOW, dry_run=False)


def test_refuses_an_arbitrary_unlisted_table(tmp_path):
    db_path = _make_db(tmp_path, "some_other_table", [(1, _NOW - 400 * _DAY)])
    with pytest.raises(ValueError):
        apply_retention(db_path, table="some_other_table", ts_column="ts_utc",
                         retention_days=30, now_ts=_NOW, dry_run=False)


def test_nothing_past_cutoff_is_a_clean_no_op(tmp_path):
    table = "production_decision_records"
    rows = [(1, _NOW - 1 * _DAY), (2, _NOW - 2 * _DAY)]
    db_path = _make_db(tmp_path, table, rows)
    result = apply_retention(db_path, table=table, ts_column="ts_utc",
                              retention_days=30, now_ts=_NOW, dry_run=False)
    assert result["rows_affected"] == 0
    assert _count(db_path, table) == 2
