"""STREAM-DB-SWITCH's one-time copy (tools/stream_db_switch_copy.py): from a file made the way production's
stream_capture.db was (its quote, book and option tables indexed by symbol, not by receipt time), a new file
with the writer's schema and receipt-time indexes holding the newest five sessions: every equity row, and
of the option quotes and option books only each day's 0DTE contracts (a ticker with none that day: its
nearest expiration). The old file is not changed.

Real data: Schwab's /markets answers asked on 2026-10-07 (tests/fixtures/real_schwab_markets_2026_10_07.json,
in the old file's stream_markets_raw as the daemon records them) and the option chains the daemon captured
2026-10-07 (tests/real_chains.py: SPY with a same-day expiration, MRVL with none). STAND-INS: the messages'
contents (only their table, symbol and receipt time are what this proves).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from stream_spine import RECEIPT_TIME_INDEXES, CaptureWriter
from tests.real_chains import MRVL, SPY_0DTE
from time_et import ET
from tools.stream_db_switch_copy import copy

MARKETS = Path(__file__).parent / "fixtures" / "real_schwab_markets_2026_10_07.json"
#: production's file: its three big tables indexed by symbol and time (PRAGMA index_list on it)
SYMBOL_INDEXES = ("CREATE INDEX idx_sqr_sym_ts ON stream_quotes_raw(symbol, ts_recv)",
                  "CREATE INDEX idx_sbkr_sym_ts ON stream_book_raw(symbol, ts_recv)",
                  "CREATE INDEX idx_soqr_sym_ts ON stream_options_quotes_raw(symbol, ts_recv)")


def _et(text: str) -> float:
    return datetime.fromisoformat(text).replace(tzinfo=ET).timestamp()


def _old_file(path: Path) -> "dict[str, list[str]]":
    """The old file and the option symbols written to it on 2026-10-07, by kind."""
    CaptureWriter(path)
    spy_today = sorted({c["symbol"] for c in SPY_0DTE.chain if c["expirationDate"].startswith("2026-10-07")})
    spy_later = sorted({c["symbol"] for c in SPY_0DTE.chain if not c["expirationDate"].startswith("2026-10-07")})
    mrvl_near = sorted({c["symbol"] for c in MRVL.chain if c["expirationDate"].startswith("2026-10-09")})
    mrvl_later = sorted({c["symbol"] for c in MRVL.chain if c["expirationDate"][:10] > "2026-10-09"})
    with sqlite3.connect(path) as conn:
        for index in RECEIPT_TIME_INDEXES:
            conn.execute(f"DROP INDEX {RECEIPT_TIME_INDEXES[index].split()[2]}")
        for sql in SYMBOL_INDEXES:
            conn.execute(sql)
        for day, a in json.loads(MARKETS.read_text(encoding="utf-8"))["answers"].items():
            conn.execute("INSERT INTO stream_markets_raw(ts_recv,date,status,native_json,src) VALUES(?,?,?,?,?)",
                         (_et("2026-10-07 08:00"), day, a["status"], a["body"], "schwab_markets"))
        for when in ("2026-09-29 12:00", "2026-10-07 12:00"):
            conn.execute("INSERT INTO stream_quotes_raw(ts_recv,symbol,last,src,native_json) VALUES(?,?,?,?,?)",
                         (_et(when), "SPY", 776.61, "schwab_l1", '{"key":"SPY"}'))
            for service in ("NYSE_BOOK", "OPTIONS_BOOK"):
                symbol = "SPY" if service == "NYSE_BOOK" else spy_today[0]
                conn.execute("INSERT INTO stream_book_raw(ts_recv,symbol,service,native_json,src) VALUES(?,?,?,?,?)",
                             (_et(when), symbol, service, "{}", "schwab_book"))
        for i, symbol in enumerate(spy_today + spy_later + mrvl_near + mrvl_later):
            for when in ("2026-09-29 12:00", "2026-10-07 12:00"):
                conn.execute("INSERT INTO stream_options_quotes_raw(ts_recv,symbol,native_json,src) VALUES(?,?,?,?)",
                             (_et(when) + i / 1000, symbol, "{}", "schwab_options_l1"))
        conn.execute("INSERT INTO stream_book_raw(ts_recv,symbol,service,native_json,src) VALUES(?,?,?,?,?)",
                     (_et("2026-10-07 12:30"), mrvl_later[0], "OPTIONS_BOOK", "{}", "schwab_book"))
        for when in ("2026-09-28 12:00", "2026-09-29 12:00"):              # both before; the newest stays
            conn.execute("INSERT INTO stream_watchlist(ts_recv,symbol,op,tickers_json,status,native_json,src) "
                         "VALUES(?,?,?,?,?,?,?)", (_et(when), "SPY", "added", '["SPY"]', None, None, "daemon_watchlist"))
    return {"spy_today": spy_today, "spy_later": spy_later, "mrvl_near": mrvl_near, "mrvl_later": mrvl_later}


def _rows(path: Path, sql: str) -> list:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        return conn.execute(sql).fetchall()


def test_the_new_file_holds_five_sessions_and_each_days_0dte_contracts(tmp_path):
    """2026-10-07 17:00 ET: Schwab's /markets says the newest five sessions began 2026-10-01 00:00 ET. The new
    file holds every equity row received since then, SPY's contracts expiring 10-07 and MRVL's expiring
    10-09 (it lists none on 10-07), nothing received before 10-01 but the newest watchlist row, and the
    writer's receipt-time indexes; the old file is as it was."""
    old, new = tmp_path / "old.db", tmp_path / "new.db"
    sym = _old_file(old)
    before = {t: _rows(old, f"SELECT COUNT(*) FROM {t}")[0][0]
              for t in ("stream_quotes_raw", "stream_book_raw", "stream_options_quotes_raw", "stream_watchlist")}
    counts = copy(old, new, datetime(2026, 10, 7, 17, 0, tzinfo=ET))

    assert {s for (s,) in _rows(new, "SELECT symbol FROM stream_options_quotes_raw")} == \
        set(sym["spy_today"]) | set(sym["mrvl_near"])
    assert min(t for (t,) in _rows(new, "SELECT ts_recv FROM stream_options_quotes_raw")) >= _et("2026-10-01 00:00")
    assert _rows(new, "SELECT symbol, service FROM stream_book_raw ORDER BY rowid") == \
        [("SPY", "NYSE_BOOK"), (sym["spy_today"][0], "OPTIONS_BOOK")]
    assert _rows(new, "SELECT COUNT(*) FROM stream_quotes_raw") == [(1,)]
    assert [datetime.fromtimestamp(t, ET).strftime("%m-%d") for (t,) in _rows(new, "SELECT ts_recv FROM stream_watchlist")] \
        == ["09-29"]
    indexes = {r[1] for t in RECEIPT_TIME_INDEXES for r in _rows(new, f"PRAGMA index_list({t})")}
    assert indexes >= {sql.split()[2] for sql in RECEIPT_TIME_INDEXES.values()}
    assert counts["stream_options_quotes_raw"]["2026-10-07"] == \
        (len(sym["spy_today"] + sym["spy_later"] + sym["mrvl_near"] + sym["mrvl_later"]),
         len(sym["spy_today"] + sym["mrvl_near"]))
    assert {t: _rows(old, f"SELECT COUNT(*) FROM {t}")[0][0] for t in before} == before


def test_the_copy_never_writes_over_a_file(tmp_path):
    """The new file must not exist: the copy writes a new file only."""
    old, new = tmp_path / "old.db", tmp_path / "new.db"
    _old_file(old)
    new.write_bytes(b"")
    try:
        copy(old, new, datetime(2026, 10, 7, 17, 0, tzinfo=ET))
    except SystemExit as e:
        assert "exists" in str(e)
    else:
        raise AssertionError("the copy wrote over an existing file")
    assert new.read_bytes() == b""
