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
import app.options.order_flow.streaming as ofs
import server as srv
from schwab_client import flatten_chain_contracts
from stream_spine import options_quote_msg
from tests.feed_live_helper import daemon_holds, no_daemon
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
            ofs._price_rows.pop(tk, None)


def _hold(tk, contracts, fetched_ts, price, streamed=()):
    """The daemon's status (Schwab's socket open, `tk` and the `streamed` contracts held), each
    streamed (symbol, fields, receive time) pushed, and `tk`'s chain published at _AT; the status
    beats at _AT (the publication's time) and again now (the routes' time)."""
    held = {"LEVELONE_EQUITIES": [tk], "LEVELONE_OPTIONS": [s for s, _f, _t in streamed]}
    daemon_holds(_AT.timestamp(), held)
    ofs._price_rows[tk] = {"ticker": tk, "spot": price, "trade_ts": fetched_ts}
    for sym, fields, ts in streamed:
        ofs._ingest_pushed(f"optquote.{sym}", options_quote_msg(symbol=sym, content={"key": sym, **fields},
                                                                src="schwab_options_l1", ts_recv=ts))
    srv._publish_levels(tk, [dict(c) for c in contracts], fetched_ts, now=_AT)
    daemon_holds(time.time(), held)


def _get(**kw):
    return json.loads(srv.get_chain(**{"expiry": None, **kw}).body)


def test_no_held_chain_is_unavailable_with_its_reason():
    body = _get(ticker="ZZNOCHAIN")
    assert body["status"] == "unavailable" and body["contracts"] == []
    assert body["scope"]["reason"]


def test_every_contract_of_the_expiry_is_served_exactly_as_schwab_sent_it():
    _hold("TSLA", _TSLA_CONTRACTS, _AT.timestamp(), 330.0)
    body = _get(ticker="tsla")
    assert body["status"] == "ok" and body["expiry"] == _TSLA_EXPIRY
    assert body["scope"]["kind"] == "complete_single_expiry"
    assert body["contracts"] == _TSLA_CONTRACTS
    fractional = [c for c in body["contracts"] if c["strikePrice"] != int(c["strikePrice"])]
    assert len(fractional) == _TSLA["n_fractional_strikes"]


def test_only_the_requested_expiry_is_served():
    _hold("MRVL", _MRVL_CONTRACTS, _AT.timestamp(), _MRVL["full"]["underlying"]["last"])
    expiries = sorted({c["expirationDate"][:10] for c in _MRVL_CONTRACTS})
    first, last = _get(ticker="MRVL"), _get(ticker="MRVL", expiry=expiries[-1])
    missing = _get(ticker="MRVL", expiry="2031-01-17")
    assert len(expiries) == 21 and first["expiry"] == expiries[0]
    for body, expiry in ((first, expiries[0]), (last, expiries[-1])):
        assert body["contracts"] == [c for c in _MRVL_CONTRACTS if c["expirationDate"].startswith(expiry)]
    assert missing["status"] == "unavailable" and "2031-01-17" in missing["scope"]["reason"]


def test_a_held_contract_is_served_as_its_one_record_every_other_as_the_chain():
    """One record per held contract (operator 2026-10-13): Schwab's REST answer, each field the
    stream has sent in its place, whenever the chain was fetched (a volume streamed before it
    included); a field the stream has not sent, and open interest, are the chain's as sent; every
    other contract is the chain's as Schwab sent it. The route serves what the levels priced."""
    now = _AT.timestamp()
    target = _TSLA_CONTRACTS[0]
    volume, gamma = (target["totalVolume"] or 0) + 4321, (target["gamma"] or 0) + 0.05
    _hold("TSLA", _TSLA_CONTRACTS, now, 330.0,
          [(target["symbol"], {"TOTAL_VOLUME": volume, "GAMMA": gamma}, now - 8)])
    body = _get(ticker="TSLA")
    served = next(c for c in body["contracts"] if c["symbol"] == target["symbol"])
    assert served == {**target, "totalVolume": volume, "gamma": gamma}
    assert [c for c in body["contracts"] if c["symbol"] != target["symbol"]] == _TSLA_CONTRACTS[1:]


def test_the_route_answers_over_real_http():
    from starlette.testclient import TestClient
    _hold("TSLA", _TSLA_CONTRACTS, _AT.timestamp(), 330.0)
    with TestClient(srv.app) as client:
        r = client.get("/api/chain", params={"ticker": "TSLA"})
    assert r.status_code == 200 and r.json()["expiry"] == _TSLA_EXPIRY
