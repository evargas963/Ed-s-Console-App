"""Full chain for all level math (operator decision 2026-09-25).

MEASURED 2026-09-25 across the 42 board tickers: the strike window (20 strikes for most names)
missed the gamma flip for 10 tickers, moved max pain for 16 and the put wall for 4, and put the
$SPX walls 3-4% away from the same code run on the full chain. SPY, QQQ, MU and $SPX refused a
one-shot strike_range=ALL request with HTTP 502 and answered it in date-range parts.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

import math_levels as ml
import server as srv

_EXPIRIES = [date(2030, 1, 4) + timedelta(days=7 * i) for i in range(8)]


def _contract(exp: date, strike: float, side: str = "CALL") -> dict:
    # institutional-synthetic-ok: transport test -- the vendor stand-in only needs distinct
    # expiry keys to split on; fetch_full_chain never reads a contract field.
    return {"symbol": f"ZZ {exp:%y%m%d}{side[0]}{int(strike * 1000):08d}",
            "putCall": side, "strikePrice": strike, "expirationDate": f"{exp}T20:00:00.000+00:00",
            "openInterest": 100, "multiplier": 100, "volatility": 30.0}


def _payload(exps: list[date]) -> dict:
    out = {"underlying": {"last": 100.0}, "callExpDateMap": {}, "putExpDateMap": {}}
    for e in exps:
        out["callExpDateMap"][f"{e}:7"] = {"100.0": [_contract(e, 100.0, "CALL")]}
        out["putExpDateMap"][f"{e}:7"] = {"100.0": [_contract(e, 100.0, "PUT")]}
    return out


class _Resp:
    def __init__(self, code, payload=None):
        self.status_code = code
        self._p = payload or {}

    def json(self):
        return self._p


class _Vendor:
    """A Schwab stand-in that refuses any request spanning more than `max_expiries` expiries
    with HTTP 502 -- the observed answer to an over-large chain request."""

    def __init__(self, max_expiries: int, refuse: "set[date] | None" = None):
        self.max_expiries = max_expiries
        self.refuse = refuse or set()
        self.calls: list[tuple] = []

    def get_option_expiration_chain(self, ticker):
        return _Resp(200, {"expirationList": [{"expirationDate": e.isoformat()} for e in _EXPIRIES]})

    def gated(self, client, ticker, *, strike_count=None, strike_range=None, priority=False,
              to_date=None, from_date=None):
        assert strike_count is None and strike_range == "ALL", "level math must never use a window"
        lo, hi = from_date or _EXPIRIES[0], to_date or _EXPIRIES[-1]
        span = [e for e in _EXPIRIES if lo <= e <= hi]
        self.calls.append((lo, hi))
        if len(span) > self.max_expiries:
            return _Resp(502), 0.1, 0.2
        if any(e in self.refuse for e in span):
            return _Resp(400), 0.1, 0.2
        return _Resp(200, _payload(span)), 0.1, 0.2


@pytest.fixture
def vendor(monkeypatch):
    def make(max_expiries, refuse=None):
        v = _Vendor(max_expiries, refuse)
        monkeypatch.setattr(srv, "_gated_safe_get_chain", v.gated)
        monkeypatch.setattr(srv, "_full_chain_parts", {})
        return v
    return make


def _expiries_in(resp) -> set:
    return {c["expirationDate"][:10] for c in srv.flatten_chain_contracts(resp.json())}


def test_one_request_when_the_vendor_answers_it(vendor):
    v = vendor(max_expiries=100)
    r = srv.fetch_full_chain(v, "ZZ")
    assert r.status_code == 200 and r.parts == 1 and len(v.calls) == 1
    assert _expiries_in(r) == {e.isoformat() for e in _EXPIRIES}
    assert r.gate_wait_sec == pytest.approx(0.1) and r.fetch_sec == pytest.approx(0.2)


def test_a_too_big_chain_is_split_until_every_part_lands(vendor):
    v = vendor(max_expiries=3)                 # one-shot 502, halves 502, quarters land
    r = srv.fetch_full_chain(v, "ZZ")
    assert r.status_code == 200
    assert _expiries_in(r) == {e.isoformat() for e in _EXPIRIES}, "every expiry, none twice-lost"
    assert len(srv.flatten_chain_contracts(r.json())) == 2 * len(_EXPIRIES)
    assert r.parts == 4


def test_the_learned_split_is_reused_without_the_refused_one_shot(vendor):
    v = vendor(max_expiries=3)
    srv.fetch_full_chain(v, "ZZ")
    v.calls.clear()
    r = srv.fetch_full_chain(v, "ZZ")
    assert r.status_code == 200 and len(v.calls) == 4, v.calls
    assert (_EXPIRIES[0], _EXPIRIES[-1]) not in v.calls, "the known-refused one-shot was re-sent"


def test_a_part_that_cannot_land_is_no_chain_not_a_partial_one(vendor):
    v = vendor(max_expiries=3, refuse={_EXPIRIES[5]})
    r = srv.fetch_full_chain(v, "ZZ")
    assert r.status_code == 400 and r.json() == {}
    assert "incomplete" in r.reason


def test_a_symbol_refusal_is_not_split(vendor):
    v = vendor(max_expiries=100, refuse={_EXPIRIES[0]})
    r = srv.fetch_full_chain(v, "ZZ")
    assert r.status_code == 400 and len(v.calls) == 1


def test_single_expiry_mode_takes_every_strike_of_that_expiry(vendor):
    v = vendor(max_expiries=100)
    r = srv.fetch_full_chain(v, "ZZ", expiry=_EXPIRIES[2])
    assert r.status_code == 200 and v.calls == [(_EXPIRIES[2], _EXPIRIES[2])]
    assert _expiries_in(r) == {_EXPIRIES[2].isoformat()}


def test_vectorized_gamma_profile_equals_the_per_contract_black_scholes_loop():
    """compute_gamma_profile is the same sum of bs_gamma terms, evaluated as arrays -- checked
    on REAL Schwab chains (TSLA and CDE complete single-expiry captures)."""
    import json
    from datetime import datetime, timedelta
    from pathlib import Path

    fx = Path(__file__).resolve().parent / "fixtures"
    for name in ("real_tsla_complete_chain_strike_range_all.json",
                 "real_cde_complete_chain_half_dollar.json"):
        chain = json.loads((fx / name).read_text(encoding="utf-8"))["chain"]
        expiry = datetime.fromisoformat(chain[0]["expirationDate"].replace("Z", "+00:00"))
        now = expiry - timedelta(days=3)          # value it before its own expiry
        strikes = sorted(float(c["strikePrice"]) for c in chain)
        spot = strikes[len(strikes) // 2]
        parsed = [p for p in (ml._contract_inputs(c, now=now) for c in chain) if p]
        assert len(parsed) > 20, name
        for model in (ml.SIGN_MODEL_NAIVE, ml.SIGN_MODEL_EMPIRICAL_PRIOR):
            got = ml.compute_gamma_profile(chain, spot, sign_model=model, now=now)
            assert len(got) == 241
            lo, hi = spot * 0.85, spot * 1.15          # the function's own grid (span 0.15, 240 steps)
            for i, (shown, total) in enumerate(got):
                s = lo + (hi - lo) * i / 240           # summed at the exact price; shown rounded
                assert shown == round(s, 4)
                ref = 0.0
                for strike, oi, mult, t, sig, sign in parsed:
                    g = ml.bs_gamma(s, strike, t, sig)
                    if g is not None:
                        ref += ml._dealer_sign(sign, model) * g * oi * mult * s * s * 0.01
                assert math.isclose(total, ref, rel_tol=1e-9, abs_tol=1e-6), (name, model, s, total, ref)
