"""Schwab Streamer Guide has no ADMIN QOS command. A live request was code 21.

The daemon must not send a command that is always rejected. The 1 s LEVELONE_EQUITIES
ceiling is recorded on CaptureStats.qos and in the status file."""
from __future__ import annotations

import inspect

import app.market_data.schwab.streaming.capture as cap


def test_qos_is_not_sent_on_the_socket() -> None:
    src = inspect.getsource(cap._schwab_connect_after_login)
    assert "request_stream_qos" not in src
    assert "command=\"QOS\"" not in inspect.getsource(cap)
    assert "record_stream_delivery_ceiling(stats)" in src


def test_delivery_ceiling_is_recorded_and_published() -> None:
    stats = cap.CaptureStats()
    out = cap.record_stream_delivery_ceiling(stats)
    # only what was measured: the 1.01 s grid and the rejected TDA-format request; whether
    # Schwab accepts QOS in another format is not claimed either way (audit of #280)
    assert out["supported"] == "unverified"
    assert out["ceiling_sec"] == 1.0
    assert "code 21" in out["evidence"] and "1.01 s grid" in out["evidence"]
    assert stats.qos == out
    assert '"qos": stats.qos' in inspect.getsource(cap.write_status)
    assert cap.STREAM_DELIVERY_CEILING_SEC == 1.0
