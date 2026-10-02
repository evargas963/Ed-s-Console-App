"""Full chain for all level math (operator decision 2026-09-25).

MEASURED 2026-09-25 across the 42 board tickers: the strike window (20 strikes for most names)
missed the gamma flip for 10 tickers, moved max pain for 16 and the put wall for 4, and put the
$SPX walls 3-4% away from the same code run on the full chain. SPY, QQQ, MU and $SPX refused a
one-shot strike_range=ALL request with HTTP 502 and answered it in date-range parts.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

import schwab_client as sc
from schwab_client import flatten_chain_contracts
import time_et

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

    def get(self, *, strike_range=None, to_date=None, from_date=None):
        assert strike_range == "ALL"
        lo, hi = from_date or _EXPIRIES[0], to_date or _EXPIRIES[-1]
        span = [e for e in _EXPIRIES if lo <= e <= hi]
        self.calls.append((lo, hi))
        if len(span) > self.max_expiries:
            return _Resp(502)
        if any(e in self.refuse for e in span):
            return _Resp(400)
        return _Resp(200, _payload(span))

    def quote(self, symbols):
        """Schwab's quotes endpoint: no quote for these synthetic contracts."""
        return _Resp(200, {})


@pytest.fixture(autouse=True)
def _before_the_expiries(pin_clock):
    """_EXPIRIES are 2030 dates and expired listings are dropped against today: valued before
    them, the test never ages out."""
    return pin_clock(2029, 12, 3, 12, 0)


@pytest.fixture
def vendor(monkeypatch):
    """The stand-in answers schwab_client's chain and quotes requests."""
    monkeypatch.setattr(sc, "safe_get_chain", lambda client, ticker, **kw: client.get(**kw))
    monkeypatch.setattr(sc, "safe_get_quotes", lambda client, symbols: client.quote(symbols))

    def make(max_expiries, refuse=None):
        monkeypatch.setattr(sc, "_full_chain_parts", {})
        return _Vendor(max_expiries, refuse)
    return make


def _expiries_in(resp) -> set:
    return {c["expirationDate"][:10] for c in flatten_chain_contracts(resp.json())}


def test_one_request_when_the_vendor_answers_it(vendor):
    v = vendor(max_expiries=100)
    r = sc.fetch_full_chain(v, "ZZ")
    assert r.status_code == 200 and r.parts == 1 and len(v.calls) == 1
    assert _expiries_in(r) == {e.isoformat() for e in _EXPIRIES}


def test_a_too_big_chain_is_split_until_every_part_lands(vendor):
    v = vendor(max_expiries=3)                 # one-shot 502, halves 502, quarters land
    r = sc.fetch_full_chain(v, "ZZ")
    assert r.status_code == 200
    assert _expiries_in(r) == {e.isoformat() for e in _EXPIRIES}, "every expiry, none twice-lost"
    assert len(flatten_chain_contracts(r.json())) == 2 * len(_EXPIRIES)
    assert r.parts == 4


def test_the_learned_split_is_reused_without_the_refused_one_shot(vendor):
    v = vendor(max_expiries=3)
    sc.fetch_full_chain(v, "ZZ")
    v.calls.clear()
    r = sc.fetch_full_chain(v, "ZZ")
    assert r.status_code == 200 and len(v.calls) == 4, v.calls
    assert (_EXPIRIES[0], _EXPIRIES[-1]) not in v.calls, "the known-refused one-shot was re-sent"


def test_every_part_and_every_quote_batch_is_asked_at_once(vendor, monkeypatch):
    """Operator 2026-10-01: ask Schwab as fast as we can. The chain's parts are requested
    together, then its quote batches together: each request below waits until all of its kind
    are in flight, so one asked after another never completes."""
    import threading
    v = vendor(max_expiries=3)
    sc.fetch_full_chain(v, "ZZ")                  # learns the 4-part split
    monkeypatch.setattr(sc, "QUOTES_BATCH_MAX", 4)                # 16 contracts: 4 batches
    parts, batches = threading.Barrier(4, timeout=5), threading.Barrier(4, timeout=5)
    ask, answer = v.get, v.quote

    def get(**kw):
        parts.wait()
        return ask(**kw)

    def quote(symbols):
        batches.wait()
        return answer(symbols)
    monkeypatch.setattr(v, "get", get)
    monkeypatch.setattr(v, "quote", quote)
    r = sc.fetch_full_chain(v, "ZZ")
    assert r.status_code == 200 and r.parts == 4
    assert len(flatten_chain_contracts(r.json())) == 2 * len(_EXPIRIES)


def test_a_part_that_cannot_land_is_no_chain_not_a_partial_one(vendor):
    v = vendor(max_expiries=3, refuse={_EXPIRIES[5]})
    r = sc.fetch_full_chain(v, "ZZ")
    assert r.status_code == 400 and r.json() == {}
    assert "incomplete" in r.reason


def test_a_symbol_refusal_is_not_split(vendor):
    v = vendor(max_expiries=100, refuse={_EXPIRIES[0]})
    r = sc.fetch_full_chain(v, "ZZ")
    assert r.status_code == 400 and len(v.calls) == 1


def test_an_expired_listed_expiry_is_never_requested(vendor, monkeypatch):
    """MEASURED 2026-09-26 (Saturday): Schwab's expiration list still carries Friday's expired
    expiry, and any chain request whose fromDate is in the past is refused with HTTP 400 -- every
    board ticker failed all weekend and was quarantined. The expired listing is dropped before
    the date ranges are built."""
    v = vendor(3)
    yesterday = time_et.now_et().date() - timedelta(days=1)
    monkeypatch.setattr(v, "get_option_expiration_chain", lambda ticker: _Resp(200, {
        "expirationList": [{"expirationDate": e.isoformat()} for e in [yesterday, *_EXPIRIES]]}))

    ask = v.get

    def refuses_the_past(**kw):
        if kw.get("from_date") is not None and kw["from_date"] < time_et.now_et().date():
            return _Resp(400)
        return ask(**kw)
    monkeypatch.setattr(v, "get", refuses_the_past)
    r = sc.fetch_full_chain(v, "ZZ")
    assert r.status_code == 200, r.reason
    assert all(lo >= time_et.now_et().date() for lo, _hi in v.calls[1:])
