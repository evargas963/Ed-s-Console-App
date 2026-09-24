"""The capture daemon asks Schwab for Express delivery (ADMIN QOS level 0) on every session.

MEASURED 2026-09-24 08:27 CT on the live daemon: all 43 streamed LEVELONE_EQUITIES symbols
arrived on a 1.01 s grid -- Schwab's default QOS level 2 (Fast, 1000 ms). The request's
outcome is recorded and reported; a rejection is visible, never hidden or retried."""
from __future__ import annotations

import asyncio
import inspect

import app.market_data.schwab.streaming.capture as cap


class _Stream:
    def __init__(self, code=0):
        self._lock = asyncio.Lock()
        self.sent = []
        self._code = code

    def _make_request(self, *, service, command, parameters):
        return {"service": service, "command": command, "parameters": parameters}, 7

    async def _send(self, obj):
        self.sent.append(obj)

    async def _await_response(self, request_id, service, command):
        if self._code != 0:
            from schwab.streaming import UnexpectedResponseCode
            raise UnexpectedResponseCode(
                {"response": [{"content": {"code": self._code, "msg": "not permitted"}}]}, "bad code")


def test_qos_request_is_admin_qos_level_zero_and_recorded():
    st, stats = _Stream(), cap.CaptureStats()
    out = asyncio.run(cap.request_stream_qos(st, stats))
    assert st.sent == [{"requests": [{"service": "ADMIN", "command": "QOS",
                                      "parameters": {"qoslevel": "0"}}]}]
    assert out == stats.qos == {"requested": 0, "code": 0, "msg": None}


def test_a_rejected_qos_is_reported_not_raised():
    stats = cap.CaptureStats()
    out = asyncio.run(cap.request_stream_qos(_Stream(code=3), stats))
    assert out == {"requested": 0, "code": 3, "msg": "not permitted"}


def test_a_broken_client_never_breaks_the_stream():
    stats = cap.CaptureStats()
    out = asyncio.run(cap.request_stream_qos(object(), stats))
    assert out["code"] is None and "AttributeError" in out["msg"]


def test_every_session_asks_before_subscribing_and_status_reports_it():
    src = inspect.getsource(cap._schwab_connect_after_login)
    assert src.index("await request_stream_qos(stream, stats)") < src.index("level_one_equity_subs")
    assert '"qos": getattr(stats, "qos", None)' in inspect.getsource(cap.write_status)
    assert cap.STREAM_QOS_LEVEL == 0
