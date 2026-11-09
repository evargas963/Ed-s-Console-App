"""db.inventory: what the census counts in each database, read without writing, from databases the
Recorder itself made (CaptureWriter's schema, EdDB's schema and its write of a captured SPY print's
level cross).
"""

from __future__ import annotations

import re

import pytest

from db import ColumnInventory, EdDB, LevelCrossEvent, inventory
from stream_spine import RECEIPT_TIME_INDEXES, STREAM_SCHEMA_SQL, CaptureWriter
from terrain_read import CROSSED_UP
from tests.real_chains import SPY_PRINT_A_STRIKE_AWAY

CREATED = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+) \(", STREAM_SCHEMA_SQL)


def _block(table: str) -> str:
    return STREAM_SCHEMA_SQL.split(f"CREATE TABLE IF NOT EXISTS {table} (", 1)[1].split(");", 1)[0]


def test_every_stream_table_the_writer_creates_is_counted_with_its_columns(tmp_path):
    path = tmp_path / "stream_capture.db"
    CaptureWriter(path)

    tables = {t.name: t for t in inventory(path)}

    assert set(tables) == set(CREATED)
    assert all(t.rows == 0 for t in tables.values())
    quotes = [c.name for c in tables["stream_quotes_raw"].columns]
    assert quotes[:13] == [
        "ts_recv",
        "symbol",
        "bid",
        "ask",
        "last",
        "bid_size",
        "ask_size",
        "last_size",
        "total_volume",
        "quote_time_ms",
        "trade_time_ms",
        "src",
        "native_json",
    ]
    assert "schwab_ts" in quotes  # added by the writer after the CREATE, still counted
    for table, index in RECEIPT_TIME_INDEXES.items():
        name = index.split()[2]
        assert name in tables[table].indexes
    assert [c.name for c in tables["stream_spill_progress"].columns] == [
        w.split()[0] for w in _block("stream_spill_progress").strip().split(",")
    ]


def test_a_console_row_is_counted_and_the_sqlite_clock_column_shows_its_default(tmp_path):
    path = tmp_path / "ed_console.db"
    edb = EdDB(path, allow_noncanonical=True)
    edb.record_level_crosses(
        [
            LevelCrossEvent(
                ticker="SPY",
                ts_utc=SPY_PRINT_A_STRIKE_AWAY["ts_recv"],
                ts_et="2026-10-22 16:39:03 ET",
                level_name="Call g-Wall",
                level_value=765.0,
                direction=CROSSED_UP,
                spot_at_cross=SPY_PRINT_A_STRIKE_AWAY["native"]["LAST_PRICE"],
                zone_before=None,
                zone_after=None,
                timeframe="1m",
            )
        ]
    )

    (crosses,) = [t for t in inventory(path) if t.name == "level_crosses"]

    assert crosses.rows == 1
    assert ColumnInventory("created_at", "datetime('now')") in crosses.columns
    assert ColumnInventory("ticker", None) in crosses.columns
    assert crosses.indexes == ("idx_cross_ticker_ts",)


def test_reading_writes_nothing_to_the_database(tmp_path):
    path = tmp_path / "stream_capture.db"
    CaptureWriter(path)
    before = path.read_bytes()

    inventory(path)

    assert path.read_bytes() == before
    assert (
        not path.with_name(path.name + "-wal").exists()
        or path.with_name(path.name + "-wal").stat().st_size == 0
    )


def test_a_database_that_is_not_there_raises_and_is_not_made(tmp_path):
    path = tmp_path / "not_there.db"

    with pytest.raises(Exception, match="unable to open database"):
        inventory(path)

    assert not path.exists()
