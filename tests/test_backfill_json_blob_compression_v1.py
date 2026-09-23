"""tools/backfill_json_blob_compression_v1.py — proves the backfill actually compresses
legacy plain-JSON rows in place, is idempotent, is resumable across batches, and never
corrupts an already-compressed row it re-scans."""
from __future__ import annotations

import json
import sqlite3

from json_blob_codec import decode_json_blob, is_compressed_blob
from tools.backfill_json_blob_compression_v1 import backfill_table_column

_SQL_CREATE = """
CREATE TABLE t (
    ticker TEXT NOT NULL,
    ts_utc REAL NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (ticker, ts_utc)
)
"""


def _make_db(tmp_path, rows: list[tuple[str, float, object]]) -> "str":
    db_path = tmp_path / "t.db"
    con = sqlite3.connect(str(db_path))
    con.execute(_SQL_CREATE)
    for ticker, ts, obj in rows:
        con.execute(
            "INSERT INTO t (ticker, ts_utc, payload_json) VALUES (?,?,?)",
            (ticker, ts, json.dumps(obj)),
        )
    con.commit()
    con.close()
    return str(db_path)


def _read_all(db_path: str) -> list[tuple]:
    con = sqlite3.connect(db_path)
    try:
        return con.execute("SELECT ticker, ts_utc, payload_json FROM t ORDER BY ts_utc").fetchall()
    finally:
        con.close()


def test_dry_run_reports_but_does_not_modify_rows(tmp_path):
    db_path = _make_db(tmp_path, [("SPY", 1.0, {"a": 1}), ("SPY", 2.0, {"b": 2})])
    result = backfill_table_column(
        db_path, table="t", blob_column="payload_json", key_columns=["ticker", "ts_utc"],
        dry_run=True,
    )
    assert result["rows_scanned"] == 2
    assert result["rows_compressed"] == 2
    rows = _read_all(db_path)
    assert all(not is_compressed_blob(r[2]) for r in rows), "dry-run must not write anything"


def test_execute_actually_compresses_every_row(tmp_path):
    db_path = _make_db(tmp_path, [("SPY", 1.0, {"a": 1}), ("QQQ", 2.0, {"b": [1, 2, 3]})])
    result = backfill_table_column(
        db_path, table="t", blob_column="payload_json", key_columns=["ticker", "ts_utc"],
        dry_run=False,
    )
    assert result["rows_compressed"] == 2
    rows = _read_all(db_path)
    assert all(is_compressed_blob(r[2]) for r in rows)
    # Content survives the round trip exactly.
    by_ticker = {r[0]: decode_json_blob(r[2]) for r in rows}
    assert by_ticker["SPY"] == {"a": 1}
    assert by_ticker["QQQ"] == {"b": [1, 2, 3]}


def test_second_run_is_a_no_op_idempotent(tmp_path):
    db_path = _make_db(tmp_path, [("SPY", 1.0, {"a": 1})])
    backfill_table_column(db_path, table="t", blob_column="payload_json",
                           key_columns=["ticker", "ts_utc"], dry_run=False)
    second = backfill_table_column(db_path, table="t", blob_column="payload_json",
                                    key_columns=["ticker", "ts_utc"], dry_run=False)
    assert second["rows_scanned"] == 1
    assert second["rows_compressed"] == 0, "already-compressed row must be skipped, not re-touched"


def test_mixed_compressed_and_plain_rows_only_touches_the_plain_ones(tmp_path):
    db_path = _make_db(tmp_path, [("A", 1.0, {"x": 1}), ("B", 2.0, {"y": 2}), ("C", 3.0, {"z": 3})])
    # Pre-compress row B by hand, simulating a mixed-state live table mid-backfill.
    from json_blob_codec import encode_json_blob
    con = sqlite3.connect(db_path)
    con.execute("UPDATE t SET payload_json=? WHERE ticker='B'", (encode_json_blob({"y": 2}),))
    con.commit()
    con.close()

    result = backfill_table_column(db_path, table="t", blob_column="payload_json",
                                    key_columns=["ticker", "ts_utc"], dry_run=False)
    assert result["rows_scanned"] == 3
    assert result["rows_compressed"] == 2   # A and C only
    rows = _read_all(db_path)
    assert all(is_compressed_blob(r[2]) for r in rows)


def test_batches_smaller_than_row_count_still_cover_every_row(tmp_path):
    rows_in = [(f"T{i}", float(i), {"n": i}) for i in range(25)]
    db_path = _make_db(tmp_path, rows_in)
    result = backfill_table_column(
        db_path, table="t", blob_column="payload_json", key_columns=["ticker", "ts_utc"],
        batch_size=7, dry_run=False,
    )
    assert result["batches_run"] == 4   # ceil(25/7)
    assert result["rows_scanned"] == 25
    assert result["rows_compressed"] == 25
    rows = _read_all(db_path)
    assert len(rows) == 25
    assert all(is_compressed_blob(r[2]) for r in rows)
    assert {decode_json_blob(r[2])["n"] for r in rows} == set(range(25))


def test_bytes_before_and_after_reflect_real_compression_ratio(tmp_path):
    big_repetitive = {"strikes": [{"strike": 500 + i, "oi": 100} for i in range(200)]}
    db_path = _make_db(tmp_path, [("SPY", 1.0, big_repetitive)])
    result = backfill_table_column(db_path, table="t", blob_column="payload_json",
                                    key_columns=["ticker", "ts_utc"], dry_run=False)
    assert result["bytes_after"] < result["bytes_before"]
    assert result["bytes_before"] / result["bytes_after"] > 2.0
