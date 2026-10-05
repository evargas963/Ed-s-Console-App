"""The recorded universe: every ticker with data stored in the databases, as the capture daemon
reads it at its start (capture.recorded_universe), and the console's one copy of it, the daemon's
heartbeat.

Real data: Schwab's SPY and TSLA 1-minute bars as the daemon recorded them
(tests/fixtures/real_daemon_bars_spy_tsla_2026_09_29_30.json), a captured TSLA option quote
(tests/fixtures/real_options_stream_history_samples.json), Schwab's CRWD chain
(tests/fixtures/real_crwd_complete_chain_quarter.json), Schwab's empty instrument answer `{}`
(tests/fixtures/real_schwab_instruments_2026_08_20.json) and one stored FINRA short-volume row
(ed_console.db world_finra_short_volume, 2026-07-15 AAPL, as stored)."""
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
_EMPTY = json.loads((FX / "real_schwab_instruments_2026_08_20.json").read_text(encoding="utf-8"))[
    "answers"]["none_listed"]["body"]


def _record_bars(writer: CaptureWriter, *symbols: str) -> None:
    with sqlite3.connect(writer.db_path) as con:
        for r in [r for s in symbols for r in daemon_bars("real_daemon_bars_spy_tsla_2026_09_29_30.json", s)[:3]]:
            writer.insert(f"bar1m.{r['symbol']}", bar_msg(
                symbol=r["symbol"], bar_start_ms=r["bar_start_ms"], open=r["open"], high=r["high"],
                low=r["low"], close=r["close"], volume=r["volume"], src=r["src"], ts_recv=r["ts_recv"],
                native=r["native"], schwab_ts=r["schwab_ts"]), conn=con)


def test_the_console_and_the_daemon_hold_one_universe(tmp_path):
    """The daemon reads every ticker with data stored, in both databases (its record of Schwab's
    bars, the chain history), once at its start; the console carries the daemon's universe from
    its heartbeat, in one order, never a copy of its own."""
    console_db, stream_db = tmp_path / "ed_console.db", tmp_path / "stream_capture.db"
    _record_bars(CaptureWriter(stream_db), "SPY", "TSLA")
    persist_complete_chain_capture(console_db, ticker="CRWD", expiry=_CRWD["expiry"], contracts=_CRWD["chain"],
                                   spot=_CRWD.get("spot"), completeness_basis=CAPTURE_BASIS, ts_utc=time.time())
    d = capture.Daemon(MessageBus(), HealthRegistry(), universe=capture.recorded_universe(console_db, stream_db))
    lmp.record_feed_heartbeat(d.status())
    try:
        assert d.universe == server._universe() == ["CRWD", "SPY", "TSLA"]
    finally:
        lmp.record_feed_down()


def test_a_first_run_with_no_database_holds_no_ticker(tmp_path):
    """A database not created yet holds no ticker, and the daemon still starts."""
    assert capture.recorded_universe(tmp_path / "not_created_yet.db", tmp_path / "nor_this.db") == []


def test_an_option_contract_a_world_table_and_an_answer_schwab_did_not_list_are_not_tickers(tmp_path):
    """An option contract's symbol is a contract, a `world_` table is a public dataset from
    another source, and a ticker whose instrument answer did not list it never joined: none of
    them is in the universe. The ticker under the contract's quotes is, where its own data is
    stored."""
    console_db, stream_db = tmp_path / "ed_console.db", tmp_path / "stream_capture.db"
    writer = CaptureWriter(stream_db)
    _record_bars(writer, "TSLA")
    contract = _OPT["contracts"][0]
    event = next(e for e in contract["events"] if e["kind"] == "l1")
    with sqlite3.connect(stream_db) as con:
        writer.insert(f"optquote.{contract['symbol']}", options_quote_msg(
            symbol=contract["symbol"], content=event["content"], src="schwab_options_l1"), conn=con)
        writer.insert("instrument.ZZZZ", instrument_msg(symbol="ZZZZ", http_status=200, body=_EMPTY,
                                                        listed=False, ts=time.time()), conn=con)
    with sqlite3.connect(console_db) as con:
        con.execute("CREATE TABLE world_finra_short_volume (date TEXT NOT NULL, symbol TEXT NOT NULL, "
                    "short_volume INTEGER, short_exempt_volume INTEGER, total_volume INTEGER, market TEXT, "
                    "fetched_at TEXT DEFAULT (datetime('now')), PRIMARY KEY (date, symbol))")
        con.execute("INSERT INTO world_finra_short_volume VALUES ('2026-07-15', 'AAPL', 12298806, 69012, "
                    "22885472, 'B,Q,N', '2026-07-21 13:02:27')")
    assert contract["symbol"].startswith("TSLA ")
    assert capture.recorded_universe(console_db, stream_db) == ["TSLA"]


def test_a_heartbeat_with_no_universe_is_an_unknown_universe_never_an_empty_one():
    """A daemon that sends no universe (one from before this change) reads as unknown, never as
    an empty universe that would drop every ticker's levels."""
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
