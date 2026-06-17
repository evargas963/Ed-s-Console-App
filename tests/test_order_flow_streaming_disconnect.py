"""Regression: stream disconnect must not spin recv loop or serve frozen L1 cache."""

from __future__ import annotations

import time

import order_flow_streaming as ofs


def _reset_stream_globals() -> None:
    ofs._stream_running = False
    ofs._streaming_logged_in = False
    ofs._stream_client = None
    ofs._active_streaming_ticker = None
    ofs._streaming_last_update_ts = None
    ofs._last_subscribe_completed_ts = None
    ofs._subscribed_equity_syms = []


def test_is_stream_disconnect_error_recognizes_websocket_close():
    class ConnectionClosedOK(Exception):
        pass

    assert ofs._is_stream_disconnect_error(ConnectionClosedOK()) is True
    assert ofs._is_stream_disconnect_error(RuntimeError("other")) is False


def test_streaming_l1_cache_usable_requires_recent_tick():
    _reset_stream_globals()
    ofs._stream_running = True
    ofs._streaming_logged_in = True
    ofs._active_streaming_ticker = "SPY"
    ofs._streaming_last_update_ts = time.time()
    assert ofs.streaming_l1_cache_usable("SPY") is True

    ofs._streaming_last_update_ts = time.time() - 10.0
    assert ofs.streaming_l1_cache_usable("SPY") is False
    # Authority may still read "streaming" until STREAMING_STALE_MS (25s); fast-quote must not use cache.
    assert ofs.get_plane_authority_for_ticker("SPY") == "streaming"


def test_get_plane_authority_rest_only_when_logged_out():
    _reset_stream_globals()
    ofs._stream_running = True
    ofs._streaming_logged_in = False
    ofs._active_streaming_ticker = "SPY"
    assert ofs.get_plane_authority_for_ticker("SPY") == "rest_only"
