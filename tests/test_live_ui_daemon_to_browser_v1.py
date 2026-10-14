"""Schwab's LEVELONE_EQUITIES messages straight from the capture daemon to the console (live_ui.py),
end to end, by their Schwab delivery type (Streamer API §1.1: Change).

The REAL daemon-side path: Schwab's frames into the daemon's own handler (capture._publisher), its
real bus (stream_spine.MessageBus), the real server (serve_live_ui), and a REAL WebSocket client
standing in for the console's _rows_loop, over a real local socket. Real data: every message
Schwab sent 2026-10-05 14:00:00-14:00:03 CT (tests/fixtures/real_stream_mix_2026_10_05_1400ct.json:
7,420 LEVELONE_OPTIONS, 152 LEVELONE_EQUITIES, 12 book messages). STAND-IN (named): the daemon's
status each beat reports (socket open, symbols held).
"""
from __future__ import annotations

import asyncio
import json
import socket
import time
from pathlib import Path

from app.market_data.schwab.streaming import capture, live_ui
from stream_spine import HealthRegistry, MessageBus

FX = Path(__file__).resolve().parent / "fixtures"
_MIX = json.loads((FX / "real_stream_mix_2026_10_05_1400ct.json").read_text(encoding="utf-8"))["messages"]
_EVERY = sorted({m["item"]["key"] for m in _MIX})
#: the daemon's receipts of Schwab's CHART_EQUITY bars that carry Schwab's own item, in receive order
_BARS = sorted((r for r in json.loads((FX / "real_daemon_bars_spy_tsla_2026_10_01_02.json").read_text(
    encoding="utf-8"))["rows"] if r["native"]), key=lambda r: r["ts_recv"])
_NEWS = json.loads((FX / "real_schwab_news_headline_spx_2026_10_05.json").read_text(encoding="utf-8"))


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Feed:
    """The daemon's status as its heartbeat reports it (STAND-IN)."""

    def __call__(self) -> dict:
        return {"ts": time.time(), "schwab_socket_open": True, "held": {"LEVELONE_EQUITIES": ["SPY"]}, "health": {}}


def _frame(bus, service: str, item: dict, schwab_ts) -> None:
    """One Schwab frame into the daemon's own handler for `service`, as schwab-py hands it."""
    capture._publisher(service, bus, HealthRegistry())({"timestamp": schwab_ts, "content": [item]})


async def _run(body):
    """The daemon's server and a client on it."""
    from websockets.asyncio.client import connect

    port = _free_port()
    bus = MessageBus()
    stop = asyncio.Event()
    stats: dict = {}
    server = asyncio.create_task(live_ui.serve_live_ui(
        bus, stop, heartbeat_fn=_Feed(), host="127.0.0.1", port=port, stats=stats))
    end = time.monotonic() + 5
    while not stats.get("listening") and time.monotonic() < end:
        await asyncio.sleep(0.01)
    assert stats.get("listening")
    try:
        async with connect(f"ws://127.0.0.1:{port}", max_size=None) as ws:
            await body(bus, ws, stats)
    finally:
        stop.set()
        await asyncio.wait_for(asyncio.gather(server, return_exceptions=True), 5)


async def _received(ws, quiet: float = 0.5, timeout: float = 20.0) -> "tuple[list[dict], list[dict]]":
    """(every Schwab message, every beat) the client receives until `quiet` s pass with no
    Schwab message."""
    messages, beats = [], []
    end, last = time.monotonic() + timeout, time.monotonic()
    while time.monotonic() < end and time.monotonic() - last < quiet:
        try:
            frame = json.loads(await asyncio.wait_for(ws.recv(), quiet))
        except (asyncio.TimeoutError, TimeoutError):
            break
        if frame["type"] == "schwab":
            messages += frame["messages"]
            last = time.monotonic()
        elif frame["type"] == "feed":
            beats.append(frame)
    return messages, beats


def test_every_service_reaches_the_screen_by_its_delivery_type():
    """Every symbol of the real mix subscribed, then every message Schwab sent, with the real
    CHART_EQUITY bars and NEWS_HEADLINE item behind it. Change (LEVELONE_EQUITIES,
    LEVELONE_OPTIONS): each symbol's fields as the last Schwab sent each, none lost. Whole
    (NYSE_BOOK, NASDAQ_BOOK, OPTIONS_BOOK): each book as Schwab sent it, the newest last. Sequence
    (CHART_EQUITY, NEWS_HEADLINE): every bar and headline, in the order Schwab sent them."""
    bars = [(r["native"], r["schwab_ts"]) for r in _BARS]
    every = sorted({*_EVERY, *(b["key"] for b, _ts in bars), _NEWS["symbol"]})

    async def body(bus, ws, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": every}))
        while json.loads(await asyncio.wait_for(ws.recv(), 3))["type"] != "symbols":
            pass                                  # the daemon has taken the subscription
        for m in _MIX:
            _frame(bus, m["service"], m["item"], m["schwab_ts"])
        for item, ts in bars:
            _frame(bus, "CHART_EQUITY", item, ts)
        _frame(bus, "NEWS_HEADLINE", _NEWS["content"], _NEWS["schwab_ts"])
        got, _beats = await _received(ws)
        by = lambda svc: [m for m in got if m["service"] == svc]   # noqa: E731
        sent = lambda svc: [m for m in _MIX if m["service"] == svc]   # noqa: E731
        assert {m["service"] for m in got} == set(live_ui.DELIVERY)
        for svc in ("LEVELONE_EQUITIES", "LEVELONE_OPTIONS"):
            want: dict = {}
            for m in sent(svc):
                want.setdefault(m["item"]["key"], {}).update(m["item"])
            fields: dict = {}
            for m in by(svc):
                fields.setdefault(m["key"], {}).update(m["content"])
            assert fields == want, f"a {svc} field Schwab sent was lost or changed"
        for svc in ("NYSE_BOOK", "NASDAQ_BOOK", "OPTIONS_BOOK"):
            for key in {m["item"]["key"] for m in sent(svc)}:
                books = [m["item"] for m in sent(svc) if m["item"]["key"] == key]
                shown = [m["content"] for m in by(svc) if m["key"] == key]
                assert shown and shown[-1] == books[-1], f"{svc} {key}: the newest book is not the one shown"
                assert all(b in books for b in shown), f"{svc} {key}: a book was changed"
        assert [(m["key"], m["content"]) for m in by("CHART_EQUITY")] == [(b["key"], b) for b, _ts in bars]
        assert [m["content"] for m in by("NEWS_HEADLINE")] == [_NEWS["content"]]
    asyncio.run(_run(body))


def test_a_headline_carries_its_time_as_the_screen_shows_it():
    """Schwab's headline time (field 1, epoch ms) labelled once, by the daemon, in Central Time."""
    from time_et import ct_label

    m = live_ui.schwab_message("news." + _NEWS["symbol"], {"symbol": _NEWS["symbol"], "content": _NEWS["content"],
                                                           "schwab_ts": _NEWS["schwab_ts"], "ts_recv": _NEWS["ts_recv"]})
    assert m["content"] == _NEWS["content"] and m["time_ct"] == ct_label(_NEWS["content"]["1"] / 1000.0)


def test_a_symbol_nobody_asked_for_is_never_sent():
    async def body(bus, ws, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        for m in _MIX:
            _frame(bus, m["service"], m["item"], m["schwab_ts"])
        got, _beats = await _received(ws)
        assert got and {m["key"] for m in got} == {"SPY"}
    asyncio.run(_run(body))


def test_a_new_subscription_gets_each_symbols_current_record_at_once():
    """Schwab sent AAPL's fields before the client asked for it: on subscribing it gets every
    field Schwab has sent, each the last one, without waiting for a new message."""
    aapl = [m for m in _MIX if m["service"] == "LEVELONE_EQUITIES" and m["item"]["key"] == "AAPL"]
    want: dict = {}
    for m in aapl:
        want.update(m["item"])

    async def body(bus, ws, stats):
        for m in aapl:
            _frame(bus, m["service"], m["item"], m["schwab_ts"])
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["AAPL"]}))
        got, _beats = await _received(ws, quiet=0.3)
        assert [m["content"] for m in got] == [want]
    asyncio.run(_run(body))


def test_each_bar_carries_schwabs_fields_as_the_chart_draws_them():
    """Every real CHART_EQUITY bar: its start (CHART_TIME_MILLIS, s), open, high, low, close and
    volume as Schwab sent them, the change over the bar (close - open, and its percent of the open)
    and its start labelled in Central Time, each by its one producer."""
    from time_et import ct_label

    for r in _BARS:
        n = r["native"]
        m = live_ui.schwab_message("bar1m." + n["key"], {"symbol": n["key"], "native": n, "schwab_ts": r["schwab_ts"],
                                                         "ts_recv": r["ts_recv"]})
        chg = n["CLOSE_PRICE"] - n["OPEN_PRICE"]
        assert m["content"] == n
        assert m["bar"] == {"t": n["CHART_TIME_MILLIS"] / 1000.0, "o": n["OPEN_PRICE"], "h": n["HIGH_PRICE"],
                            "l": n["LOW_PRICE"], "c": n["CLOSE_PRICE"], "v": n["VOLUME"], "chg": chg,
                            "chg_pct": chg / n["OPEN_PRICE"] * 100}
        assert m["time_ct"] == ct_label(n["CHART_TIME_MILLIS"] / 1000.0)


def test_a_contract_opened_after_its_messages_gets_every_field_schwab_streamed():
    """Operator 2026-10-14 (the bank's running balance): a screen that asks for a contract Schwab
    has been streaming gets, at once, every LEVELONE_OPTIONS field Schwab sent for it, each the
    last one, as sent; before, it got nothing until the next change, and then only that change."""
    key = max({m["item"]["key"] for m in _MIX if m["service"] == "LEVELONE_OPTIONS"},
              key=lambda k: sum(1 for m in _MIX if m["item"]["key"] == k))
    sent = [m for m in _MIX if m["item"]["key"] == key]
    want: dict = {}
    for m in sent:
        want.update(m["item"])

    async def body(bus, ws, stats):
        for m in sent:
            _frame(bus, m["service"], m["item"], m["schwab_ts"])
        await ws.send(json.dumps({"op": "subscribe", "symbols": [key]}))
        got, _beats = await _received(ws, quiet=0.3)
        assert len(sent) > 1 and [(m["service"], m["content"]) for m in got] == [("LEVELONE_OPTIONS", want)]
    asyncio.run(_run(body))


def test_each_beat_is_the_daemons_whole_status():
    async def body(bus, ws, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        while (frame := json.loads(await asyncio.wait_for(ws.recv(), 3)))["type"] != "feed":
            pass
        assert set(frame) == {"type", "feed", "state", "trades"} and frame["feed"]["held"] == {"LEVELONE_EQUITIES": ["SPY"]}
        assert set(frame["state"]["SPY"]) == set(live_ui.EQUITY_SERVICES)
    asyncio.run(_run(body))


def test_shutdown_is_not_held_up_by_a_connected_client():
    async def body(bus, ws, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        await asyncio.wait_for(ws.recv(), 2)
    t0 = time.monotonic()
    asyncio.run(_run(body))
    assert time.monotonic() - t0 < 5


def test_the_daemons_socket_and_the_console_listen_on_this_computer_only():
    """Operator 2026-10-14: "Bind both 8800 and 8000 to 127.0.0.1. I only use this computer."
    The daemon's socket, served as the daemon serves it (its own host), listens on 127.0.0.1;
    the console is started by the launcher on 127.0.0.1. Before, both listened on every address."""
    import launch

    async def go():
        stop, stats = asyncio.Event(), {}
        server = asyncio.create_task(live_ui.serve_live_ui(MessageBus(), stop, heartbeat_fn=_Feed(), port=0, stats=stats))
        end = time.monotonic() + 5
        while not stats.get("listening") and time.monotonic() < end:
            await asyncio.sleep(0.01)
        stop.set()
        await asyncio.wait_for(server, 5)
        return stats["listening"]
    assert asyncio.run(go()).startswith("ws://127.0.0.1:")
    host = launch.CONSOLE[launch.CONSOLE.index("--host") + 1]
    assert host == "127.0.0.1"
