"""OPTIONS_ORDER_FLOW_V1 — GET /api/chain, the contract-selection surface.

Serializer, not a second producer: delegates to server._latest_chain_and_spot, the SAME
stored-chain reader terrain/radar/order-flow-microstructure already use. This file proves
the route serves Schwab's native per-contract fields verbatim (no reshaping), fails closed
to an empty contracts list when nothing is stored, and derives `expiry` from the contracts
actually present rather than fabricating it.
"""

from __future__ import annotations

_SPY_CALL_CONTRACT = {
    "symbol": "SPY   260820C00767000",
    "putCall": "CALL",
    "strikePrice": 767.0,
    "bid": 1.26,
    "ask": 1.28,
    "last": 1.27,
    "delta": 0.45644607,
    "gamma": 0.02911,
    "theta": -0.31,
    "vega": 0.19,
    "volatility": 12.4,
    "openInterest": 2097,
    "totalVolume": 44994,
    "expirationDate": "2026-08-20 00:00:00.0",
    "daysToExpiration": 12,
}
_SPY_PUT_CONTRACT = {
    "symbol": "SPY   260820P00767000",
    "putCall": "PUT",
    "strikePrice": 767.0,
    "bid": 1.10,
    "ask": 1.14,
    "last": 1.12,
    "delta": -0.44,
    "gamma": 0.02911,
    "theta": -0.30,
    "vega": 0.19,
    "volatility": 12.6,
    "openInterest": 1850,
    "totalVolume": 30112,
    "expirationDate": "2026-08-20 00:00:00.0",
    "daysToExpiration": 12,
}


def test_chain_fails_closed_with_no_stored_chain(monkeypatch):
    import server as srv
    from starlette.testclient import TestClient

    monkeypatch.setattr(srv, "_latest_chain_and_spot", lambda t: (None, None))
    with TestClient(srv.app) as client:
        r = client.get("/api/chain", params={"ticker": "ZZZZ"})
        assert r.status_code == 200
        body = r.json()
        assert body["ticker"] == "ZZZZ"
        assert body["contracts"] == []
        assert body["status"] == "no_chain"
        assert body["expiry"] is None


def test_chain_serves_real_stored_contracts_verbatim(monkeypatch):
    """Not a synthetic shortcut: proves the route serializes Schwab's native per-contract
    dict AS-IS (same keys _latest_chain_and_spot's real callers — terrain_engine,
    order_flow_engine consumers — already read: symbol/putCall/strikePrice/delta/gamma/
    openInterest/totalVolume), never a reshaped or invented schema."""
    import server as srv
    from starlette.testclient import TestClient

    contracts = [_SPY_CALL_CONTRACT, _SPY_PUT_CONTRACT]
    monkeypatch.setattr(srv, "_latest_chain_and_spot", lambda t: (contracts, 765.43))
    with TestClient(srv.app) as client:
        r = client.get("/api/chain", params={"ticker": "SPY"})
        assert r.status_code == 200
        body = r.json()
        assert body["ticker"] == "SPY"
        assert body["spot"] == 765.43
        assert body["status"] == "ok"
        assert body["contracts"] == contracts   # byte-for-byte pass-through, no reshaping
        syms = {c["symbol"] for c in body["contracts"]}
        assert syms == {"SPY   260820C00767000", "SPY   260820P00767000"}


def test_chain_derives_expiry_from_contracts_not_fabricated(monkeypatch):
    import server as srv
    from starlette.testclient import TestClient

    monkeypatch.setattr(srv, "_latest_chain_and_spot",
                        lambda t: ([_SPY_CALL_CONTRACT], 765.43))
    with TestClient(srv.app) as client:
        r = client.get("/api/chain", params={"ticker": "SPY"})
        assert r.json()["expiry"] == "2026-08-20"


def test_chain_uppercases_and_strips_ticker(monkeypatch):
    import server as srv
    from starlette.testclient import TestClient

    seen = []

    def _spy(t):
        seen.append(t)
        return None, None
    monkeypatch.setattr(srv, "_latest_chain_and_spot", _spy)
    with TestClient(srv.app) as client:
        r = client.get("/api/chain", params={"ticker": " spy "})
        assert r.status_code == 200
        assert r.json()["ticker"] == "SPY"
    assert seen == ["SPY"]
