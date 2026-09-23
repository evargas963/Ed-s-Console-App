"""/api/options/vanna-by-strike and /api/options/charm-by-strike (operator field-inventory
audit, 2026-09-13): both wrap ALREADY-canonical, already-tested faucets --
math_exposure_core.compute_exposures_by_strike's own call_vanna/put_vanna (RC-211's exact
BS-vanna faucet) and math_levels.compute_charm_by_strike (the same function /api/forces's
charm_below/charm_above already sum) -- against the SAME live wide chain the terrain loop
already cached (_terrain_cache[tk]["_contracts_rest"]), zero extra vendor calls. These tests
prove the wiring, not the math (bs_vanna/bs_charm/compute_charm_by_strike are proven
elsewhere: test_charm_by_strike_v1.py, test_charm_sign_finite_difference.py)."""
from __future__ import annotations

import datetime
import json
from datetime import date, timedelta
from pathlib import Path

import server
from time_et import ET
import app.api.routes.options
import terrain_state

_FX = Path(__file__).resolve().parent / "fixtures"
_REAL = json.loads((_FX / "real_crwd_complete_chain_quarter.json").read_text(encoding="utf-8"))
_SPOT = float(_REAL["spot"])
_CONTRACTS = [dict(ct) for ct in _REAL["chain"]]
# The captured fixture's every contract shares one expirationDate, frozen at capture time
# ("2026-09-18T20:00:00.000+00:00"). math_levels._contract_inputs computes time-to-expiry from
# REAL wall-clock now_et() with no injection point reachable through app.api.routes.options.get_charm_by_strike
# (an HTTP route, no `now` parameter) -- once real time passes that captured date, t_years <= 0
# and EVERY contract fails closed, so `available` silently flips to False (REPRODUCED
# 2026-09-21: real time had already passed it). This test proves the WIRING (see module
# docstring), not the math, so the exact date doesn't matter -- only that it stays in the
# future. Shift every contract's own expirationDate forward by the same delta that would put
# the ORIGINAL capture date 30 days out from today, preserving the captured Greeks/OI/IV
# (and the time-of-day/timezone suffix) untouched.
_ORIG_EXPIRY = "2026-09-18"
_SHIFT_DAYS = (date.today() + timedelta(days=30) - date.fromisoformat(_ORIG_EXPIRY)).days
for _ct in _CONTRACTS:
    _exp = _ct.get("expirationDate") or ""
    if _exp.startswith(_ORIG_EXPIRY):
        _new_date = (date.fromisoformat(_ORIG_EXPIRY) + timedelta(days=_SHIFT_DAYS)).isoformat()
        _ct["expirationDate"] = _new_date + _exp[len(_ORIG_EXPIRY):]
TK = server.ticker_storage_key("CRWD")

# RC-REHAB-2: this fixture's chain (real_crwd_complete_chain_quarter.json) was captured
# 2026-09-02 with a UNIFORM expirationDate of 2026-09-18T20:00:00Z baked into every contract.
# Both faucets under test derive T from time_et.now_et() (fail-closed at T<=0), so once real
# wall-clock time reached that date every contract went "expired" for BOTH the endpoint's own
# call and this file's reference call -- not a production bug (the fail-closed guard is
# correct), but it silently broke what these tests are actually for. compute_charm_by_strike
# never opens a bucket for an expired contract, so its endpoint hard-fails (available=False).
# compute_exposures_by_strike is looser: has_oi opens a bucket regardless of T, and
# call_vanna/put_vanna are pre-initialized to a real 0.0 that an expired T simply never
# overwrites -- so the "matches" comparison kept passing, but only by comparing two
# independently-computed 0.0s, not by exercising real per-contract vanna math. Freezing `now`
# to a moment inside the fixture's own capture window restores both tests to proving what
# they claim to prove.
_FROZEN_NOW = datetime.datetime(2026, 9, 2, 14, 30, tzinfo=ET)


def _clear_cache():
    with terrain_state._terrain_cache_lock:
        terrain_state._terrain_cache.pop(TK, None)


def _put_live_chain():
    with terrain_state._terrain_cache_lock:
        terrain_state._terrain_cache[TK] = {
            "_contracts_rest": _CONTRACTS, "_contracts_rest_spot": _SPOT,
        }


def setup_function(_fn):
    _clear_cache()


def teardown_function(_fn):
    _clear_cache()


def test_vanna_by_strike_unavailable_with_no_cached_chain():
    body = json.loads(app.api.routes.options.get_vanna_by_strike(ticker="CRWD").body)
    assert body["available"] is False
    assert "reason" in body


def test_charm_by_strike_unavailable_with_no_cached_chain():
    body = json.loads(app.api.routes.options.get_charm_by_strike(ticker="CRWD").body)
    assert body["available"] is False
    assert "reason" in body


def test_vanna_by_strike_matches_the_same_canonical_faucet_call_vanna_minus_put_vanna(monkeypatch):
    monkeypatch.setattr("time_et.now_et", lambda: _FROZEN_NOW)
    _put_live_chain()
    from math_exposure_core import compute_exposures_by_strike as cebs

    body = json.loads(app.api.routes.options.get_vanna_by_strike(ticker="CRWD").body)
    assert body["available"] is True
    assert body["spot"] == _SPOT
    rows = {r[0]: r[1] for r in body["rows"]}
    assert rows, "a real chain must yield at least one vanna row"

    # Vanna is intraday time-to-expiry sensitive (bs_vanna's own t_years, via
    # _tte_memo/now_et() inside compute_exposures_by_strike) -- `now_et` is frozen above so the
    # endpoint's own internal call and this reference call see the IDENTICAL instant (not just
    # a close one), the tight tolerance below is purely float-rounding slack, not a clock race.
    exposures, _ = cebs(_CONTRACTS, spot=_SPOT, require_oi=True)
    checked = 0
    nonzero = 0
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
        if expected != 0.0:
            nonzero += 1
    assert checked > 5
    # RC-REHAB-2: with `now` frozen inside the fixture's own capture window every contract has
    # T > 0, so this must exercise REAL per-contract vanna math, not 218 contracts silently
    # collapsing to a vacuous 0.0-matches-0.0 comparison (which is what an expired chain gives).
    assert nonzero > 5


def test_charm_by_strike_matches_the_same_canonical_faucet_compute_charm_by_strike(monkeypatch):
    monkeypatch.setattr("time_et.now_et", lambda: _FROZEN_NOW)
    _put_live_chain()
    from math_levels import compute_charm_by_strike as ccs

    body = json.loads(app.api.routes.options.get_charm_by_strike(ticker="CRWD").body)
    assert body["available"] is True
    rows = {r[0]: r[1] for r in body["rows"]}
    assert rows, "a real chain must yield at least one charm row"

    # Charm is intraday time-to-expiry sensitive (_contract_inputs's own now=now_et()) --
    # `now_et` is frozen above so the endpoint's own internal call and this reference call see
    # the IDENTICAL instant; the tight tolerance below is purely float-rounding slack.
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
    v_rows = json.loads(app.api.routes.options.get_vanna_by_strike(ticker="CRWD").body)["rows"]
    c_rows = json.loads(app.api.routes.options.get_charm_by_strike(ticker="CRWD").body)["rows"]
    assert [r[0] for r in v_rows] == sorted(r[0] for r in v_rows)
    assert [r[0] for r in c_rows] == sorted(r[0] for r in c_rows)
