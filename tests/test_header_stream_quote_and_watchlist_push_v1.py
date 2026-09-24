"""quote_tick is the ONE displayed-price event (header + watchlist) from the plane.

Replaces l1_quote / wl_quote (2026-09-24 Instant-UI Phase 2): emit on plane write, keep a
1 s idle beat of the same event, never paint last/bid/ask from l1_projection.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import time

import live_market_plane as lmp
import server as srv
from planes import l1_events
from tests.feed_live_helper import feed_live_during


def _events(chunks):
    out = []
    for c in chunks:
        c = c.decode() if isinstance(c, bytes) else c
        if c.startswith("event: "):
            name, data = c.split("\n", 2)[:2]
            out.append((name[len("event: "):], json.loads(data[len("data: "):])))
    return out


def _read(watch, n, monkeypatch, seconds=3.0):
    monkeypatch.setattr(srv, "_l1_light_sse_try_reserve", lambda req, key: (asyncio.Queue(), ("r", "t", "e")))
    monkeypatch.setattr(srv, "_l1_light_sse_release", lambda *a: None)
    monkeypatch.setattr(srv, "_l1_bind_sse_watch", lambda *a: None)

    async def go():
        resp = await srv.get_analytics_light_stream(request=None, ticker="ZZHDR", expiry=None, watch=watch)
        it = resp.body_iterator
        chunks, end = [], time.monotonic() + seconds
        while len(chunks) < n and time.monotonic() < end:
            chunks.append(await asyncio.wait_for(it.__anext__(), timeout=seconds))
        await it.aclose()
        return chunks
    return _events(asyncio.run(go()))


def test_quote_tick_payload_is_the_plane_row_not_a_projection(monkeypatch) -> None:
    feed_live_during(monkeypatch, "ZZQT")
    projected: list[str] = []
    monkeypatch.setattr(srv, "_project_l1", lambda *a, **k: projected.append("hit") or {})
    ts = 1_700_000_000.0
    assert lmp.record_from_level_one_equity(
        "ZZQT",
        {"LAST_PRICE": 11.5, "BID_PRICE": 11.4, "ASK_PRICE": 11.6, "NET_CHANGE_PERCENT": 1.25},
        received_ts=ts,
    )
    ev = srv._quote_tick_event("ZZQT")
    assert ev["_sse_event_name"] == "quote_tick"
    assert ev["ticker"] == "ZZQT"
    assert ev["spot"] == 11.5
    assert ev["bid"] == 11.4
    assert ev["ask"] == 11.6
    assert ev["chg_pct"] == 1.25
    assert ev["ts_recv"] == ts
    assert ev["spot_state"] == "live"
    assert ev["quote_ingestion"] == "schwab_streaming_level_one"
    assert projected == []


def test_connect_sends_quote_tick_for_header_and_every_watch_symbol(monkeypatch) -> None:
    feed_live_during(monkeypatch, "ZZHDR", "ZZW1")
    lmp.record_from_level_one_equity("ZZHDR", {"LAST_PRICE": 10.0}, received_ts=time.time())
    lmp.record_from_level_one_equity("ZZW1", {"LAST_PRICE": 20.0}, received_ts=time.time())
    ev = _read("ZZW1,ZZW2", 4, monkeypatch)
    ticks = [e for e in ev if e[0] == "quote_tick"]
    by_tk = {e[1]["ticker"]: e[1] for e in ticks}
    assert by_tk["ZZHDR"]["spot"] == 10.0 and by_tk["ZZHDR"]["spot_state"] == "live"
    assert by_tk["ZZW1"]["spot"] == 20.0 and by_tk["ZZW1"]["spot_state"] == "live"
    assert by_tk["ZZW2"]["spot"] is None and by_tk["ZZW2"]["spot_state"] == "unavailable"
    assert all(e[0] != "l1_quote" and e[0] != "wl_quote" for e in ev)


def test_notify_quote_tick_reaches_a_watching_client_and_keeps_latest_per_symbol(monkeypatch) -> None:
    feed_live_during(monkeypatch, "ZZW1")
    q: asyncio.Queue = asyncio.Queue(maxsize=8)
    srv._l1_light_sse_clients.append((q, ("ZZHDR", "__auto__")))
    srv._l1_light_sse_watch[id(q)] = ("ZZW1",)
    try:
        lmp.record_from_level_one_equity("ZZW1", {"LAST_PRICE": 20.0}, received_ts=time.time())
        srv._notify_quote_tick("ZZW1")
        lmp.record_from_level_one_equity("ZZW1", {"LAST_PRICE": 20.5}, received_ts=time.time())
        srv._notify_quote_tick("ZZW1")
        latest = None
        while True:
            try:
                _sk, env = srv._l1_sse_thread_queue.get_nowait()
            except Exception:
                break
            if env.get("_sse_event_name") == "quote_tick" and env.get("ticker") == "ZZW1":
                latest = env
        assert latest is not None and latest["spot"] == 20.5
        srv._l1_put_quote_tick_client_queue(q, {"_sse_event_name": "quote_tick", "ticker": "ZZW1", "spot": 20.0})
        srv._l1_put_quote_tick_client_queue(q, {"_sse_event_name": "quote_tick", "ticker": "ZZW1", "spot": 20.5})
        held = []
        while not q.empty():
            held.append(q.get_nowait())
        qt = [e for e in held if e.get("_sse_event_name") == "quote_tick" and e.get("ticker") == "ZZW1"]
        assert len(qt) == 1 and qt[0]["spot"] == 20.5
    finally:
        srv._l1_light_sse_clients[:] = [
            pair for pair in srv._l1_light_sse_clients if pair[0] is not q
        ]
        srv._l1_light_sse_watch.pop(id(q), None)


def test_notify_quote_updated_does_not_project_without_a_subscriber(monkeypatch) -> None:
    feed_live_during(monkeypatch, "ZZNOP")
    rebuilt: list[str] = []
    monkeypatch.setattr(srv, "_l1_on_quote_updated", lambda t: rebuilt.append(t))
    assert not srv._l1_ticker_has_projection_subscriber("ZZNOP")
    l1_events.notify_quote_updated("ZZNOP")
    assert rebuilt == []


def test_notify_quote_updated_projects_when_an_l1_client_is_subscribed(monkeypatch) -> None:
    feed_live_during(monkeypatch, "ZZYES")
    q: asyncio.Queue = asyncio.Queue()
    srv._l1_light_sse_clients.append((q, ("ZZYES", "__auto__")))
    rebuilt: list[str] = []
    monkeypatch.setattr(srv, "_l1_on_quote_updated", lambda t: rebuilt.append(t))
    try:
        l1_events.notify_quote_updated("ZZYES")
        assert rebuilt == ["ZZYES"]
    finally:
        srv._l1_light_sse_clients[:] = [
            pair for pair in srv._l1_light_sse_clients if pair[0] is not q
        ]
        while True:
            try:
                srv._l1_sse_thread_queue.get_nowait()
            except Exception:
                break


def test_watchlist_route_and_stream_share_quote_tick() -> None:
    from pathlib import Path

    assert "_quote_tick_event(" in inspect.getsource(srv._watchlist_row)
    src = inspect.getsource(srv.get_analytics_light_stream)
    assert "_format_quote_tick_sse" in src
    assert "l1_quote" not in src
    assert "wl_quote" not in src
    text = (Path(__file__).resolve().parent.parent / "static" / "js" / "ed-core.js").read_text(
        encoding="utf-8"
    )
    assert "addEventListener('quote_tick'" in text
    assert "addEventListener('l1_quote'" not in text
    assert "addEventListener('wl_quote'" not in text
    assert "Displayed last/bid/ask come from quote_tick" in text
