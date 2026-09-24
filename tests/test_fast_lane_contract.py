"""Fast lane /api/fast-quote contract — additive, quote-only payload."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))




def test_fast_quote_is_read_only_from_the_streamed_plane(monkeypatch):
    """2026-09-24: /api/fast-quote never fetches REST and never writes the plane; it returns
    the streamed, fresh LAST_PRICE row or stream_unavailable."""
    import time

    from starlette.testclient import TestClient

    import live_market_plane as lmp
    import server

    assert not hasattr(server, "_fetch_fast_quote_payload")
    assert not hasattr(server, "_build_rest_fast_quote_payload")
    monkeypatch.setattr(server, "_touch_tracked_ticker_view", lambda t: None)
    client = TestClient(server.app)
    r = client.get("/api/fast-quote", params={"ticker": "NOSTREAMX"})
    assert r.status_code == 200 and r.json() == {
        "ok": False, "ticker": "NOSTREAMX", "error": "stream_unavailable"}
    lmp.record_from_level_one_equity("FQLIVE", {"key": "FQLIVE", "LAST_PRICE": 12.5},
                                     received_ts=time.time())
    body = client.get("/api/fast-quote", params={"ticker": "FQLIVE"}).json()
    assert body["ok"] is True and body["spot"] == 12.5
    assert body["quote_ingestion"] == "schwab_streaming_level_one"
