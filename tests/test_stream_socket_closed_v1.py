"""The daemon closes Schwab's stream socket when a connection ends (feed.connection.disconnect).

schwab-py's logout sends LOGOUT and leaves the websocket open; Schwab's Streamer API §1: on
LOGOUT the "Streamer will close the connection". A connection gone silent answers nothing and
closes nothing, so the daemon's end stayed open after each such reconnect. The daemon now drops
its end when the logout fails, without the closing handshake a silent peer would make it wait
for. Real daemon connection against the local streamer (tests/schwab_stream_standin.py) and the
local Schwab (tests/schwab_rest_standin.py).
"""

from __future__ import annotations

import asyncio

from app.market_data.schwab.streaming import capture
from stream_spine import HealthRegistry, MessageBus
from tests.schwab_rest_standin import LocalSchwab
from tests.schwab_stream_standin import LocalStreamer
from tests.shared_helpers import until


def _connection_ended(tmp_path, *, silent_on_logout: bool):
    """Run one daemon connection to the local streamer and end it.

    Return whether its socket was closed once the connection had ended, read on the running
    loop as the daemon goes on (asyncio.run's teardown closes what is left, so after it the
    answer would be the teardown's), and how long the end took from the stop.
    """
    streamer = LocalStreamer({}, data={}, beat=0.05)
    streamer.silent_on_logout = silent_on_logout
    rest = LocalSchwab(streamer.url)
    client = rest.client(tmp_path)
    conn = capture.Daemon(MessageBus(), HealthRegistry(), []).connection

    async def go():
        stop = asyncio.Event()
        run = asyncio.create_task(conn.run_connection(client, stop))
        await until(lambda: conn.stream is not None and conn.stream.schwab_ts is not None, 30)
        stream = conn.stream
        stopped = asyncio.get_running_loop().time()
        stop.set()
        done, _pending = await asyncio.wait([run], timeout=30)
        assert run in done, "the connection did not end"
        took = asyncio.get_running_loop().time() - stopped
        # the daemon goes on: its end of the socket closes, as it would on its own
        await until(lambda: stream._socket.closed, 5, lambda: "the websocket stayed open")
        return stream._socket.closed, took

    try:
        return asyncio.run(go())
    finally:
        streamer.close()
        rest.close()


def test_a_connection_logged_out_is_closed(tmp_path):
    closed, _took = _connection_ended(tmp_path, silent_on_logout=False)
    assert closed, "the websocket stayed open after the logout"


def test_a_silent_connection_is_dropped_when_its_logout_gets_no_answer(tmp_path):
    """Induced condition: the streamer answers no LOGOUT and keeps the socket open."""
    closed, took = _connection_ended(tmp_path, silent_on_logout=True)
    assert closed, "the websocket stayed open after a logout with no answer"
    # the logout's own wait (5 s) and no closing handshake's after it (websockets' 10 s)
    assert took < 9, f"the connection took {took:.1f} s to end"
