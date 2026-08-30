"""OPTIONS_ORDER_FLOW_V1 — GET /api/chain, the contract-selection surface.

COMPLETE, live, single-expiry-scoped chain (OPTIONS_ORDER_FLOW_V1 completeness repair,
2026-08-30): tries a LIVE fetch through server._gated_safe_get_chain — the SAME single,
rate-limited chain-fetch faucet every other chain read in server.py uses — scoped to
exactly one expiry (from_date=to_date) so a wide strike_count stays budget-safe by
construction. Falls closed to the STORED analytical snapshot (server._latest_chain_and_spot)
on any live-fetch failure, explicitly labeled via `scope.kind` so a caller can never mistake
one for the other.

Every test here MUST mock the live-fetch entry points (get_client / _gated_safe_get_chain)
explicitly — never rely on real credentials happening to be absent in the test environment
to fall through to the stored-snapshot path. A prior version of this file only mocked
_latest_chain_and_spot and, once real Schwab credentials existed on disk in this worktree
(added for an unrelated live-data probe earlier in this session), the unmocked live path
made a REAL network call during collection and hung the test run — caught and fixed here.

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
_REAL_EXPIRY = _REAL_CONTRACTS[0]["expirationDate"][:10]


def _no_live_client(monkeypatch, srv):
    """Force the live-fetch branch to fail immediately (simulating 'no Schwab client
    available') so a test can exercise the fallback path deterministically, without
    depending on whatever credentials happen to exist on disk in this environment."""
    def _raise(*a, **k):
        raise RuntimeError("no live Schwab client in this test")
    monkeypatch.setattr(srv, "get_client", _raise)


class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _chain_json_for(contracts, side_key_fn):
    """Build a minimal Schwab-shaped callExpDateMap/putExpDateMap payload from a flat
    contract list, keyed the way flatten_chain_contracts expects to read it back."""
    out = {"callExpDateMap": {}, "putExpDateMap": {}}
    for c in contracts:
        side = "callExpDateMap" if c.get("putCall") == "CALL" else "putExpDateMap"
        exp_key = f"{c['expirationDate'][:10]}:1"
        strike_key = str(c["strikePrice"])
        out[side].setdefault(exp_key, {}).setdefault(strike_key, []).append(c)
    return out


def test_chain_fails_closed_with_no_stored_chain(monkeypatch):
    import server as srv
    from starlette.testclient import TestClient

    _no_live_client(monkeypatch, srv)
    monkeypatch.setattr(srv, "_latest_chain_and_spot", lambda t: (None, None))
    with TestClient(srv.app) as client:
        r = client.get("/api/chain", params={"ticker": "ZZZZ"})
        assert r.status_code == 200
        body = r.json()
        assert body["ticker"] == "ZZZZ"
        assert body["contracts"] == []
        assert body["status"] == "no_chain"
        assert body["expiry"] is None
        assert body["scope"]["kind"] == "stored_analytical_snapshot_fallback"


def test_chain_falls_back_to_stored_contracts_verbatim_on_live_failure(monkeypatch):
    """Proves the FALLBACK route serializes Schwab's native per-contract dicts AS-IS —
    the same real captured chain _latest_chain_and_spot's real callers already read —
    never a reshaped or invented schema."""
    import server as srv
    from starlette.testclient import TestClient

    _no_live_client(monkeypatch, srv)
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
        assert body["scope"]["kind"] == "stored_analytical_snapshot_fallback"


def test_chain_derives_expiry_from_contracts_not_fabricated(monkeypatch):
    import server as srv
    from starlette.testclient import TestClient

    _no_live_client(monkeypatch, srv)
    monkeypatch.setattr(srv, "_latest_chain_and_spot",
                        lambda t: (_REAL_CONTRACTS, _REAL_SPOT))
    with TestClient(srv.app) as client:
        r = client.get("/api/chain", params={"ticker": "SPY"})
        assert r.json()["expiry"] == _REAL_EXPIRY


def test_chain_uppercases_and_strips_ticker(monkeypatch):
    import server as srv
    from starlette.testclient import TestClient

    _no_live_client(monkeypatch, srv)
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


def test_chain_live_fetch_serves_complete_single_expiry_scope(monkeypatch):
    """The live path — real chain, verbatim, correctly scoped to exactly one expiry."""
    import server as srv
    from starlette.testclient import TestClient

    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_REAL_EXPIRY])
    c_json = _chain_json_for(_REAL_CONTRACTS, None)
    c_json["underlying"] = {"last": _REAL_SPOT}
    # A LIST, not a single dict: the running app's own background loops (terrain,
    # analytics bg workers) also call _gated_safe_get_chain concurrently once the
    # TestClient boots the real app — patching the module-level function catches those
    # calls too, with a DIFFERENT (analytical) strike_count. Filtering by
    # COMPLETE_CHAIN_STRIKE_COUNT below isolates THIS endpoint's own call deterministically.
    calls = []

    def _fake_gated(client, ticker, *, strike_count, from_date, to_date, priority):
        calls.append(dict(ticker=ticker, strike_count=strike_count,
                          from_date=from_date, to_date=to_date, priority=priority))
        if strike_count == srv.COMPLETE_CHAIN_STRIKE_COUNT:
            return _FakeResp(200, c_json), 0.0, 0.1
        return _FakeResp(200, {"callExpDateMap": {}, "putExpDateMap": {}}), 0.0, 0.1
    monkeypatch.setattr(srv, "_gated_safe_get_chain", _fake_gated)
    with TestClient(srv.app) as client:
        r = client.get("/api/chain", params={"ticker": "SPY"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["expiry"] == _REAL_EXPIRY
        assert body["scope"]["kind"] == "complete_single_expiry"
        assert body["scope"]["requested_expiry"] == _REAL_EXPIRY
        assert body["scope"]["returned_expiries"] == [_REAL_EXPIRY]
        assert len(body["contracts"]) == 40
        syms = {c["symbol"] for c in body["contracts"]}
        assert "SPY   260717C00734000" in syms
    # Budget-safety proof: the fetch is bounded to EXACTLY one expiry via from_date==to_date,
    # never an open/unbounded multi-expiry window.
    complete_calls = [c for c in calls if c["strike_count"] == srv.COMPLETE_CHAIN_STRIKE_COUNT]
    assert len(complete_calls) >= 1
    assert complete_calls[0]["from_date"] == complete_calls[0]["to_date"]


def test_chain_live_fetch_accepts_explicit_expiry_param(monkeypatch):
    import server as srv
    from starlette.testclient import TestClient

    monkeypatch.setattr(srv, "get_client", lambda: object())
    fetch_expiries_called = []
    monkeypatch.setattr(srv, "_fetch_expiries_light",
                        lambda t: fetch_expiries_called.append(t) or ["9999-01-01"])
    c_json = _chain_json_for(_REAL_CONTRACTS, None)
    c_json["underlying"] = {"last": _REAL_SPOT}

    def _fake_gated(client, ticker, *, strike_count, from_date, to_date, priority):
        return _FakeResp(200, c_json), 0.0, 0.1
    monkeypatch.setattr(srv, "_gated_safe_get_chain", _fake_gated)
    with TestClient(srv.app) as client:
        r = client.get("/api/chain", params={"ticker": "SPY", "expiry": _REAL_EXPIRY})
        assert r.status_code == 200
        assert r.json()["expiry"] == _REAL_EXPIRY
    # An explicit expiry must skip the nearest-expiry lookup entirely.
    assert fetch_expiries_called == []


def test_chain_live_fetch_non_200_falls_back_to_stored_snapshot(monkeypatch):
    import server as srv
    from starlette.testclient import TestClient

    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_REAL_EXPIRY])
    monkeypatch.setattr(srv, "_gated_safe_get_chain",
                        lambda *a, **k: (_FakeResp(502, {}), 0.0, 0.1))
    monkeypatch.setattr(srv, "_latest_chain_and_spot",
                        lambda t: (_REAL_CONTRACTS, _REAL_SPOT))
    with TestClient(srv.app) as client:
        r = client.get("/api/chain", params={"ticker": "SPY"})
        assert r.status_code == 200
        body = r.json()
        assert body["scope"]["kind"] == "stored_analytical_snapshot_fallback"
        assert body["status"] == "ok"
        assert len(body["contracts"]) == 40


def test_chain_live_fetch_exception_falls_back_to_stored_snapshot(monkeypatch):
    import server as srv
    from starlette.testclient import TestClient

    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_REAL_EXPIRY])

    def _boom(*a, **k):
        raise RuntimeError("simulated vendor error")
    monkeypatch.setattr(srv, "_gated_safe_get_chain", _boom)
    monkeypatch.setattr(srv, "_latest_chain_and_spot",
                        lambda t: (_REAL_CONTRACTS, _REAL_SPOT))
    with TestClient(srv.app) as client:
        r = client.get("/api/chain", params={"ticker": "SPY"})
        assert r.status_code == 200
        assert r.json()["scope"]["kind"] == "stored_analytical_snapshot_fallback"


def test_chain_defensive_scope_check_reports_only_actually_returned_expiries(monkeypatch):
    """Never trust the request alone to guarantee the response's own expirationDate
    matches what was asked for — the reported returned_expiries reflects the CONTRACTS
    actually present, not an assumption."""
    import server as srv
    from starlette.testclient import TestClient

    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_REAL_EXPIRY])
    # A contract carrying a DIFFERENT expirationDate than requested (defensive scenario).
    drifted = dict(_REAL_CONTRACTS[0])
    drifted["expirationDate"] = "2099-01-01T00:00:00.000+00:00"
    c_json = _chain_json_for([drifted], None)
    c_json["underlying"] = {"last": _REAL_SPOT}
    monkeypatch.setattr(srv, "_gated_safe_get_chain",
                        lambda *a, **k: (_FakeResp(200, c_json), 0.0, 0.1))
    with TestClient(srv.app) as client:
        r = client.get("/api/chain", params={"ticker": "SPY"})
        body = r.json()
        assert body["scope"]["returned_expiries"] == ["2099-01-01"]
        assert body["scope"]["requested_expiry"] == _REAL_EXPIRY
