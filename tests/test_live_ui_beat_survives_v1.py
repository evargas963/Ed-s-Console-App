"""The daemon's price socket beats every browser every second and waits on none
(app/market_data/schwab/streaming/live_ui.py): a browser that stops reading for a moment is
skipped, not closed, and gets its beats again; the others never wait on it; one that has taken
no beat for the liveness limit (live_ui.BROWSER_SILENCE_SEC, 3 s) is closed.

Through the real serve_live_ui on 127.0.0.1 with real WebSocket clients, fed production's captured
stream (tests/fixtures/real_stream_mix_2026_10_05_1400ct.json: every LEVELONE_EQUITIES item
received 2026-10-05 14:00:00-14:00:03 CT, as Schwab sent it) through the daemon's own handler
(capture._publisher).

STAND-INS, each named:
  * the daemon's heartbeat (`_Heartbeat`): Schwab's socket open, holding every captured symbol;
  * a browser that stops reading (`_PausableBrowser`): a WebSocket client that reads its socket
    only while reading; while it is stopped its socket receive buffer is 4 KB, so nothing reads
    for it and the daemon's writes back up at the daemon, as a busy browser's do;
  * the stream while that browser is stopped (`_burst`): the captured window replayed back to back
    as fast as the daemon takes it, so the backlog outgrows any loopback socket buffer (Linux
    sizes them in megabytes) within half a second.
"""
from __future__ import annotations

import asyncio
import json
import socket
import time
from datetime import datetime
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.client import ClientProtocol
from websockets.exceptions import ConnectionClosed
from websockets.frames import Frame, Opcode
from websockets.protocol import State
from websockets.uri import parse_uri

from app.market_data.schwab.streaming import capture, live_ui
from stream_spine import HealthRegistry, MessageBus
from time_et import ET, session_label

_MIX = json.loads((Path(__file__).parent / "fixtures" / "real_stream_mix_2026_10_05_1400ct.json")
                  .read_text(encoding="utf-8"))
_EQ = [m for m in _MIX["messages"] if m["service"] == "LEVELONE_EQUITIES"]
_SYMS = sorted({m["item"]["key"] for m in _EQ})
#: a healthy browser's beats come every HEARTBEAT_SEC; this is the widest gap allowed between two
_BEAT_GAP_MAX = live_ui.HEARTBEAT_SEC * 1.5
_SMALL_RCVBUF, _LARGE_RCVBUF = 4096, 1 << 22


class _Heartbeat:
    def __init__(self) -> None:
        self.open = True

    def __call__(self) -> dict:
        return {"ts": time.time(), "schwab_socket_open": self.open,
                "held": {"LEVELONE_EQUITIES": _SYMS}, "health": {}}


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _publish_window(handler) -> None:
    for m in _EQ:
        handler({"content": [m["item"]], "timestamp": m["schwab_ts"]})


async def _burst(handler) -> None:
    """The captured window through the daemon's handler, back to back, until cancelled."""
    while True:
        for m in _EQ:
            handler({"content": [m["item"]], "timestamp": m["schwab_ts"]})
            await asyncio.sleep(0)           # each message reaches the browsers on its own


class _PausableBrowser:
    """A WebSocket client (websockets' own sans-I/O protocol) that reads its socket only while
    `reading` is set. It reads 4 KB at a time into a 4 KB receive buffer until its first pause;
    on `resume` it reads up to a megabyte at a time into a 4 MB buffer, to catch up at once."""

    def __init__(self, port: int) -> None:
        self.port, self.beats, self.closed = port, [], None
        self.proto = ClientProtocol(parse_uri(f"ws://127.0.0.1:{port}/"), max_size=None)
        self.reading = asyncio.Event()
        self.reading.set()
        self.chunk = _SMALL_RCVBUF

    async def open(self, subscribe: str) -> None:
        loop = asyncio.get_running_loop()
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, _SMALL_RCVBUF)
        self.sock.setblocking(False)
        await loop.sock_connect(self.sock, ("127.0.0.1", self.port))
        self.proto.send_request(self.proto.connect())
        await self._flush()
        while self.proto.state is State.CONNECTING:
            await self._read()
        self.proto.send_text(subscribe.encode())
        await self._flush()
        self.task = asyncio.create_task(self._run())

    def pause(self) -> None:
        self.reading.clear()

    def resume(self) -> None:
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, _LARGE_RCVBUF)
        self.chunk = 1 << 20
        self.reading.set()

    async def _flush(self) -> None:
        for data in self.proto.data_to_send():
            if data:
                await asyncio.get_running_loop().sock_sendall(self.sock, data)

    async def _read(self) -> None:
        data = await asyncio.get_running_loop().sock_recv(self.sock, self.chunk)
        if data:
            self.proto.receive_data(data)
        else:
            self.proto.receive_eof()
        await self._flush()                 # a pong, or the reply to the daemon's close

    async def _run(self) -> None:
        while self.closed is None:
            await self.reading.wait()
            await self._read()
            for ev in self.proto.events_received():
                if isinstance(ev, Frame) and ev.opcode is Opcode.TEXT:
                    if json.loads(ev.data).get("type") == "feed":
                        self.beats.append(time.monotonic())
                elif isinstance(ev, Frame) and ev.opcode is Opcode.CLOSE:
                    self.closed = self.proto.close_rcvd
            if self.proto.state is State.CLOSED and self.closed is None:
                self.closed = "connection lost"

    def close(self) -> None:
        self.task.cancel()
        self.sock.close()


class _Reader:
    """Reads a healthy browser's frames, noting when each beat arrived."""

    def __init__(self, ws) -> None:
        self.ws, self.beats, self.closed = ws, [], None
        self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            while True:
                msg = json.loads(await self.ws.recv())
                if msg.get("type") == "feed":
                    self.beats.append(time.monotonic())
        except ConnectionClosed as e:
            self.closed = e


async def _session(body) -> None:
    port, bus, stop, stats = _free_port(), MessageBus(), asyncio.Event(), {}
    heartbeat = _Heartbeat()
    server = asyncio.create_task(live_ui.serve_live_ui(
        bus, stop, heartbeat_fn=heartbeat, host="127.0.0.1", port=port, stats=stats))
    end = time.monotonic() + 5
    while not stats.get("listening") and time.monotonic() < end:
        await asyncio.sleep(0.01)
    assert stats.get("listening")
    handler = capture._publisher("LEVELONE_EQUITIES", bus, HealthRegistry())
    _publish_window(handler)
    try:
        await body(port, handler, heartbeat, stats)
    finally:
        stop.set()
        await asyncio.wait_for(asyncio.gather(server, return_exceptions=True), 15)


async def _two_browsers(port: int):
    healthy = await connect(f"ws://127.0.0.1:{port}")
    subscribe = json.dumps({"op": "subscribe", "symbols": _SYMS})
    await healthy.send(subscribe)
    paused = _PausableBrowser(port)
    await paused.open(subscribe)
    return healthy, _Reader(healthy), paused


async def _paused_for(p: _PausableBrowser, handler, sec: float) -> None:
    """`p` reads nothing for `sec` while the stream bursts; then it reads again."""
    p.pause()
    burst = asyncio.create_task(_burst(handler))
    await asyncio.sleep(sec)
    burst.cancel()
    await asyncio.gather(burst, return_exceptions=True)
    p.resume()


def _gaps(beats: list[float]) -> list[float]:
    return [round(b - a, 2) for a, b in zip(beats, beats[1:])]


def test_a_browser_that_stops_reading_for_a_moment_stays_and_the_others_never_wait():
    """Measured 2026-10-06: the daemon closed a browser that did not take a beat within 1 s, every
    2-3 s, and the screen flashed OFFLINE. A browser that stops reading for 1.5 s stays connected
    and gets beats again after; the healthy browser gets a beat every second the whole time."""
    async def body(port, handler, heartbeat, stats):
        healthy, h, p = await _two_browsers(port)
        await asyncio.sleep(1.5)                     # both reading
        paused_at = time.monotonic()
        await _paused_for(p, handler, 1.5)
        await asyncio.sleep(3.0)                     # reading again
        assert p.closed is None, f"the browser that paused for 1.5 s was closed: {p.closed!r}"
        after = [b for b in p.beats if b > paused_at + 1.5]
        assert len(after) >= 2, f"the paused browser got {len(after)} beats in the 3 s after it read again"
        assert h.closed is None and len(h.beats) >= 5, (h.closed, len(h.beats))
        assert max(_gaps(h.beats)) < _BEAT_GAP_MAX, f"the healthy browser waited: gaps {_gaps(h.beats)}"
        await healthy.close()
        p.close()
    asyncio.run(_session(body))


def test_a_browser_silent_past_the_liveness_limit_is_closed_and_the_others_never_wait():
    """The paused browser reads nothing for longer than BROWSER_SILENCE_SEC: the daemon closes
    it (once it reads again it finds the close), and the healthy browser's beats never wait."""
    assert live_ui.BROWSER_SILENCE_SEC == 3.0

    async def body(port, handler, heartbeat, stats):
        healthy, h, p = await _two_browsers(port)
        await asyncio.sleep(1.5)
        await _paused_for(p, handler, live_ui.BROWSER_SILENCE_SEC + 2.0)
        end = time.monotonic() + 8
        while p.closed is None and time.monotonic() < end:
            await asyncio.sleep(0.1)
        assert p.closed is not None, "a browser silent past the liveness limit was never closed"
        assert stats["beat_send_failures"] >= 1
        assert h.closed is None, f"the healthy browser was closed: {h.closed!r}"
        assert max(_gaps(h.beats)) < _BEAT_GAP_MAX, f"the healthy browser waited: gaps {_gaps(h.beats)}"
        await healthy.close()
        p.close()
    asyncio.run(_session(body))


def test_a_closed_schwab_socket_reads_feed_down_within_one_beat_and_keeps_the_last_values():
    """Nothing from Schwab; only the beat knows. The heartbeat says Schwab's socket closed: within
    one beat every row reads feed_live False and keeps Schwab's last values (AGENTS.md rule 5);
    in an open session it carries the outage and the not-live words, while Closed neither (the
    session from time_et.session_label at the row's own time)."""
    spy = [m["item"] for m in _EQ if m["item"]["key"] == "SPY" and "LAST_PRICE" in m["item"]]

    async def body(port, handler, heartbeat, stats):
        async with connect(f"ws://127.0.0.1:{port}") as ws:
            await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
            heartbeat.open = False
            end = time.monotonic() + live_ui.HEARTBEAT_SEC * 2.5
            row = None
            while row is None and time.monotonic() < end:
                msg = json.loads(await asyncio.wait_for(ws.recv(), end - time.monotonic()))
                if msg.get("type") == "feed" and msg["feed"]["schwab_socket_open"] is False:
                    row = next(r for r in msg["rows"] if r["ticker"] == "SPY")
            assert row is not None, "no beat said the Schwab socket closed"
            assert row["feed_live"] is False
            assert row["spot"] == spy[-1]["LAST_PRICE"]
            session = session_label(datetime.fromtimestamp(row["server_ts"], ET))
            if session == "Closed":
                assert row["outage"] is None and row["not_live"] is None
            else:
                assert row["outage"] == f"Schwab LEVELONE_EQUITIES feed down during {session}"
                assert row["not_live"].startswith("NOT LIVE · " + row["outage"] + " · last trade ")
    asyncio.run(_session(body))
