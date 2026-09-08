"""Regression: staleness gating must not serve a frozen L1 cache.

Rewritten for the single-stream-authority repair:
app/options/order_flow/streaming.py no longer owns a Schwab socket (that
disconnect-classification logic now lives solely in the canonical capture daemon), so
`_is_stream_disconnect_error` no longer exists here. The BEHAVIOR this file protects —
staleness must gate `streaming_l1_cache_usable` before it gates the coarser
`get_plane_authority_for_ticker` bucket — is unchanged and still asserted.
"""

from __future__ import annotations

import time

import app.options.order_flow.streaming as ofs


def _reset_feed_globals() -> None:
    ofs._feed_running = False
    ofs._active_ticker = None
    ofs._streaming_last_update_ts = None
    ofs._last_subscribe_completed_ts = None
    ofs._l1_cursor = {}
    ofs._book_cursor = {}


def test_streaming_l1_cache_usable_requires_recent_tick():
    _reset_feed_globals()
    ofs._feed_running = True
    ofs._active_ticker = "SPY"
    ofs._streaming_last_update_ts = time.time()
    assert ofs.streaming_l1_cache_usable("SPY") is True

    ofs._streaming_last_update_ts = time.time() - 10.0
    assert ofs.streaming_l1_cache_usable("SPY") is False
    # Authority may still read "streaming" until STREAMING_STALE_MS (25s); fast-quote must not use cache.
    assert ofs.get_plane_authority_for_ticker("SPY") == "streaming"


def test_get_plane_authority_rest_only_when_feed_not_running():
    _reset_feed_globals()
    ofs._feed_running = False
    ofs._active_ticker = "SPY"
    assert ofs.get_plane_authority_for_ticker("SPY") == "rest_only"


def test_get_plane_authority_rest_mismatch_for_a_different_ticker():
    _reset_feed_globals()
    ofs._feed_running = True
    ofs._active_ticker = "SPY"
    ofs._streaming_last_update_ts = time.time()
    assert ofs.get_plane_authority_for_ticker("QQQ") == "rest_mismatch"
