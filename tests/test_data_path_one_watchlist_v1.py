"""The one watchlist and the daemon's subscriptions, Schwab to the screen, through the real code.

The capture daemon's connection (capture.Daemon.run) on the real schwab-py StreamClient, logged in
to Schwab's streamer played locally (tests/schwab_stream_standin.py) through Schwab's REST host
played locally (tests/schwab_rest_standin.py); the console in the daemon's program
(streaming.bind_daemon, its feed reading the daemon's bus) and its routes (server.post_watchlist,
delete_watchlist); the list the page's socket carries on each beat, the daemon's status
(capture.Daemon.status).

Real data: Schwab's /quotes answers to SPY, TSLA, SPCX, META, QQQ, IWM and ZQZQZ asked alone, as
the watchlist check asks (2026-10-07; ZQZQZ is named in errors.invalidSymbols); Schwab's answers to
an ADD past LEVELONE_OPTIONS' limit as logged on 2026-10-07 04:40:39 (code 19, then code 24 "ADD
command failed"); SPY's captured 2026-11-20 chain with its stored price and MRVL's full chain, as
the option rule's inputs on the daemon's bus. STAND-INS (named in the stand-ins): the streamer's
login, a code-0 answer's message, the limit a test sets; the daemon's clock at each chain's capture.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import live_market_plane as lmp
import server
import time_et
from app.market_data.schwab.streaming import capture, live_ui
from app.market_data.schwab.streaming.live_push import MARKET_CONTEXT
from app.options.order_flow import streaming as ofs
from feed import connection
from feed.chain_sweep import ChainSweep, chain_messages
from feed.schwab_client import build_client_from_token, flatten_chain_contracts
from option_contract import read_chain
from push import surface as push_surface
from state import level_store
from stream_spine import LOG, CaptureWriter, HealthRegistry, MessageBus, quote_msg
from tests.feed_live_helper import daemon_status, mark_feed_down
from tests.page_on_socket import pages
from tests.real_chains import CRWD
from tests.schwab_rest_standin import CHECKS, QUOTES, LocalSchwab
from tests.schwab_stream_standin import FIELD_REPLIES, HIGHEST_FIELD, LocalStreamer, refusal
from time_et import ET

#: SPY's 2026-11-20 contracts (442) and the price stored with them
SPY_CHAIN = json.loads(
    (Path(__file__).parent / "fixtures" / "real_spy_2026_11_20_chain_and_quotes.json").read_text(
        encoding="utf-8"
    )
)
EQUITY = ("LEVELONE_EQUITIES", "CHART_EQUITY", "NEWS_HEADLINE", "NYSE_BOOK", "NASDAQ_BOOK")


async def _until(cond, seconds: float = 15.0) -> None:
    deadline = time_et.elapsed() + seconds
    while not cond():
        assert time_et.elapsed() < deadline, "not reached in time"
        await asyncio.sleep(0.02)


class _Schwab:
    """The local streamer and REST host, and the daemon's client of them as the daemon builds it."""

    def __init__(self, tmp_path, limits: dict, data: dict, lag: float = 0.0):
        self.streamer = LocalStreamer(limits, data, lag)
        self.rest = LocalSchwab(self.streamer.url)
        self.client = self.rest.client(tmp_path)

    def close(self) -> None:
        self.streamer.close()
        self.rest.close()


def _answers(log) -> list[tuple[str, str, int, str]]:
    """(service, command, code, Schwab's message) of each answer the daemon recorded, in order."""
    out = []
    while not log.queue.empty():
        topic, msg = log.queue.get_nowait()
        if topic.startswith("sub."):
            out.append((msg["service"], msg["command"], msg["code"], msg["reason"]))
    return out


def _market(bus, ticker: str, contracts: list[dict], price: float, ts: float) -> None:
    """`ticker`'s chain and price on the daemon's bus: the option rule's inputs.

    As the chain sweep and the stream publish them.
    """
    for topic, msg in chain_messages(ticker, contracts, ts, price, ts, False):
        bus.publish(topic, msg)
    bus.publish(
        f"quote.{ticker}",
        quote_msg(
            symbol=ticker,
            last=price,
            src="schwab_l1",
            ts_recv=ts,
            native={"key": ticker, "LAST_PRICE": price},
        ),
    )


async def _held_when_settled(daemon, stop: asyncio.Event, tasks: list) -> dict:
    """Ask once more with nothing changed, then stop the daemon; return what it held then.

    Its logout, answered before run() ends, follows on the same connection every request it made:
    Schwab has received each one.
    """
    daemon.connection.ask()  # nothing changed: nothing is asked
    await _until(lambda: not daemon.connection.wake.is_set())  # it has taken what is queued
    connected = dict(daemon.connection.held)
    stop.set()
    await asyncio.wait_for(asyncio.gather(*tasks), 10)
    return connected


def _forget_price(ticker: str) -> None:
    """Drop the plane row `ticker`'s price wrote."""
    lmp._by_ticker.pop(ticker, None)
    lmp._fields_by_ticker.pop(ticker, None)


def test_the_daemon_subscribes_once_and_each_of_schwabs_answers_reaches_its_own_request(tmp_path):
    """2026-10-07 (stream_capture.log 04:40:39): Schwab answered a refused ADD twice.

    Code 19 and then code 24, and every request after it was logged "unexpected requestid": each
    answer had been taken as the next request's. Now one reader matches each answer to its
    request by its requestid. Every watchlist ticker is asked for on each equity service and the
    market context on quotes, bars and news, in one request per service; SPY's 442
    2026-11-20 contracts on LEVELONE_OPTIONS past a limit of 2 (a stand-in limit) get Schwab's
    refusal, both answers recorded as sent. The refusal states the limit, so that service is
    asked once more, a SUBS of the first 2 of the option rule's order, which Schwab accepts; on
    OPTIONS_BOOK, where the stand-in sets no limit, all 442 are asked once and held. Nothing
    else is asked again.
    """
    schwab = _Schwab(
        tmp_path,
        limits={"LEVELONE_OPTIONS": 2},
        data={"LEVELONE_EQUITIES": FIELD_REPLIES["level_one_equities_data"]},
    )
    bus = MessageBus()
    log = bus.subscribe("sub.", policy=LOG)
    quotes = bus.subscribe("quote.SPY", policy=LOG)
    daemon = capture.Daemon(
        bus, HealthRegistry(), ["SPY", "TSLA"], clock=lambda: SPY_CHAIN["capture_ts_utc"]
    )
    symbols = sorted(c["symbol"] for c in SPY_CHAIN["chain"])

    async def go():
        stop = asyncio.Event()
        tasks = [
            asyncio.create_task(daemon.run(lambda: schwab.client, stop)),
            asyncio.create_task(daemon.follow_market(stop)),
        ]
        _market(bus, "SPY", SPY_CHAIN["chain"], SPY_CHAIN["spot"], SPY_CHAIN["capture_ts_utc"])
        await _until(
            lambda: len(schwab.streamer.answers) >= 10
        )  # login + 8 requests, one answered twice
        # the daemon has recorded each answer but the login's, and taken SPY's data entry (its
        # quote follows the one _market published)
        await _until(lambda: log.queue.qsize() == 9 and quotes.queue.qsize() >= 2)
        return await _held_when_settled(daemon, stop, tasks)

    try:
        held = asyncio.run(go())
    finally:
        schwab.close()
        _forget_price("SPY")
    asked = [
        (r["service"], r["command"], sorted(r["parameters"]["keys"].split(",")))
        for r in schwab.streamer.requests
        if r["service"] != "ADMIN"
    ]
    assert schwab.streamer.requests[-1]["command"] == "LOGOUT", "every request came before it"
    context = sorted(["SPY", "TSLA", *MARKET_CONTEXT])
    order = list(daemon.option_order)  # SPY's contracts in the option rule's order
    assert sorted(order) == symbols  # each of the 442 once: no number of ours caps a service
    assert sorted(asked) == sorted(
        [
            *[
                (svc, "SUBS", context)
                for svc in ("LEVELONE_EQUITIES", "CHART_EQUITY", "NEWS_HEADLINE")
            ],
            *[(svc, "SUBS", ["SPY", "TSLA"]) for svc in ("NYSE_BOOK", "NASDAQ_BOOK")],
            ("LEVELONE_OPTIONS", "SUBS", symbols),
            ("OPTIONS_BOOK", "SUBS", symbols),
            ("LEVELONE_OPTIONS", "SUBS", sorted(order[:2])),  # within the limit Schwab stated
        ]
    )
    answers = _answers(log)
    assert [a for a in answers if a[0] == "LEVELONE_OPTIONS"] == [
        ("LEVELONE_OPTIONS", "SUBS", 19, refusal("LEVELONE_OPTIONS", 2, len(symbols) - 2)),
        ("LEVELONE_OPTIONS", "SUBS", 0, "SUBS command succeeded"),  # it kept the 2 that fit
        ("LEVELONE_OPTIONS", "SUBS", 0, "SUBS command succeeded"),
    ], "both of Schwab's answers to the refused request, as sent, then its answer to the next"
    assert all(code == 0 for svc, _c, code, _m in answers if svc != "LEVELONE_OPTIONS"), answers
    assert held["NYSE_BOOK"] == {"SPY", "TSLA"} and held["OPTIONS_BOOK"] == set(symbols)
    # the daemon holds what Schwab holds: the first 2 of the rule's order
    assert held["LEVELONE_OPTIONS"] == set(order[:2])
    assert schwab.streamer.held["LEVELONE_OPTIONS"] == order[:2]
    # each request asks for every field number Schwab accepts on its service (code 22 past it), and
    # the fields Schwab sends past its Streamer Guide (LEVELONE_EQUITIES 52-56) reach SPY's record
    # as sent
    assert {
        (r["service"], r["parameters"]["fields"])
        for r in schwab.streamer.requests
        if r["service"] != "ADMIN"
    } == {(svc, ",".join(map(str, range(HIGHEST_FIELD[svc] + 1)))) for svc in connection.SERVICES}
    sent = next(i for i in FIELD_REPLIES["level_one_equities_data"]["content"] if i["key"] == "SPY")
    published = []
    while not quotes.queue.empty():
        published.append(quotes.queue.get_nowait()[1])
    frame_ts = FIELD_REPLIES["level_one_equities_data"]["timestamp"]
    [native] = [m["native"] for m in published if m["schwab_ts"] == frame_ts]  # Schwab's frame
    assert {k: native.get(k) for k in ("52", "53", "54", "55", "56")} == {
        k: sent[k] for k in ("52", "53", "54", "55", "56")
    }


def test_a_subscription_split_under_schwabs_message_limit_keeps_every_part(tmp_path):
    """MRVL's 2,432 contracts are more than one request carries, so they are sent in parts.

    MRVL's 2,432 contracts (its full chain as Schwab sent it, tests/fixtures/
    real_mrvl_full_chain_vs_strike_window.json), MRVL alone on the watchlist so the rule streams
    every one, are more than one request carries, so the subscription is sent in parts. A SUBS
    replaces all a service holds (measured live 2026-10-07: of 3,001 contracts sent as SUBS 2,181 +
    SUBS 819 + ADD 1, only the last 820 ever updated), so only the first part is SUBS and the rest
    ADD: Schwab holds them all.
    """
    mrvl = json.loads(
        (
            Path(__file__).parent / "fixtures" / "real_mrvl_full_chain_vs_strike_window.json"
        ).read_text(encoding="utf-8")
    )
    contracts = flatten_chain_contracts(mrvl["full"])
    symbols = sorted(ct["symbol"] for ct in contracts)
    schwab = _Schwab(tmp_path, limits={}, data={})  # no limit hit, nothing streamed
    bus = MessageBus()
    daemon = capture.Daemon(bus, HealthRegistry(), ["MRVL"], clock=lambda: mrvl["captured_utc"])

    async def go():
        stop = asyncio.Event()
        tasks = [
            asyncio.create_task(daemon.run(lambda: schwab.client, stop)),
            asyncio.create_task(daemon.follow_market(stop)),
        ]
        _market(bus, "MRVL", contracts, mrvl["full"]["underlying"]["last"], mrvl["captured_utc"])
        await _until(lambda: len(daemon.connection.held["LEVELONE_OPTIONS"]) == len(symbols))
        stop.set()
        await asyncio.wait_for(asyncio.gather(*tasks), 10)

    try:
        asyncio.run(go())
    finally:
        schwab.close()
        _forget_price("MRVL")
    commands = [c for c, _k in schwab.streamer.asked("LEVELONE_OPTIONS")]
    assert len(commands) > 1 and commands == ["SUBS"] + ["ADD"] * (len(commands) - 1)
    assert sorted(schwab.streamer.held["LEVELONE_OPTIONS"]) == symbols, "Schwab holds every part"


@pytest.mark.parametrize(
    ("code", "msg"),
    [
        (22, "SUBS command failed"),  # as Schwab answered a field number it does not take
        (19, "You've reached the maximum number of symbols allowed."),  # no limit in its text
    ],
)
def test_a_refusal_that_states_no_limit_is_recorded_and_not_asked_again(tmp_path, code, msg):
    """Schwab refuses OPTIONS_BOOK's request and states no symbol limit to fit within.

    Induced condition: the streamer here answers each OPTIONS_BOOK request with `code` and `msg`
    (code 19's text without its limit is not one Schwab has sent). The daemon records the answer
    as sent, holds nothing on that service, asks it for nothing more and keeps its connection, on
    which LEVELONE_OPTIONS holds SPY's 442 contracts.
    """
    schwab = _Schwab(tmp_path, limits={}, data={})
    answer = schwab.streamer.answer

    def refuse(req: dict) -> list[dict]:
        frames = answer(req)
        if req["service"] == "OPTIONS_BOOK":
            frames[0]["response"][0]["content"] = {"code": code, "msg": msg}
        return frames

    schwab.streamer.answer = refuse
    bus = MessageBus()
    log = bus.subscribe("sub.OPTIONS_BOOK", policy=LOG)
    daemon = capture.Daemon(
        bus, HealthRegistry(), ["SPY"], clock=lambda: SPY_CHAIN["capture_ts_utc"]
    )
    symbols = {c["symbol"] for c in SPY_CHAIN["chain"]}

    async def go():
        stop = asyncio.Event()
        tasks = [
            asyncio.create_task(daemon.run(lambda: schwab.client, stop)),
            asyncio.create_task(daemon.follow_market(stop)),
        ]
        _market(bus, "SPY", SPY_CHAIN["chain"], SPY_CHAIN["spot"], SPY_CHAIN["capture_ts_utc"])
        await _until(
            lambda: log.queue.qsize() == 1 and daemon.connection.held["LEVELONE_OPTIONS"] == symbols
        )
        return await _held_when_settled(daemon, stop, tasks)

    try:
        held = asyncio.run(go())
    finally:
        schwab.close()
        _forget_price("SPY")
    asked = [(c, set(keys)) for c, keys in schwab.streamer.asked("OPTIONS_BOOK")]
    assert asked == [("SUBS", symbols)], "asked once, and not again"
    assert _answers(log) == [("OPTIONS_BOOK", "SUBS", code, msg)]
    assert held["OPTIONS_BOOK"] == frozenset() and held["LEVELONE_OPTIONS"] == symbols
    assert len([r for r in schwab.streamer.requests if r["command"] == "LOGIN"]) == 1


def test_a_dropped_connection_subscribes_once_again_with_one_session_at_a_time(tmp_path):
    """Schwab drops the socket: the daemon logs out, connects again and asks for everything.

    It connects again (a new session that holds nothing) and asks for everything once again; the
    frames are taken whole (no size cap).
    """
    schwab = _Schwab(tmp_path, limits={}, data={})  # no limit hit, nothing streamed
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), ["SPY"])

    def subs():
        return [
            r
            for r in schwab.streamer.requests
            if r["command"] == "SUBS" and r["service"] == "NYSE_BOOK"
        ]

    async def go():
        stop = asyncio.Event()
        run = asyncio.create_task(daemon.run(lambda: schwab.client, stop))
        await _until(lambda: len(subs()) == 1 and daemon.connection.held["NYSE_BOOK"])
        await daemon.connection.stream._socket.close()  # the socket is gone
        await _until(lambda: len(subs()) == 2 and daemon.connection.held["NYSE_BOOK"])
        stop.set()
        await asyncio.wait_for(run, 10)

    try:
        asyncio.run(go())
    finally:
        schwab.close()
    logins = [r for r in schwab.streamer.requests if r["command"] == "LOGIN"]
    assert len(logins) == 2 and [r["parameters"]["keys"] for r in subs()] == ["SPY", "SPY"]


def test_a_request_schwab_never_answers_ends_the_connection(tmp_path):
    """A request unanswered for REQUEST_TIMEOUT_SEC means the connection is broken.

    It ends with that reason (Schwab's streamer here takes NYSE_BOOK requests and never answers
    them, while its heartbeats carry Schwab's time past the request).
    """
    schwab = _Schwab(tmp_path, limits={}, data={})  # no limit hit, nothing streamed
    answer = schwab.streamer.answer
    schwab.streamer.answer = lambda req: [] if req["service"] == "NYSE_BOOK" else answer(req)
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), ["SPY"])
    started = time_et.elapsed()

    async def go():
        await daemon.connection.run_connection(schwab.client, asyncio.Event())

    try:
        try:
            asyncio.run(asyncio.wait_for(go(), connection.REQUEST_TIMEOUT_SEC + 10))
            raise AssertionError("the connection did not end")
        except ConnectionError as e:
            assert (
                str(e) == f"no answer to NYSE_BOOK SUBS in {connection.REQUEST_TIMEOUT_SEC:.0f} s"
            )
    finally:
        schwab.close()
    assert time_et.elapsed() - started >= connection.REQUEST_TIMEOUT_SEC
    assert daemon.connection.stream is None, "the broken session is logged out and dropped"


#: How far behind Schwab's stream the daemon's reader ran, measured in production's log
#: (logs/stream_capture.2026-11-09.log): Schwab stamped its answer to NASDAQ_BOOK SUBS (requestid
#: 5) 1794237724246 ms, 09:22:04.246 CT, 0.400 s after the daemon sent it, and the daemon took it
#: at 09:22:22.213 CT; at 09:22:22.335 the connection ended "no answer to LEVELONE_OPTIONS SUBS in
#: 15 s", and the logout that followed read Schwab's answer to that SUBS (requestid 6) waiting next.
READER_LAG_SEC = 22.213 - 4.246


def test_an_answer_schwab_sent_at_once_but_read_late_keeps_the_connection(tmp_path):
    """Schwab answers each request at once; its answers reach the reader 17.967 s later.

    As on 2026-11-09 (READER_LAG_SEC): the reader ran behind Schwab's stream, so Schwab's
    answers waited behind the frames before them. The connection had ended at 15 s on this
    computer's clock, as if Schwab had not answered, and with it every option subscription; a
    reconnect asked Schwab for all of them again. Schwab's own time on the frames read says it
    answered: the connection stays, and every request is answered and held.
    """
    schwab = _Schwab(tmp_path, limits={}, data={}, lag=READER_LAG_SEC)
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), ["SPY"])

    async def go():
        stop = asyncio.Event()
        run = asyncio.create_task(daemon.connection.run_connection(schwab.client, stop))
        await _until(lambda: run.done() or all(daemon.connection.held[s] for s in EQUITY), 30)
        held = dict(daemon.connection.held)
        answers = [s.answers for s in daemon.connection._sent.values()]
        stop.set()
        await asyncio.wait_for(run, 10)  # the connection's own error, raised
        return held, answers

    started = time_et.elapsed()
    try:
        held, answers = asyncio.run(go())
    finally:
        schwab.close()
    assert time_et.elapsed() - started > READER_LAG_SEC > connection.REQUEST_TIMEOUT_SEC
    assert [r["command"] for r in schwab.streamer.requests].count("LOGIN") == 1, "one session"
    wanted = {svc: frozenset(want) for svc, want in daemon.wanted().items()}
    assert {svc: held[svc] for svc in wanted} == wanted, "every request answered and held"
    assert answers == [1] * len(EQUITY), answers


def test_an_added_ticker_is_checked_once_asked_for_everywhere_and_a_removed_one_no_more(tmp_path):
    """Through the console's route, in the daemon's program: tickers added and removed.

    TSLA added is checked with one
    /quotes request (Schwab quotes it), added, asked for on every equity service and by the
    chain sweep, and stored; ZQZQZ (Schwab names it in errors.invalidSymbols) is not added; TSLA
    removed is asked for no more. The stored list is the daemon's after a restart.
    """
    schwab = _Schwab(tmp_path, limits={}, data={})  # no limit hit, nothing streamed
    db = tmp_path / "stream_capture.db"
    bus = MessageBus()
    daemon = capture.Daemon(bus, HealthRegistry(), ["SPY"])
    daemon.chains = ChainSweep(
        tmp_path / "ed_console.db",
        daemon.watchlist,
        lambda _t, _m: None,
        failures=CaptureWriter(db),
        streamed=daemon.option_record,
    )

    def asked(svc):
        return [(c, k) for c, k in schwab.streamer.asked(svc)]

    async def go():
        stop = asyncio.Event()
        writer = CaptureWriter(db, batch_rows=1, batch_sec=0.01)
        tasks = [
            asyncio.create_task(writer.run(bus.subscribe("", policy=LOG), stop=stop)),
            asyncio.create_task(daemon.run(lambda: schwab.client, stop)),
        ]
        await _until(lambda: daemon.connection.held["NASDAQ_BOOK"] == {"SPY"})
        ofs.bind_daemon(daemon)  # the console in the daemon's program (capture.serve_console)
        assert ofs.start_order_flow_stream()
        records = bus.subscribe("watchlist", policy=LOG)
        try:
            beats = [daemon.status(time_et.now())]  # a beat built before the add
            added = json.loads((await server.post_watchlist("tsla")).body)
            await _until(lambda: daemon.connection.held["NASDAQ_BOOK"] == {"SPY", "TSLA"})
            swept_after_add = list(daemon.chains.watchlist)
            beats.append(daemon.status(time_et.now()))
            invalid = json.loads((await server.post_watchlist("ZQZQZ")).body)
            removed = json.loads((await server.delete_watchlist("TSLA")).body)
            beats.append(daemon.status(time_et.now()))
            await _until(lambda: daemon.connection.held["NASDAQ_BOOK"] == {"SPY"})
        finally:
            ofs.stop_order_flow_stream()
            ofs.bind_daemon(None)
            stop.set()
            await asyncio.gather(*tasks)
        sent = [records.queue.get_nowait()[1] for _ in range(records.queue.qsize())]
        return added, invalid, removed, swept_after_add, beats, sent

    try:
        added, invalid, removed, swept_after_add, beats, sent = asyncio.run(go())
    finally:
        schwab.close()
    assert swept_after_add == ["SPY", "TSLA"], "the chain sweep fetches an added ticker"
    # the page's next beat carries each change (live_ui beat: the daemon's status)
    assert [b["watchlist"] for b in beats] == [["SPY"], ["SPY", "TSLA"], ["SPY"]]
    # each answer is stamped as its record was, on the clock each beat is stamped by: a beat built
    # before the add is older than the add's answer, one built after it is not
    assert [r["op"] for r in sent] == ["added", "invalid", "removed"]
    assert beats[0]["ts"] < added["ts"] <= beats[1]["ts"]
    assert added == {
        "ok": True,
        "op": "added",
        "ticker": "TSLA",
        "tickers": ["SPY", "TSLA"],
        "ts": sent[0]["ts_recv"],
        "status": 200,
        "answer": CHECKS["TSLA"]["body"],
        "text": "TSLA is added to the watchlist",
    }
    assert invalid == {
        "ok": False,
        "op": "invalid",
        "ticker": "ZQZQZ",
        "tickers": ["SPY", "TSLA"],
        "ts": sent[1]["ts_recv"],
        "status": 200,
        "answer": {"errors": {"invalidSymbols": ["ZQZQZ"]}},
        "text": 'ZQZQZ is not added: Schwab does not quote it ({"errors": {"invalidSymbols": '
        '["ZQZQZ"]}})',
    }
    assert removed == {
        "ok": True,
        "op": "removed",
        "ticker": "TSLA",
        "tickers": ["SPY"],
        "ts": sent[2]["ts_recv"],
        "status": None,
        "answer": None,
        "text": "TSLA is removed from the watchlist",
    }
    assert [q["symbols"] for q in schwab.rest.asked(QUOTES)] == ["TSLA", "ZQZQZ"], (
        "one check per add"
    )
    for svc in EQUITY:
        assert [(c, k) for c, k in asked(svc) if "TSLA" in k] == [
            ("ADD", ["TSLA"]),
            ("UNSUBS", ["TSLA"]),
        ], svc
    assert not any(
        "ZQZQZ" in r["parameters"]["keys"]
        for r in schwab.streamer.requests
        if "keys" in r["parameters"]
    )
    assert daemon.chains.watchlist == ["SPY"], "and stops fetching a removed one"
    assert capture.stored_watchlist(db) == ["SPY"], "the newest stored list"


def test_with_the_watchlist_empty_the_sweep_asks_for_nothing_and_waits(tmp_path, caplog):
    """An empty watchlist in an open session (Wednesday 2026-10-07 10:00 ET).

    No request to Schwab and no rotation, until a ticker is added.
    """
    schwab = LocalSchwab()
    sweep = ChainSweep(
        tmp_path / "ed_console.db",
        [],
        lambda _t, _m: None,
        clock=lambda: datetime(2026, 10, 7, 10, 0, tzinfo=ET).timestamp(),
        failures=CaptureWriter(tmp_path / "stream_capture.db"),
        streamed=lambda _s: None,
    )
    client = schwab.client(tmp_path)
    try:
        with caplog.at_level("INFO", logger="chain_history"):
            # two passes of the sweep's thread (ChainSweep.work runs one a second): each asks
            # for nothing, so the thread waits
            passes = [sweep.step(lambda: client, threading.Event()) for _ in range(2)]
    finally:
        schwab.close()
    assert passes == [False, False], "a pass asked Schwab for something"
    assert schwab.requests == [], "nothing asked of Schwab"
    assert not [r for r in caplog.records if "chain rotation" in r.getMessage()], (
        "no rotation of nothing"
    )


#: the heatmap's window as the page asks it: Auto, following the price, every column
_HEATMAP = {"scope": "auto", "centre": None, "shift": 0, "cols": None, "expiry": None}


def _surface(tk) -> dict:
    # the panel as the page's socket asks it: requested while a page has the ticker selected
    requested = tk in live_ui.selected(server.app.state)
    return push_surface.gamma_surface(tk, time_et.now(), _HEATMAP, requested=requested)


def test_a_viewed_ticker_warms_only_on_the_watchlist_and_a_silent_daemon_says_so_first():
    """The gamma surface's reason for a ticker with no surface.

    From push.surface.gamma_surface: on the watchlist it warms (its chain is coming); off
    it, it says it is not on the watchlist; with the daemon's heartbeat late, the last list still
    stands and the reason says the daemon is not reporting; a chain Schwab refused says Schwab's
    answer.
    """
    on, off = "ZZWLON", "ZZWLOFF"
    # levels, no surface: CRWD's real chain delivered now with no price held
    delivered = time_et.now()
    server._publish_levels(
        off,
        read_chain(CRWD.chain),
        delivered,
        chain_spot=(None, None),
        now=datetime.fromtimestamp(delivered, ET),
    )
    try:
        with pages() as served:
            for tk in (on, off):
                served.open(tk)
            lmp.record_feed_heartbeat(
                daemon_status(time_et.now(), schwab_socket_open=True, watchlist=[on])
            )
            d_on, d_off = (_surface(tk) for tk in (on, off))
            assert (d_on["warming"], d_on["reason"]) == (
                True,
                "no terrain snapshot has been computed yet",
            )
            assert (d_off["warming"], d_off["reason"]) == (
                False,
                "no chain is fetched for this ticker: it is not on the watchlist",
            )
            # the heatmap's banner and heading for each, as the program says them
            assert (d_on["banner_said"], d_off["banner_said"]) == (
                "LIVE SURFACE WARMING · no live surface for this symbol",
                "LIVE SURFACE REQUESTED · no live surface for this symbol",
            )
            assert d_on["none_said"] == d_off["none_said"] == "Gamma surface unavailable"
            server._on_chain(on, None, time_et.now(), "full chain returned HTTP 400", None, False)
            assert _surface(on)["reason"] == (
                "no terrain snapshot has been computed yet — "
                "chain fetch failed (full chain returned HTTP 400)"
            )
            mark_feed_down()
            silent = _surface(off)
            assert silent["warming"] is False
            unasked = push_surface.gamma_surface(off, time_et.now(), _HEATMAP, requested=False)
            assert unasked["banner_said"] == "no live surface for this symbol"  # no page shows it
            assert silent["reason"].startswith(
                "the capture daemon is not reporting (no current heartbeat)"
            )
            assert "it is not on the watchlist" in silent["reason"]
            assert "WATCHLIST UNKNOWN" not in server._status_line(time_et.now())
            assert "daemon not reporting" in server._status_line(time_et.now())
    finally:
        with level_store._lock:
            level_store._levels.pop(off, None)
            level_store._levels.pop(on, None)
        level_store.chain_priced(on)


def test_the_page_is_told_the_market_context_with_its_display_names():
    """The market context is served in the page with each symbol's display name.

    The daemon streams it whatever the watchlist holds. The volatility index, which the header
    and the Desk's Volatility card show, is marked, so the page picks no symbol by its name.
    """
    page = Path(server.__file__).parent / "static" / "index.html"
    html = server._with_page_settings(page.read_text(encoding="utf-8"))
    assert (
        '[{"key": "$SPX", "display": "SPX", "volatility": false}, '
        '{"key": "$NDX", "display": "NDX", "volatility": false}, '
        '{"key": "$VIX", "display": "VIX", "volatility": true}]' in html.replace("&quot;", '"')
    )


def test_the_page_is_told_the_words_for_its_own_connection_states():
    """The page's own connection words are served in the page, one list (AGENTS.md rule 4).

    The page holds none of its own: it reads them from the meta (ed-core.js PAGE_WORDS), so every
    surface says a state in this one wording.
    """
    page = Path(server.__file__).parent / "static" / "index.html"
    html = server._with_page_settings(page.read_text(encoding="utf-8"))
    served = re.search(r'<meta name="ed-page-words" content="([^"]*)" />', html)
    assert served is not None
    assert json.loads(served.group(1).replace("&quot;", '"')) == server.PAGE_WORDS
    assert server.PAGE_WORDS["offline"] == "OFFLINE"
    assert server.PAGE_WORDS["waiting_stream"].format(name="VIX") == "waiting for the VIX stream"


def test_a_page_without_a_settings_meta_is_refused_not_served_empty():
    """A layout change that loses a setting's empty meta fails at once, not as a blank page."""
    with pytest.raises(ValueError, match="ed-market-context"):
        server._with_page_settings('<meta name="ed-market-context" content="">')


def test_the_routes_that_take_a_json_body_read_it_and_refuse_none():
    """Over HTTP through the real app, with no daemon connected.

    A POST with no body, without its
    field, with a field of the wrong type or with a body that is not a JSON object is refused
    before the route runs; one with its JSON reaches the route: an add says the daemon is away, no
    contract selected is taken, and a contract no chain lists is refused by the route.
    """
    client = TestClient(server.app, raise_server_exceptions=False)
    for route, field in (("/api/watchlist", "ticker"), ("/api/flow-contract", "contract")):
        assert client.post(route).status_code == 422, route
        assert client.post(route, json={}).status_code == 422, route
        assert client.post(route, json={field: 5}).status_code == 422, route
        assert client.post(route, json=[]).status_code == 422, route
        plain = client.post(route, content="x", headers={"Content-Type": "text/plain"})
        assert plain.status_code == 422, route
    away = client.post("/api/watchlist", json={"ticker": "TSLA"})
    assert (away.status_code, away.json()) == (
        503,
        {"ok": False, "text": "TSLA is not added: no capture daemon runs in this program"},
    )
    gone = client.delete("/api/watchlist/TSLA")
    assert (gone.status_code, gone.json()["text"]) == (
        503,
        "TSLA is not removed: no capture daemon runs in this program",
    )
    assert client.post("/api/flow-contract", json={"contract": None}).status_code == 200
    extra = client.post("/api/flow-contract", json={"contract": None, "x": 1})
    assert extra.status_code == 200
    unlisted = "ZZZZ  261120C00100000"
    refused = client.post("/api/flow-contract", json={"contract": unlisted})
    assert (refused.status_code, refused.json()["contract"]) == (409, unlisted)


def test_a_repeated_add_an_unlisted_removal_and_an_add_with_no_sign_in_change_nothing(tmp_path):
    """Each request the daemon cannot carry out is answered, once, and leaves the list as it was.

    An add of a ticker already on the list (a request sent twice) is answered ON_LIST with no
    check; a removal of one not on it, NOT_ON_LIST; an add when the daemon's one Schwab client
    cannot be built (no usable sign-in: the real builder through capture.OneSchwabClient), is
    answered NOT_CHECKED with the reason, not added.
    """
    bus = MessageBus()
    daemon = capture.Daemon(bus, HealthRegistry(), ["SPY"])
    missing = tmp_path / "schwab_token.json"
    daemon.schwab_client = capture.OneSchwabClient(
        lambda: build_client_from_token(str(missing), "LiveLookingKey", "LiveLookingSecret")
    )

    async def go():
        answers = bus.subscribe("watchlist", policy=LOG)
        for rid, action, ticker in (
            ("r1", "add", "spy"),
            ("r2", "remove", "qqq"),
            ("r3", "add", "qqq"),
        ):
            await daemon.watchlist_request(
                {"op": "watchlist", "action": action, "ticker": ticker, "id": rid}
            )
        return [answers.queue.get_nowait()[1] for _ in range(answers.queue.qsize())]

    got = asyncio.run(go())
    assert [(m["request_id"], m["op"], m["ticker"], m["tickers"]) for m in got] == [
        ("r1", capture.ON_LIST, "SPY", ["SPY"]),
        ("r2", capture.NOT_ON_LIST, "QQQ", ["SPY"]),
        ("r3", capture.NOT_CHECKED, "QQQ", ["SPY"]),
    ]
    assert got[2]["answer"].startswith("ConnectionError: no Schwab client ("), got[2]["answer"]
    assert [m["text"] for m in got] == [
        "SPY is already on the watchlist",
        "QQQ is not on the watchlist",
        f"QQQ is not added: it was not checked with Schwab ({json.dumps(got[2]['answer'])})",
    ]
    assert (got[0]["status"], got[0]["answer"], got[1]["status"], got[1]["answer"]) == (
        None,
        None,
        None,
        None,
    )
    assert daemon.watchlist == ["SPY"]


def test_an_add_asked_before_the_schwab_connection_starts_is_answered_not_checked():
    """A ticker added before the daemon runs (no Schwab client yet) is not added.

    The console is told it was not checked, and why, and no request is made.
    """
    bus = MessageBus()
    daemon = capture.Daemon(bus, HealthRegistry(), ["SPY"])

    async def go():
        answers = bus.subscribe("watchlist", policy=LOG)
        await daemon.watchlist_request(
            {"op": "watchlist", "action": "add", "ticker": "tsla", "id": "r1"}
        )
        return [answers.queue.get_nowait()[1] for _ in range(answers.queue.qsize())]

    got = asyncio.run(go())
    assert [(m["request_id"], m["op"], m["ticker"], m["answer"]) for m in got] == [
        (
            "r1",
            capture.NOT_CHECKED,
            "TSLA",
            "ConnectionError: the Schwab connection has not started",
        )
    ]
    assert daemon.watchlist == ["SPY"]


def test_the_same_ticker_added_twice_at_once_is_added_once(tmp_path):
    """Two adds of TSLA in flight together (a request sent twice): the list holds TSLA once.

    Each is checked with Schwab's /quotes, the first answer adds it, and the other, finding it
    added during its check, is answered ON_LIST.
    """
    schwab = LocalSchwab("ws://127.0.0.1:1")  # REST only: no stream connection is opened
    bus = MessageBus()
    daemon = capture.Daemon(bus, HealthRegistry(), ["SPY"])
    client = schwab.client(tmp_path)
    daemon.schwab_client = lambda: client

    async def go():
        answers = bus.subscribe("watchlist", policy=LOG)
        await asyncio.gather(
            *(
                daemon.watchlist_request(
                    {"op": "watchlist", "action": "add", "ticker": "tsla", "id": rid}
                )
                for rid in ("r1", "r2")
            )
        )
        return [answers.queue.get_nowait()[1] for _ in range(answers.queue.qsize())]

    try:
        got = asyncio.run(go())
    finally:
        schwab.close()
    assert sorted(m["op"] for m in got) == sorted([capture.ADDED, capture.ON_LIST])
    assert {m["request_id"] for m in got} == {"r1", "r2"}
    assert daemon.watchlist == ["SPY", "TSLA"]
    assert [q["symbols"] for q in schwab.asked(QUOTES)] == ["TSLA", "TSLA"], (
        f"each add checked; the stand-in's requests: {schwab.requests}; the answers: {got}"
    )


def test_two_requests_the_daemon_answers_in_one_turn_each_get_their_own_answer():
    """A watchlist record answers one request: the next one never replaces it on the bus.

    Through the console's own request path and reader (order_flow.streaming.watchlist_request,
    _bus_loop), in the daemon's program: an add of SPY, already listed, and a removal of QQQ, not
    listed, sent together. The daemon answers each at once, both in one turn of the loop, before
    the console's reader takes either. Each caller gets its own record; before, the first waited
    out WATCHLIST_ANSWER_SEC and was told nothing.
    """
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), ["SPY"])

    async def go():
        ofs.bind_daemon(daemon)
        assert ofs.start_order_flow_stream()
        try:
            return await asyncio.wait_for(
                asyncio.gather(
                    ofs.watchlist_request("add", "spy"), ofs.watchlist_request("remove", "qqq")
                ),
                5.0,
            )
        finally:
            ofs.stop_order_flow_stream()
            ofs.bind_daemon(None)

    listed, unlisted = asyncio.run(go())
    assert (listed["op"], listed["ticker"], listed["text"]) == (
        capture.ON_LIST,
        "SPY",
        "SPY is already on the watchlist",
    )
    assert (unlisted["op"], unlisted["ticker"], unlisted["text"]) == (
        capture.NOT_ON_LIST,
        "QQQ",
        "QQQ is not on the watchlist",
    )
    assert listed["request_id"] != unlisted["request_id"]
    assert daemon.watchlist == ["SPY"]
