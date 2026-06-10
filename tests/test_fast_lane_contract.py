"""Fast lane /api/fast-quote contract — additive, quote-only payload."""
from __future__ import annotations

import sys
from pathlib import Path


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


def test_fast_quote_auth_failure_serves_carried_forward_plane(monkeypatch):
    import order_flow_streaming as ofs
    import server as srv

    stale = {
        "ticker": "SPY",
        "spot": 749.73,
        "bid": 749.70,
        "ask": 749.76,
        "spot_disp": "749.73",
        "quote_ingestion": "schwab_streaming_level_one",
        "quote_source_detail": {"carried_forward": False},
    }
    monkeypatch.setattr(srv._lmp, "get_quote", lambda _t: dict(stale))
    monkeypatch.setattr(
        ofs,
        "get_plane_authority_for_ticker",
        lambda _t: "rest_only",
    )

    def _boom(*_a, **_k):
        raise RuntimeError(
            'unsupported_token_type: 400 Bad Request: "invalid_grant refresh token revoked"'
        )

    monkeypatch.setattr(srv, "_build_rest_fast_quote_payload", _boom)
    payload = srv._fetch_fast_quote_payload("SPY")
    assert payload["spot"] == 749.73
    assert payload["quote_source_detail"]["carried_forward"] is True
    assert payload["quote_source_detail"]["schwab_auth_degraded"] is True

    from starlette.testclient import TestClient

    with TestClient(srv.app) as client:
        r = client.get("/api/fast-quote", params={"ticker": "SPY"})
        assert r.status_code == 200
        body = r.json()
        assert body["spot"] == 749.73
        assert body["quote_source_detail"]["carried_forward"] is True


def test_fast_quote_missing_token_file_returns_401_not_503(monkeypatch):
    import order_flow_streaming as ofs
    import server as srv
    from fastapi import HTTPException

    monkeypatch.setattr(srv._lmp, "get_quote", lambda _t: None)
    monkeypatch.setattr(
        ofs,
        "get_plane_authority_for_ticker",
        lambda _t: "rest_only",
    )

    def _no_client(*_a, **_k):
        raise HTTPException(
            status_code=503,
            detail="Schwab auth failed: Token file not found: schwab_token.json",
        )

    monkeypatch.setattr(srv, "get_client", _no_client)
    from starlette.testclient import TestClient

    with TestClient(srv.app) as client:
        r = client.get("/api/fast-quote", params={"ticker": "SPY"})
        assert r.status_code == 401
        body = r.json()
        assert body.get("error") == "token_invalid"
        assert "reauth_schwab" in str(body.get("remediation", ""))
