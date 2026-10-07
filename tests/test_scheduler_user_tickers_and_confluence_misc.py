"""The watchlist: the one list both processes hold."""

from __future__ import annotations


def test_the_console_and_the_daemon_hold_one_watchlist(tmp_path):
    """ONE-13 (2026-09-28 audit), and one list (2026-10-07): the console carries the daemon's
    watchlist from its heartbeat, and the daemon starts from the newest list its writer stored
    (stream_watchlist), in its order."""
    import live_market_plane as lmp
    import server
    from app.market_data.schwab.streaming import capture
    from stream_spine import CaptureWriter, HealthRegistry, MessageBus
    db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(db)
    writer.insert(*capture.watchlist_message(["SPY", "TSLA"], op=capture.ADDED, ticker="TSLA", request_id=1))
    writer.insert(*capture.watchlist_message(["SPY", "TSLA", "$SPX"], op=capture.ADDED, ticker="$SPX", request_id=2))
    d = capture.Daemon(MessageBus(), HealthRegistry(), capture.stored_watchlist(db))
    lmp.record_feed_heartbeat(d.status())
    assert d.watchlist == server._watchlist() == ["SPY", "TSLA", "$SPX"]


def test_a_first_run_with_no_database_starts_with_an_empty_watchlist(tmp_path):
    """2026-10-01 audit: the daemon read its list read-only before the database existed, so on a
    first run it died before its Schwab connection."""
    from app.market_data.schwab.streaming.capture import stored_watchlist
    assert stored_watchlist(tmp_path / "not_created_yet.db") == []


def test_a_heartbeat_with_no_watchlist_is_an_unknown_watchlist_never_an_empty_one():
    """2026-10-01 audit: a daemon that sends no list (one from before this change) read as an
    empty list, and the console dropped every ticker's levels each second."""
    import time

    import live_market_plane as lmp
    import server
    lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True})
    assert server._watchlist() is None
