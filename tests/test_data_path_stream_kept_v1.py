"""stream_capture.db holds what the operator trades, for the newest five trading sessions
(docs/DATA_FLOW.md §2 D4): the daemon's writer records an option quote or option book only for a
contract the daemon keeps (Daemon.saves: each watchlist ticker's soonest expiration, the 5 listed
strikes each side of the price, and the Flow panel's contract), every equity message, and once
after each close of the last option market removes the rows received before the newest five
sessions began (keep_sessions, CaptureWriter.prune). The live stream and the levels are untouched.

Real data: the option chains the daemon captured 2026-10-07 (tests/real_chains.py) and Schwab's
/markets answers held by tests/conftest.py. STAND-INS: the messages' contents (only their topic,
symbol and receipt time are what this proves) and the daemon's clock.
"""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime

from app.market_data.schwab.streaming import capture
from calibration.complete_chain_capture import chain_messages
from stream_spine import LOG, CaptureWriter, HealthRegistry, MessageBus, book_msg, options_quote_msg, quote_msg
from tests.real_chains import MRVL, SPY_0DTE
from time_et import ET


async def _until(ok, seconds: float = 30.0) -> None:
    deadline = asyncio.get_running_loop().time() + seconds
    while not ok():
        assert asyncio.get_running_loop().time() < deadline, "timed out"
        await asyncio.sleep(0.02)


def _rows(db, sql: str) -> list:
    with sqlite3.connect(db) as conn:
        return conn.execute(sql).fetchall()


def _et(text: str) -> float:
    return datetime.fromisoformat(text).replace(tzinfo=ET).timestamp()


def test_only_the_option_contracts_traded_are_recorded_and_every_equity_message(tmp_path):
    """SPY 2026-10-07 12:32 ET at 776.61, its same-day expiration listed: strikes 772 to 782 (777
    nearest, 5 listed each side), calls and puts. MRVL at 283.73, no same-day expiration: its
    nearest, 2026-10-09, strikes 270 to 295 (282.5 nearest). The contract selected on the Flow panel
    is recorded wherever it is. No other option quote or option book is recorded; both tickers'
    equity quotes are."""
    db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01)
    bus = MessageBus()
    daemon = capture.Daemon(bus, HealthRegistry(), ["SPY", "MRVL"], clock=lambda: SPY_0DTE.now.timestamp())
    daemon.writer = writer
    writer.saves = daemon.saves
    flow = next(c["symbol"] for c in MRVL.chain if c["expirationDate"].startswith("2026-11-20"))
    spy_kept = {c["symbol"] for c in SPY_0DTE.chain if 772 <= c["strikePrice"] <= 782}
    mrvl_kept = {c["symbol"] for c in MRVL.chain
                 if c["expirationDate"].startswith("2026-10-09") and 270 <= c["strikePrice"] <= 295}
    every = [c["symbol"] for c in SPY_0DTE.chain + MRVL.chain]
    near, far = sorted(spy_kept)[0], next(s for s in every if s not in spy_kept | mrvl_kept | {flow})

    async def go():
        stop = asyncio.Event()
        tasks = [asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop)),
                 asyncio.create_task(daemon.follow_market(stop))]
        await asyncio.sleep(0)
        for rc in (SPY_0DTE, MRVL):
            for topic, msg in chain_messages(rc.ticker, rc.chain, rc.now.timestamp()):
                bus.publish(topic, msg)
            bus.publish(f"quote.{rc.ticker}", quote_msg(symbol=rc.ticker, last=rc.spot, src="schwab_l1",
                                                        native={"key": rc.ticker, "LAST_PRICE": rc.spot}))
        await _until(lambda: daemon.saved_options == frozenset(spy_kept | mrvl_kept))
        daemon.console_frame({"op": "flow_contract", "contract": flow}, None)
        for sym in every:
            bus.publish(f"optquote.{sym}", options_quote_msg(symbol=sym, content={"key": sym, "MARK": 1.0},
                                                             src="schwab_options_l1"))
        for sym in (near, far):
            bus.publish(f"book.{sym}", book_msg(symbol=sym, service="OPTIONS_BOOK", content={"key": sym},
                                                src="schwab_book"))
        bus.publish("quote.SPY", quote_msg(symbol="SPY", last=776.62, src="schwab_l1",
                                           native={"key": "SPY", "LAST_PRICE": 776.62}))
        await _until(lambda: writer.status()["rows_written"] == len(spy_kept | mrvl_kept) + 1 + 1 + 3)
        stop.set()
        await asyncio.gather(*tasks)
    asyncio.run(go())

    assert len(spy_kept) == len(mrvl_kept) == 22                 # 11 strikes, a call and a put each
    options = {s for (s,) in _rows(db, "SELECT symbol FROM stream_options_quotes_raw")}
    assert options == spy_kept | mrvl_kept | {flow}, "not exactly the kept contracts and the Flow panel's"
    assert [s for (s,) in _rows(db, "SELECT symbol FROM stream_book_raw")] == [near]
    assert sorted(s for (s,) in _rows(db, "SELECT symbol FROM stream_quotes_raw")) == ["MRVL", "SPY", "SPY"]


def _recorded(bus) -> None:
    """Rows on both sides of 2026-10-01 00:00 ET, as the daemon publishes them."""
    for when in ("2026-09-30 15:00", "2026-10-01 09:31"):
        bus.publish("quote.SPY", quote_msg(symbol="SPY", last=1.0, src="schwab_l1", ts_recv=_et(when),
                                           native={"key": "SPY"}))
        bus.publish("feedstatus.LEVELONE_EQUITIES", {"ts": _et(when), "service": "LEVELONE_EQUITIES",
                                                     "socket_open": True, "held": 1})
    for when in ("2026-09-30 15:00", "2026-10-07 15:00"):
        bus.publish("optquote.SPY   261007C00777000", options_quote_msg(
            symbol="SPY   261007C00777000", content={"key": "SPY   261007C00777000"}, src="schwab_options_l1",
            ts_recv=_et(when)))
    for when in ("2026-09-29 12:00", "2026-09-30 12:00"):          # both before; the newest stays
        topic, msg = capture.watchlist_message(["SPY"], op="added", ticker="SPY", request_id=when)
        bus.publish(topic, {**msg, "ts_recv": _et(when)})


def _kept_at(tmp_path, clock: str, wait: float) -> str:
    """The rows left after the daemon's keep runs at `clock` (ET) for `wait` seconds or until the
    old rows are gone: a summary per table."""
    db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01)
    bus = MessageBus()
    daemon = capture.Daemon(bus, HealthRegistry(), ["SPY"], clock=lambda: _et(clock))
    daemon.writer = writer

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop))
        await asyncio.sleep(0)
        _recorded(bus)
        await _until(lambda: writer.status()["rows_written"] == 8)
        keep = asyncio.create_task(capture.keep_sessions(daemon, stop))
        try:
            await _until(lambda: _rows(db, "SELECT COUNT(*) FROM stream_feed_status")[0][0] == 1, wait)
        except AssertionError:
            pass                                                         # nothing was removed
        stop.set()
        await asyncio.gather(task, keep)
    asyncio.run(go())
    counts = " ".join(f"{name}:{_rows(db, f'SELECT COUNT(*) FROM {table}')[0][0]}" for name, table in (
        ("quotes", "stream_quotes_raw"), ("options", "stream_options_quotes_raw"),
        ("feed", "stream_feed_status"), ("watchlist", "stream_watchlist")))
    newest = datetime.fromtimestamp(_rows(db, "SELECT MAX(ts_recv) FROM stream_watchlist")[0][0], ET)
    return f"{counts} newest-watchlist:{newest:%m-%d %H:%M}"


def test_after_the_last_option_close_rows_before_the_newest_five_sessions_are_removed(tmp_path):
    """2026-10-07 17:00 ET, the last option market (IND) closed at 16:15: Schwab's /markets says
    the market was open 09-30, 10-01, 10-02, 10-05, 10-06 and 10-07, so the newest five sessions
    run from 2026-10-01 00:00 ET. Every row received before it is removed from each table, except
    the newest watchlist row, which the daemon reads at its start."""
    assert _kept_at(tmp_path, "2026-10-07 17:00", 30.0) == \
        "quotes:1 options:1 feed:1 watchlist:1 newest-watchlist:09-30 12:00"


def test_nothing_is_removed_while_the_options_trade_or_the_market_is_unknown(tmp_path):
    """2026-10-07 12:00 ET, the options open; and 2027-10-12, a date Schwab's held answers do not
    reach: no row is removed (never on a guess)."""
    untouched = "quotes:2 options:2 feed:2 watchlist:2 newest-watchlist:09-30 12:00"
    assert _kept_at(tmp_path / "open", "2026-10-07 12:00", 1.5) == untouched
    assert _kept_at(tmp_path / "unknown", "2027-10-12 17:00", 1.5) == untouched
