"""GET /api/chain: one expiry of the full chain the daemon delivered (strike_range=ALL), every Schwab
field as sent, each contract the daemon streams priced from its stream (question 1: everything
Schwab sent, exactly as sent; question 2: the screen shows the newest).

Through the real code: the levels producer holds the chain (server._publish_levels), the daemon's
status and pushed option messages reach the console (live_market_plane.record_feed_heartbeat,
streaming._ingest_pushed), the route. Real data: TSLA's complete 2026-08-31 chain (236 contracts,
tests/fixtures/real_tsla_complete_chain_strike_range_all.json) and MRVL's full chain, 21 expirations
(tests/fixtures/real_mrvl_full_chain_vs_strike_window.json). STAND-INS (named): TSLA's price (the
capture carries none: 330.0) and each streamed value.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import pytest

import app.options.order_flow.state as ofls
import server as srv
from schwab_client import flatten_chain_contracts
from tests.feed_live_helper import (daemon_holds, forget_price, ledger_open, no_daemon, price_sent,
                                    through_the_daemons_bus)
from time_et import ET

_FIXTURES = Path(__file__).parent / "fixtures"
_TSLA = json.loads((_FIXTURES / "real_tsla_complete_chain_strike_range_all.json").read_text(encoding="utf-8"))
_TSLA_CONTRACTS = _TSLA["chain"]
_TSLA_EXPIRY = _TSLA["expiry"]
_MRVL = json.loads((_FIXTURES / "real_mrvl_full_chain_vs_strike_window.json").read_text(encoding="utf-8"))
_MRVL_CONTRACTS = flatten_chain_contracts(_MRVL["full"])
_AT = datetime(2026, 8, 30, 12, 0, tzinfo=ET)          # before every expiry of both chains


@pytest.fixture(autouse=True)
def _clean():
    ofls.clear_all_live_state()
    no_daemon()
    yield
    ofls.clear_all_live_state()
    no_daemon()
    with srv._terrain_cache_lock:
        for tk in ("TSLA", "MRVL"):
            srv._terrain_cache.pop(tk, None)
            forget_price(tk)


def _hold(tk, contracts, fetched_ts, price, streamed=()):
    """The daemon's status (Schwab's socket open, `tk` and the `streamed` contracts held), `tk`'s
    contracts' records opened (feed_live_helper.ledger_open), each streamed (symbol, fields,
    receive time) posted to its record, and the round published at _AT; the status beats at _AT
    (the publication's time) and again now (the routes' time)."""
    held = {"LEVELONE_EQUITIES": [tk], "LEVELONE_OPTIONS": [s for s, _f, _t in streamed]}
    daemon_holds(_AT.timestamp(), held)
    price_sent(tk, price, fetched_ts)
    bus = ledger_open(tk, contracts, fetched_ts)
    for sym, fields, ts in streamed:
        through_the_daemons_bus(bus, sym, [fields], [ts])
    srv._publish_levels(tk, fetched_ts, now=_AT)
    daemon_holds(time.time(), held)


def _get(ticker, expiry=None):
    """/api/chain's answer at _AT (before every expiry of both chains: the front is the first)."""
    return srv.chain_payload(srv.ticker_storage_key(ticker), expiry, _AT.timestamp())


def _as_sent(served: list) -> list:
    """The served contracts' Schwab fields: each without its record's ticker, stream time and
    field times."""
    return [{k: v for k, v in c.items() if k not in ("ticker", "streamTime", "fieldTimes")} for c in served]


def test_no_held_chain_is_unavailable_with_its_reason():
    body = _get(ticker="ZZNOCHAIN")
    assert body["status"] == "unavailable" and body["contracts"] == []
    assert body["scope"]["reason"]


def test_every_contract_of_the_expiry_is_served_exactly_as_schwab_sent_it():
    _hold("TSLA", _TSLA_CONTRACTS, _AT.timestamp(), 330.0)
    body = _get(ticker="tsla")
    assert body["status"] == "ok" and body["expiry"] == _TSLA_EXPIRY
    assert body["scope"]["kind"] == "complete_single_expiry"
    assert _as_sent(body["contracts"]) == _TSLA_CONTRACTS
    assert all(c["ticker"] == "TSLA" and set(c["fieldTimes"]) == set(c) - {"fieldTimes"} for c in body["contracts"])
    fractional = [c for c in body["contracts"] if c["strikePrice"] != int(c["strikePrice"])]
    assert len(fractional) == _TSLA["n_fractional_strikes"]


def test_only_the_requested_expiry_is_served():
    _hold("MRVL", _MRVL_CONTRACTS, _AT.timestamp(), _MRVL["full"]["underlying"]["last"])
    expiries = sorted({c["expirationDate"][:10] for c in _MRVL_CONTRACTS})
    first, last = _get(ticker="MRVL"), _get(ticker="MRVL", expiry=expiries[-1])
    missing = _get(ticker="MRVL", expiry="2031-01-17")
    assert len(expiries) == 21 and first["expiry"] == expiries[0]
    for body, expiry in ((first, expiries[0]), (last, expiries[-1])):
        assert _as_sent(body["contracts"]) == [c for c in _MRVL_CONTRACTS if c["expirationDate"].startswith(expiry)]
    assert missing["status"] == "unavailable" and "2031-01-17" in missing["scope"]["reason"]


def test_a_held_contract_is_served_as_its_one_record_every_other_as_the_chain():
    """One record per held contract (operator 2026-10-13): Schwab's REST answer, each field a
    newer stream message sent in its place, with that message's Schwab time; a field the stream has
    not sent, and open interest, are the REST answer's as sent; every other contract is the
    chain's as Schwab sent it. STAND-IN (named): the streamed volume and gamma."""
    now = _AT.timestamp()
    target = _TSLA_CONTRACTS[0]
    streamed_at = target["quoteTimeInLong"] / 1000 + 60          # a minute after the chain's quote
    volume, gamma = (target["totalVolume"] or 0) + 4321, (target["gamma"] or 0) + 0.05
    _hold("TSLA", _TSLA_CONTRACTS, now, 330.0,
          [(target["symbol"], {"TOTAL_VOLUME": volume, "GAMMA": gamma}, streamed_at)])
    body = _get(ticker="TSLA")
    served = next(c for c in body["contracts"] if c["symbol"] == target["symbol"])
    assert _as_sent([served]) == [{**target, "totalVolume": volume, "gamma": gamma}]
    ms = int(streamed_at * 1000)
    assert (served["fieldTimes"]["gamma"], served["fieldTimes"]["totalVolume"], served["streamTime"]) == (ms, ms, ms)
    assert served["fieldTimes"]["openInterest"] == target["quoteTimeInLong"]
    assert _as_sent([c for c in body["contracts"] if c["symbol"] != target["symbol"]]) == _TSLA_CONTRACTS[1:]


def test_the_route_answers_over_real_http():
    from starlette.testclient import TestClient
    _hold("TSLA", _TSLA_CONTRACTS, _AT.timestamp(), 330.0)
    with TestClient(srv.app) as client:
        r = client.get("/api/chain", params={"ticker": "TSLA", "expiry": _TSLA_EXPIRY})   # now: it has expired
    assert r.status_code == 200 and r.json()["expiry"] == _TSLA_EXPIRY
