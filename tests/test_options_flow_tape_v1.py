"""app.options.order_flow.history.tape_rows_for_symbol: the Options Flow tape, from the stored
LEVELONE_OPTIONS messages. Schwab sends a field only when it changes, so a row is a change of
the contract's merged last trade (time, price or size), at the trade's own time; no side."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.options.order_flow.history import tape_rows_for_symbol
from stream_spine import STREAM_SCHEMA_SQL

SYM = "SPY   260918C00600000"
_REAL = json.loads((Path(__file__).parent / "fixtures" / "real_option_l1_partial_trades.json")
                   .read_text(encoding="utf-8"))


def _write_ticks(path: Path, rows: list[tuple[float, dict]], symbol: str = SYM) -> None:
    con = sqlite3.connect(path)
    try:
        con.executescript(STREAM_SCHEMA_SQL)
        for ts_recv, content in rows:
            con.execute(
                "INSERT INTO stream_options_quotes_raw(ts_recv,symbol,native_json,src) "
                "VALUES(?,?,?,?)",
                (ts_recv, symbol, json.dumps(content), "schwab_options_l1"),
            )
        con.commit()
    finally:
        con.close()


def _full_context(**overrides) -> dict:
    base = {
        "key": SYM, "STRIKE_TYPE": 600, "CONTRACT_TYPE": "C",
        "EXPIRATION_YEAR": 2026, "EXPIRATION_MONTH": 9, "EXPIRATION_DAY": 18,
        "MULTIPLIER": 100, "UNDERLYING": "SPY",
    }
    base.update(overrides)
    return base


def test_a_trade_schwab_reports_by_its_changed_fields_alone_is_a_row(tmp_path):
    """2026-09-30 audit, on real messages (TSLA 260930C00380000, its subscription snapshot and
    the five messages after it, tests/fixtures/real_option_l1_partial_trades.json): the 5th
    carries a new trade time and LAST_SIZE with no LAST_PRICE, the 6th a new trade time alone.
    Both are trades at the price that stood (TOTAL_VOLUME moves 12 -> 13 -> 14), and both were
    dropped because a row required the price on the same message. The 3rd carries no LAST_SIZE:
    the size that stood is its size."""
    sym, msgs = _REAL["symbol"], _REAL["messages"]
    assert [sorted(k for k in ("TRADE_TIME_MILLIS", "LAST_PRICE", "LAST_SIZE") if k in m["native"])
            for m in msgs[2:]] == [["LAST_PRICE", "TRADE_TIME_MILLIS"],
                                   ["LAST_PRICE", "LAST_SIZE", "TRADE_TIME_MILLIS"],
                                   ["LAST_SIZE", "TRADE_TIME_MILLIS"], ["TRADE_TIME_MILLIS"]]
    db = tmp_path / "stream_capture.db"
    _write_ticks(db, [(m["ts_recv"], m["native"]) for m in msgs], symbol=sym)
    rows = tape_rows_for_symbol(sym, since_ts=0, db_path=db, limit=50)
    assert [(r["trade"], r["size"], r["volume"]) for r in rows] == [
        (0.25, 1, 14), (0.25, 1, 13), (0.25, 10, 12), (0.22, 1, 2), (0.25, 1, 0)]
    assert [r["premium"] for r in rows] == [25.0, 25.0, 250.0, 22.0, 25.0]
    # the contract, carried from the snapshot onto messages that do not repeat it
    assert {(r["symbol"], r["underlying"], r["expiry"], r["type"], r["strike"]) for r in rows} == {
        (sym, "TSLA", "2026-09-30", "CALL", 380.0)}
    # the quote as it stood at each row, Schwab's own
    assert (rows[0]["bid"], rows[0]["ask"]) == (0.2, 0.25) and (rows[3]["bid"], rows[3]["ask"]) == (0.16, 0.27)
    # no side and no position against the quote
    assert "classification" not in rows[0]


def test_a_row_is_timed_by_the_trade_not_by_when_the_message_arrived(tmp_path):
    """The snapshot Schwab sends on subscription reports the contract's last trade, here the
    prior session's: received Tue 09/29 07:28 AM CT, traded Mon 09/28 02:59:59 PM CT. The row
    showed the receive time as the trade's. Same real messages."""
    sym, msgs = _REAL["symbol"], _REAL["messages"]
    db = tmp_path / "stream_capture.db"
    _write_ticks(db, [(m["ts_recv"], m["native"]) for m in msgs], symbol=sym)
    rows = tape_rows_for_symbol(sym, since_ts=0, db_path=db, limit=50)
    snapshot = rows[-1]
    assert snapshot["trade_ts"] == msgs[0]["native"]["TRADE_TIME_MILLIS"] / 1000.0
    assert snapshot["ts_recv"] - snapshot["trade_ts"] > 16 * 3600
    assert snapshot["time"] == "Mon 09/28 02:59:59 PM CT"
    assert [r["time"] for r in rows[:4]] == ["Tue 09/29 08:30:04 AM CT", "Tue 09/29 08:30:03 AM CT",
                                             "Tue 09/29 08:30:02 AM CT", "Tue 09/29 08:30:00 AM CT"]


def test_a_re_emitted_duplicate_of_the_same_trade_is_not_counted_twice(tmp_path):
    """Schwab re-sends the SAME (TRADE_TIME_MILLIS, LAST_PRICE, LAST_SIZE) trade in a snapshot
    (a reconnect) -- this must collapse to ONE tape row. Stand-in (named): hand-built
    messages."""
    db = tmp_path / "stream_capture.db"
    tick = _full_context(TRADE_TIME_MILLIS=999000, LAST_PRICE=1.18, LAST_SIZE=1,
                         BID_PRICE=1.17, ASK_PRICE=1.19, TOTAL_VOLUME=70984)
    _write_ticks(db, [
        (1000.0, tick),
        (1005.0, dict(tick, DELTA=0.360)),   # same trade, only a Greek changed
        (1010.0, dict(tick, VOLATILITY=7.2)),
    ])
    rows = tape_rows_for_symbol(SYM, since_ts=0, db_path=db, limit=50)
    assert len(rows) == 1


def test_newest_first_ordering_and_limit_bound(tmp_path):
    db = tmp_path / "stream_capture.db"
    _write_ticks(db, [
        (float(1000 + i), _full_context(TRADE_TIME_MILLIS=1000 + i, LAST_PRICE=1.0 + i * 0.01, LAST_SIZE=1,
                                        BID_PRICE=1.0, ASK_PRICE=2.0))
        for i in range(5)
    ])
    rows = tape_rows_for_symbol(SYM, since_ts=0, db_path=db, limit=3)
    assert len(rows) == 3
    assert [r["ts_recv"] for r in rows] == sorted((r["ts_recv"] for r in rows), reverse=True)
    assert rows[0]["trade"] == 1.04   # the LAST (newest) genuine trade written


def test_fails_closed_to_empty_when_the_db_file_does_not_exist(tmp_path):
    assert tape_rows_for_symbol(SYM, since_ts=0, db_path=tmp_path / "no_such.db", limit=50) == []


def test_fails_closed_to_empty_for_a_blank_symbol():
    assert tape_rows_for_symbol("", since_ts=0, db_path="anything.db", limit=50) == []
