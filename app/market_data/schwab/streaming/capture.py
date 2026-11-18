"""The capture daemon: the ONE Schwab streaming connection (Schwab allows one per account).

    python -m app.market_data.schwab.streaming.capture_main  (launch.py -> start_capture_daemon.bat)

It is the only part of Ed Console that talks to Schwab. Beside the loop below, its chain sweep
(run_chains) fetches full option chains on its own thread, one request at a time, without end:
every watchlist ticker, each in its turn in one rotation, a ticker on a page before each other.

  0. WATCHLIST The one list of tickers Schwab is asked for (Watchlist): the daemon holds it,
             is its only writer, and keeps every change as a `watchlist` record (the writer
             stores it in the database's stream_watchlist; the newest is read at startup).
             The console, in this program, asks for an add or a removal (console_frame):
             {"op": "watchlist", "action": "add"|"remove", "ticker": T, "id": n}. An added
             ticker is checked with one /quotes request: one Schwab names in
             errors.invalidSymbols, or does not quote, is not added. The record carries the
             request's id and Schwab's answer back to the console.

  1. WANTED  What Schwab's stream is asked for (wanted): every watchlist ticker on each equity
             service (with the market context the page header shows, MARKET_CONTEXT, on
             LEVELONE_EQUITIES, CHART_EQUITY and NEWS_HEADLINE), and the option contracts the
             option rule picks (pick_options: the contract selected on the Flow panel, then every
             ticker's contracts dealt in turn, each ticker's in shown_first's order of its newest
             chain, none expired). Feed's one connection (feed.connection.Connection) asks for
             it, matches Schwab's answers, publishes every frame on the bus and reconnects.

What Schwab offers (its answers on the live connection): LEVELONE_EQUITIES, CHART_EQUITY, NYSE_BOOK
(exchange book), NASDAQ_BOOK (market-maker quotes), LEVELONE_OPTIONS, OPTIONS_BOOK and
NEWS_HEADLINE answer code 0; both books accepted 30 symbols. TIMESALE_* and ACTIVES_* answer
code 11 (not available) -- there is no trade-by-trade tape and no trade side.
"""

from __future__ import annotations

import asyncio
import atexit
import bisect
import contextlib
import json
import logging
import logging.handlers
import os
import queue
import signal
import socket
import sqlite3
import sys
import threading
from collections.abc import Awaitable, Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from itertools import zip_longest
from pathlib import Path
from types import FrameType
from typing import Any, TextIO, TypedDict, override

import uvicorn

import live_market_plane as lmp
import live_price_rows
import runtime_layout
import server
import time_et
from app.market_data.schwab.streaming.live_push import MARKET_CONTEXT
from app.market_data.schwab.streaming.live_ui import (
    CONSOLE_HOST,
    PageSocket,
    selected,
    serve_live_ui,
)
from app.market_data.schwab.streaming.program_lock import (
    Ports,
    StopRequest,
    acquire_owner_lock,
    record_ports,
    release_owner_lock,
)
from app.options.order_flow import streaming as console_feed
from calc.terrain_engine import nearest_position
from config import build_config, load_dotenv_file
from feed.chain_sweep import ChainSweep
from feed.connection import SERVICES, Connection, held_key
from feed.schwab_client import SchwabClientState, build_client_from_token, check_ticker
from instrument_identity import ticker_storage_key
from option_contract import OptionContract
from stream_spine import (
    LATEST,
    LOG,
    CaptureWriter,
    HealthRegistry,
    MessageBus,
)
from time_et import (
    ET,
    ct_label,
    option_market_open,
    options_closed_at,
    session_label,
    sessions_since,
)

log = logging.getLogger("capture")

#: every watchlist ticker is streamed on each of these
EQUITY_SERVICES = ("LEVELONE_EQUITIES", "CHART_EQUITY", "NEWS_HEADLINE", "NYSE_BOOK", "NASDAQ_BOOK")
#: the market context every page's header shows (live_push.MARKET_CONTEXT) is streamed on these,
#: whatever the watchlist holds
MARKET_CONTEXT_SERVICES = ("LEVELONE_EQUITIES", "CHART_EQUITY", "NEWS_HEADLINE")


# ---------------------------------------------------------------------------- the watchlist

#: the bus topic of the watchlist record (stream_spine writes it to stream_watchlist)
WATCHLIST_TOPIC = "watchlist"
WATCHLIST_SRC = "daemon_watchlist"
#: what a watchlist record says happened
ADDED, REMOVED, INVALID, NOT_CHECKED, ON_LIST, NOT_ON_LIST = (
    "added",
    "removed",
    "invalid",
    "not checked",
    "already on the list",
    "not on the list",
)


def stored_watchlist(db_path: str | Path) -> list[str]:
    """Return the watchlist as the newest stored record holds it, read once at startup.

    The record is stream_watchlist, written by the daemon's writer; the watchlist is empty
    when none was ever stored.
    """
    if not Path(db_path).is_file():
        return []
    conn = sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='stream_watchlist'").fetchone():
            return []
        rows = conn.execute(
            "SELECT tickers_json FROM stream_watchlist ORDER BY rowid DESC LIMIT 1"
        ).fetchall()
    finally:
        conn.close()
    return [t for (tickers,) in rows for t in json.loads(tickers)]


def watchlist_message(
    tickers: list[str],
    *,
    op: str,
    ticker: str,
    request_id: Any,
    ts_recv: float,
    status: int | None = None,
    answer: Any = None,
) -> tuple[str, dict[str, Any]]:
    """Return the watchlist after one request as its bus record, made at `ts_recv`.

    The record holds the whole list, what happened to `ticker` (`op`), the console's request
    id, and Schwab's /quotes answer to the check (an add) with its HTTP status, as sent.
    """
    return WATCHLIST_TOPIC, {
        "src": WATCHLIST_SRC,
        "ts_recv": ts_recv,
        "tickers": list(tickers),
        "op": op,
        "ticker": ticker,
        "request_id": request_id,
        "status": status,
        "answer": answer,
    }


# ---------------------------------------------------------------------------- the option rule


def shown_first(contracts: list[OptionContract], price: float, now: float) -> tuple[str, ...]:
    """`contracts` (a chain as the sweep delivers it) in the option rule's order at `now`.

    The contracts the heatmap shows come first. A contract's distance is the larger of two counts:
    its expiration's place among the chain's expirations, nearest first, and twice its strike's
    count of listed strikes from the one nearest `price` (nearest_position, the heatmap's centre
    row; twice, since the window reaches both ways from it). The nearest distance first, so the
    order grows as the heatmap's window does: as many strikes as expirations (strike_window's
    rows of the nearest expirations). Of equal distances the highest Schwab gamma, as sent (one
    Schwab sent none of, or as -999, last); then the nearest expiration, the strike nearest
    `price` (the lower of two equally near), calls before puts. A contract has expired once now
    passes its
    expirationDate and is left out (it stays in the records; it is never streamed); so is one
    whose strike or expiration is not a number, whose side is not CALL or PUT, or that has no
    symbol to stream (rule 2).
    """
    listed = [
        (c.expires_at, c.strike, c.side, c.symbol, c.gamma)
        for c in contracts
        if c.symbol
        and c.strike is not None
        and c.expires_at is not None
        and c.side is not None
        and c.expires_at > now
    ]
    expirations = sorted({expires for expires, *_ in listed})
    strikes = sorted({strike for _e, strike, *_ in listed})
    centre = nearest_position(strikes, price) if strikes else 0
    rows = []
    for expires, strike, side, symbol, gamma in listed:
        distance = max(
            bisect.bisect_left(expirations, expires),
            2 * abs(bisect.bisect_left(strikes, strike) - centre),
        )
        row = (expires, abs(strike - price), strike, side, symbol)
        if gamma is not None:
            rows.append((distance, 0, -gamma, *row))
        else:  # no gamma: after every contract as near that has one
            rows.append((distance, 1, *row))
    return tuple(r[-1] for r in sorted(rows))


#: listed strikes each side of the one nearest the price whose option quotes and option books are
#: recorded (the operator's setting; Daemon.saves)
STRIKES_SAVED = 5

#: one expiration of a chain: its time, its listed strikes ascending, each strike's symbols
type Ladder = tuple[float, list[float], dict[float, list[str]]]


def strike_ladders(contracts: list[OptionContract]) -> list[Ladder]:
    """Return a chain's expirations, soonest first.

    Each is (expiration time, its listed strikes ascending, each strike's contract symbols). A
    contract whose strike or expiration is not a number, or that has no symbol to stream, is
    left out (rule 2).
    """
    by: dict[float, dict[float, list[str]]] = {}
    for c in contracts:
        if c.symbol and c.strike is not None and c.expires_at is not None:
            by.setdefault(c.expires_at, {}).setdefault(c.strike, []).append(c.symbol)
    return [(expires, sorted(by_strike), by_strike) for expires, by_strike in sorted(by.items())]


def saved_window(ladders: list[Ladder], price: float, now: float) -> frozenset[str]:
    """Return the contracts recorded of one ticker.

    They are its soonest expiration not passed at `now` (today's when one is listed, else the
    nearest), at the strike nearest `price` (the lower of two equally near) and the
    STRIKES_SAVED listed strikes each side of it.
    """
    for expires, strikes, symbols in ladders:
        if expires > now:
            i = nearest_position(strikes, price)
            return frozenset(
                s
                for k in strikes[max(0, i - STRIKES_SAVED) : i + STRIKES_SAVED + 1]
                for s in symbols[k]
            )
    return frozenset()


def _request_ended(task: asyncio.Future[None]) -> None:
    """Handle a watchlist request's end: one that ended on an error is logged with its traceback."""
    if not task.cancelled() and task.exception() is not None:
        e = task.exception()
        log.error("watchlist request: ended on %s: %s", type(e).__name__, e, exc_info=e)


# ---------------------------------------------------------------------------- the daemon


class Daemon:
    def __init__(
        self,
        bus: MessageBus,
        health: HealthRegistry,
        watchlist: Iterable[str] = (),
        *,
        clock: Callable[[], float] = time_et.now,
        on_page: Callable[[], Iterable[str]] = frozenset,
    ) -> None:
        self.bus = bus
        self.health = health
        #: the tickers the open pages have selected, read each time it is needed (shown)
        self.on_page = on_page
        #: the time a chain is put in the option rule's order at (shown_first's `now`, read as it
        #: arrives)
        self.clock = clock
        #: the one list of tickers Schwab is asked for, in its order (stored_watchlist at startup)
        self.watchlist: list[str] = list(watchlist)
        #: the option contracts the option rule picked, in its order (pick_options)
        self.option_order: tuple[str, ...] = ()
        #: the contract Ed selected on the Flow panel (the console's {"op": "flow_contract"}),
        #: streamed on both option services on top of the rule
        self.flow_contract: str | None = None
        #: per watchlist ticker: its newest whole chain while it waits for a price, that chain in
        #: the rule's order (shown_first), its strikes per expiration (strike_ladders) and its
        #: recorded contracts (saved_window, as last placed); every contract the writer records
        #: (saves)
        self._chains: dict[str, list[OptionContract]] = {}
        self._ranked: dict[str, tuple[str, ...]] = {}
        self._ladders: dict[str, list[Ladder]] = {}
        self._windows: dict[str, frozenset[str]] = {}
        self.saved_options: frozenset[str] = frozenset()
        self.chains: ChainSweep | None = None  # its round time, its tickers
        self.writer: CaptureWriter | None = None  # its state rides the heartbeat
        #: the daemon's one Schwab client (run): the checks
        self.schwab_client: Callable[[], object] | None = None
        #: the one Schwab stream connection, asking for what is wanted (wanted)
        self.connection = Connection(bus, health, self.wanted, time_et.now)

    def wanted(self) -> dict[str, tuple[str, ...]]:
        """Return what Schwab is asked for, per service, in the order it is asked.

        That is every watchlist ticker on each equity service, then the market context on
        MARKET_CONTEXT_SERVICES, and the option contracts in the rule's order on each option
        service (the connection cuts each at the symbol limit Schwab states for it).
        """
        out = {svc: tuple(self.watchlist) for svc in EQUITY_SERVICES}
        for svc in MARKET_CONTEXT_SERVICES:
            out[svc] = tuple(dict.fromkeys([*self.watchlist, *MARKET_CONTEXT]))
        for svc in lmp.OPTION_SERVICES:
            out[svc] = self.option_order
        return out

    def shown(self) -> list[str]:
        """Return the watchlist tickers a page has selected, in the watchlist's order."""
        on_page = set(self.on_page())
        return [tk for tk in self.watchlist if tk in on_page]

    def page_selected(self, ticker: str) -> None:
        """Act on a page newly selecting `ticker` (live_ui's on_select).

        Its levels are repriced (server.ticker_selected) and the option rule runs again, so
        Schwab's stream is asked for its contracts first.
        """
        server.ticker_selected(ticker)
        self.pick_options()

    def pick_options(self) -> None:
        """Run the option rule: the ticker on a page first (operator 2026-11-11).

        It runs when a ticker's chain is put in the rule's order (_rank), on a watchlist change,
        on the Flow panel's selection and when a page selects a ticker. The contract selected on
        the Flow panel streams on both option services when a watchlist ticker's chain lists it,
        not expired; then every ticker's recorded contracts (its window, _place), so what the
        writer records of a ticker no page shows is still streamed; then every contract of the
        tickers a page shows (shown); then every other ticker's. Each of the three in the rule's
        order (shown_first), dealt across its tickers, each ticker's first, then each one's
        second. No number of ours caps them: every one is asked until Schwab states its symbol
        limit for the service (code 19), and from then the first that many of this order are
        (wanted). A ticker without a chain and a price yet has none. When what is wanted changes,
        the difference is asked (ask: one UNSUBS and one ADD per service).
        """
        ranked = {tk: self._ranked[tk] for tk in self.watchlist if tk in self._ranked}
        flow = [c for c in [self.flow_contract] if any(c in r for r in ranked.values())]
        recorded = [
            [s for s in order if s in self._windows[tk]]
            for tk, order in ranked.items()
            if tk in self._windows
        ]
        on_page = [ranked[tk] for tk in self.shown() if tk in ranked]
        self.option_order = tuple(
            dict.fromkeys(
                # every ticker's first, then every ticker's second, ...
                s
                for rows in ([flow], recorded, on_page, list(ranked.values()))
                for row in zip_longest(*rows)
                for s in row
                if s is not None
            )
        )
        self.connection.ask()

    def _keep_options(self) -> None:
        """Set the option contracts recorded (saved_options).

        They are each ticker's window and the Flow panel's.
        """
        self.saved_options = frozenset(c for c in [self.flow_contract] if c is not None).union(
            *self._windows.values()
        )

    def _place(self, ticker: str, now: float) -> None:
        """Place `ticker`'s recorded window (saved_window) at its live price and `now`.

        While its row has no price, the window it has stands.
        """
        price = live_price_rows.spot(ticker)
        if price is not None and ticker in self._ladders:
            window = saved_window(self._ladders[ticker], price, now)
            if window != self._windows.get(ticker):
                self._windows[ticker] = window
                self._keep_options()

    def saves(self, topic: str, msg: dict[str, Any]) -> bool:
        """Tell whether the writer records a bus message (CaptureWriter.saves).

        It records an option quote or an option book only for a contract in saved_options;
        every other message always.
        """
        option = topic.startswith("optquote.") or (
            topic.startswith("book.") and msg["service"] == "OPTIONS_BOOK"
        )
        return not option or msg["symbol"] in self.saved_options

    async def _rank(self, ticker: str, now: float) -> None:
        """Put `ticker`'s waiting chain in the rule's order (shown_first) and redo the pick.

        The order is taken at its live price and `now`, on the program's pricing thread, never on
        the event loop; while its row has no price, the chain waits and the order stands. A
        ticker removed meanwhile takes nothing.
        """
        price = live_price_rows.spot(ticker)
        if price is not None:
            chain = self._chains.pop(ticker)
            ranked = await asyncio.get_running_loop().run_in_executor(
                server._chain_pricing, shown_first, chain, price, now
            )
            if ticker in self.watchlist:
                self._ranked[ticker] = ranked
                self.pick_options()

    async def _took_quote(self, sym: str, msg: dict[str, Any]) -> None:
        """Take one equity quote's current record on the bus into the plane.

        Each field is taken at the receive time of the message that carried it, and its price
        row goes to the option rule (_took_row).
        """
        if lmp.record_from_level_one_equity(
            sym,
            msg["native"],
            received_ts=msg["ts_recv"],
            field_received={f: s[1] for f, s in msg["field_ts"].items()},
        ):
            await self._took_row(ticker_storage_key(sym))

    async def _took_row(self, ticker: str) -> None:
        """Act on `ticker`'s price row published.

        A watchlist ticker's window is placed at the price and its waiting chain ordered (the
        window first: the rule streams it).
        """
        if ticker in self.watchlist:
            now = self.clock()
            self._place(ticker, now)
            if ticker in self._chains:
                await self._rank(ticker, now)

    async def _took_chain(self, ticker: str, record: list[dict[str, Any]]) -> None:
        """Order a watchlist ticker's newest whole chain on the bus (its parts) at its live price.

        The chain is the sweep's one read of it (complete_chain_capture.chain_messages); its
        ladders are laid out on the program's pricing thread (server._chain_pricing), never on the
        event loop, whose one reader takes Schwab's stream (docs/DATA_FLOW.md §4.1); a ticker
        removed meanwhile takes nothing. A failed fetch carries no contracts and changes nothing.
        """
        if ticker in self.watchlist and all("contracts" in part for part in record):
            now = self.clock()
            chain: list[OptionContract] = [ct for part in record for ct in part["contracts"]]
            ladders = await asyncio.get_running_loop().run_in_executor(
                server._chain_pricing, strike_ladders, chain
            )
            if ticker in self.watchlist:
                self._chains[ticker], self._ladders[ticker] = chain, ladders
                self._place(ticker, now)
                await self._rank(ticker, now)

    async def follow_market(self, stop: asyncio.Event) -> None:
        """Follow the market until `stop`, or a follower's end.

        Each equity quote goes into the plane, whose rows the browsers and the option rule read
        (_took_quote), and each ticker's newest whole chain into the option rule (_took_chain).
        """

        async def follow(prefix: str, take: Callable[[str, Any], Awaitable[None]]) -> None:
            sub = self.bus.subscribe(prefix, policy=LATEST)
            try:
                while True:
                    topic, record = await sub.get()
                    await take(topic.split(".", 1)[1], record)
            finally:
                self.bus.unsubscribe(sub)

        tasks: set[asyncio.Task[object]] = {
            asyncio.create_task(follow("quote.", self._took_quote)),
            asyncio.create_task(follow("chain.", self._took_chain)),
            asyncio.ensure_future(stop.wait()),
        }
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        for task in done:
            task.result()  # a follower's error, raised for run to name

    def console_frame(self, req: dict[str, Any]) -> None:
        """Act on a request from the console in this program.

        It is a watchlist request ({"op": "watchlist"}, answered on the bus) or the contract
        selected on the Flow panel ({"op": "flow_contract", "contract": symbol or null}).
        """
        if req["op"] == "watchlist":
            task = asyncio.ensure_future(self.watchlist_request(req))
            task.add_done_callback(_request_ended)
        elif req["op"] == "flow_contract":
            self.flow_contract = req["contract"]
            log.info("flow contract: %s", self.flow_contract)
            self.pick_options()
            self._keep_options()

    async def watchlist_request(self, req: dict[str, Any]) -> None:
        """Act on one add or removal from the console.

        The request is {"op": "watchlist", "action", "ticker", "id"}, answered with the
        watchlist record (watchlist_message), which the writer stores and the console receives.
        An added ticker is checked first with one /quotes request (check_ticker) and added only
        when Schwab quotes it; on the list, Schwab is asked for it at once on every service and
        by the chain sweep, and a removed one is asked for no more.
        """
        ticker, rid = ticker_storage_key(str(req["ticker"])), req["id"]
        status = answer = None

        def told(op: str, **answered: Any) -> None:  # the list now, and what happened, at once
            self.bus.publish(
                *watchlist_message(
                    self.watchlist,
                    op=op,
                    ticker=ticker,
                    request_id=rid,
                    ts_recv=self.clock(),
                    **answered,
                )
            )

        if req["action"] == "remove":
            if ticker not in self.watchlist:
                told(NOT_ON_LIST)
                return
            self.watchlist, op = [t for t in self.watchlist if t != ticker], REMOVED
            for held in (self._chains, self._ranked, self._ladders, self._windows):
                held.pop(ticker, None)  # added again, it waits for its next chain
            self._keep_options()
        else:
            if ticker in self.watchlist:
                told(ON_LIST)
                return
            try:
                quoted, status, answer = await asyncio.to_thread(
                    check_ticker, self.schwab_client(), ticker
                )
            except Exception as e:  # the check could not be made: not added, and why
                log.warning(
                    "watchlist: %s not checked: %s: %s", ticker, type(e).__name__, e, exc_info=True
                )
                told(NOT_CHECKED, answer=f"{type(e).__name__}: {e}")
                return
            if not quoted:
                log.warning(
                    "watchlist: %s not added: Schwab's /quotes answered %s: %s",
                    ticker,
                    status,
                    json.dumps(answer),
                )
                told(INVALID, status=status, answer=answer)
                return
            if ticker in self.watchlist:  # added by another request during the check
                told(ON_LIST)
                return
            self.watchlist, op = [*self.watchlist, ticker], ADDED
        log.info("watchlist: %s %s; the list: %s", ticker, op, ",".join(self.watchlist))
        if self.chains is not None:
            self.chains.watchlist = list(self.watchlist)
        self.pick_options()  # every ticker's share changes with the list
        self.connection.ask()
        told(op, status=status, answer=answer)

    def option_record(self, symbol: str) -> tuple[str, dict[str, Any]] | None:
        """Return `symbol`'s current LEVELONE_OPTIONS record on the bus, (topic, record).

        It is returned while this connection holds it on LEVELONE_OPTIONS; None otherwise (the
        chain sweep reads each
        contract's Greeks from it, and asks the quotes endpoint for every contract it returns None
        for: a record left from a connection that ended is not held).
        """
        held = symbol in self.connection.held["LEVELONE_OPTIONS"]
        return self.bus.current.get(held_key("LEVELONE_OPTIONS", symbol)) if held else None

    def status(self, now: float) -> dict[str, Any]:
        """Return what the console and browsers are told every second (live_ui's beat).

        It is taken at `now`, which the header shows as `clock_ct` and `day_ct`.
        """
        # open while a stream exists and Schwab sent a frame within DEAD_SEC; why not, only when not
        socket_open = self.connection.socket_open(now)
        return {
            "ts": now,
            "clock_ct": time_et.ct_clock(now),
            "day_ct": time_et.ct_day(now),
            "session": session_label(datetime.fromtimestamp(now, ET)),
            "schwab_socket_open": socket_open,
            "schwab_down": None if socket_open else self.connection.schwab_down,
            "watchlist": list(self.watchlist),
            "chain_round_sec": self.chains.round_sec if self.chains is not None else None,
            "chains_began": self.chains.began if self.chains is not None else None,
            "chains_waiting": self.chains.waiting if self.chains is not None else None,
            "held": {k: sorted(v) for k, v in self.connection.held.items()},
            "health": self.health.report(now),
            "writer": self.writer.status() if self.writer is not None else None,
        }

    async def run(self, schwab_client: Callable[[], object], stop: asyncio.Event) -> None:
        """Run the stream connection until stop (Connection.run: it reconnects with backoff).

        It runs on the daemon's one Schwab client (`schwab_client()`), which also makes the
        watchlist's checks.
        """
        self.schwab_client = schwab_client
        await self.connection.run(schwab_client, stop)


# ---------------------------------------------------------------------------- process


#: Exit code of a daemon stopped on request (launch.py stop, Ctrl+C in its window):
#: start_capture_daemon.bat does not restart it.
EXIT_STOPPED = 5


#: days of the daemon's log kept, one file a day (the operator's setting)
LOG_DAYS_KEPT = 45


class DailyLog(logging.StreamHandler[TextIO]):
    """The daemon's log in `folder`, one file a day (runtime_layout.daemon_log_path).

    Days go by each line's own time: the first line of a day opens that day's file, then the
    files past the newest LOG_DAYS_KEPT are deleted. No file is renamed, so another process
    holding one open never stops a line; a file it cannot delete (held open) is logged and tried
    again the next day. A day's file the disk will not open goes to logging's own error report
    (handleError, as any failed line does), never to the code that logged; the next line tries
    it again.
    """

    def __init__(self, folder: Path):
        super().__init__()
        self.folder, self.day = folder, None

    def emit(self, record: logging.LogRecord) -> None:
        day = date.fromtimestamp(record.created)
        if day != self.day:
            try:
                self._open(day)
            except OSError:
                self.handleError(record)
                return
        super().emit(record)

    def _open(self, day: date) -> None:
        stream = open(runtime_layout.daemon_log_path(self.folder, day), "a", encoding="utf-8")
        if self.day is not None:
            self.stream.close()
        self.day, self.stream = day, stream
        for old in sorted(self.folder.glob("stream_capture.????-??-??.log"))[:-LOG_DAYS_KEPT]:
            try:
                old.unlink()
            except OSError as e:
                log.warning(
                    "log: %s not deleted, tried again the next day: %s: %s",
                    old.name,
                    type(e).__name__,
                    e,
                )

    def close(self) -> None:
        with self.lock:
            if self.day is not None:
                self.stream.close()
        super().close()


def stop_on_interrupt(stop: asyncio.Event, loop: asyncio.AbstractEventLoop) -> None:
    """Make Ctrl+C (or Ctrl+Break) in the program's window ask for its one clean stop.

    It is the one `launch.py stop` asks for (stop_on_request): everything held is written, then
    it exits EXIT_STOPPED and its window closes. A second press ends it at once
    (KeyboardInterrupt, main).
    """

    def interrupted(_signum: int, _frame: FrameType | None) -> None:
        log.warning("Ctrl+C: stopping cleanly; press it again to end at once")
        for sig in INTERRUPTS:
            signal.signal(sig, signal.default_int_handler)
        loop.call_soon_threadsafe(stop.set)

    for sig in INTERRUPTS:
        signal.signal(sig, interrupted)


#: how long the stop request's waiter waits at a time (stop_on_request)
STOP_WAIT_SEC = 0.25


async def stop_on_request(stop: asyncio.Event, request: StopRequest) -> None:
    """Wait on the program's stop request and, once asked, set the program's one stop.

    This is the one waiter on the request (program_lock.StopRequest, which launch.py stop sets);
    the stop it sets is the one Ctrl+C sets, so everything held is written and the program exits
    EXIT_STOPPED. It waits STOP_WAIT_SEC at a time on a thread of its own, never one of the
    loop's shared threads, which the pages' panels and the chain sweep can all hold; a stop from
    anywhere else ends it within that wait; a request asked twice stops it once.
    """
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="stop request") as own:
        while not stop.is_set():
            if await loop.run_in_executor(own, request.wait, STOP_WAIT_SEC):
                log.info("capture daemon: stop requested (launch.py stop)")
                stop.set()


#: the window's interrupts: Ctrl+C, and Ctrl+Break where Windows has it
INTERRUPTS = (signal.SIGINT, *([signal.SIGBREAK] if hasattr(signal, "SIGBREAK") else []))


def _start_log() -> None:
    """Send every line, with its time to the millisecond, to the day's log file and the window.

    The file is runtime_layout.daemon_log_path under <runtime>/logs, written as the line is
    logged. The window is the error output (the daemon runs under `python` in it), written by a
    thread of its own from a queue (logging.handlers.QueueListener), so a window that holds its
    writes (a selection the operator makes to read it, a slow console) never stops the daemon: no
    line waits on it. From here an error reaches both (main logs one that ends the daemon).
    WINDOW_ONLY's lines go to the window alone: what Schwab streamed is recorded in
    the database, not a second time in the file.
    """
    folder = runtime_layout.logs_dir()
    folder.mkdir(parents=True, exist_ok=True)
    window: queue.SimpleQueue[logging.LogRecord] = queue.SimpleQueue()
    day = DailyLog(folder)
    day.addFilter(lambda record: record.name != WINDOW_ONLY.name)
    logging.basicConfig(
        level=logging.INFO,
        handlers=[day, logging.handlers.QueueHandler(window)],
        format="%(asctime)s.%(msecs)03d %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    writer = logging.handlers.QueueListener(window, logging.StreamHandler())
    writer.start()
    # at exit the writer prints every line still queued, then ends: none is lost with the process
    atexit.register(writer.stop)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # each request's line is log_request's


FEED_STATUS_EVERY_SEC = 60.0


async def record_feed_status(
    daemon: Daemon, stop: asyncio.Event, every: float = FEED_STATUS_EVERY_SEC
) -> None:
    """Record every `every` seconds (once a minute) the status of each Schwab feed.

    Per feed: checked at X (the same X for every feed), is the socket open, when Schwab last
    sent anything, how many symbols are subscribed, and when this feed last carried data -- so a
    quiet feed and a dead one read differently in the database.
    """
    while True:
        now = daemon.connection.clock()
        try:
            stream = daemon.connection.stream
            last_frame = stream.last_frame_ts if stream is not None else None
            st = daemon.status(now)
            for svc in SERVICES:
                daemon.bus.publish(
                    f"feedstatus.{svc}",
                    {
                        "ts": now,
                        "service": svc,
                        "socket_open": st["schwab_socket_open"],
                        "schwab_last_frame_ts": last_frame,
                        "held": len(daemon.connection.held[svc]),
                        "last_data_ts": daemon.health.last(svc),
                    },
                )
        except Exception as e:  # this round's rows are missing and the log says why; the next
            # round still runs (the console's status line reports the record's age)
            log.warning("feed status round failed: %s: %s", type(e).__name__, e, exc_info=True)
        if await time_et.set_within(stop, every):
            return


class _PagesServer(uvicorn.Server):
    """The console's web server inside this program.

    The program's interrupt handler
    (INTERRUPTS) is the one stop, so the server takes no signal of its own: uvicorn's would stop
    the pages first and wait out every open page before the program heard it.
    """

    @override
    @contextlib.contextmanager
    def capture_signals(self):
        yield


class _Pages(TypedDict):
    """The uvicorn settings the console's web server is given (PAGES)."""

    timeout_graceful_shutdown: int
    log_config: None
    access_log: bool
    ws: type[PageSocket]
    ws_per_message_deflate: bool


#: the console's web server's settings (serve_console): each page request is not the window's
#: (PUSH and REQUEST lines are); the page's socket (/ws) drops a page that stops reading
#: (live_ui.PageSocket) and sends its frames uncompressed
PAGES: _Pages = {
    "timeout_graceful_shutdown": 10,
    "log_config": None,
    "access_log": False,
    "ws": PageSocket,
    "ws_per_message_deflate": False,
}


async def serve_console(daemon: Daemon, stop: asyncio.Event, sock: socket.socket) -> None:
    """Serve the console's pages and routes (server.app) and the page's socket until `stop`.

    The page's socket is on `sock`. They read the daemon's one bus (console_feed.bind_daemon):
    one program, one copy of every value.
    """
    console_feed.bind_daemon(daemon)
    web = _PagesServer(uvicorn.Config(server.app, **PAGES))
    host, port = sock.getsockname()[:2]
    log.info("console: serving the pages on http://%s:%s", host, port)
    serving = asyncio.create_task(web.serve(sockets=[sock]), name="console web server")
    await asyncio.wait({serving, asyncio.ensure_future(stop.wait())}, return_when="FIRST_COMPLETED")
    web.should_exit = True
    await serving


#: the daemon's window alone (_start_log), never its log file
WINDOW_ONLY = logging.getLogger("capture.window")

#: each streamed bus topic kind -> the Schwab service it is (a book message names its own) and
#: the key holding Schwab's item as sent
STREAM_ITEM = {
    "quote": ("LEVELONE_EQUITIES", "native"),
    "bar1m": ("CHART_EQUITY", "native"),
    "optquote": ("LEVELONE_OPTIONS", "content"),
    "news": ("NEWS_HEADLINE", "content"),
    "book": (None, "content"),
}


def pushed_fields(item: dict[str, Any]) -> str:
    """Return one pushed Schwab item, readable on one line.

    Each field Schwab sent in it is shown, a single value as sent, a list (a book's levels) as
    how many it holds.
    """
    return ", ".join(
        f"{k} [{len(v)}]" if isinstance(v, list) else f"{k} {v}"
        for k, v in item.items()
        if k != "key"
    )


async def show_stream(bus: MessageBus, stop: asyncio.Event, every: float = 1.0) -> None:
    """Show the stream in the daemon's window, every `every` seconds.

    Per Schwab service: the messages Schwab pushed
    (PUSH: none of it was asked for; the REQUEST lines are the REST calls), how many symbols they
    came for, and the newest one's fields as Schwab sent them (pushed_fields), so the operator
    can watch what the stream carries.
    """
    sub = bus.subscribe("", policy=LOG)
    try:
        while not stop.is_set():
            await asyncio.sleep(every)
            seen: dict[str, list[Any]] = {}
            while not sub.queue.empty():
                topic, msg = sub.queue.get_nowait()
                kind = topic.split(".", 1)[0]
                if kind not in STREAM_ITEM:
                    continue
                service, item = STREAM_ITEM[kind]
                if service is None:
                    service = msg["service"]
                if service not in seen:
                    seen[service] = [0, set(), None]
                entry = seen[service]
                entry[0] += 1
                entry[1].add(msg["symbol"])
                entry[2] = (msg["symbol"], msg[item])
            for service, (n, symbols, (symbol, item)) in sorted(seen.items()):
                WINDOW_ONLY.info(
                    "PUSH %s: %d messages, %d symbols | newest %s: %s",
                    service,
                    n,
                    len(symbols),
                    symbol,
                    pushed_fields(item),
                )
    finally:
        bus.unsubscribe(sub)


#: trading sessions the stream's tables keep (the operator's setting), and how often keep_sessions
#: looks
SESSIONS_KEPT = 5
KEEP_EVERY_SEC = 60.0


async def keep_sessions(daemon: Daemon, stop: asyncio.Event) -> None:
    """Keep the newest SESSIONS_KEPT sessions, once after each close of the last option market.

    Once after each close of the last option market (time_et.options_closed_at), the writer
    removes every row received before the newest SESSIONS_KEPT sessions began
    (time_et.sessions_since, from Schwab's /markets answers; CaptureWriter.prune). While today's
    market is unknown or open, or fewer sessions are held, nothing is removed: never on a
    guess.
    """
    kept_for = warned_for = None
    stopped = asyncio.ensure_future(stop.wait())
    try:
        while not stopped.done():
            now = datetime.fromtimestamp(daemon.clock(), ET)
            closed = options_closed_at(now) if option_market_open(now) is False else None
            if closed is not None and closed != kept_for:
                since = sessions_since(now, SESSIONS_KEPT)
                if since is not None:
                    daemon.writer.prune(since.timestamp())
                    log.info(
                        "keep: removing rows received before %s (the newest %d sessions stay)",
                        ct_label(since.timestamp()),
                        SESSIONS_KEPT,
                    )
                    kept_for = closed
                elif closed != warned_for:
                    log.warning(
                        "keep: fewer than %d sessions held from Schwab's /markets; nothing removed",
                        SESSIONS_KEPT,
                    )
                    warned_for = closed
            await asyncio.wait({stopped}, timeout=KEEP_EVERY_SEC)
    finally:
        stopped.cancel()


def _worker_ended(worker: asyncio.Future[None]) -> None:
    """Handle the chain sweep's end: one that ended on an error is logged with its traceback."""
    if not worker.cancelled() and worker.exception() is not None:
        e = worker.exception()
        log.error("chain sweep: ended on %s: %s", type(e).__name__, e, exc_info=e)


async def run_chains(
    daemon: Daemon,
    db_path: Path | str,
    schwab_client: Callable[[], object],
    stop: asyncio.Event,
    *,
    failures: CaptureWriter,
) -> None:
    """Run the chain sweep (calibration.complete_chain_capture.ChainSweep) on its own thread.

    So the stream never waits on a chain; each chain part is published on the event loop, and
    the bus keeps each ticker's newest whole chain (stream_spine.MessageBus._chain). The sweep
    reads
    each option's LEVELONE_OPTIONS record from the bus for its Greeks. A chain whose history write
    fails is kept by `failures`, the daemon's writer (its failures ride the heartbeat). A sweep
    that ends on an error is logged with it (_worker_ended): its thread has no error output of
    its own to reach. It ends with the sweep.
    """
    loop = asyncio.get_running_loop()
    halt = threading.Event()
    sweep = ChainSweep(
        db_path,
        daemon.watchlist,
        lambda topic, msg: loop.call_soon_threadsafe(daemon.bus.publish, topic, msg),
        failures=failures,
        streamed=daemon.option_record,
        shown=daemon.shown,
    )
    daemon.chains = sweep
    worker = loop.run_in_executor(None, sweep.work, schwab_client, halt)
    worker.add_done_callback(_worker_ended)
    stopped = asyncio.ensure_future(stop.wait())
    try:
        await asyncio.wait({worker, stopped}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stopped.cancel()
        halt.set()
        await asyncio.gather(worker, return_exceptions=True)


def one_schwab_client(build: Callable[[], SchwabClientState]) -> Callable[[], object]:
    """Return the daemon's one Schwab client, for the stream and every chain request.

    It comes as a function that returns it: built (`build()`, a SchwabClientState) when first
    asked for, then kept for the daemon's life. Its session is the one owner of the token: it
    refreshes it (one refresh at a time, schwab_client.OneRefreshSession) and writes it to the
    token file. A build that fails raises, and the next ask builds again; a built client is
    never replaced.
    """
    built: list[object] = []
    building = threading.Lock()

    def schwab_client() -> object:
        with building:
            if not built:
                state = build()
                if not state.ok or state.client is None:
                    raise ConnectionError(f"no Schwab client ({state.message})")
                built.append(state.client)
            return built[0]

    return schwab_client


def open_sockets() -> socket.socket:
    """Open the program's one listening socket before anything serves it.

    It serves the console's pages and the page's price socket (/ws), on the port ED_CONSOLE_PORT
    names, read as it opens (a test's program: a free port of its own). The port it holds is
    known at once (port 0: the system's pick as it binds, no gap for another program to take it).
    A port another program holds ends the start here, naming it.
    """
    return socket.create_server((CONSOLE_HOST, int(os.environ.get("ED_CONSOLE_PORT", "8000"))))


async def run(lock_fd: int, request: StopRequest) -> int:
    """Run the whole daemon until the stop.

    The stop is Ctrl+C in its window (stop_on_interrupt) or its stop `request` set by launch.py
    stop (stop_on_request). Its writer, its web server, the price rows' beat, the chain sweep,
    the market follower, the stop request's waiter and the Schwab connection each run until the
    stop; one that ends first ends the daemon with an error naming it, which
    start_capture_daemon.bat restarts. The port its socket holds goes in its lock (`lock_fd`),
    where launch.py reads it.
    """
    pages = open_sockets()
    record_ports(lock_fd, Ports(console=pages.getsockname()[1]))
    load_dotenv_file()
    cfg = build_config()
    schwab_client = one_schwab_client(
        lambda: build_client_from_token(
            api_key=cfg.api_key, app_secret=cfg.app_secret, token_path=cfg.token_path
        )
    )
    stop = asyncio.Event()
    stop_on_interrupt(stop, asyncio.get_running_loop())
    bus, health = MessageBus(), HealthRegistry()
    writer = CaptureWriter()
    daemon = Daemon(
        bus,
        health,
        stored_watchlist(writer.db_path),
        on_page=lambda: selected(server.app.state),
    )
    daemon.writer = writer
    writer.saves = daemon.saves
    wsub = bus.subscribe("", policy=LOG)  # the record of every message
    tasks = [
        asyncio.create_task(writer.run(wsub, stop=stop), name="writer"),
        asyncio.create_task(
            run_chains(daemon, writer.db_path, schwab_client, stop, failures=writer),
            name="chain sweep",
        ),
        asyncio.create_task(record_feed_status(daemon, stop), name="feed status"),
        asyncio.create_task(show_stream(bus, stop), name="stream window"),
        asyncio.create_task(keep_sessions(daemon, stop), name="keep"),
        asyncio.create_task(daemon.follow_market(stop), name="market follower"),
        asyncio.create_task(
            serve_live_ui(
                stop,
                state=server.app.state,
                heartbeat_fn=daemon.status,
                panels=server.PAGE_PANELS,
                priced=server.PRICED_PANELS,
                on_select=daemon.page_selected,
            ),
            name="live ui",
        ),
        asyncio.create_task(serve_console(daemon, stop, pages), name="console"),
        asyncio.create_task(stop_on_request(stop, request), name="stop request"),
    ]
    try:
        await asyncio.sleep(0)  # servers subscribe before the first message
        tasks.append(asyncio.create_task(daemon.run(schwab_client, stop), name="schwab connection"))
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        ended = None if stop.is_set() else done.pop()
    finally:
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
    if ended is not None:
        raise RuntimeError(
            f"the capture daemon's {ended.get_name()} ended before the stop"
        ) from ended.exception()
    return EXIT_STOPPED


def main() -> int:
    if sys.argv[1:]:  # everything it needs comes from the console; no switch can move it
        print(f"the capture daemon takes no arguments (got {sys.argv[1:]})", file=sys.stderr)
        return 2
    # a worktree must not run a live daemon against production's runtime
    binding = runtime_layout.live_binding_error()
    if binding is not None:
        print(f"CAPTURE DAEMON REFUSED: {binding}", file=sys.stderr, flush=True)
        return 2
    _start_log()
    request = StopRequest()  # before the lock: a program the lock names can always be asked
    try:
        fd, lock = acquire_owner_lock()
        try:
            return asyncio.run(run(fd, request))
        except KeyboardInterrupt:
            log.info("capture daemon: stopped by Ctrl+C in its window")
            return 0
        except BaseException:
            log.exception("capture daemon: ended by an error")
            raise
        finally:
            release_owner_lock(fd, lock)
    finally:
        request.close()
