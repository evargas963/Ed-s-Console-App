"""The one watchlist and the daemon's subscriptions, Schwab to the screen, through the real code.

The capture daemon's connection (capture.Daemon.run) on the real schwab-py StreamClient, logged in
to Schwab's streamer played locally (tests/schwab_stream_standin.py) through Schwab's REST host
played locally (tests/schwab_rest_standin.py); the daemon's local socket (live_push); the console
in the daemon's program (streaming.bind_daemon, its feed reading the daemon's bus) and its routes
(server.post_watchlist, delete_watchlist); the list the page's socket carries on each beat, the
daemon's status (capture.Daemon.status).

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
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient
from websockets.asyncio.client import connect

import live_market_plane as lmp
import push_changes
import server
import time_et
from app.market_data.schwab.streaming import capture
from app.market_data.schwab.streaming.live_push import MARKET_CONTEXT, serve_live_push
from app.options.order_flow import streaming as ofs
from calibration.complete_chain_capture import ChainSweep, chain_messages
from option_contract import read_chain
from schwab_client import build_client_from_token, flatten_chain_contracts
from stream_spine import LOG, CaptureWriter, HealthRegistry, MessageBus, quote_msg
from tests.feed_live_helper import daemon_status
from tests.real_chains import CRWD
from tests.schwab_rest_standin import CHECKS, QUOTES, LocalSchwab
from tests.schwab_stream_standin import FIELD_REPLIES, HIGHEST_FIELD, LocalStreamer, refusal
from tests.test_live_push_channel_v1 import listener
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

    def __init__(self, tmp_path, limits: dict, data: dict):
        self.streamer = LocalStreamer(limits, data)
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
    for topic, msg in chain_messages(ticker, contracts, ts, price, ts):
        bus.publish(topic, msg)
    bus.publish(
        f"quote.{ticker}",
        quote_msg(
            symbol=ticker, last=price, src="schwab_l1", native={"key": ticker, "LAST_PRICE": price}
        ),
    )


def test_the_daemon_subscribes_once_and_each_of_schwabs_answers_reaches_its_own_request(tmp_path):
    """2026-10-07 (stream_capture.log 04:40:39): Schwab answered a refused ADD twice.

    Code 19 and then code 24, and every request after it was logged "unexpected requestid": each
    answer had been taken as the next request's. Now one reader matches each answer to its
    request by its requestid. Every watchlist ticker is asked for on each equity service and the
    header's market context on quotes, bars and news, in one request per service; SPY's 442
    2026-11-20 contracts on LEVELONE_OPTIONS past a limit of 2 (a stand-in limit) get Schwab's
    refusal, both answers recorded as sent, and nothing is asked again.
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
            lambda: len(schwab.streamer.answers) >= 9
        )  # login + 7 requests, one answered twice
        await asyncio.sleep(0.5)
        daemon.ask()  # nothing changed: nothing is asked
        await asyncio.sleep(0.5)
        connected = dict(daemon.held)
        stop.set()
        await asyncio.wait_for(asyncio.gather(*tasks), 10)
        return connected

    try:
        held = asyncio.run(go())
    finally:
        schwab.close()
        lmp._by_ticker.pop("SPY", None)  # the plane row its price wrote
        lmp._fields_by_ticker.pop("SPY", None)
    asked = [
        (r["service"], r["command"], sorted(r["parameters"]["keys"].split(",")))
        for r in schwab.streamer.requests
        if r["service"] != "ADMIN"
    ]
    context = sorted(["SPY", "TSLA", *MARKET_CONTEXT])
    book = sorted(daemon.options["OPTIONS_BOOK"])
    assert len(book) == 50  # SPY's half of 100
    assert sorted(asked) == sorted(
        [
            *[
                (svc, "SUBS", context)
                for svc in ("LEVELONE_EQUITIES", "CHART_EQUITY", "NEWS_HEADLINE")
            ],
            *[(svc, "SUBS", ["SPY", "TSLA"]) for svc in ("NYSE_BOOK", "NASDAQ_BOOK")],
            ("LEVELONE_OPTIONS", "SUBS", symbols),
            ("OPTIONS_BOOK", "SUBS", book),
        ]
    )
    answers = _answers(log)
    assert [a for a in answers if a[0] == "LEVELONE_OPTIONS"] == [
        ("LEVELONE_OPTIONS", "SUBS", 19, refusal("LEVELONE_OPTIONS", 2, len(symbols) - 2)),
        ("LEVELONE_OPTIONS", "SUBS", 24, "SUBS command failed"),
    ], "both of Schwab's answers, as sent"
    assert all(code == 0 for svc, _c, code, _m in answers if svc != "LEVELONE_OPTIONS"), answers
    assert held["NYSE_BOOK"] == {"SPY", "TSLA"} and held["LEVELONE_OPTIONS"] == frozenset()
    # each request asks for every field number Schwab accepts on its service (code 22 past it), and
    # the fields Schwab sends past its Streamer Guide (LEVELONE_EQUITIES 52-56) reach SPY's record
    # as sent
    assert {
        (r["service"], r["parameters"]["fields"])
        for r in schwab.streamer.requests
        if r["service"] != "ADMIN"
    } == {(svc, ",".join(map(str, range(HIGHEST_FIELD[svc] + 1)))) for svc in capture.SERVICES}
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
        await _until(lambda: len(daemon.held["LEVELONE_OPTIONS"]) == len(symbols))
        stop.set()
        await asyncio.wait_for(asyncio.gather(*tasks), 10)

    try:
        asyncio.run(go())
    finally:
        schwab.close()
        lmp._by_ticker.pop("MRVL", None)  # the plane row its price wrote
        lmp._fields_by_ticker.pop("MRVL", None)
    commands = [c for c, _k in schwab.streamer.asked("LEVELONE_OPTIONS")]
    assert len(commands) > 1 and commands == ["SUBS"] + ["ADD"] * (len(commands) - 1)
    assert sorted(schwab.streamer.held["LEVELONE_OPTIONS"]) == symbols, "Schwab holds every part"


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
        await _until(lambda: len(subs()) == 1 and daemon.held["NYSE_BOOK"])
        await daemon.stream._socket.close()  # the socket is gone
        await _until(lambda: len(subs()) == 2 and daemon.held["NYSE_BOOK"])
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
    them).
    """
    schwab = _Schwab(tmp_path, limits={}, data={})  # no limit hit, nothing streamed
    answer = schwab.streamer.answer
    schwab.streamer.answer = lambda req: [] if req["service"] == "NYSE_BOOK" else answer(req)
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), ["SPY"])
    started = time_et.elapsed()

    async def go():
        await daemon.run_connection(schwab.client, asyncio.Event())

    try:
        try:
            asyncio.run(asyncio.wait_for(go(), capture.REQUEST_TIMEOUT_SEC + 10))
            raise AssertionError("the connection did not end")
        except ConnectionError as e:
            assert str(e) == f"no answer to NYSE_BOOK SUBS in {capture.REQUEST_TIMEOUT_SEC:.0f} s"
    finally:
        schwab.close()
    assert time_et.elapsed() - started >= capture.REQUEST_TIMEOUT_SEC
    assert daemon.stream is None, "the broken session is logged out and dropped"


def test_a_console_frame_the_daemon_cannot_read_is_logged_with_what_arrived(caplog):
    """The daemon's local socket reads every frame a client sends (launch.py stop's is one).

    One that is not JSON, or JSON that is not an object, is logged with what arrived, never dropped
    unseen; a request after it still reaches the daemon.
    """
    got, stats = [], {}
    request = {"op": "watchlist", "add": "SPY"}

    async def go():
        stop = asyncio.Event()
        sock, url = listener()
        served = asyncio.create_task(serve_live_push(stop, got.append, sock, stats=stats))
        ws = await connect(url, max_size=None)
        try:
            for frame in ("not json", "[1, 2]", json.dumps(request)):
                await ws.send(frame)
            await _until(lambda: got)
        finally:  # a failure still closes the socket: cancelling over an open one can hang
            await ws.close()
            stop.set()
            await served

    with caplog.at_level(logging.WARNING, logger="app.market_data.schwab.streaming.live_push"):
        asyncio.run(go())
    warned = [r.getMessage() for r in caplog.records if r.name.endswith("live_push")]
    assert got == [request]
    assert any("'not json'" in m for m in warned), warned
    assert any("'[1, 2]'" in m for m in warned), warned


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
        lambda t, m: None,
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
        await _until(lambda: daemon.held["NASDAQ_BOOK"] == {"SPY"})
        ofs.bind_daemon(daemon)  # the console in the daemon's program (capture.serve_console)
        assert ofs.start_order_flow_stream()
        records = bus.subscribe("watchlist", policy=LOG)
        try:
            beats = [daemon.status(time_et.now())]  # a beat built before the add
            added = json.loads((await server.post_watchlist("tsla")).body)
            await _until(lambda: daemon.held["NASDAQ_BOOK"] == {"SPY", "TSLA"})
            swept_after_add = list(daemon.chains.watchlist)
            beats.append(daemon.status(time_et.now()))
            invalid = json.loads((await server.post_watchlist("ZQZQZ")).body)
            removed = json.loads((await server.delete_watchlist("TSLA")).body)
            beats.append(daemon.status(time_et.now()))
            await _until(lambda: daemon.held["NASDAQ_BOOK"] == {"SPY"})
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
    }
    assert invalid == {
        "ok": False,
        "op": "invalid",
        "ticker": "ZQZQZ",
        "tickers": ["SPY", "TSLA"],
        "ts": sent[1]["ts_recv"],
        "status": 200,
        "answer": {"errors": {"invalidSymbols": ["ZQZQZ"]}},
    }
    assert removed == {
        "ok": True,
        "op": "removed",
        "ticker": "TSLA",
        "tickers": ["SPY"],
        "ts": sent[2]["ts_recv"],
        "status": None,
        "answer": None,
    }
    assert [q["symbols"] for q in schwab.rest.asked(QUOTES)] == ["TSLA", "ZQZQZ"], (
        "one check per add"
    )
    for svc in EQUITY:
        assert [(c, k) for c, k in asked(svc) if "TSLA" in k] == [
            ("ADD", ["TSLA"]),
            ("UNSUBS", ["TSLA"]),
        ], svc
    assert not any("ZQZQZ" in r["parameters"].get("keys", "") for r in schwab.streamer.requests)
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
        lambda t, m: None,
        clock=lambda: datetime(2026, 10, 7, 10, 0, tzinfo=ET).timestamp(),
        failures=CaptureWriter(tmp_path / "stream_capture.db"),
        streamed=lambda s: None,
    )
    client = schwab.client(tmp_path)
    stop = threading.Event()
    worker = threading.Thread(target=sweep.work, args=(lambda: client, stop), daemon=True)
    try:
        with caplog.at_level("INFO", logger="chain_history"):
            worker.start()
            time.sleep(1.5)
    finally:
        stop.set()
        worker.join(10)
        schwab.close()
    assert schwab.requests == [], "nothing asked of Schwab"
    assert not [r for r in caplog.records if "chain rotation" in r.getMessage()], (
        "no rotation of nothing"
    )


def test_a_viewed_ticker_warms_only_on_the_watchlist_and_a_silent_daemon_says_so_first():
    """The gamma surface's reason for a ticker with no surface.

    From server.get_options_gamma_surface: on the watchlist it warms (its chain is coming); off
    it, it says it is not on the watchlist; with the daemon's heartbeat late, the last list still
    stands and the reason says the daemon is not reporting; a chain Schwab refused says Schwab's
    answer.
    """
    on, off = "ZZWLON", "ZZWLOFF"
    pages = [push_changes.subscribe(tk) for tk in (on, off)]
    # levels, no surface: CRWD's real chain delivered now with no price held
    server._publish_levels(off, read_chain(CRWD.chain), time_et.now(), chain_spot=(None, None))
    try:
        lmp.record_feed_heartbeat(
            daemon_status(time_et.now(), schwab_socket_open=True, watchlist=[on])
        )
        d_on, d_off = (json.loads(server.get_options_gamma_surface(tk).body) for tk in (on, off))
        assert (d_on["warming"], d_on["reason"]) == (
            True,
            "no terrain snapshot has been computed yet",
        )
        assert (d_off["warming"], d_off["reason"]) == (
            False,
            "no chain is fetched for this ticker: it is not on the watchlist",
        )
        server._on_chain(on, None, time_et.now(), "full chain returned HTTP 400", None)
        assert json.loads(server.get_options_gamma_surface(on).body)["reason"] == (
            "no terrain snapshot has been computed yet — "
            "chain fetch failed (full chain returned HTTP 400)"
        )
        lmp.record_feed_heartbeat(
            daemon_status(time_et.now() - 100, schwab_socket_open=True, watchlist=[on])
        )
        silent = json.loads(server.get_options_gamma_surface(off).body)
        assert silent["warming"] is False
        assert silent["reason"].startswith(
            "the capture daemon is not reporting (no current heartbeat)"
        )
        assert "it is not on the watchlist" in silent["reason"]
        assert "WATCHLIST UNKNOWN" not in server._status_line(time_et.now())
        assert "daemon not reporting" in server._status_line(time_et.now())
    finally:
        for tk, page in zip((on, off), pages):
            push_changes.unsubscribe(tk, page)
        with server._terrain_cache_lock:
            server._terrain_cache.pop(off, None)
            server._terrain_cache.pop(on, None)
        server._terrain_refresh_last_error.pop(on, None)
        lmp.record_feed_down()


def test_the_page_is_told_the_market_context_with_its_display_names():
    """The header's market context is served in the page with each symbol's display name.

    The daemon streams it whatever the watchlist holds.
    """
    html = server._with_page_settings(server._MARKET_CONTEXT_META)
    assert (
        '[{"key": "$SPX", "display": "SPX"}, {"key": "$NDX", "display": "NDX"}, '
        '{"key": "$VIX", "display": "VIX"}]' in html.replace("&quot;", '"')
    )


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
    assert client.post("/api/watchlist", json={"ticker": "TSLA"}).status_code == 503
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
    cannot be built (no usable sign-in: the real builder through capture.one_schwab_client), is
    answered NOT_CHECKED with the reason, not added.
    """
    bus = MessageBus()
    daemon = capture.Daemon(bus, HealthRegistry(), ["SPY"])
    missing = tmp_path / "schwab_token.json"
    daemon.schwab_client = capture.one_schwab_client(
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
    assert (got[0]["status"], got[0]["answer"], got[1]["status"], got[1]["answer"]) == (
        None,
        None,
        None,
        None,
    )
    assert daemon.watchlist == ["SPY"]


def test_the_same_ticker_added_twice_at_once_is_added_once(tmp_path):
    """Two adds of TSLA in flight together (a request sent twice): each is checked with Schwab's
    /quotes, the first answer adds it, and the other, finding it added during its check, is
    answered ON_LIST; the list holds TSLA once.
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
    assert [q["symbols"] for q in schwab.asked(QUOTES)] == ["TSLA", "TSLA"], "each add checked"
