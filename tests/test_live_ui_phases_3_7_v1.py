"""Instant-UI Phases 3–7 seams. Each expected value is independently derived."""
from __future__ import annotations


def test_token_write_is_atomic_temp_replace(tmp_path):
    from schwab_client import write_token_file_atomically

    dest = tmp_path / "schwab_token.json"
    payload = {"access_token": "aaa", "refresh_token": "bbb"}
    write_token_file_atomically(str(dest), payload)
    text = dest.read_text(encoding="utf-8")
    assert '"access_token": "aaa"' in text
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == [], leftovers


def test_the_console_takes_the_daemons_price_row_and_ticks_on_it(monkeypatch):
    """End to end on the real parts: the daemon's price push (live_ui.serve_live_ui on a real
    bus and socket) and the console's client of it (streaming._rows_loop). A Schwab trade on the
    bus reaches the console as the daemon's row: that row is the console's spot, and its arrival
    is the equity's tick. Stand-in trade (named): BBB 10.00."""
    import asyncio
    import socket
    import time

    import app.options.order_flow.streaming as ofs
    import live_market_plane as lmp
    import server
    from app.market_data.schwab.streaming import live_ui
    from stream_spine import MessageBus, quote_msg

    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    hits: list[str] = []
    monkeypatch.setattr(ofs, "_on_tick_callback", lambda sym: hits.append(sym))
    monkeypatch.setattr(ofs, "_equity_demand", {"watchlist": ["BBB"], "board": []})
    monkeypatch.setattr(ofs, "LIVE_UI_URL", f"ws://127.0.0.1:{port}")
    monkeypatch.setattr(ofs, "_price_rows", {})
    monkeypatch.setattr(ofs, "_feed_running", True)
    monkeypatch.setattr(lmp, "_by_ticker", {})
    monkeypatch.setattr(lmp, "_fields_by_ticker", {})

    async def main():
        bus, stop, stats = MessageBus(), asyncio.Event(), {}
        feed = lambda: {"ts": time.time(), "schwab_socket_open": True,  # noqa: E731
                        "held": {"LEVELONE_EQUITIES": ["BBB"]}, "health": {}}
        daemon = asyncio.create_task(live_ui.serve_live_ui(bus, stop, heartbeat_fn=feed,
                                                           host="127.0.0.1", port=port, stats=stats))
        console = asyncio.create_task(ofs._rows_loop())
        try:
            end = time.monotonic() + 5
            while ofs.price_row("BBB") is None and time.monotonic() < end:
                await asyncio.sleep(0.05)                           # subscribed: the snapshot row
            hits.clear()
            now = time.time()
            bus.publish("quote.BBB", quote_msg(symbol="BBB", last=10.0, src="schwab_l1", ts_recv=now,
                                               native={"key": "BBB", "LAST_PRICE": 10.0,
                                                       "TRADE_TIME_MILLIS": int(now * 1000)}))
            while (ofs.price_row("BBB") or {}).get("spot") != 10.0 and time.monotonic() < end:
                await asyncio.sleep(0.02)
            return server.resolve_spot("BBB")[:2]
        finally:
            stop.set()
            console.cancel()
            await asyncio.gather(daemon, console, return_exceptions=True)

    assert asyncio.run(main()) == (10.0, server.SPOT_SOURCE_PLANE)
    assert "BBB" in hits                                           # the trade's row was the tick
