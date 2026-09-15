"""/api/options/vanna-by-strike and /api/options/charm-by-strike (operator field-inventory
audit, 2026-09-13): both wrap ALREADY-canonical, already-tested faucets --
math_exposure_core.compute_exposures_by_strike's own call_vanna/put_vanna (RC-211's exact
BS-vanna faucet) and math_levels.compute_charm_by_strike (the same function /api/forces's
charm_below/charm_above already sum) -- against the SAME live wide chain the terrain loop
already cached (_terrain_cache[tk]["_contracts_rest"]), zero extra vendor calls. These tests
prove the wiring, not the math (bs_vanna/bs_charm/compute_charm_by_strike are proven
elsewhere: test_charm_by_strike_v1.py, test_charm_sign_finite_difference.py)."""
from __future__ import annotations

import json
from pathlib import Path

import server

_FX = Path(__file__).resolve().parent / "fixtures"
_REAL = json.loads((_FX / "real_crwd_complete_chain_quarter.json").read_text(encoding="utf-8"))
_SPOT = float(_REAL["spot"])
_CONTRACTS = [dict(ct) for ct in _REAL["chain"]]
TK = server.ticker_storage_key("CRWD")


def _clear_cache():
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)


def _put_live_chain():
    with server._terrain_cache_lock:
        server._terrain_cache[TK] = {
            "_contracts_rest": _CONTRACTS, "_contracts_rest_spot": _SPOT,
        }


def setup_function(_fn):
    _clear_cache()


def teardown_function(_fn):
    _clear_cache()


def test_vanna_by_strike_unavailable_with_no_cached_chain():
    body = json.loads(server.get_vanna_by_strike(ticker="CRWD").body)
    assert body["available"] is False
    assert "reason" in body


def test_charm_by_strike_unavailable_with_no_cached_chain():
    body = json.loads(server.get_charm_by_strike(ticker="CRWD").body)
    assert body["available"] is False
    assert "reason" in body


def test_vanna_by_strike_matches_the_same_canonical_faucet_call_vanna_minus_put_vanna():
    _put_live_chain()
    from math_exposure_core import compute_exposures_by_strike as cebs

    body = json.loads(server.get_vanna_by_strike(ticker="CRWD").body)
    assert body["available"] is True
    assert body["spot"] == _SPOT
    rows = {r[0]: r[1] for r in body["rows"]}
    assert rows, "a real chain must yield at least one vanna row"

    # Vanna is intraday time-to-expiry sensitive (bs_vanna's own t_years, via
    # _tte_memo/now_et() inside compute_exposures_by_strike) -- the endpoint's own internal
    # call and this reference call are two genuinely separate instants a few milliseconds
    # apart, so a tight tolerance (not exact equality) is the honest comparison, the same
    # discipline the charm test below already applies for the identical reason.
    exposures, _ = cebs(_CONTRACTS, spot=_SPOT, require_oi=True)
    checked = 0
    for k, b in exposures.items():
        # has_oi=False (2026-09-14 SPX honest-absence fix): a bucket can exist in
        # require_oi=True's own output with every accumulator still at its pre-initialized
        # 0.0 -- not a real computed value, so the endpoint's own has_oi gate correctly
        # omits it from `rows` instead of reporting this bucket's fabricated 0.0.
        if not b.get("has_oi"):
            continue
        cv, pv = b.get("call_vanna"), b.get("put_vanna")
        if cv is None and pv is None:
            continue
        expected = round((cv or 0.0) - (pv or 0.0), 2)
        assert abs(rows[round(float(k), 2)] - expected) < 0.1
        checked += 1
    assert checked > 5


def test_charm_by_strike_matches_the_same_canonical_faucet_compute_charm_by_strike():
    _put_live_chain()
    from math_levels import compute_charm_by_strike as ccs

    body = json.loads(server.get_charm_by_strike(ticker="CRWD").body)
    assert body["available"] is True
    rows = {r[0]: r[1] for r in body["rows"]}
    assert rows, "a real chain must yield at least one charm row"

    # Charm is intraday time-to-expiry sensitive (_contract_inputs's own now=now_et()) -- the
    # endpoint's own internal call and this reference call are two genuinely separate instants
    # a few milliseconds apart, so a tight tolerance (not exact equality) is the honest
    # comparison; a real bug in the wiring would be off by orders of magnitude more than this.
    per_ch = ccs(_CONTRACTS, _SPOT)
    checked = 0
    for k, b in per_ch.items():
        if b.get("net_charm") is None:
            continue
        assert abs(rows[round(float(k), 2)] - round(float(b["net_charm"]), 4)) < 0.01
        checked += 1
    assert checked > 5


def test_vanna_and_charm_rows_are_sorted_by_strike_ascending():
    _put_live_chain()
    v_rows = json.loads(server.get_vanna_by_strike(ticker="CRWD").body)["rows"]
    c_rows = json.loads(server.get_charm_by_strike(ticker="CRWD").body)["rows"]
    assert [r[0] for r in v_rows] == sorted(r[0] for r in v_rows)
    assert [r[0] for r in c_rows] == sorted(r[0] for r in c_rows)
