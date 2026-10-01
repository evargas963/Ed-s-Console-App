"""/api/options/vanna-by-strike and /api/options/charm-by-strike (operator field-inventory
audit, 2026-09-13): both wrap ALREADY-canonical, already-tested faucets --
math_exposure_core.compute_exposures_by_strike's own call_vanna/put_vanna (RC-211's exact
BS-vanna faucet) and math_levels.compute_charm_by_strike (the same function /api/forces's
charm_below/charm_above already sum) -- read off the snapshot _publish_levels last
published (the _vanna_rows/_charm_rows _publish_levels writes into the cached payload),
zero extra vendor calls or pricing. These tests
prove the wiring, not the math (bs_vanna/bs_charm/compute_charm_by_strike are proven
elsewhere: test_charm_by_strike_v1.py, test_charm_sign_finite_difference.py)."""
from __future__ import annotations

import pytest

import json
import time
from pathlib import Path

import server
from terrain_engine import compute_terrain


_FX = Path(__file__).resolve().parent / "fixtures"
_REAL = json.loads((_FX / "real_crwd_complete_chain_quarter.json").read_text(encoding="utf-8"))
_SPOT = float(_REAL["spot"])
_CONTRACTS = [dict(ct) for ct in _REAL["chain"]]


@pytest.fixture(autouse=True)
def _at_capture(pin_clock):
    """The CRWD chain (expiry 2026-09-18) was captured 2026-09-02: valued then, it never ages
    out and never lands on a holiday (a rolling today+30 shift did)."""
    return pin_clock(2026, 9, 2, 10, 5)
TK = server.ticker_storage_key("CRWD")


def _clear_cache():
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)


def _put_live_chain():
    snap = compute_terrain(TK, _CONTRACTS, _SPOT)
    with server._terrain_cache_lock:
        server._terrain_cache[TK] = {"ticker": TK, "spot": snap.spot, "computed_ts_utc": time.time(),
                                     "_vanna_rows": server._vanna_rows(snap),
                                     "_charm_rows": server._charm_rows(snap)}


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


def test_vanna_by_strike_matches_the_same_canonical_faucet_call_vanna_minus_put_vanna(monkeypatch):
    _put_live_chain()
    from math_exposure_core import bucket_metric, compute_exposures_by_strike as cebs
    # stand-in (named): the live price, $1 above the price the chain was captured at
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **_k: (_SPOT + 1.0, server.SPOT_SOURCE_PLANE, time.time()))

    body = json.loads(server.get_vanna_by_strike(ticker="CRWD").body)
    assert body["available"] is True
    # spot is the live price (the header's own); the rows were computed at priced_at_spot
    assert body["spot"] == _SPOT + 1.0 and body["priced_at_spot"] == _SPOT
    rows = {r[0]: r[1] for r in body["rows"]}
    assert rows, "a real chain must yield at least one vanna row"

    # Vanna is intraday time-to-expiry sensitive (bs_vanna's own t_years, via
    # _tte_memo/now_et() inside compute_exposures_by_strike) -- the endpoint's own internal
    # call and this reference call are two genuinely separate instants a few milliseconds
    # apart, so a tight tolerance (not exact equality) is the honest comparison, the same
    # discipline the charm test below already applies for the identical reason.
    exposures, _ = cebs(_CONTRACTS, spot=_SPOT)
    checked = 0
    for k, b in exposures.items():
        # a strike with no valid vanna (its accumulators still at their 0.0 start) has no row
        net = bucket_metric(b, "net_vanna")
        if net is None:
            assert round(float(k), 2) not in rows
            continue
        assert abs(rows[round(float(k), 2)] - round(net, 2)) < 0.1
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
