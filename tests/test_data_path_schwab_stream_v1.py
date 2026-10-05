"""Schwab's streamer to the daemon's bus, through the daemon's own connection: `Daemon.run_connection`
(connect, sync, read_for, disconnect) logs schwab-py in, subscribes with schwab-py's public
requests (`level_one_equity_subs`, `nyse_book_unsubs`, ...), reads with `handle_message`, and
times every frame with its decoder (`StreamClient.set_json_decoder`).

Stand-ins, named: Schwab's streamer is a websocket server on 127.0.0.1 that answers each request
with code 0 (in the unanswered-request test, only LOGIN and LOGOUT) and sends the recorded frames
of a service after its SUBS is answered; the Schwab
client is a stand-in whose user preferences point streamerSocketUrl at that server. The records
keep each item as schwab-py labeled it, so each wire frame is the item with Schwab's field numbers
put back (schwab-py's own field enums). Frame timestamps: the bar's is the one recorded; the
quote's, option quote's and books' records keep none, so each uses the item's own QUOTE_TIME_MILLIS
or BOOK_TIME. OPTIONS_BOOK has no recorded item: it is subscribed and unsubscribed, not sent.
Schwab's heartbeat frame is a stand-in with the shape of Schwab's notify frame."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from schwab.streaming import StreamClient
from websockets.asyncio.server import serve

from app.market_data.schwab.streaming.capture import NEWS_FIELDS, REQUEST_TIMEOUT_SEC, Daemon
from stream_spine import LOG, HealthRegistry, MessageBus

FX = Path(__file__).resolve().parent / "fixtures"
_EQUITY = json.loads((FX / "real_equity_book.json").read_text(encoding="utf-8"))
_NYSE = json.loads((FX / "real_spy_nyse_nasdaq_books.json").read_text(encoding="utf-8"))["books"]["NYSE_BOOK"]
_BAR = next(r for r in json.loads((FX / "real_daemon_bars_spy_tsla_spx_2026_10_01_02.json")
                                  .read_text(encoding="utf-8"))["rows"] if r["native"])
_OPTION = json.loads((FX / "real_options_stream_history_samples.json")
                     .read_text(encoding="utf-8"))["contracts"][0]["events"][0]["content"]
_CONTRACT = _OPTION["key"]

#: (service, the recorded item as schwab-py labels it, the frame's timestamp, the bus topic)
RECORDED = [
    ("LEVELONE_EQUITIES", _EQUITY["quote"]["native"], _EQUITY["quote"]["native"]["QUOTE_TIME_MILLIS"],
     "quote.TSLA"),
    ("NASDAQ_BOOK", _EQUITY["book"]["native"], _EQUITY["book"]["native"]["BOOK_TIME"], "book.TSLA"),
    ("NYSE_BOOK", _NYSE["content"], _NYSE["content"]["BOOK_TIME"], "book.SPY"),
    ("CHART_EQUITY", _BAR["native"], _BAR["schwab_ts"], "bar1m.SPY"),
    ("LEVELONE_OPTIONS", _OPTION, _OPTION["QUOTE_TIME_MILLIS"], f"optquote.{_CONTRACT}"),
]
WANTED = {"LEVELONE_EQUITIES": ["TSLA"], "NASDAQ_BOOK": ["TSLA"], "NYSE_BOOK": ["SPY"],
          "CHART_EQUITY": ["SPY"], "LEVELONE_OPTIONS": [_CONTRACT], "OPTIONS_BOOK": [_CONTRACT],
          "NEWS_HEADLINE": ["SPY"]}
#: every field of each service, as the daemon asks for it
FIELDS = {"LEVELONE_EQUITIES": StreamClient.LevelOneEquityFields, "CHART_EQUITY": StreamClient.ChartEquityFields,
          "LEVELONE_OPTIONS": StreamClient.LevelOneOptionFields, "NYSE_BOOK": StreamClient.BookFields,
          "NASDAQ_BOOK": StreamClient.BookFields, "OPTIONS_BOOK": StreamClient.BookFields}


def _numbered(item: dict, fields) -> dict:
    """`item` with Schwab's field number in place of each name schwab-py gave it."""
    numbers = {f.name: str(f.value) for f in fields}
    return {numbers.get(k, k): v for k, v in item.items()}


def _as_sent(service: str, item: dict) -> dict:
    """The item as Schwab's socket sends it: numbered, a book's levels and venues included."""
    if service not in ("NYSE_BOOK", "NASDAQ_BOOK"):
        return _numbered(item, FIELDS[service])
    out = _numbered(item, StreamClient.BookFields)
    for side, level, venue in (("BIDS", StreamClient.BidFields, StreamClient.PerExchangeBidFields),
                               ("ASKS", StreamClient.AskFields, StreamClient.PerExchangeAskFields)):
        out[str(StreamClient.BookFields[side].value)] = [
            {**_numbered(lvl, level), str(level[side].value): [_numbered(v, venue) for v in lvl[side]]}
            for lvl in item[side]]
    return out


def _frame(service: str, item: dict, ts: int) -> str:
    return json.dumps({"data": [{"service": service, "timestamp": ts, "command": "SUBS",
                                 "content": [_as_sent(service, item)]}]})


class _Preferences:
    """GET /userPreference as the stand-in client returns it: the streamer at `url`."""

    status_code = 200

    def __init__(self, url: str) -> None:
        self.url = url

    def json(self) -> dict:
        return {"streamerInfo": [{"streamerSocketUrl": self.url, "schwabClientCustomerId": "stand-in",
                                  "schwabClientCorrelId": "stand-in", "schwabClientChannel": "N9",
                                  "schwabClientFunctionId": "APIAPP"}]}


def _stand_in_client(url: str) -> SimpleNamespace:
    """The Schwab client as schwab-py's StreamClient.login reads it: its user preferences and its
    token's access_token."""
    return SimpleNamespace(token_metadata=SimpleNamespace(token={"access_token": "stand-in"}),
                           get_user_preferences=lambda: _Preferences(url))


def _answer(req: dict) -> str:
    return json.dumps({"response": [{"service": req["service"], "requestid": req["requestid"],
                                     "command": req["command"], "timestamp": 0,
                                     "content": {"code": 0, "msg": "stand-in"}}]})


def _published(sub) -> list:
    out = []
    while not sub.queue.empty():
        out.append(sub.queue.get_nowait())
    return out


def test_every_service_is_requested_through_schwab_py_and_every_frame_reaches_the_bus_as_sent():
    """The daemon's connection subscribes every service it is asked for, then, when the console's
    list empties, unsubscribes each; every request reaches Schwab with every field of its
    service, and every recorded frame reaches the bus as Schwab sent it, with its timestamp."""
    requests: list[dict] = []
    frames = {svc: _frame(svc, item, ts) for svc, item, ts, _topic in RECORDED}

    async def streamer(ws) -> None:
        async for text in ws:
            for req in json.loads(text)["requests"]:
                requests.append(req)
                await ws.send(_answer(req))
                if req["command"] == "SUBS" and req["service"] in frames:
                    await ws.send(frames[req["service"]])

    bus, health = MessageBus(), HealthRegistry()
    log = bus.subscribe("", policy=LOG)

    async def run() -> None:
        async with serve(streamer, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            daemon, stop = Daemon(bus, health), asyncio.Event()
            daemon.set_wanted(WANTED)
            loop = asyncio.get_running_loop()
            loop.call_later(1.0, daemon.set_wanted, {})
            loop.call_later(2.0, stop.set)
            await daemon.run_connection(_stand_in_client(f"ws://127.0.0.1:{port}"), stop)
    asyncio.run(run())

    asked = [(r["service"], r["command"], r["parameters"].get("keys"), r["parameters"].get("fields"))
             for r in requests if r["service"] != "ADMIN"]
    every_field = {svc: ",".join(str(v) for v in sorted(f.value for f in enum)) for svc, enum in FIELDS.items()}
    every_field["NEWS_HEADLINE"] = ",".join(str(f) for f in NEWS_FIELDS)
    assert sorted(asked) == sorted(
        [(svc, "SUBS", syms[0], every_field[svc]) for svc, syms in WANTED.items()]
        + [(svc, "UNSUBS", syms[0], None) for svc, syms in WANTED.items()])
    assert [r["command"] for r in requests if r["service"] == "ADMIN"] == ["LOGIN", "LOGOUT"]

    published = _published(log)
    assert sorted((m["service"], m["command"], m["code"]) for t, m in published if t.startswith("sub.")) == \
        sorted([(svc, "SUBS", 0) for svc in WANTED] + [(svc, "UNSUBS", 0) for svc in WANTED])
    data = {t: m for t, m in published if not t.startswith("sub.")}
    assert sorted(data) == sorted(topic for *_rest, topic in RECORDED)
    for svc, item, ts, topic in RECORDED:
        as_sent = data[topic].get("native") or data[topic].get("content")
        assert (as_sent, data[topic]["schwab_ts"]) == (item, ts), f"{svc} changed on its way to the bus"
        assert health.last(svc) is not None


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
                    await ws.send(_frame("LEVELONE_EQUITIES", item, ts))
                await ws.send(_answer(req))

    bus, health = MessageBus(), HealthRegistry()
    log = bus.subscribe("quote.", policy=LOG)

    async def run() -> tuple[float, float]:
        async with serve(streamer, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            daemon = Daemon(bus, health)
            await daemon.connect(_stand_in_client(f"ws://127.0.0.1:{port}"))
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
    """Schwab never answers a SUBS: after REQUEST_TIMEOUT_SEC the sync raises ConnectionError,
    which ends the connection (Daemon.run reconnects), and nothing counts as held or refused."""
    async def streamer(ws) -> None:
        async for text in ws:
            for req in json.loads(text)["requests"]:
                if req["service"] == "ADMIN":
                    await ws.send(_answer(req))

    bus, health = MessageBus(), HealthRegistry()

    async def run() -> tuple[str, Daemon]:
        async with serve(streamer, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            daemon = Daemon(bus, health)
            await daemon.connect(_stand_in_client(f"ws://127.0.0.1:{port}"))
            try:
                daemon.set_wanted({"NYSE_BOOK": ["SPY"]})
                daemon.wanted_changed.clear()
                try:
                    await daemon.sync()
                except ConnectionError as e:
                    return str(e), daemon
                return "", daemon
            finally:
                await daemon.disconnect()
    ended, daemon = asyncio.run(run())

    assert ended == f"no answer to NYSE_BOOK SUBS in {REQUEST_TIMEOUT_SEC:.0f} s"
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
            port = server.sockets[0].getsockname()[1]
            daemon = Daemon(bus, health)
            await daemon.connect(_stand_in_client(f"ws://127.0.0.1:{port}"))
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
