"""Schwab's streamer to the daemon's bus, through the daemon's own connection: `Daemon.run` /
`run_connection` (connect, sync, read_for, disconnect) logs schwab-py in, subscribes with
schwab-py's public requests (`level_one_equity_subs`, `nyse_book_add`, ...), reads with
`handle_message`, and times every frame with its decoder (`StreamClient.set_json_decoder`).

Stand-ins, named: Schwab's streamer is a websocket server on 127.0.0.1. It answers each request
with code 0 unless the test says otherwise (code 19 for a refused symbol, no answer, a closed
socket), and sends recorded frames where the test says. The Schwab client is a stand-in whose user
preferences point streamerSocketUrl at that server. The records keep each item as schwab-py
labeled it, so each wire frame is the item with Schwab's field numbers put back (schwab-py's own
field enums). Frame timestamps: the bar's is the one recorded; the quote's, option quote's and
books' records keep none, so each uses the item's own QUOTE_TIME_MILLIS or BOOK_TIME. Schwab's
heartbeat frame is a stand-in with the shape of Schwab's notify frame. The frame over 1 MiB is
the recorded NYSE book item repeated. The daemon's times (silence, reconnect wait, request wait)
are passed in short, so a test does not wait Schwab's real 30 s."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from schwab.streaming import StreamClient
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from app.market_data.schwab.streaming.capture import NEWS_FIELDS, SERVICES, Daemon
from stream_spine import LOG, HealthRegistry, MessageBus

FX = Path(__file__).resolve().parent / "fixtures"
_EQUITY = json.loads((FX / "real_equity_book.json").read_text(encoding="utf-8"))
_NYSE = json.loads((FX / "real_spy_nyse_nasdaq_books.json").read_text(encoding="utf-8"))["books"]["NYSE_BOOK"]
_BAR = next(r for r in json.loads((FX / "real_daemon_bars_spy_tsla_spx_2026_10_01_02.json")
                                  .read_text(encoding="utf-8"))["rows"] if r["native"])
_OPTIONS = json.loads((FX / "real_options_stream_history_samples.json").read_text(encoding="utf-8"))["contracts"]
_OPTION = next(e["content"] for e in _OPTIONS[0]["events"] if e["kind"] == "l1")
_OPTION_BOOK = next(e["content"] for e in _OPTIONS[0]["events"] if e["kind"] == "book")
_CONTRACT, _OTHER_CONTRACT = _OPTIONS[0]["symbol"], _OPTIONS[1]["symbol"]

#: (service, the recorded item as schwab-py labels it, the frame's timestamp, the bus topic)
RECORDED = [
    ("LEVELONE_EQUITIES", _EQUITY["quote"]["native"], _EQUITY["quote"]["native"]["QUOTE_TIME_MILLIS"],
     "quote.TSLA"),
    ("NASDAQ_BOOK", _EQUITY["book"]["native"], _EQUITY["book"]["native"]["BOOK_TIME"], "book.TSLA"),
    ("NYSE_BOOK", _NYSE["content"], _NYSE["content"]["BOOK_TIME"], "book.SPY"),
    ("CHART_EQUITY", _BAR["native"], _BAR["schwab_ts"], "bar1m.SPY"),
    ("LEVELONE_OPTIONS", _OPTION, _OPTION["QUOTE_TIME_MILLIS"], f"optquote.{_CONTRACT}"),
    ("OPTIONS_BOOK", _OPTION_BOOK, _OPTION_BOOK["BOOK_TIME"], f"book.{_CONTRACT}"),
]
WANTED = {"LEVELONE_EQUITIES": ["TSLA"], "CHART_EQUITY": ["SPY"], "NYSE_BOOK": ["SPY"],
          "NASDAQ_BOOK": ["TSLA"], "LEVELONE_OPTIONS": [_CONTRACT], "OPTIONS_BOOK": [_CONTRACT],
          "NEWS_HEADLINE": ["SPY"]}
#: one more symbol per service: what the daemon ADDs
ADDED = {"LEVELONE_EQUITIES": "SPY", "CHART_EQUITY": "TSLA", "NYSE_BOOK": "TSLA", "NASDAQ_BOOK": "SPY",
         "LEVELONE_OPTIONS": _OTHER_CONTRACT, "OPTIONS_BOOK": _OTHER_CONTRACT, "NEWS_HEADLINE": "TSLA"}
#: every field of each service, as the daemon asks for it
FIELDS = {"LEVELONE_EQUITIES": StreamClient.LevelOneEquityFields, "CHART_EQUITY": StreamClient.ChartEquityFields,
          "LEVELONE_OPTIONS": StreamClient.LevelOneOptionFields, "NYSE_BOOK": StreamClient.BookFields,
          "NASDAQ_BOOK": StreamClient.BookFields, "OPTIONS_BOOK": StreamClient.BookFields}
BOOKS = ("NYSE_BOOK", "NASDAQ_BOOK", "OPTIONS_BOOK")


def _numbered(item: dict, fields) -> dict:
    """`item` with Schwab's field number in place of each name schwab-py gave it."""
    numbers = {f.name: str(f.value) for f in fields}
    return {numbers.get(k, k): v for k, v in item.items()}


def _as_sent(service: str, item: dict) -> dict:
    """The item as Schwab's socket sends it: numbered, a book's levels and venues included."""
    if service not in BOOKS:
        return _numbered(item, FIELDS[service])
    out = _numbered(item, StreamClient.BookFields)
    for side, level, venue in (("BIDS", StreamClient.BidFields, StreamClient.PerExchangeBidFields),
                               ("ASKS", StreamClient.AskFields, StreamClient.PerExchangeAskFields)):
        if side in item:
            out[str(StreamClient.BookFields[side].value)] = [
                {**_numbered(lvl, level), str(level[side].value): [_numbered(v, venue) for v in lvl[side]]}
                for lvl in item[side]]
    return out


def _frame(service: str, items: list[dict], ts: int) -> str:
    return json.dumps({"data": [{"service": service, "timestamp": ts, "command": "SUBS",
                                 "content": [_as_sent(service, item) for item in items]}]})


class _Preferences:
    """GET /userPreference as the stand-in client returns it: the streamer at `url`."""

    status_code = 200

    def __init__(self, url: str) -> None:
        self.url = url

    def json(self) -> dict:
        return {"streamerInfo": [{"streamerSocketUrl": self.url, "schwabClientCustomerId": "stand-in",
                                  "schwabClientCorrelId": "stand-in", "schwabClientChannel": "N9",
                                  "schwabClientFunctionId": "APIAPP"}]}


def _stand_in_client(server) -> SimpleNamespace:
    """The Schwab client as schwab-py's StreamClient.login reads it: its user preferences (the
    stand-in streamer `server`) and its token's access_token."""
    url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    return SimpleNamespace(token_metadata=SimpleNamespace(token={"access_token": "stand-in"}),
                           get_user_preferences=lambda: _Preferences(url))


def _answer(req: dict, code: int = 0) -> str:
    return json.dumps({"response": [{"service": req["service"], "requestid": req["requestid"],
                                     "command": req["command"], "timestamp": 0,
                                     "content": {"code": code, "msg": "stand-in"}}]})


def _published(sub) -> list:
    out = []
    while not sub.queue.empty():
        out.append(sub.queue.get_nowait())
    return out


def _asked(requests: list[dict]) -> list:
    """(service, command, keys) of every request but the session's own (ADMIN)."""
    return [(r["service"], r["command"], r["parameters"]["keys"]) for r in requests if r["service"] != "ADMIN"]


def test_every_service_is_requested_through_schwab_py_and_every_frame_reaches_the_bus_as_sent():
    """The daemon's connection subscribes every service it is asked for, adds a symbol to each,
    then, when the console's list empties, unsubscribes each. Every request reaches Schwab exactly
    as Schwab's streamer takes it (SUBS and ADD with every field of the service, UNSUBS with
    none), and every recorded frame reaches the bus as Schwab sent it, with its timestamp."""
    requests: list[dict] = []
    frames = {svc: _frame(svc, [item], ts) for svc, item, ts, _topic in RECORDED}
    answered = {"SUBS": 0, "ADD": 0, "UNSUBS": 0}
    bus, health = MessageBus(), HealthRegistry()
    log = bus.subscribe("", policy=LOG)
    daemon, stop = Daemon(bus, health), asyncio.Event()

    async def streamer(ws) -> None:
        async for text in ws:
            for req in json.loads(text)["requests"]:
                requests.append(req)
                await ws.send(_answer(req))
                command = req["command"]
                if command == "SUBS" and req["service"] in frames:
                    await ws.send(frames[req["service"]])
                if command not in answered:
                    continue
                answered[command] += 1
                if answered[command] < len(SERVICES):
                    continue
                if command == "SUBS":            # every service held: one more symbol each
                    daemon.set_wanted({svc: [*syms, ADDED[svc]] for svc, syms in WANTED.items()})
                elif command == "ADD":           # the console's list empties
                    daemon.set_wanted({})
                else:                            # the frames read, the connection ends
                    asyncio.get_running_loop().call_later(1.0, stop.set)

    async def run() -> None:
        async with serve(streamer, "127.0.0.1", 0) as server:
            daemon.set_wanted(WANTED)
            await asyncio.wait_for(daemon.run_connection(_stand_in_client(server), stop), 20)
    asyncio.run(run())

    def fields(svc: str) -> str:
        if svc == "NEWS_HEADLINE":
            return ",".join(str(f) for f in NEWS_FIELDS)
        return ",".join(str(v) for v in sorted(f.value for f in FIELDS[svc]))

    def request(svc: str, command: str, keys: str) -> dict:
        parameters = {"keys": keys} if command == "UNSUBS" else {"keys": keys, "fields": fields(svc)}
        return {"service": svc, "command": command, "SchwabClientCustomerId": "stand-in",
                "SchwabClientCorrelId": "stand-in", "parameters": parameters}
    sent = [{k: v for k, v in r.items() if k != "requestid"} for r in requests if r["service"] != "ADMIN"]
    assert sent == ([request(svc, "SUBS", WANTED[svc][0]) for svc in SERVICES]
                    + [request(svc, "ADD", ADDED[svc]) for svc in SERVICES]
                    + [request(svc, "UNSUBS", ",".join(sorted([WANTED[svc][0], ADDED[svc]]))) for svc in SERVICES])
    assert [r["command"] for r in requests if r["service"] == "ADMIN"] == ["LOGIN", "LOGOUT"]

    published = _published(log)
    assert [(m["service"], m["command"], m["code"]) for t, m in published if t.startswith("sub.")] == \
        [(svc, cmd, 0) for cmd in ("SUBS", "ADD", "UNSUBS") for svc in SERVICES]
    data = [(t, m) for t, m in published if not t.startswith("sub.")]
    assert sorted(t for t, _m in data) == sorted(topic for *_rest, topic in RECORDED)
    by_topic = dict(data)
    for svc, item, ts, topic in RECORDED:
        msg = by_topic[topic]
        as_sent = msg["native"] if "native" in msg else msg["content"]
        assert (as_sent, msg["schwab_ts"]) == (item, ts), f"{svc} changed on its way to the bus"
        assert health.last(svc) is not None


def test_sync_sends_the_difference_and_nothing_when_nothing_changed():
    """The board's tickers on its services and the console's book: one SUBS each, every answer
    on the bus; a second sync with nothing changed sends nothing."""
    requests: list[dict] = []

    async def streamer(ws) -> None:
        async for text in ws:
            for req in json.loads(text)["requests"]:
                requests.append(req)
                await ws.send(_answer(req))

    bus = MessageBus()
    log = bus.subscribe("sub.", policy=LOG)

    async def run() -> tuple[list, Daemon]:
        async with serve(streamer, "127.0.0.1", 0) as server:
            daemon = Daemon(bus, HealthRegistry(), board=["SPY", "AAPL"])
            await daemon.connect(_stand_in_client(server))
            try:
                daemon.set_wanted({"NYSE_BOOK": ["SPY"]})
                await daemon.sync()
                first = _asked(requests)
                await daemon.sync()
                return first, daemon
            finally:
                await daemon.disconnect()
    first, daemon = asyncio.run(run())

    assert first == [("LEVELONE_EQUITIES", "SUBS", "AAPL,SPY"), ("CHART_EQUITY", "SUBS", "AAPL,SPY"),
                     ("NYSE_BOOK", "SUBS", "SPY"), ("NEWS_HEADLINE", "SUBS", "AAPL,SPY")]
    assert _asked(requests) == first, "nothing changed, nothing sent"
    assert [m["code"] for _t, m in _published(log)] == [0, 0, 0, 0]


def test_a_refused_symbol_is_recorded_and_asked_for_again_only_after_the_list_changes():
    """Schwab answers code 19 for a request holding BAD: the daemon records it refused, holds
    nothing, does not ask again, and asks again once the console's list changes."""
    requests: list[dict] = []
    refusing = {"BAD"}

    async def streamer(ws) -> None:
        async for text in ws:
            for req in json.loads(text)["requests"]:
                requests.append(req)
                keys = set(req["parameters"].get("keys", "").split(","))
                await ws.send(_answer(req, 19 if req["command"] != "UNSUBS" and keys & refusing else 0))

    bus = MessageBus()
    log = bus.subscribe("sub.", policy=LOG)

    async def run() -> tuple[dict, frozenset, list, list, frozenset]:
        async with serve(streamer, "127.0.0.1", 0) as server:
            daemon = Daemon(bus, HealthRegistry())
            await daemon.connect(_stand_in_client(server))
            try:
                daemon.set_wanted({"OPTIONS_BOOK": ["BAD"]})
                await daemon.sync()
                refused, held = dict(daemon.refused["OPTIONS_BOOK"]), daemon.held["OPTIONS_BOOK"]
                await daemon.sync()
                before_change = _asked(requests)
                refusing.clear()
                daemon.set_wanted({"OPTIONS_BOOK": ["BAD", "SPY"]})
                await daemon.sync()
                return refused, held, before_change, _asked(requests), daemon.held["OPTIONS_BOOK"]
            finally:
                await daemon.disconnect()
    refused, held, before_change, after_change, held_after = asyncio.run(run())

    assert list(refused) == ["BAD"] and "19" in refused["BAD"] and held == frozenset()
    answers = [m for _t, m in _published(log)]
    assert answers[0]["code"] == -1 and "19" in answers[0]["reason"]
    assert before_change == [("OPTIONS_BOOK", "SUBS", "BAD")], "a refused symbol is not asked for again"
    assert after_change == before_change + [("OPTIONS_BOOK", "SUBS", "BAD,SPY")]
    assert held_after == frozenset({"BAD", "SPY"})


def test_a_socket_that_dies_during_a_sync_ends_the_connection_and_refuses_nothing():
    async def streamer(ws) -> None:
        async for text in ws:
            for req in json.loads(text)["requests"]:
                if req["service"] == "OPTIONS_BOOK":
                    await ws.close()
                    return
                await ws.send(_answer(req))

    async def run() -> tuple[BaseException | None, Daemon]:
        async with serve(streamer, "127.0.0.1", 0) as server:
            daemon = Daemon(MessageBus(), HealthRegistry())
            await daemon.connect(_stand_in_client(server))
            try:
                daemon.set_wanted({"OPTIONS_BOOK": ["SPY"]})
                try:
                    await daemon.sync()
                except ConnectionClosed as e:
                    return e, daemon
                return None, daemon
            finally:
                await daemon.disconnect()
    ended, daemon = asyncio.run(run())

    assert isinstance(ended, ConnectionClosed)
    assert daemon.refused["OPTIONS_BOOK"] == {}, "a dead socket is not Schwab refusing a symbol"


class _Sessions:
    """The stand-in's record of the daemon's sessions: each connection's requests, and the most
    sessions logged in at once."""

    def __init__(self) -> None:
        self.requests: list[list[dict]] = []
        self.live = self.most_live = 0

    def login(self) -> None:
        self.live += 1
        self.most_live = max(self.most_live, self.live)


def test_a_dropped_socket_is_replaced_and_everything_wanted_is_resubscribed():
    """Schwab sends a frame over 1 MiB, then drops the socket. The frame arrives whole (no
    receive cap of ours); the daemon reconnects with a new session that holds nothing, and
    subscribes the wanted list again. At most one Schwab session at any instant."""
    sessions = _Sessions()
    item_bytes = len(json.dumps(_as_sent("NYSE_BOOK", _NYSE["content"])))
    big = _frame("NYSE_BOOK", [_NYSE["content"]] * (2**20 // item_bytes + 2), _NYSE["content"]["BOOK_TIME"])
    assert len(big) > 2**20
    stop = asyncio.Event()

    async def streamer(ws) -> None:
        mine: list[dict] = []
        sessions.requests.append(mine)
        logged_in = False
        try:
            async for text in ws:
                for req in json.loads(text)["requests"]:
                    mine.append(req)
                    if req["command"] == "LOGIN":
                        sessions.login()
                        logged_in = True
                    elif req["command"] == "LOGOUT":
                        sessions.live -= 1
                        logged_in = False
                    await ws.send(_answer(req))
                    if req["command"] == "SUBS" and len(sessions.requests) == 1:
                        await ws.send(big)
                        await ws.close()                     # Schwab drops the socket
                        return
                    if req["command"] == "SUBS":
                        stop.set()
        finally:
            if logged_in:
                sessions.live -= 1

    bus = MessageBus()
    books = bus.subscribe("book.", policy=LOG)

    async def run() -> None:
        async with serve(streamer, "127.0.0.1", 0) as server:
            daemon = Daemon(bus, HealthRegistry(), backoff_sec=(0.05,))
            daemon.set_wanted({"NYSE_BOOK": ["SPY"]})
            client = _stand_in_client(server)
            await asyncio.wait_for(daemon.run(lambda: client, stop), 20)
    asyncio.run(run())

    assert [[(r["service"], r["command"]) for r in s] for s in sessions.requests] == [
        [("ADMIN", "LOGIN"), ("NYSE_BOOK", "SUBS")],
        [("ADMIN", "LOGIN"), ("NYSE_BOOK", "SUBS"), ("ADMIN", "LOGOUT")]]
    assert sessions.most_live == 1 and sessions.live == 0
    got = _published(books)
    assert len(got) == len(json.loads(big)["data"][0]["content"]), "the frame over 1 MiB did not arrive whole"
    assert all(m["content"] == _NYSE["content"] for _t, m in got)


def test_silence_from_schwab_ends_the_session_which_is_logged_out_before_the_next(caplog):
    """No frame from Schwab for the daemon's dead time: the session is logged out, then a new
    one logs in and subscribes again."""
    sessions = _Sessions()
    stop = asyncio.Event()

    async def streamer(ws) -> None:
        mine: list[dict] = []
        sessions.requests.append(mine)
        async for text in ws:
            for req in json.loads(text)["requests"]:
                mine.append(req)
                if req["command"] == "LOGIN":
                    sessions.login()
                elif req["command"] == "LOGOUT":
                    sessions.live -= 1
                await ws.send(_answer(req))
                if req["command"] == "SUBS" and len(sessions.requests) == 2:
                    stop.set()

    async def run() -> None:
        async with serve(streamer, "127.0.0.1", 0) as server:
            daemon = Daemon(MessageBus(), HealthRegistry(), dead_sec=0.5, backoff_sec=(0.05,))
            daemon.set_wanted({"NYSE_BOOK": ["SPY"]})
            client = _stand_in_client(server)
            await asyncio.wait_for(daemon.run(lambda: client, stop), 20)
    with caplog.at_level(logging.WARNING, logger="capture"):
        asyncio.run(run())

    assert [[(r["service"], r["command"]) for r in s] for s in sessions.requests] == [
        [("ADMIN", "LOGIN"), ("NYSE_BOOK", "SUBS"), ("ADMIN", "LOGOUT")],
        [("ADMIN", "LOGIN"), ("NYSE_BOOK", "SUBS"), ("ADMIN", "LOGOUT")]]
    assert sessions.most_live == 1
    assert "no frame from Schwab for 0.5 s" in caplog.text


def test_a_frame_handed_back_from_schwab_pys_queue_is_not_a_new_frame_from_schwab():
    """Schwab sends a quote while a request waits for its answer; schwab-py keeps the quote and
    hands it to the next handle_message. The quote reaches the bus, and the time of Schwab's last
    frame (the liveness test, and the feed record's schwab_last_frame_ts) stays the time Schwab
    sent its last frame, not the time schwab-py handed the kept one on."""
    item, ts = _EQUITY["quote"]["native"], _EQUITY["quote"]["native"]["QUOTE_TIME_MILLIS"]

    async def streamer(ws) -> None:
        async for text in ws:
            for req in json.loads(text)["requests"]:
                if req["command"] == "SUBS":
                    await ws.send(_frame("LEVELONE_EQUITIES", [item], ts))
                await ws.send(_answer(req))

    bus, health = MessageBus(), HealthRegistry()
    log = bus.subscribe("quote.", policy=LOG)

    async def run() -> tuple[float, float]:
        async with serve(streamer, "127.0.0.1", 0) as server:
            daemon = Daemon(bus, health)
            await daemon.connect(_stand_in_client(server))
            try:
                daemon.set_wanted({"LEVELONE_EQUITIES": ["TSLA"]})
                daemon.wanted_changed.clear()
                await daemon.sync()
                last_from_schwab = daemon.stream.last_frame_ts
                await asyncio.sleep(0.3)
                await daemon.read_for(0.5)
                return last_from_schwab, daemon.stream.last_frame_ts
            finally:
                await daemon.disconnect()
    last_from_schwab, last_after_read = asyncio.run(run())

    assert [(t, m["native"], m["schwab_ts"]) for t, m in _published(log)] == [("quote.TSLA", item, ts)]
    assert last_after_read == last_from_schwab


def test_a_request_schwab_never_answers_ends_the_connection():
    """Schwab never answers a SUBS: after the daemon's request wait the sync raises
    ConnectionError, which ends the connection (Daemon.run reconnects), and nothing counts as
    held or refused."""
    async def streamer(ws) -> None:
        async for text in ws:
            for req in json.loads(text)["requests"]:
                if req["service"] == "ADMIN":
                    await ws.send(_answer(req))

    async def run() -> tuple[str, Daemon]:
        async with serve(streamer, "127.0.0.1", 0) as server:
            daemon = Daemon(MessageBus(), HealthRegistry(), request_timeout_sec=0.5)
            await daemon.connect(_stand_in_client(server))
            try:
                daemon.set_wanted({"NYSE_BOOK": ["SPY"]})
                with pytest.raises(ConnectionError) as e:
                    await daemon.sync()
                return str(e.value), daemon
            finally:
                await daemon.disconnect()
    ended, daemon = asyncio.run(run())

    assert ended == "no answer to NYSE_BOOK SUBS in 0.5 s"
    assert daemon.held["NYSE_BOOK"] == frozenset() and daemon.refused["NYSE_BOOK"] == {}


def test_schwabs_heartbeat_alone_keeps_the_connection_alive():
    """A heartbeat is no data and reaches no handler, but it is a frame from Schwab: the time of
    Schwab's last frame moves to it, and the status says the socket is open."""
    async def streamer(ws) -> None:
        async for text in ws:
            for req in json.loads(text)["requests"]:
                await ws.send(_answer(req))
                if req["command"] == "LOGIN":
                    await asyncio.sleep(0.3)
                    await ws.send(json.dumps({"notify": [{"heartbeat": "1790973511496"}]}))

    bus, health = MessageBus(), HealthRegistry()
    log = bus.subscribe("", policy=LOG)

    async def run() -> tuple[float, float, dict]:
        async with serve(streamer, "127.0.0.1", 0) as server:
            daemon = Daemon(bus, health)
            await daemon.connect(_stand_in_client(server))
            try:
                logged_in = daemon.stream.last_frame_ts
                await daemon.read_for(1.0)
                return logged_in, daemon.stream.last_frame_ts, daemon.status()
            finally:
                await daemon.disconnect()
    logged_in, after, status = asyncio.run(run())

    assert after >= logged_in + 0.25, "the heartbeat did not count as a frame from Schwab"
    assert status["schwab_socket_open"] is True
    assert _published(log) == []
