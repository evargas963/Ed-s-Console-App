"""Every symbol a screen shows a live price for is streamed on request.

The capture daemon has no built-in symbol list (operator 2026-09-23: universality). With spot
= streamed LAST_PRICE only (no REST fallback), a symbol nobody asked the daemon to stream
would read UNAVAILABLE forever. The console sends every symbol its screens show (the active
ticker, the header's context, the watchlist) in the wanted list, with no cap (operator
2026-10-01); the daemon streams the board itself.
"""
from __future__ import annotations

import time

import app.options.order_flow.streaming as ofs
import live_market_plane as lmp


def test_every_symbol_shown_is_asked_for_each_once():
    watchlist = ["AAPL", "TSLA", "spy", "SPX"] + [f"Z{i:03d}" for i in range(400)]
    assert ofs.equity_symbols("tsla", watchlist) == [
        "TSLA", *ofs.MARKET_CONTEXT_SYMBOLS, "AAPL", "SPY"] + [f"Z{i:03d}" for i in range(400)]


def test_the_board_is_the_daemons_list_never_copied_into_the_consoles(monkeypatch):
    """2026-10-01 audit: the console copied the daemon's board into its own wanted list, so a
    ticker taken off the table was still streamed after a daemon restart (the daemon reloads the
    console's last list). The console holds the board's price rows, read from the daemon's
    heartbeat: every equity the daemon streams (what it holds), and asks for none of them."""
    import push_changes
    monkeypatch.setattr(push_changes, "_open", [])
    monkeypatch.setattr(ofs, "_watchlist", ["AAPL"])
    lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True, "board": ["MU", "AAPL"],
                               "held": {"LEVELONE_EQUITIES": ["MU", "AAPL", "$SPX"]}})
    assert "MU" not in ofs.current_wanted()["LEVELONE_EQUITIES"]
    assert ofs._rows_wanted() == ["$SPX", "AAPL", "MU"]


def test_the_watchlist_route_declares_the_browsers_watchlist(monkeypatch):
    from fastapi.testclient import TestClient

    import server

    seen = []
    monkeypatch.setattr(ofs, "declare_watchlist", seen.append)
    client = TestClient(server.app)
    r = client.post("/api/streaming/watchlist-symbols", json={"symbols": ["AAPL", "ZZZ"]})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert seen == [["AAPL", "ZZZ"]]
    assert client.post("/api/streaming/watchlist-symbols", json={"symbols": "AAPL"}).status_code == 400
