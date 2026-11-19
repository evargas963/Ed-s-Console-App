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
from app.market_data.schwab.streaming.live_ui import Asked
from feed.schwab_client import flatten_chain_contracts
from option_contract import GREEKS, LISTED, read_chain
from push import chain as push_chain
from state import level_store
from stream_spine import book_msg, verbatim_msg
from tests.feed_live_helper import daemon_status
from tests.page_on_socket import Pages
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
    with level_store._lock:
        for tk in ("TSLA", "MRVL"):
            level_store._levels.pop(tk, None)
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


#: the chain fields the screens show, each as Schwab sent it (option_contract.chain_row)
_SHOWN = (
    "symbol",
    "putCall",
    "strikePrice",
    "expirationDate",
    "daysToExpiration",
    "settlementType",
    "openInterest",
    "totalVolume",
    "multiplier",
    "volatility",
    "nonStandard",
    *GREEKS,
    *LISTED,
)


def _as_shown(contracts):
    """`contracts` as the screen shows them: the fields it shows as sent, bid and ask the quote's.

    No other /chains field is sent. The chain's own bid and ask are not used (the stream's, or
    /quotes'); these captures carry no /quotes answer, so they show none. Open interest and
    volume are served whole with separators, the IV with two decimals (operator 2026-11-16).
    """

    def text(v, fmt):
        return None if v is None else format(v, fmt)

    return [
        {
            **{k: c[k] for k in _SHOWN if k in c},
            "bid": None,
            "ask": None,
            "oi_text": text(c.get("openInterest"), ",.0f"),
            "volume_text": text(c.get("totalVolume"), ",.0f"),
            "iv_text": text(c.get("volatility"), ".2f"),
            "bid_text": None,
            "ask_text": None,
        }
        for c in contracts
    ]


def _get(ticker, expiry=None):
    """Return the chain panel for `ticker` (as typed) at `expiry` (None: the front one), now."""
    return push_chain.chain(srv.ticker_storage_key(ticker), time_et.now(), {"expiry": expiry})


def test_no_held_chain_is_unavailable_with_its_reason():
    body = _get(ticker="ZZNOCHAIN")
    assert body["status"] == "unavailable" and body["contracts"] == []
    assert body["ladder"] == []  # the page draws the ladder it is sent: no rows, not no key
    assert body["scope"]["reason"]
    assert set(body["scope"]) == {"kind", "reason"}


def test_every_contract_of_the_expiry_is_served_exactly_as_schwab_sent_it():
    _hold("TSLA", _TSLA_CONTRACTS, _AT.timestamp(), 330.0)
    body = _get(ticker="tsla")
    assert body["status"] == "ok" and body["expiry"] == _TSLA_EXPIRY
    # the expiry is served once (`expiry`), and no label of ours rides with the chain
    assert body["scope"] == {"kind": "complete_single_expiry"}
    assert body["contracts"] == _as_shown(_TSLA_CONTRACTS)
    fractional = [c for c in body["contracts"] if c["strikePrice"] != int(c["strikePrice"])]
    assert len(fractional) == _TSLA["n_fractional_strikes"]


def test_a_contract_with_no_side_is_logged_and_left_off_the_ladder_with_no_count_served(caplog):
    """Induced condition: one of TSLA's real contracts sent with a putCall that is neither side.

    The ladder cannot place it. The panel serves Schwab's contracts as sent and no count of
    ours; the console's log names the ticker, the expiry and how many were left off.
    """
    odd = dict(_TSLA_CONTRACTS[0], putCall="X")
    _hold("TSLA", [odd, *_TSLA_CONTRACTS[1:]], _AT.timestamp(), 330.0)
    with caplog.at_level("WARNING", logger="ed_server"):
        body = _get(ticker="tsla")
    assert body["status"] == "ok" and "contracts_not_on_ladder" not in body
    on_ladder = {r[s]["symbol"] for r in body["ladder"] for s in ("call", "put") if r[s]}
    assert odd["symbol"] not in on_ladder and len(on_ladder) == len(_TSLA_CONTRACTS) - 1
    said = [r.getMessage() for r in caplog.records if "not on the chain ladder" in r.getMessage()]
    assert len(said) == 1 and said[0].startswith(f"TSLA {_TSLA_EXPIRY}: 1 contract(s)"), said
    # the chain as Schwab sends it: every contract placed, nothing logged
    _hold("TSLA", _TSLA_CONTRACTS, _AT.timestamp(), 330.0)
    caplog.clear()
    with caplog.at_level("WARNING", logger="ed_server"):
        whole = _get(ticker="tsla")
    assert len({r[s]["symbol"] for r in whole["ladder"] for s in ("call", "put") if r[s]}) == len(
        _TSLA_CONTRACTS
    )
    assert not [r for r in caplog.records if "not on the chain ladder" in r.getMessage()]


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
    assert overlaid["totalVolume"] == streamed
    assert level_store.published_levels("TSLA").gamma_surface["stream_overlay_contracts"] == 1
    assert overlaid["volume_text"] == f"{streamed:,.0f}"  # the streamed volume, as shown
    assert all(
        overlaid[k] == v
        for k, v in _as_shown([target])[0].items()
        if k not in ("totalVolume", "volume_text")
    )
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
    assert level_store.published_levels("TSLA").gamma_surface["stream_overlay_contracts"] == 1


#: inside a window Schwab sent for the option markets (tests/conftest.MARKETS_ANSWERS: 2026-10-07)
_OPEN = datetime(2026, 10, 7, 11, 0, tzinfo=ET)


def _stream_after_pricing(contract, fields, socket_open=True):
    """Price TSLA's chain with `contract` streamed, then stream `fields` of it at _OPEN.

    No pricing runs after: the panel at _OPEN is all that can show the newer values. The daemon's
    status at _OPEN holds the contract, its socket open or not (`socket_open`).
    """
    sym = contract["symbol"]
    first = {"BID_PRICE": contract["bid"], "ASK_PRICE": contract["ask"], "TOTAL_VOLUME": 1}
    _hold("TSLA", _TSLA_CONTRACTS, _AT.timestamp(), 330.0, [(sym, first, _AT.timestamp())])
    held = {"LEVELONE_EQUITIES": ["TSLA"], "LEVELONE_OPTIONS": [sym]}
    status = daemon_status(_OPEN.timestamp(), schwab_socket_open=socket_open, held=held)
    lmp.record_feed_heartbeat(status)
    ofs._ingest_pushed(
        f"optquote.{sym}",
        verbatim_msg(
            symbol=sym,
            content={"key": sym, **fields},
            src="schwab_options_l1",
            ts_recv=_OPEN.timestamp(),
        ),
    )
    body = push_chain.chain("TSLA", _OPEN.timestamp(), {"expiry": None})
    return next(c for c in body["contracts"] if c["symbol"] == sym)


def test_a_quote_streamed_after_the_last_pricing_is_shown_when_it_arrives():
    """A live contract's bid, ask and volume on screen are Schwab's newest, not the last pricing's.

    The levels price the chain at most once a second and a pricing takes seconds (measured
    2026-11-18 on SPY: the ladder a median 4.4 s behind Schwab while marked live); the chain
    screens show each value as Schwab sends it (operator 2026-11-19: the screen always live).
    """
    target = _TSLA_CONTRACTS[0]
    bid, ask, volume = target["bid"] + 0.07, target["ask"] + 0.11, target["totalVolume"] + 99
    shown = _stream_after_pricing(
        target, {"BID_PRICE": bid, "ASK_PRICE": ask, "TOTAL_VOLUME": volume}
    )
    assert (shown["bid"], shown["ask"], shown["totalVolume"]) == (bid, ask, volume)
    assert shown["volume_text"] == f"{volume:,.0f}" and shown["bid_text"] == f"{bid:.2f}"
    assert shown["openInterest"] == target["openInterest"]  # the chain's (rule 3)


def test_a_contract_not_live_keeps_the_values_last_priced():
    """Schwab's socket closed: the contract is not live, and the values last priced stand."""
    target = _TSLA_CONTRACTS[0]
    shown = _stream_after_pricing(
        target, {"BID_PRICE": target["bid"] + 0.07, "TOTAL_VOLUME": 5}, socket_open=False
    )
    assert (shown["bid"], shown["ask"], shown["totalVolume"]) == (
        target["bid"],
        target["ask"],
        1,
    )


def test_every_option_quote_sends_the_chain_panel_of_its_ticker():
    """Each LEVELONE_OPTIONS message, Greeks or not, tells the chain screens of its ticker."""
    _hold("TSLA", _TSLA_CONTRACTS, _AT.timestamp(), 330.0)
    sym = _TSLA_CONTRACTS[0]["symbol"]
    told: list[str] = []
    ofs.FEED.on_flow = told.append
    try:
        ofs._ingest_pushed(
            f"optquote.{sym}",
            verbatim_msg(
                symbol=sym,
                content={"key": sym, "BID_PRICE": 1.0},
                src="schwab_options_l1",
                ts_recv=_AT.timestamp(),
            ),
        )
    finally:
        ofs.FEED.on_flow = None
    assert told == [sym] and srv._tick_ticker(sym) == "TSLA" and "chain" in srv.FLOW_PANELS


def test_a_quote_taken_on_the_loop_marks_the_pages_at_once_with_no_wake_up_write():
    """The bus intake runs on the loop; each option quote marks the pages there and then.

    Handed to its own loop (call_soon_threadsafe) each quote wrote the loop's wake-up socket, a
    system call per message: measured 2026-11-19 at the open, the option intake fell a minute
    behind Schwab. On the loop's own thread the page's chain panel is marked before the call
    returns; handed to the loop, it was not marked until the loop ran the hand-off.
    """
    _hold("TSLA", _TSLA_CONTRACTS, _AT.timestamp(), 330.0)
    sym = _TSLA_CONTRACTS[0]["symbol"]
    pages = Pages()
    page = pages.open("TSLA", "chain:ladder")
    ofs.FEED.on_flow = srv.flow_changed
    try:

        async def take() -> set[str]:
            ofs._ingest_pushed(
                f"optquote.{sym}",
                verbatim_msg(
                    symbol=sym,
                    content={"key": sym, "BID_PRICE": _TSLA_CONTRACTS[0]["bid"]},
                    src="schwab_options_l1",
                    ts_recv=_AT.timestamp(),
                ),
            )
            return set(page.panels)  # before the loop runs anything else

        marked = pages.loop.run_until_complete(take())
    finally:
        ofs.FEED.on_flow = None
        pages.stop()
    assert marked == {"chain:ladder"}


def test_every_option_book_sends_the_flow_panel_of_its_ticker():
    """Each OPTIONS_BOOK message tells the Flow panel (`contract`) of the contract's ticker."""
    _hold("TSLA", _TSLA_CONTRACTS, _AT.timestamp(), 330.0)
    # TSLA 2026-08-31 367.5 call's first OPTIONS_BOOK message as Schwab sent it
    history = json.loads(
        (_FIXTURES / "real_options_stream_history_samples.json").read_text(encoding="utf-8")
    )
    sym, book = next(
        (c["symbol"], e["content"])
        for c in history["contracts"]
        for e in c["events"]
        if e["kind"] == "book"
    )
    assert sym in {c["symbol"] for c in _TSLA_CONTRACTS}
    told: list[str] = []
    ofs.FEED.on_flow = told.append
    try:
        ofs._ingest_pushed(
            f"book.{sym}",
            book_msg(
                symbol=sym,
                service="OPTIONS_BOOK",
                content=book,
                src="schwab_book",
                ts_recv=_AT.timestamp(),
            ),
        )
    finally:
        ofs.FEED.on_flow = None
    assert told == [sym] and srv._tick_ticker(sym) == "TSLA" and "contract" in srv.FLOW_PANELS


def test_the_panel_is_plain_json_as_the_socket_sends_it_and_no_route_serves_it():
    _hold("TSLA", _TSLA_CONTRACTS, _AT.timestamp(), 330.0)
    body = _get(ticker="TSLA")
    assert json.loads(json.dumps(body)) == body and body["expiry"] == _TSLA_EXPIRY
    assert "/api/chain" not in {r.path for r in srv.app.routes}
    asked = Asked("TSLA", _AT.timestamp(), {"expiry": None})
    assert srv.PAGE_PANELS["chain"](asked) == push_chain.chain("TSLA", asked.now, asked.params)
