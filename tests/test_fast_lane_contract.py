"""Fast lane /api/fast-quote contract — additive, quote-only payload."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_fast_quote_endpoint_returns_fast_fields(monkeypatch):
    import server as srv

    def fake_payload(t: str):
        return {
            "ticker": t.upper().strip(),
            "spot": 100.0,
            "bid": 99.9,
            "ask": 100.1,
            "spot_disp": "100.00",
            "bid_disp": "99.90",
            "ask_disp": "100.10",
            "spread": 0.002,
            "fast_generation_id": 1,
            "fast_server_ts": 1_700_000_000.0,
        }

    monkeypatch.setattr(srv, "_fetch_fast_quote_payload", fake_payload)
    from starlette.testclient import TestClient

    with TestClient(srv.app) as client:
        r = client.get("/api/fast-quote", params={"ticker": "SPY"})
        assert r.status_code == 200
        b = r.json()
        assert b["ticker"] == "SPY"
        assert "fast_generation_id" in b and "fast_server_ts" in b
        assert b["spot_disp"] == "100.00"
        assert "fusion_available" not in b and "call_signal" not in b
        assert "session_label" not in b
