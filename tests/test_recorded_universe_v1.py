"""The recorded universe as the capture daemon reads it at its start (capture.recorded_tickers):
the tickers Schwab's recorded instrument answers list, and every other ticker with data stored,
to be looked up; and the console's one copy of the universe, the daemon's heartbeat.

Real data: Schwab's SPY and TSLA 1-minute bars as the daemon recorded them
(tests/fixtures/real_daemon_bars_spy_tsla_2026_09_29_30.json), a captured TSLA option quote
(tests/fixtures/real_options_stream_history_samples.json), Schwab's CRWD chain
(tests/fixtures/real_crwd_complete_chain_quarter.json), Schwab's instrument answers of
2026-08-20 (tests/fixtures/real_schwab_instruments_2026_08_20.json: SPY's, which lists SPY, and
symbol-search's `{}` for `SPY.*`, which lists nothing) and one stored FINRA short-volume row
(ed_console.db world_finra_short_volume, 2026-07-15 AAPL, as stored). Stand-in, named: the
instrument answers are written for the symbols the test names (SPY's answer as SPY's; `{}` as
the answer for ZZZZ and, later, SPY)."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import live_market_plane as lmp
import server
from app.market_data.schwab.streaming import capture
from calibration.complete_chain_capture import CAPTURE_BASIS, persist_complete_chain_capture
from stream_spine import CaptureWriter, HealthRegistry, MessageBus, bar_msg, instrument_msg, options_quote_msg
from tests.feed_live_helper import daemon_bars

FX = Path(__file__).resolve().parent / "fixtures"
_OPT = json.loads((FX / "real_options_stream_history_samples.json").read_text(encoding="utf-8"))
_CRWD = json.loads((FX / "real_crwd_complete_chain_quarter.json").read_text(encoding="utf-8"))
_ANSWERS = json.loads((FX / "real_schwab_instruments_2026_08_20.json").read_text(encoding="utf-8"))["answers"]
_SPY_LISTED = _ANSWERS["spy_fundamental"]["body"]
_NONE_LISTED = _ANSWERS["symbol_search_spy_pattern"]["body"]


def _record_bars(writer: CaptureWriter, *symbols: str) -> None:
    with sqlite3.connect(writer.db_path) as con:
        for r in [r for s in symbols for r in daemon_bars("real_daemon_bars_spy_tsla_2026_09_29_30.json", s)[:3]]:
            writer.insert(f"bar1m.{r['symbol']}", bar_msg(
                symbol=r["symbol"], bar_start_ms=r["bar_start_ms"], open=r["open"], high=r["high"],
                low=r["low"], close=r["close"], volume=r["volume"], src=r["src"], ts_recv=r["ts_recv"],
                native=r["native"], schwab_ts=r["schwab_ts"]), conn=con)


def _record_answer(writer: CaptureWriter, symbol: str, body: str, listed: bool, ts: float) -> None:
    with sqlite3.connect(writer.db_path) as con:
        writer.insert(f"instrument.{symbol}", instrument_msg(symbol=symbol, http_status=200, body=body,
                                                             listed=listed, ts=ts), conn=con)


def test_the_console_and_the_daemon_hold_one_universe(tmp_path):
    """Stored in both databases: SPY and TSLA (bars), CRWD (the chain history). Only SPY has an
    instrument answer of Schwab's that lists it. Every stored ticker is in the universe -- its
    record goes on while its lookup is pending -- and the two not yet listed are put to
    Schwab's lookup. The console carries the daemon's universe from its heartbeat."""
    console_db, stream_db = tmp_path / "ed_console.db", tmp_path / "stream_capture.db"
    writer = CaptureWriter(stream_db)
    _record_bars(writer, "SPY", "TSLA")
    _record_answer(writer, "SPY", _SPY_LISTED, True, time.time())
    persist_complete_chain_capture(console_db, ticker="CRWD", expiry=_CRWD["expiry"], contracts=_CRWD["chain"],
                                   spot=_CRWD.get("spot"), completeness_basis=CAPTURE_BASIS, ts_utc=time.time())
    listed, unconfirmed = capture.recorded_tickers(console_db, stream_db)
    assert (listed, unconfirmed) == (["SPY"], ["CRWD", "TSLA"])
    d = capture.Daemon(MessageBus(), HealthRegistry())
    d.load(listed, unconfirmed)
    assert [d.joins.get_nowait() for _ in range(d.joins.qsize())] == ["CRWD", "TSLA"]
    lmp.record_feed_heartbeat(d.status())
    try:
        assert sorted(d.universe) == server._universe() == ["CRWD", "SPY", "TSLA"]
    finally:
        lmp.record_feed_down()


def test_schwabs_newest_answer_decides(tmp_path):
    """A ticker Schwab listed and, in a later answer, did not, is not listed: it is looked up
    again."""
    stream_db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(stream_db)
    _record_answer(writer, "SPY", _SPY_LISTED, True, 1.0)
    _record_answer(writer, "SPY", _NONE_LISTED, False, 2.0)
    assert capture.recorded_tickers(stream_db) == ([], ["SPY"])


def test_a_first_run_with_no_database_holds_no_ticker(tmp_path):
    """A database not created yet holds no ticker, and the daemon still starts."""
    assert capture.recorded_tickers(tmp_path / "not_created_yet.db", tmp_path / "nor_this.db") == ([], [])


def test_an_option_contract_and_a_world_table_are_not_tickers(tmp_path):
    """An option contract's symbol is a contract and a `world_` table is a public dataset from
    another source: neither is a ticker. A ticker Schwab did not list is stored data (its
    answer), to be asked again; the ticker under the contract's quotes is, where its own data
    is stored."""
    console_db, stream_db = tmp_path / "ed_console.db", tmp_path / "stream_capture.db"
    writer = CaptureWriter(stream_db)
    _record_bars(writer, "TSLA")
    _record_answer(writer, "ZZZZ", _NONE_LISTED, False, time.time())
    contract = _OPT["contracts"][0]
    event = next(e for e in contract["events"] if e["kind"] == "l1")
    with sqlite3.connect(stream_db) as con:
        writer.insert(f"optquote.{contract['symbol']}", options_quote_msg(
            symbol=contract["symbol"], content=event["content"], src="schwab_options_l1"), conn=con)
    with sqlite3.connect(console_db) as con:
        con.execute("CREATE TABLE world_finra_short_volume (date TEXT NOT NULL, symbol TEXT NOT NULL, "
                    "short_volume INTEGER, short_exempt_volume INTEGER, total_volume INTEGER, market TEXT, "
                    "fetched_at TEXT DEFAULT (datetime('now')), PRIMARY KEY (date, symbol))")
        con.execute("INSERT INTO world_finra_short_volume VALUES ('2026-07-15', 'AAPL', 12298806, 69012, "
                    "22885472, 'B,Q,N', '2026-07-21 13:02:27')")
    assert contract["symbol"].startswith("TSLA ")
    assert capture.recorded_tickers(console_db, stream_db) == ([], ["TSLA", "ZZZZ"])


def test_a_heartbeat_with_no_universe_is_an_unknown_universe_never_an_empty_one():
    """A heartbeat that carries no universe reads as unknown, never as an empty universe that
    would drop every ticker's levels."""
    lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True})
    try:
        assert server._universe() is None
    finally:
        lmp.record_feed_down()


def test_an_unknown_universe_is_said_so():
    """With the daemon's heartbeat late, the universe is unknown, never empty."""
    lmp.record_feed_down()
    assert "UNIVERSE UNKNOWN" in server._status_line()


def test_the_console_status_line_counts_live_prices_across_the_universe():
    """The console's status line counts every universe ticker's price row (an index, an ETF, a
    single name, an arbitrary one), never one ticker's. None of these has a price row here."""
    lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True,
                               "universe": ["$ZZQX", "ZZQQ", "ZZMU", "ZZQX"]})
    try:
        assert "live prices: 0 of 4 universe tickers" in server._status_line()
    finally:
        lmp.record_feed_down()


def test_a_heartbeat_whose_universe_changed_wakes_the_console():
    """The console's levels loop waits on live_market_plane.universe_changed: set by the first
    heartbeat, by one after a silence and by one whose universe changed; not by a repeat."""
    lmp.record_feed_down()
    lmp.universe_changed.clear()
    now = time.time()
    lmp.record_feed_heartbeat({"ts": now, "schwab_socket_open": True, "universe": ["SPY"]})
    assert lmp.universe_changed.is_set()
    lmp.universe_changed.clear()
    lmp.record_feed_heartbeat({"ts": now + 1, "schwab_socket_open": True, "universe": ["SPY"]})
    assert not lmp.universe_changed.is_set()
    lmp.record_feed_heartbeat({"ts": now + 2, "schwab_socket_open": True, "universe": ["QQQ", "SPY"]})
    assert lmp.universe_changed.is_set()
    lmp.universe_changed.clear()
    lmp.record_feed_heartbeat({"ts": now + 9, "schwab_socket_open": True, "universe": ["QQQ", "SPY"]})
    assert lmp.universe_changed.is_set(), "after a silence"
    lmp.record_feed_down()
