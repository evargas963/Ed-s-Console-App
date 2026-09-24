"""The header stream (/api/analytics/light/stream) sends the current quote at once, a live
verdict every second, and pushes each watchlist row the moment it changes (2026-09-24:
the header waited up to 9 s and the watchlist polled every 12 s)."""
from __future__ import annotations

import asyncio
import json
import time

import live_market_plane as lmp
import server as srv
from tests.feed_live_helper import feed_live_during


def _events(chunks):
    out = []
    for c in chunks:
        c = c.decode() if isinstance(c, bytes) else c
        if c.startswith("event: "):
            name, data = c.split("\n", 2)[:2]
            out.append((name[len("event: "):], json.loads(data[len("data: "):])))
    return out


def _read(watch, n, monkeypatch, during=None, seconds=3.0):
    monkeypatch.setattr(srv, "_l1_light_sse_try_reserve", lambda req, key: (asyncio.Queue(), ("r", "t", "e")))
    monkeypatch.setattr(srv, "_l1_light_sse_release", lambda *a: None)

    async def go():
        resp = await srv.get_analytics_light_stream(request=None, ticker="ZZHDR", expiry=None, watch=watch)
        it = resp.body_iterator
        chunks, end = [], time.monotonic() + seconds
        while len(chunks) < n and time.monotonic() < end:
            chunks.append(await asyncio.wait_for(it.__anext__(), timeout=seconds))
            if during and len(chunks) == during[0]:
                during[1]()
        await it.aclose()
        return chunks
    return _events(asyncio.run(go()))


def test_connect_sends_the_quote_and_every_watchlist_row_at_once(monkeypatch):
    feed_live_during(monkeypatch, "ZZHDR", "ZZW1")
    lmp.record_from_level_one_equity("ZZHDR", {"key": "ZZHDR", "LAST_PRICE": 10.0}, received_ts=time.time())
    lmp.record_from_level_one_equity("ZZW1", {"key": "ZZW1", "LAST_PRICE": 20.0}, received_ts=time.time())
    ev = _read("ZZW1,ZZW2", 4, monkeypatch)
    assert ev[0][0] == "l1_quote" and ev[0][1]["spot"] == 10.0 and ev[0][1]["spot_state"] == "live"
    rows = {e[1]["ticker"]: e[1]["row"] for e in ev if e[0] == "wl_quote"}
    assert rows["ZZW1"]["spot"] == 20.0 and rows["ZZW1"]["spot_state"] == "live"
    assert rows["ZZW2"] is None                               # not held -> UNAVAILABLE, not a guess


def test_a_changed_watchlist_row_is_pushed_without_polling(monkeypatch):
    feed_live_during(monkeypatch, "ZZHDR", "ZZW1")
    lmp.record_from_level_one_equity("ZZW1", {"key": "ZZW1", "LAST_PRICE": 20.0}, received_ts=time.time())

    def tick():
        lmp.record_from_level_one_equity("ZZW1", {"key": "ZZW1", "LAST_PRICE": 20.5}, received_ts=time.time())
    t0 = time.monotonic()
    ev = _read("ZZW1", 4, monkeypatch, during=(3, tick))   # after ": ok", l1_quote, first row
    pushed = [e[1]["row"]["spot"] for e in ev if e[0] == "wl_quote" and e[1]["row"]]
    assert pushed[:2] == [20.0, 20.5]
    assert time.monotonic() - t0 < 1.0                        # checked every 0.1 s, not a 12 s poll


def test_watchlist_route_and_push_share_one_row_builder():
    import inspect
    assert "_watchlist_row(" in inspect.getsource(srv.api_watchlist_quotes)
    assert "_watchlist_row(" in inspect.getsource(srv.get_analytics_light_stream)
