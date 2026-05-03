"""Pilot step 3 data loader: canonical vs staging table paths."""

from __future__ import annotations

import sqlite3

import pytest

from research.pilot_step3.data_loader import (
    SOURCE_TABLE_CANONICAL,
    SOURCE_TABLE_STAGING,
    load_spy_1m_bars,
)


def _mk_staging_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE price_bars_1m_staging (
            batch_id TEXT NOT NULL,
            ticker TEXT NOT NULL,
            bar_start_ts_utc REAL NOT NULL,
            bar_end_ts_utc REAL NOT NULL,
            open REAL, high REAL, low REAL, close REAL NOT NULL,
            volume REAL, source TEXT NOT NULL,
            ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (batch_id, ticker, bar_start_ts_utc)
        );
        """
    )


def test_load_staging_requires_batch_id(tmp_path) -> None:
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    _mk_staging_schema(conn)
    conn.close()
    with pytest.raises(ValueError, match="batch_id is required"):
        load_spy_1m_bars(str(db), ticker="SPY", source_table=SOURCE_TABLE_STAGING, batch_id=None)
    with pytest.raises(ValueError, match="batch_id is required"):
        load_spy_1m_bars(str(db), ticker="SPY", source_table=SOURCE_TABLE_STAGING, batch_id="   ")


def test_load_staging_filters_batch_and_ticker(tmp_path) -> None:
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    _mk_staging_schema(conn)
    conn.execute(
        """
        INSERT INTO price_bars_1m_staging
        (batch_id, ticker, bar_start_ts_utc, bar_end_ts_utc, open, high, low, close, volume, source)
        VALUES
        ('b1', 'SPY', 1000.0, 1060.0, 1, 2, 0.5, 1.5, 100, 't'),
        ('b1', 'SPY', 1060.0, 1120.0, 1.5, 2, 1, 1.8, 110, 't'),
        ('b2', 'SPY', 1000.0, 1060.0, 9, 9, 9, 9, 9, 't'),
        ('b1', 'QQQ', 1000.0, 1060.0, 9, 9, 9, 9, 9, 't')
        """
    )
    conn.commit()
    conn.close()

    rep = load_spy_1m_bars(str(db), ticker="SPY", source_table=SOURCE_TABLE_STAGING, batch_id="b1", require_rth_only=False)
    assert rep.staging_mode is True
    assert rep.source_table == SOURCE_TABLE_STAGING
    assert rep.batch_id == "b1"
    assert len(rep.bars) == 2
    assert rep.n_rows == 2


def test_load_canonical_default_source_table(tmp_path) -> None:
    db = tmp_path / "t.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE price_bars_1m (
            ticker TEXT NOT NULL,
            bar_start_ts_utc REAL NOT NULL,
            bar_end_ts_utc REAL NOT NULL,
            open REAL, high REAL, low REAL, close REAL NOT NULL,
            volume REAL, source TEXT,
            PRIMARY KEY (ticker, bar_start_ts_utc)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO price_bars_1m
        (ticker, bar_start_ts_utc, bar_end_ts_utc, open, high, low, close, volume, source)
        VALUES ('SPY', 1000.0, 1060.0, 1, 2, 0.5, 1.5, 100, 'x')
        """
    )
    conn.commit()
    conn.close()

    rep = load_spy_1m_bars(str(db), ticker="SPY", require_rth_only=False)
    assert rep.staging_mode is False
    assert rep.source_table == SOURCE_TABLE_CANONICAL
    assert rep.batch_id is None
    assert len(rep.bars) == 1
