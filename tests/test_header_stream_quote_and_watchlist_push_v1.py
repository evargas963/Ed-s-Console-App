"""The displayed price (header + watchlist + chart) is ONE row: live_price_rows.price_row.

Since the daemon-to-browser change (Stage 1 of the live-UI architecture) the capture daemon
pushes that row straight to the browser (app/market_data/schwab/streaming/live_ui.py, proven
end to end in tests/test_live_ui_daemon_to_browser_v1.py). The console keeps no price
relay: its analytics stream carries gamma/L1 analytics only, and its watchlist route reads
the same row function -- so a price on screen and a price in a console calculation cannot
come from two rules.
"""
from __future__ import annotations

import asyncio
import inspect
import time
from pathlib import Path

import live_market_plane as lmp
import live_price_rows
import server as srv
from planes import l1_events
from tests.feed_live_helper import feed_live_during

ROOT = Path(__file__).resolve().parent.parent


def test_the_price_row_is_the_plane_row_not_a_projection(monkeypatch) -> None:
    feed_live_during(monkeypatch, "ZZQT")
    projected: list[str] = []
    monkeypatch.setattr(srv, "_project_l1", lambda *a, **k: projected.append("hit") or {})
    ts = time.time()
    assert lmp.record_from_level_one_equity(
        "ZZQT",
        {"LAST_PRICE": 11.5, "BID_PRICE": 11.4, "ASK_PRICE": 11.6, "NET_CHANGE_PERCENT": 1.25},
        received_ts=ts,
    )
    row = live_price_rows.price_row("ZZQT")
    assert row["ticker"] == "ZZQT"
    assert row["spot"] == 11.5 and row["spot_disp"] == "11.50"
    assert row["bid"] == 11.4 and row["ask"] == 11.6
    assert row["chg_pct"] == 1.25
    assert row["ts_recv"] == ts
    assert row["spot_state"] == "live"
    assert row["quote_ingestion"] == "schwab_streaming_level_one"
    assert projected == []


def test_an_unheld_symbol_row_is_unavailable_with_every_quote_field_withheld(monkeypatch) -> None:
    feed_live_during(monkeypatch, "ZZHELD")
    lmp.record_from_level_one_equity("ZZNOTHELD", {"LAST_PRICE": 9.0, "BID_PRICE": 8.9},
                                     received_ts=time.time())
    row = live_price_rows.price_row("ZZNOTHELD")
    assert row["spot"] is None and row["spot_state"] == "unavailable" and row["feed_live"] is False
    assert row["forming_1m"] is None


def test_console_spot_and_watchlist_read_the_same_row_function(monkeypatch) -> None:
    feed_live_during(monkeypatch, "ZZW1")
    lmp.record_from_level_one_equity("ZZW1", {"LAST_PRICE": 20.0}, received_ts=time.time())
    spot, src, _ = srv.resolve_spot("ZZW1")
    assert spot == live_price_rows.live_spot("ZZW1") == 20.0 and src == srv.SPOT_SOURCE_PLANE
    assert "_lpr.live_spot(" in inspect.getsource(srv.resolve_spot)
    assert "_lpr.price_row(" in inspect.getsource(srv._watchlist_row)


def test_the_console_analytics_stream_carries_no_price(monkeypatch) -> None:
    """The price relay is gone from the console: no quote_tick producer, no watch list on the
    stream, and the stream's first frames for a live symbol carry no price."""
    for name in ("_quote_tick_event", "_notify_quote_tick", "_format_quote_tick_sse",
                 "_l1_bind_quote_tick_sink", "_l1_light_sse_watch", "QUOTE_TICK_HEARTBEAT_SEC"):
        assert not hasattr(srv, name), name
    assert "watch" not in inspect.signature(srv.get_analytics_light_stream).parameters
    assert "_notify_quote_tick" not in inspect.getsource(l1_events)

    feed_live_during(monkeypatch, "ZZHDR")
    lmp.record_from_level_one_equity("ZZHDR", {"LAST_PRICE": 10.0}, received_ts=time.time())
    monkeypatch.setattr(srv, "_l1_light_sse_try_reserve",
                        lambda req, key: (asyncio.Queue(), ("r", "t", "e")))
    monkeypatch.setattr(srv, "_l1_light_sse_release", lambda *a: None)

    async def go():
        resp = await srv.get_analytics_light_stream(request=None, ticker="ZZHDR", expiry=None)
        it = resp.body_iterator
        first = await asyncio.wait_for(it.__anext__(), timeout=3)
        try:
            await asyncio.wait_for(it.__anext__(), timeout=0.5)
            extra = True
        except asyncio.TimeoutError:
            extra = False
        await it.aclose()
        return first, extra
    first, extra = asyncio.run(go())
    assert first == ": ok\n\n" and extra is False


def test_the_page_paints_prices_only_from_the_daemon_socket() -> None:
    core = (ROOT / "static" / "js" / "ed-core.js").read_text(encoding="utf-8")
    assert "var url = priceSocketUrl();" in core and "new WebSocket(url)" in core
    assert "msg.rows.forEach(ingestPriceRow)" in core
    assert 'meta[name="ed-live-ui-port"]' in core
    for gone in ("addEventListener('quote_tick'", "addEventListener('l1_quote'",
                 "addEventListener('wl_quote'", "&watch="):
        assert gone not in core, gone
    analytics = core.split("function openAnalyticsStream(")[1].split("\n  }\n")[0]
    assert "paintQuote" not in analytics and "setWlRow" not in analytics


def test_pages_are_told_the_daemon_price_port(monkeypatch) -> None:
    """The console fills the page's price-socket port from the daemon's own setting; e2e
    points it at a dead port so no test page can ever reach the real daemon."""
    from app.market_data.schwab.streaming import live_ui
    monkeypatch.setattr(live_ui, "LIVE_UI_PORT", 8811)
    for page in (srv.root(), srv.chart_page(), srv.exposure_page()):
        html = page.body.decode("utf-8")
        assert '<meta name="ed-live-ui-port" content="8811">' in html
        assert 'content="">' not in html.split("ed-live-ui-port", 1)[1][:12]


def test_notify_quote_updated_does_not_project_without_a_subscriber(monkeypatch) -> None:
    feed_live_during(monkeypatch, "ZZNOP")
    rebuilt: list[str] = []
    monkeypatch.setattr(srv, "_l1_on_quote_updated", lambda t: rebuilt.append(t))
    assert not srv._l1_ticker_has_projection_subscriber("ZZNOP")
    l1_events.notify_quote_updated("ZZNOP")
    assert rebuilt == []


def test_the_console_rebuilds_l1_from_its_plane_row_listener() -> None:
    """The plane no longer imports the console's event module; the console registers it."""
    assert l1_events.notify_quote_updated in lmp._row_listeners
    src = inspect.getsource(lmp)
    assert "from planes" not in src and "import planes" not in src


def test_notify_quote_updated_projects_when_an_l1_client_is_subscribed(monkeypatch) -> None:
    feed_live_during(monkeypatch, "ZZYES")
    q: asyncio.Queue = asyncio.Queue()
    srv._l1_light_sse_clients.append((q, ("ZZYES", "__auto__")))
    rebuilt: list[str] = []
    monkeypatch.setattr(srv, "_l1_on_quote_updated", lambda t: rebuilt.append(t))
    try:
        l1_events.notify_quote_updated("ZZYES")
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and rebuilt != ["ZZYES"]:
            time.sleep(0.01)
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
