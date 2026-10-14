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
        bus, stop, heartbeat_fn=_Feed(), host="127.0.0.1", port=port, stats=stats,
        record_heartbeat=lambda _beat: None))
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


def test_every_equity_field_schwab_sent_reaches_the_console_and_nothing_else():
    """Every symbol of the real mix subscribed, then every message Schwab sent: each equity's
    fields as the last Schwab sent each (Change: only fields Schwab sent, none lost), merged for a
    client behind; no option quote or book (the console takes those from its own push, 8799)."""
    async def body(bus, ws, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": _EVERY}))
        for m in _MIX:
            _frame(bus, m["service"], m["item"], m["schwab_ts"])
        got, _beats = await _received(ws)
        want: dict = {}
        for m in _MIX:
            if m["service"] == "LEVELONE_EQUITIES":
                want.setdefault(m["item"]["key"], {}).update(m["item"])
        fields: dict = {}
        for m in got:
            assert m["service"] == "LEVELONE_EQUITIES"
            fields.setdefault(m["key"], {}).update(m["content"])
        assert fields == want, "an equity field Schwab sent was lost or changed"
        assert stats["frames_sent"] < sum(1 for m in _MIX if m["service"] == "LEVELONE_EQUITIES")
    asyncio.run(_run(body))


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


def test_each_beat_is_the_daemons_whole_status():
    async def body(bus, ws, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        while (frame := json.loads(await asyncio.wait_for(ws.recv(), 3)))["type"] != "feed":
            pass
        assert set(frame) == {"type", "feed"} and frame["feed"]["held"] == {"LEVELONE_EQUITIES": ["SPY"]}
    asyncio.run(_run(body))


def test_shutdown_is_not_held_up_by_a_connected_client():
    async def body(bus, ws, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        await asyncio.wait_for(ws.recv(), 2)
    t0 = time.monotonic()
    asyncio.run(_run(body))
    assert time.monotonic() - t0 < 5
