"""OPTIONS_ORDER_FLOW_V1 — GET /api/chain, the contract-selection surface.

Serializer, not a second producer: delegates to server._latest_chain_and_spot, the SAME
stored-chain reader terrain/radar/order-flow-microstructure already use. This file proves
the route serves Schwab's native per-contract fields verbatim (no reshaping), fails closed
to an empty contracts list when nothing is stored, and derives `expiry` from the contracts
actually present rather than fabricating it.

Uses the REAL captured chain in tests/fixtures/real_spy_0dte_chain_with_poison.json (40
live SPY contracts pulled from data/ed_console.db) rather than hand-built contract dicts —
institutional_correctness's no_synthetic_domain_fixtures_in_tests gate requires real chain
data for this domain.
"""

from __future__ import annotations

import json
from pathlib import Path

_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "real_spy_0dte_chain_with_poison.json")
    .read_text(encoding="utf-8")
)
_REAL_CONTRACTS = _FIXTURE["chain"]
_REAL_SPOT = _FIXTURE["spot"]


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
    """Proves the route serializes Schwab's native per-contract dicts AS-IS — the same real
    captured chain _latest_chain_and_spot's real callers already read — never a reshaped or
    invented schema."""
    import server as srv
    from starlette.testclient import TestClient

    monkeypatch.setattr(srv, "_latest_chain_and_spot",
                        lambda t: (_REAL_CONTRACTS, _REAL_SPOT))
    with TestClient(srv.app) as client:
        r = client.get("/api/chain", params={"ticker": "SPY"})
        assert r.status_code == 200
        body = r.json()
        assert body["ticker"] == "SPY"
        assert body["spot"] == _REAL_SPOT
        assert body["status"] == "ok"
        assert body["contracts"] == _REAL_CONTRACTS   # byte-for-byte pass-through
        assert len(body["contracts"]) == 40
        assert "SPY   260717C00734000" in {c["symbol"] for c in body["contracts"]}


def test_chain_derives_expiry_from_contracts_not_fabricated(monkeypatch):
    import server as srv
    from starlette.testclient import TestClient

    monkeypatch.setattr(srv, "_latest_chain_and_spot",
                        lambda t: (_REAL_CONTRACTS, _REAL_SPOT))
    with TestClient(srv.app) as client:
        r = client.get("/api/chain", params={"ticker": "SPY"})
        assert r.json()["expiry"] == _REAL_CONTRACTS[0]["expirationDate"][:10]


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
