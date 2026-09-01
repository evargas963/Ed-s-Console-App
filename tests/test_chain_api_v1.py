"""OPTIONS_ORDER_FLOW_V1 — GET /api/chain, the contract-selection surface.

COMPLETE, live, single-expiry-scoped chain (round 2 completeness repair, 2026-08-30): a
fixed strike_count is NEVER proof of completeness. MEASURED live: SPY's near expiry at
strike_count=250 returned 388 contracts (194 strikes); the SAME expiry via schwab-py's
`strike_range=Options.StrikeRange.ALL` — a DIFFERENT vendor selection dimension, not a
wider count — returned 526 contracts (263 strikes): 69 real strikes strike_count=250
silently missed. `strike_range="ALL"` is independently confirmed to be the vendor's true
complete set by a saturation check (an unrelated strike_count=500 request on the same
expiry converged to the IDENTICAL strike set). This file's tests use the REAL committed
evidence of both: tests/fixtures/real_tsla_complete_chain_strike_range_all.json (236
contracts, 54 fractional-strike rows, captured live via strike_range=ALL, saturation-
verified) and tests/fixtures/real_spy_strike_count_vs_strike_range_all_evidence.json (the
smoking-gun proof that a bounded strike_count under-counts).

Every test here MUST mock the live-fetch entry points (get_client / _gated_safe_get_chain)
explicitly — never rely on real credentials happening to be absent in the test environment
to fall through to the stored-snapshot path. A prior version of this file only mocked
_latest_chain_and_spot and, once real Schwab credentials existed on disk in this worktree
(added for the live vendor probes behind these fixtures), the unmocked live path made a
REAL network call during collection and hung the test run — caught and fixed here, and the
same discipline is kept for every test added since.

Uses the REAL captured chain in tests/fixtures/real_spy_0dte_chain_with_poison.json for the
fallback-tier tests (unchanged from the prior round) — institutional_correctness's
no_synthetic_domain_fixtures_in_tests gate requires real chain data for this domain.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

_FIXTURES = Path(__file__).parent / "fixtures"

_SPY_POISON = json.loads(
    (_FIXTURES / "real_spy_0dte_chain_with_poison.json").read_text(encoding="utf-8")
)
_REAL_CONTRACTS = _SPY_POISON["chain"]
_REAL_SPOT = _SPY_POISON["spot"]
_REAL_EXPIRY = _REAL_CONTRACTS[0]["expirationDate"][:10]

_TSLA_COMPLETE = json.loads(
    (_FIXTURES / "real_tsla_complete_chain_strike_range_all.json").read_text(encoding="utf-8")
)
_TSLA_CONTRACTS = _TSLA_COMPLETE["chain"]
_TSLA_EXPIRY = _TSLA_COMPLETE["expiry"]
_TSLA_N_FRACTIONAL = _TSLA_COMPLETE["n_fractional_strikes"]

_SPY_VS_ALL = json.loads(
    (_FIXTURES / "real_spy_strike_count_vs_strike_range_all_evidence.json").read_text(encoding="utf-8")
)


def _no_live_client(monkeypatch, srv):
    """Force the live-fetch branch to fail immediately (simulating 'no Schwab client
    available') so a test can exercise the fallback path deterministically, without
    depending on whatever credentials happen to exist on disk in this environment."""
    def _raise(*a, **k):
        raise RuntimeError("no live Schwab client in this test")
    monkeypatch.setattr(srv, "get_client", _raise)


def _fake_db(monkeypatch, srv, tmp_path):
    """A real sqlite file, not a mock — persist_complete_chain_capture/
    latest_complete_chain_capture do real sqlite3 I/O, so this proves the actual round
    trip, not a stubbed one."""
    db_path = str(tmp_path / "test_ed_console.db")
    monkeypatch.setattr(srv, "get_db", lambda: SimpleNamespace(db_path=db_path))
    return db_path


class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _chain_json_for(contracts):
    """Build a minimal Schwab-shaped callExpDateMap/putExpDateMap payload from a flat
    contract list, keyed the way flatten_chain_contracts expects to read it back."""
    out = {"callExpDateMap": {}, "putExpDateMap": {}}
    for c in contracts:
        side = "callExpDateMap" if c.get("putCall") == "CALL" else "putExpDateMap"
        exp_key = f"{c['expirationDate'][:10]}:1"
        strike_key = str(c["strikePrice"])
        out[side].setdefault(exp_key, {}).setdefault(strike_key, []).append(c)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Fallback tier (unchanged shape from round 1, still real-fixture-backed)
# ─────────────────────────────────────────────────────────────────────────────

# TEST_SYSTEM_REHAB_V2 final remediation: every TestClient call in this file below
# was replaced with a direct call to server.get_chain -- a plain sync handler with
# no auth/middleware/serialization-shaping dependency, monkeypatched through the
# exact same fixtures (_no_live_client/_fake_db/_gated_safe_get_chain/etc.) that
# apply identically whether reached via HTTP or a direct call. get_chain returns a
# JSONResponse in every branch, so each call site unwraps via json.loads(resp.body).

def test_chain_fails_closed_with_no_stored_chain(monkeypatch, tmp_path):
    import json

    import server as srv

    _no_live_client(monkeypatch, srv)
    _fake_db(monkeypatch, srv, tmp_path)
    monkeypatch.setattr(srv, "_latest_chain_and_spot", lambda t: (None, None))
    body = json.loads(srv.get_chain(ticker="ZZZZ", expiry=None).body)
    assert body["ticker"] == "ZZZZ"
    assert body["contracts"] == []
    assert body["status"] == "no_chain"
    assert body["expiry"] is None
    assert body["scope"]["kind"] == "stored_analytical_snapshot_fallback"


def test_chain_falls_back_to_stored_contracts_verbatim_on_live_failure(monkeypatch, tmp_path):
    import json

    import server as srv

    _no_live_client(monkeypatch, srv)
    _fake_db(monkeypatch, srv, tmp_path)
    monkeypatch.setattr(srv, "_latest_chain_and_spot",
                        lambda t: (_REAL_CONTRACTS, _REAL_SPOT))
    body = json.loads(srv.get_chain(ticker="SPY", expiry=None).body)
    assert body["contracts"] == _REAL_CONTRACTS   # byte-for-byte pass-through
    assert body["scope"]["kind"] == "stored_analytical_snapshot_fallback"


def test_chain_uppercases_and_strips_ticker(monkeypatch, tmp_path):
    import json

    import server as srv

    _no_live_client(monkeypatch, srv)
    _fake_db(monkeypatch, srv, tmp_path)
    seen = []

    def _spy(t):
        seen.append(t)
        return None, None
    monkeypatch.setattr(srv, "_latest_chain_and_spot", _spy)
    body = json.loads(srv.get_chain(ticker=" spy ", expiry=None).body)
    assert body["ticker"] == "SPY"
    assert seen == ["SPY"]


# ─────────────────────────────────────────────────────────────────────────────
# Complete-chain live path: strike_range="ALL", real TSLA fixture, fractional strikes
# ─────────────────────────────────────────────────────────────────────────────

def _fake_gated_isolating_ALL(c_json, calls):
    """Filters out the running app's own concurrent background chain-fetch traffic
    (terrain/analytics bg workers also call _gated_safe_get_chain once TestClient boots
    the real app) by only serving the real fixture to a strike_range='ALL' call — every
    other shape gets an empty chain, isolating THIS endpoint's own call deterministically."""
    def _fake_gated(client, ticker, *, strike_count=None, strike_range=None,
                    from_date=None, to_date=None, priority=False):
        calls.append(dict(ticker=ticker, strike_count=strike_count, strike_range=strike_range,
                          from_date=from_date, to_date=to_date, priority=priority))
        if strike_range == "ALL":
            return _FakeResp(200, c_json), 0.0, 0.1
        return _FakeResp(200, {"callExpDateMap": {}, "putExpDateMap": {}}), 0.0, 0.1
    return _fake_gated


def test_chain_live_fetch_uses_strike_range_all_never_a_bare_count(monkeypatch, tmp_path):
    """The completeness mechanism itself: the live call must use strike_range='ALL', not
    a strike_count bound — MEASURED live proof (fixtures) that a bound alone under-counts."""
    import json

    import server as srv

    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_TSLA_EXPIRY])
    _fake_db(monkeypatch, srv, tmp_path)
    c_json = _chain_json_for(_TSLA_CONTRACTS)
    c_json["underlying"] = {"last": _TSLA_COMPLETE.get("spot")}
    calls = []
    monkeypatch.setattr(srv, "_gated_safe_get_chain", _fake_gated_isolating_ALL(c_json, calls))
    body = json.loads(srv.get_chain(ticker="TSLA", expiry=None).body)
    assert body["status"] == "ok"
    assert body["scope"]["kind"] == "complete_single_expiry"
    assert body["scope"]["completeness_basis"] == srv.COMPLETENESS_BASIS_STRIKE_RANGE_ALL
    assert len(body["contracts"]) == len(_TSLA_CONTRACTS)
    all_calls = [c for c in calls if c["strike_range"] == "ALL"]
    assert len(all_calls) >= 1
    assert all_calls[0]["strike_count"] is None, "strike_count must be OMITTED when strike_range=ALL is used, exactly as proven live"
    assert all_calls[0]["from_date"] == all_calls[0]["to_date"], "budget-safety: bounded to exactly one expiry"


def test_chain_fractional_strikes_survive_vendor_to_api_unchanged(monkeypatch, tmp_path):
    """VENDOR -> API set equivalence for the real TSLA capture: every native contract
    field, every fractional strike, survives byte-for-byte — no rounding, no coercion,
    no dropped rows."""
    import json

    import server as srv

    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_TSLA_EXPIRY])
    _fake_db(monkeypatch, srv, tmp_path)
    c_json = _chain_json_for(_TSLA_CONTRACTS)
    c_json["underlying"] = {"last": _TSLA_COMPLETE.get("spot")}
    monkeypatch.setattr(srv, "_gated_safe_get_chain",
                        _fake_gated_isolating_ALL(c_json, []))
    body = json.loads(srv.get_chain(ticker="TSLA", expiry=None).body)

    vendor_symbols = {c["symbol"] for c in _TSLA_CONTRACTS}
    api_symbols = {c["symbol"] for c in body["contracts"]}
    assert api_symbols == vendor_symbols, "exact contract-symbol set equality, vendor -> API"
    assert len(api_symbols) == len(_TSLA_CONTRACTS), "no duplicate symbols"

    api_frac = [c for c in body["contracts"] if c.get("strikePrice") is not None
               and c["strikePrice"] % 1 != 0]
    assert len(api_frac) == _TSLA_N_FRACTIONAL, "every real fractional-strike row survives"
    # Byte-for-byte: pick one real fractional contract and confirm every field is untouched.
    vendor_frac_symbol = next(c["symbol"] for c in _TSLA_CONTRACTS
                              if c["strikePrice"] % 1 != 0)
    vendor_row = next(c for c in _TSLA_CONTRACTS if c["symbol"] == vendor_frac_symbol)
    api_row = next(c for c in body["contracts"] if c["symbol"] == vendor_frac_symbol)
    assert api_row == vendor_row, "no rounding, no coercion, no field loss on a real fractional strike"


def test_chain_live_fetch_persists_the_complete_capture(monkeypatch, tmp_path):
    """VENDOR -> PERSISTED set equivalence: a successful complete_single_expiry response
    durably writes the exact contract set to complete_chain_captures — proven by reading
    the REAL sqlite row back, not by asserting the persist function was merely called."""
    import server as srv
    from calibration.complete_chain_capture import latest_complete_chain_capture

    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_TSLA_EXPIRY])
    db_path = _fake_db(monkeypatch, srv, tmp_path)
    c_json = _chain_json_for(_TSLA_CONTRACTS)
    c_json["underlying"] = {"last": _TSLA_COMPLETE.get("spot")}
    monkeypatch.setattr(srv, "_gated_safe_get_chain",
                        _fake_gated_isolating_ALL(c_json, []))
    srv.get_chain(ticker="TSLA", expiry=None)

    cap = latest_complete_chain_capture(db_path, "TSLA", _TSLA_EXPIRY)
    assert cap is not None, "the complete capture must be durably persisted, not merely served"
    assert cap["completeness_basis"] == srv.COMPLETENESS_BASIS_STRIKE_RANGE_ALL
    persisted_symbols = {c["symbol"] for c in cap["contracts"]}
    vendor_symbols = {c["symbol"] for c in _TSLA_CONTRACTS}
    assert persisted_symbols == vendor_symbols, "exact contract-symbol set equality, vendor -> PERSISTED"


def test_chain_persisted_capture_serves_as_fallback_when_live_fails(monkeypatch, tmp_path):
    """PERSISTED -> API set equivalence on the fallback path: a prior complete capture
    survives a live-fetch failure and is served with its staleness stated."""
    import json

    import server as srv
    from calibration.complete_chain_capture import persist_complete_chain_capture

    db_path = _fake_db(monkeypatch, srv, tmp_path)
    persist_complete_chain_capture(
        db_path, ticker="TSLA", expiry=_TSLA_EXPIRY, contracts=_TSLA_CONTRACTS,
        spot=_TSLA_COMPLETE.get("spot"), completeness_basis="strike_range=ALL",
        ts_utc=1000.0)

    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_TSLA_EXPIRY])

    def _boom(*a, **k):
        raise RuntimeError("simulated live-fetch outage")
    monkeypatch.setattr(srv, "_gated_safe_get_chain", _boom)
    body = json.loads(srv.get_chain(ticker="TSLA", expiry=None).body)
    assert body["scope"]["kind"] == "persisted_complete_capture_fallback"
    assert body["scope"]["completeness_basis"] == "strike_range=ALL"
    assert body["scope"]["captured_age_sec"] is not None
    api_symbols = {c["symbol"] for c in body["contracts"]}
    vendor_symbols = {c["symbol"] for c in _TSLA_CONTRACTS}
    assert api_symbols == vendor_symbols, "exact contract-symbol set equality, PERSISTED -> API fallback"


def test_chain_expiry_mismatch_never_claims_complete_single_expiry(monkeypatch, tmp_path):
    """NEGATIVE CONTROL (item #4): requested expiry A, vendor response carries expiry B
    -> scope.kind must NOT be 'complete_single_expiry'. Real contracts, real drift
    (constructed from a real fixture contract with only its expirationDate altered — the
    field a scope check must react to, not a hand-built synthetic chain)."""
    import json

    import server as srv

    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_TSLA_EXPIRY])
    _fake_db(monkeypatch, srv, tmp_path)
    drifted = dict(_TSLA_CONTRACTS[0])
    drifted["expirationDate"] = "2099-01-01T00:00:00.000+00:00"
    c_json = _chain_json_for([drifted])
    c_json["underlying"] = {"last": _TSLA_COMPLETE.get("spot")}
    monkeypatch.setattr(srv, "_gated_safe_get_chain",
                        lambda *a, **k: (_FakeResp(200, c_json), 0.0, 0.1))
    body = json.loads(srv.get_chain(ticker="TSLA", expiry=None).body)
    assert body["scope"]["kind"] != "complete_single_expiry"
    assert body["scope"]["kind"] == "expiry_scope_mismatch"
    assert body["scope"]["requested_expiry"] == _TSLA_EXPIRY
    assert body["scope"]["returned_expiries"] == ["2099-01-01"]
    # Real data, still served — never silently dropped — just not claimed complete.
    assert len(body["contracts"]) == 1
    assert body["status"] == "ok"


def test_chain_expiry_mismatch_does_not_persist_a_complete_capture(monkeypatch, tmp_path):
    """A mismatched response must never be banked as if it were a proven-complete
    capture for the REQUESTED expiry — the persisted table stays empty."""
    import server as srv
    from calibration.complete_chain_capture import latest_complete_chain_capture

    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_TSLA_EXPIRY])
    db_path = _fake_db(monkeypatch, srv, tmp_path)
    drifted = dict(_TSLA_CONTRACTS[0])
    drifted["expirationDate"] = "2099-01-01T00:00:00.000+00:00"
    c_json = _chain_json_for([drifted])
    c_json["underlying"] = {"last": _TSLA_COMPLETE.get("spot")}
    monkeypatch.setattr(srv, "_gated_safe_get_chain",
                        lambda *a, **k: (_FakeResp(200, c_json), 0.0, 0.1))
    srv.get_chain(ticker="TSLA", expiry=None)
    assert latest_complete_chain_capture(db_path, "TSLA", _TSLA_EXPIRY) is None


def test_chain_live_fetch_accepts_explicit_expiry_param(monkeypatch, tmp_path):
    import json

    import server as srv

    monkeypatch.setattr(srv, "get_client", lambda: object())
    _fake_db(monkeypatch, srv, tmp_path)
    fetch_expiries_called = []
    monkeypatch.setattr(srv, "_fetch_expiries_light",
                        lambda t: fetch_expiries_called.append(t) or ["9999-01-01"])
    c_json = _chain_json_for(_TSLA_CONTRACTS)
    c_json["underlying"] = {"last": _TSLA_COMPLETE.get("spot")}
    monkeypatch.setattr(srv, "_gated_safe_get_chain",
                        lambda *a, **k: (_FakeResp(200, c_json), 0.0, 0.1))
    body = json.loads(srv.get_chain(ticker="TSLA", expiry=_TSLA_EXPIRY).body)
    assert body["expiry"] == _TSLA_EXPIRY
    # An explicit expiry must skip the nearest-expiry lookup entirely.
    assert fetch_expiries_called == []


def test_chain_live_fetch_non_200_falls_back_to_stored_snapshot(monkeypatch, tmp_path):
    import json

    import server as srv

    monkeypatch.setattr(srv, "get_client", lambda: object())
    _fake_db(monkeypatch, srv, tmp_path)
    monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_REAL_EXPIRY])
    monkeypatch.setattr(srv, "_gated_safe_get_chain",
                        lambda *a, **k: (_FakeResp(502, {}), 0.0, 0.1))
    monkeypatch.setattr(srv, "_latest_chain_and_spot",
                        lambda t: (_REAL_CONTRACTS, _REAL_SPOT))
    body = json.loads(srv.get_chain(ticker="SPY", expiry=None).body)
    assert body["scope"]["kind"] == "stored_analytical_snapshot_fallback"
    assert body["status"] == "ok"
    assert len(body["contracts"]) == 40


def test_chain_live_fetch_exception_falls_back_to_stored_snapshot(monkeypatch, tmp_path):
    import json

    import server as srv

    monkeypatch.setattr(srv, "get_client", lambda: object())
    _fake_db(monkeypatch, srv, tmp_path)
    monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_REAL_EXPIRY])

    def _boom(*a, **k):
        raise RuntimeError("simulated vendor error")
    monkeypatch.setattr(srv, "_gated_safe_get_chain", _boom)
    monkeypatch.setattr(srv, "_latest_chain_and_spot",
                        lambda t: (_REAL_CONTRACTS, _REAL_SPOT))
    body = json.loads(srv.get_chain(ticker="SPY", expiry=None).body)
    assert body["scope"]["kind"] == "stored_analytical_snapshot_fallback"


def test_real_vendor_evidence_strike_count_alone_undercounts_spy():
    """Durable machine evidence (item #3): the smoking-gun proof, read directly from the
    committed fixture — strike_count=250 alone missed 69 real SPY strikes that
    strike_range=ALL correctly returned on the SAME live request. This test does not
    exercise the endpoint; it pins the evidence itself so a future edit cannot silently
    invalidate the claim the architecture comment in server.py depends on."""
    missed = _SPY_VS_ALL["strikes_missed_by_strike_count_250"]
    assert len(missed) == 69
    assert _SPY_VS_ALL["converged_all_vs_500"] is True
    all_n = _SPY_VS_ALL["strike_range_all"]["n_contracts"]
    count250_n = _SPY_VS_ALL["strike_count_250"]["n_contracts"]
    assert all_n > count250_n
