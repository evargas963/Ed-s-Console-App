"""STREAM-DB-SWITCH's one-time copy (tools/stream_db_switch_copy.py): from a file made the way production's
stream_capture.db was (its quote, book and option tables indexed by symbol and time, not by receipt time
alone), a new file with the writer's schema and receipt-time indexes holding the newest five sessions: every
equity row, and of the option quotes and option books only each day's 0DTE contracts. The old file is not
changed, and a file already at the new path, or a spill file beside the old one, stops the copy.

Real data: three seconds of production's stream as stored (tests/fixtures/real_stream_mix_2026_10_05_1400ct.json:
2026-10-05 14:00:00-14:00:03 CT, every equity quote, book and SPY option quote, with their receipt and Schwab
times), written through the daemon's message builder and the writer's insert; Schwab's /markets answers asked
on 2026-10-07 (tests/fixtures/real_schwab_markets_2026_10_07.json, in the old file as the daemon records them).
STAND-INS: the receipt times of the two watchlist rows.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from app.market_data.schwab.streaming import capture
from stream_spine import RECEIPT_TIME_INDEXES, CaptureWriter
from time_et import ET
from tools.stream_db_switch_copy import copy

FIXTURES = Path(__file__).parent / "fixtures"
MIX = json.loads((FIXTURES / "real_stream_mix_2026_10_05_1400ct.json").read_text(encoding="utf-8"))["messages"]
MARKETS = json.loads((FIXTURES / "real_schwab_markets_2026_10_07.json").read_text(encoding="utf-8"))["answers"]
#: production's file: its three big tables indexed by symbol and time (PRAGMA index_list on it)
SYMBOL_INDEXES = ("CREATE INDEX idx_sqr_sym_ts ON stream_quotes_raw(symbol, ts_recv)",
                  "CREATE INDEX idx_sbkr_sym_ts ON stream_book_raw(symbol, ts_recv)",
                  "CREATE INDEX idx_soqr_sym_ts ON stream_options_quotes_raw(symbol, ts_recv)")
OPTIONS = ("LEVELONE_OPTIONS", "OPTIONS_BOOK")


def _et(text: str) -> float:
    return datetime.fromisoformat(text).replace(tzinfo=ET).timestamp()


def _old_file(path: Path) -> None:
    writer = CaptureWriter(path)
    with sqlite3.connect(path) as conn:
        for sql in RECEIPT_TIME_INDEXES.values():
            conn.execute(f"DROP INDEX {sql.split()[2]}")
        for sql in SYMBOL_INDEXES:
            conn.execute(sql)
        for day, a in MARKETS.items():
            conn.execute("INSERT INTO stream_markets_raw(ts_recv,date,status,native_json,src) VALUES(?,?,?,?,?)",
                         (_et("2026-10-05 08:00"), day, a["status"], a["body"], "schwab_markets"))
    with sqlite3.connect(path) as conn:
        for m in MIX:
            kind, msg = capture._message(m["service"], m["item"]["key"], m["item"], m["schwab_ts"])
            writer.insert(f"{kind}.{m['item']['key']}", {**msg, "ts_recv": m["ts_recv"]}, conn=conn)
        for when in ("2026-09-28 12:00", "2026-09-29 12:00"):
            topic, msg = capture.watchlist_message(["SPY"], op="added", ticker="SPY", request_id=when)
            writer.insert(topic, {**msg, "ts_recv": _et(when)}, conn=conn)


def _rows(path: Path, sql: str) -> list:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        return conn.execute(sql).fetchall()


def test_within_five_sessions_every_equity_row_and_that_days_0dte_contracts_are_copied(tmp_path):
    """2026-10-06 17:00 ET: Schwab's /markets says the newest five sessions began 2026-09-30. Every equity
    quote and equity book of 10-05's stream is copied, of the SPY option rows only those expiring 2026-10-05
    (each a 0DTE that day), of the watchlist rows (both before 09-30) only the newest, which the daemon
    reads at its start, and the new file has the writer's receipt-time indexes; the old file is as it was."""
    old, new = tmp_path / "old.db", tmp_path / "new.db"
    _old_file(old)
    before = {t: _rows(old, f"SELECT COUNT(*) FROM {t}") for t, _c in capture_tables()}
    counts = copy(old, new, datetime(2026, 10, 6, 17, 0, tzinfo=ET))

    zero_dte = {m["item"]["key"] for m in MIX if m["service"] in OPTIONS and m["item"]["key"][6:12] == "261005"}
    assert zero_dte, "the stream holds 10-05's 0DTE contracts"
    copied = {s for (s,) in _rows(new, "SELECT symbol FROM stream_options_quotes_raw")} | \
        {s for (s,) in _rows(new, "SELECT symbol FROM stream_book_raw WHERE service = 'OPTIONS_BOOK'")}
    assert copied == zero_dte
    equity = [m for m in MIX if m["service"] not in OPTIONS]
    assert _rows(new, "SELECT COUNT(*) FROM stream_quotes_raw")[0][0] + \
        _rows(new, "SELECT COUNT(*) FROM stream_book_raw WHERE service != 'OPTIONS_BOOK'")[0][0] == len(equity)
    assert [datetime.fromtimestamp(t, ET).strftime("%m-%d") for (t,) in _rows(new, "SELECT ts_recv FROM stream_watchlist")] \
        == ["09-29"]
    assert counts["stream_options_quotes_raw"]["2026-10-05"][0] == sum(m["service"] == "LEVELONE_OPTIONS" for m in MIX)
    indexes = {r[1] for t in RECEIPT_TIME_INDEXES for r in _rows(new, f"PRAGMA index_list({t})")}
    assert indexes >= {sql.split()[2] for sql in RECEIPT_TIME_INDEXES.values()}
    assert {t: _rows(old, f"SELECT COUNT(*) FROM {t}") for t, _c in capture_tables()} == before


def test_the_copy_never_writes_over_a_file_nor_runs_beside_a_spill(tmp_path):
    """A file at the new path, or a spill file beside the old one (messages the old file does not hold),
    stops the copy before anything is written."""
    old, new = tmp_path / "old.db", tmp_path / "new.db"
    _old_file(old)
    new.write_bytes(b"")
    for setup, word in ((lambda: None, "exists"),
                        (lambda: (new.unlink(), (tmp_path / "old.1.1.spill").write_bytes(b"")), "spill")):
        setup()
        try:
            copy(old, new, datetime(2026, 10, 6, 17, 0, tzinfo=ET))
        except SystemExit as e:
            assert word in str(e)
        else:
            raise AssertionError(f"the copy ran ({word})")
    assert not new.exists()


def capture_tables():
    from stream_spine import KEPT_BY_TIME
    return KEPT_BY_TIME
