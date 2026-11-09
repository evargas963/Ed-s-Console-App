"""The chain panel: one expiry of the full chain the daemon delivered (strike_range=ALL).

Every Schwab field as sent. A newer streamed open interest or volume replaces the chain's.
Gamma, delta, and volatility stay the chain's, as the sweep took them.

Through the real code: the levels producer holds the chain (server._publish_levels), the daemon's
status and pushed option messages reach the console (live_market_plane.record_feed_heartbeat,
streaming._ingest_pushed), the route. Real data: TSLA's complete 2026-08-31 chain (236 contracts,
tests/fixtures/real_tsla_complete_chain_strike_range_all.json) and MRVL's full chain, 21 expirations
(tests/fixtures/real_mrvl_full_chain_vs_strike_window.json). STAND-INS (named): TSLA's price (the
capture carries none: 330.0) and each streamed value.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import server as srv
import time_et
from option_contract import read_chain
from schwab_client import flatten_chain_contracts
from stream_spine import verbatim_msg
from tests.feed_live_helper import daemon_status
from time_et import ET

_FIXTURES = Path(__file__).parent / "fixtures"
_TSLA = json.loads(
    (_FIXTURES / "real_tsla_complete_chain_strike_range_all.json").read_text(encoding="utf-8")
)
_TSLA_CONTRACTS = _TSLA["chain"]
_TSLA_EXPIRY = _TSLA["expiry"]
_MRVL = json.loads(
    (_FIXTURES / "real_mrvl_full_chain_vs_strike_window.json").read_text(encoding="utf-8")
)
_MRVL_CONTRACTS = flatten_chain_contracts(_MRVL["full"])
_AT = datetime(2026, 8, 30, 12, 0, tzinfo=ET)  # before every expiry of both chains


@pytest.fixture(autouse=True)
def _clean():
    ofls.clear_all_live_state()
    yield
    ofls.clear_all_live_state()
    lmp.record_feed_down()
    with srv._terrain_cache_lock:
        for tk in ("TSLA", "MRVL"):
            srv._terrain_cache.pop(tk, None)
            lmp._by_ticker.pop(tk, None)
            lmp._fields_by_ticker.pop(tk, None)


def _hold(tk, contracts, fetched_ts, price, streamed=()):
    """Hold the daemon's status, push each streamed contract, and publish `tk`'s chain at _AT.

    The status: Schwab's socket open, `tk` and the `streamed` contracts held; each streamed
    (symbol, fields, receive time) pushed, and `tk`'s chain published at _AT; the status beats
    at _AT (the publication's time) and again now (the routes' time).
    """
    held = {"LEVELONE_EQUITIES": [tk], "LEVELONE_OPTIONS": [s for s, _f, _t in streamed]}
    lmp.record_feed_heartbeat(daemon_status(_AT.timestamp(), schwab_socket_open=True, held=held))
    lmp.record_from_level_one_equity(
        tk,
        {"LAST_PRICE": price, "TRADE_TIME_MILLIS": int(fetched_ts * 1000)},
        received_ts=fetched_ts,
    )
    for sym, fields, ts in streamed:
        ofs._ingest_pushed(
            f"optquote.{sym}",
            verbatim_msg(
                symbol=sym, content={"key": sym, **fields}, src="schwab_options_l1", ts_recv=ts
            ),
        )
    srv._publish_levels(
        tk, read_chain(contracts), fetched_ts, chain_spot=(price, fetched_ts), now=_AT
    )
    lmp.record_feed_heartbeat(daemon_status(time_et.now(), schwab_socket_open=True, held=held))


def _as_shown(contracts):
    """`contracts` as the screen shows them: every chain field as sent, bid and ask the quote's.

    The chain's own bid and ask are not used (the stream's, or /quotes'); these captures carry no
    /quotes answer, so they show none.
    """
    return [{**c, "bid": None, "ask": None} for c in contracts]


def _get(ticker, expiry=None):
    """The chain panel for `ticker` (as typed) at `expiry` (None: the front one), now."""
    return srv.chain(srv.ticker_storage_key(ticker), time_et.now(), {"expiry": expiry})


def test_no_held_chain_is_unavailable_with_its_reason():
    body = _get(ticker="ZZNOCHAIN")
    assert body["status"] == "unavailable" and body["contracts"] == []
    assert body["scope"]["reason"]


def test_every_contract_of_the_expiry_is_served_exactly_as_schwab_sent_it():
    _hold("TSLA", _TSLA_CONTRACTS, _AT.timestamp(), 330.0)
    body = _get(ticker="tsla")
    assert body["status"] == "ok" and body["expiry"] == _TSLA_EXPIRY
    assert body["scope"]["kind"] == "complete_single_expiry"
    assert body["contracts"] == _as_shown(_TSLA_CONTRACTS)
    fractional = [c for c in body["contracts"] if c["strikePrice"] != int(c["strikePrice"])]
    assert len(fractional) == _TSLA["n_fractional_strikes"]


def test_only_the_requested_expiry_is_served():
    _hold("MRVL", _MRVL_CONTRACTS, _AT.timestamp(), _MRVL["full"]["underlying"]["last"])
    expiries = sorted({c["expirationDate"][:10] for c in _MRVL_CONTRACTS})
    first, last = _get(ticker="MRVL"), _get(ticker="MRVL", expiry=expiries[-1])
    missing = _get(ticker="MRVL", expiry="2031-01-17")
    assert len(expiries) == 21 and first["expiry"] == expiries[0]
    for body, expiry in ((first, expiries[0]), (last, expiries[-1])):
        assert body["contracts"] == _as_shown(
            [c for c in _MRVL_CONTRACTS if c["expirationDate"].startswith(expiry)]
        )
    assert missing["status"] == "unavailable" and "2031-01-17" in missing["scope"]["reason"]


def test_a_streamed_volume_newer_than_the_chain_is_overlaid():
    fetched = _AT.timestamp() - 20.0
    target = _TSLA_CONTRACTS[0]
    streamed = target["totalVolume"] + 4321
    _hold(
        "TSLA",
        _TSLA_CONTRACTS,
        fetched,
        330.0,
        [(target["symbol"], {"TOTAL_VOLUME": streamed}, _AT.timestamp())],
    )
    body = _get(ticker="TSLA")
    overlaid = next(c for c in body["contracts"] if c["symbol"] == target["symbol"])
    assert overlaid["totalVolume"] == streamed and body["stream_overlay_contracts"] == 1
    assert all(overlaid[k] == v for k, v in _as_shown([target])[0].items() if k != "totalVolume")
    assert [c for c in body["contracts"] if c["symbol"] != target["symbol"]] == _as_shown(
        _TSLA_CONTRACTS[1:]
    )


def test_a_streamed_contracts_bid_and_ask_are_the_streams_never_the_chains():
    """The chain screen's bid and ask of a contract Schwab streams are LEVELONE_OPTIONS's.

    A streamed contract whose bid and ask the stream has not sent shows none (None), never the
    chain's (AGENTS.md rule 3: a pushed field has one producer).
    """
    pushed, silent = _TSLA_CONTRACTS[0], _TSLA_CONTRACTS[1]
    bid, ask = pushed["bid"] + 0.07, pushed["ask"] + 0.11
    _hold(
        "TSLA",
        _TSLA_CONTRACTS,
        _AT.timestamp() - 20.0,
        330.0,
        [
            (pushed["symbol"], {"BID_PRICE": bid, "ASK_PRICE": ask}, _AT.timestamp()),
            (silent["symbol"], {"TOTAL_VOLUME": silent["totalVolume"]}, _AT.timestamp()),
        ],
    )
    shown = {c["symbol"]: c for c in _get(ticker="TSLA")["contracts"]}
    assert (shown[pushed["symbol"]]["bid"], shown[pushed["symbol"]]["ask"]) == (bid, ask)
    assert (shown[silent["symbol"]]["bid"], shown[silent["symbol"]]["ask"]) == (None, None)


def test_a_later_streamed_gamma_does_not_replace_the_quote():
    """A streamed contract's volume is the stream's, even one streamed before the chain.

    Gamma stays the chain's, as the sweep took it: a gamma streamed after the chain does not
    replace it. Open interest is the chain's.
    """
    now = _AT.timestamp()
    target = _TSLA_CONTRACTS[0]
    volume, gamma = target["totalVolume"] + 4321, target["gamma"] + 0.05
    _hold(
        "TSLA",
        _TSLA_CONTRACTS,
        now,
        330.0,
        [
            (target["symbol"], {"TOTAL_VOLUME": volume}, now - 8),
            (target["symbol"], {"GAMMA": gamma}, now + 1),
        ],
    )
    body = _get(ticker="TSLA")
    overlaid = next(c for c in body["contracts"] if c["symbol"] == target["symbol"])
    assert overlaid["totalVolume"] == volume and overlaid["gamma"] == target["gamma"]
    assert overlaid["gamma"] != gamma
    assert overlaid["openInterest"] == target["openInterest"]  # the chain's
    assert body["stream_overlay_contracts"] == 1


def test_the_panel_is_plain_json_as_the_socket_sends_it_and_no_route_serves_it():
    _hold("TSLA", _TSLA_CONTRACTS, _AT.timestamp(), 330.0)
    body = _get(ticker="TSLA")
    assert json.loads(json.dumps(body)) == body and body["expiry"] == _TSLA_EXPIRY
    assert "/api/chain" not in {r.path for r in srv.app.routes}
    assert srv.PAGE_PANELS["chain"] is srv.chain
