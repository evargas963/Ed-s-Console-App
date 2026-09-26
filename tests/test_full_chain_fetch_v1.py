"""Full chain for all level math (operator decision 2026-09-25).

MEASURED 2026-09-25 across the 42 board tickers: the strike window (20 strikes for most names)
missed the gamma flip for 10 tickers, moved max pain for 16 and the put wall for 4, and put the
$SPX walls 3-4% away from the same code run on the full chain. SPY, QQQ, MU and $SPX refused a
one-shot strike_range=ALL request with HTTP 502 and answered it in date-range parts.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

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




def test_an_expired_listed_expiry_is_never_requested(vendor, monkeypatch):
    """MEASURED 2026-09-26 (Saturday): Schwab's expiration list still carries Friday's expired
    expiry, and any chain request whose fromDate is in the past is refused with HTTP 400 -- every
    board ticker failed all weekend and was quarantined. The expired listing is dropped before
    the date ranges are built."""
    v = vendor(3)
    yesterday = srv.now_et().date() - timedelta(days=1)
    monkeypatch.setattr(v, "get_option_expiration_chain", lambda ticker: _Resp(200, {
        "expirationList": [{"expirationDate": e.isoformat()} for e in [yesterday, *_EXPIRIES]]}))
    real = v.gated

    def refuses_the_past(client, ticker, **kw):
        if kw.get("from_date") is not None and kw["from_date"] < srv.now_et().date():
            return _Resp(400), 0.1, 0.2
        return real(client, ticker, **kw)
    monkeypatch.setattr(srv, "_gated_safe_get_chain", refuses_the_past)
    r = srv.fetch_full_chain(v, "ZZ")
    assert r.status_code == 200, r.reason
    assert all(lo >= srv.now_et().date() for lo, _hi in v.calls[1:])
