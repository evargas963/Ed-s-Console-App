"""Outage marks (operator 2026-10-14, item 2): during any outage every value keeps its last value,
marked NOT LIVE with the reason, and no value is live unless every feed it depends on is live.

Real data: SPY's 2026-10-13 0DTE chain and the first LEVELONE_OPTIONS messages of that open
(tests/fixtures/real_spy_0dte_open_stream_and_chain_2026_10_13.json), through the daemon's ledger
postings (option_ledger) and the console's real ingest (streaming._ingest_pushed). STAND-IN
(named): the daemon's status (tests/feed_live_helper.daemon_holds, or as each test writes it).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import option_ledger
import live_market_plane as lmp
import server
from app.options.order_flow import history
from app.options.order_flow import state as ofls
from app.options.order_flow import streaming as ofs
from stream_spine import MessageBus, current_key
from tests.feed_live_helper import CONNECTED_AT, daemon_holds, no_daemon

_FX = json.loads((Path(__file__).parent / "fixtures" / "real_spy_0dte_open_stream_and_chain_2026_10_13.json")
                 .read_text(encoding="utf-8"))
#: a contract's chain record, and the first message streamed after it that carries a newer trade
_CHAINS = {c["symbol"]: c for c in _FX["chain"]}
_TRADE = next(m for m in _FX["messages"] if "LAST_PRICE" in m["content"] and "TRADE_TIME_MILLIS" in m["content"]
              and m["symbol"] in _CHAINS and m["content"]["TRADE_TIME_MILLIS"] > _CHAINS[m["symbol"]]["tradeTimeInLong"])
_SYM = _TRADE["symbol"]
_CHAIN = _CHAINS[_SYM]


def _push(bus, topic, msg) -> None:
    bus.publish(topic, msg)
    ofs._ingest_pushed(topic, bus.current[current_key(topic, msg)][1])


def _priced_and_traded() -> None:
    """The contract's record opened from the chain (its ticker, SPY), then its trade as streamed."""
    bus = MessageBus()
    _push(bus, *option_ledger.posting(_SYM, option_ledger.opening(_CHAIN, "SPY"), _CHAIN["quoteTimeInLong"],
                                      _FX["chain_capture_ts_utc"]))
    _push(bus, *option_ledger.posting(_SYM, option_ledger.from_stream(_TRADE["content"], _TRADE["schwab_ts"]),
                                      _TRADE["schwab_ts"], _TRADE["ts_recv"]))


def _status(at: float, *, connected_at, picks: dict, ranked: list, held: "dict | None" = None) -> dict:
    return {"ts": at, "schwab_socket_open": True, "connected_at": connected_at,
            "held": held if held is not None else picks, "options": picks, "ranked": ranked}


def test_a_restarted_daemon_keeps_the_option_prints_until_its_rule_has_ranked_their_ticker():
    """The daemon restarts: its first status holds nothing and its rule has picked nothing, for
    it has ranked no ticker yet. The contract's print stands; once the rule has ranked SPY and
    does not pick it, it is released. Before, the restarted daemon's first status released every
    contract: the Flow tape and the option books emptied."""
    picks = {"LEVELONE_OPTIONS": [_SYM], "OPTIONS_BOOK": []}
    now = time.time()
    try:
        ofs.apply_heartbeat(_status(now, connected_at=CONNECTED_AT, picks=picks, ranked=["SPY"]))
        _priced_and_traded()
        printed = history.TAPE.prints(_SYM)
        assert printed
        none = {"LEVELONE_OPTIONS": [], "OPTIONS_BOOK": []}
        ofs.apply_heartbeat(_status(now + 1, connected_at=now + 1, picks=none, ranked=[]))   # restarted
        assert history.TAPE.prints(_SYM) == printed, "a restart released the contract"
        ofs.apply_heartbeat(_status(now + 2, connected_at=now + 1, picks=none, ranked=["SPY"]))
        assert history.TAPE.prints(_SYM) == []
    finally:
        ofls.clear_symbol(_SYM)
        no_daemon()


def test_a_value_is_live_only_once_its_service_posted_to_it_on_this_connection():
    """One rule for every Schwab service: the contract's LEVELONE_OPTIONS value is live once the
    stream posted to it on the daemon's current connection. A new connection begun after its last
    message leaves it not live until the stream posts again; a status that reports no connection
    start is not live. Before, only an equity was judged on its connection: an option contract
    of an ended connection read live."""
    held = {"LEVELONE_OPTIONS": [_SYM]}
    received = _TRADE["ts_recv"]
    try:
        daemon_holds(received + 1, held, connected_at=received - 60)
        _priced_and_traded()
        assert lmp.feed_live_for(_SYM, "LEVELONE_OPTIONS", received + 1)
        daemon_holds(received + 2, held, connected_at=received + 2)          # a new connection
        assert not lmp.feed_live_for(_SYM, "LEVELONE_OPTIONS", received + 2)
        lmp.record_feed_heartbeat({"ts": received + 3, "schwab_socket_open": True, "held": held})   # no start
        assert not lmp.feed_live_for(_SYM, "LEVELONE_OPTIONS", received + 3)
    finally:
        ofls.clear_symbol(_SYM)
        no_daemon()


def test_through_a_schwab_outage_the_tape_keeps_its_prints_marked_not_live():
    """Schwab's connection ends: the daemon holds nothing and says so, its rule still picking the
    contract. The tape still serves the contract's print, and is marked not live with the reason.
    Before, the tape read its contracts from what the daemon held: it went blank and unmarked.
    Judged at the chain's capture, in the 2026-10-13 regular session."""
    picks = {"LEVELONE_OPTIONS": [_SYM], "OPTIONS_BOOK": []}
    now = _FX["chain_capture_ts_utc"]
    try:
        ofs.apply_heartbeat(_status(now, connected_at=_TRADE["ts_recv"] - 60, picks=picks, ranked=["SPY"],
                                    held={**picks, "LEVELONE_EQUITIES": ["SPY"]}))
        _priced_and_traded()
        ended = {**_status(now + 1, connected_at=_TRADE["ts_recv"] - 60, picks=picks, ranked=["SPY"], held={}),
                 "schwab_socket_open": False}
        ofs.apply_heartbeat(ended)
        rows = server.tape_payload("SPY", None, 100)["rows"]
        assert [r["ts_recv"] for r in rows] == [p["ts_recv"] for p in history.TAPE.prints(_SYM)] != []
        v = {"ticker": "SPY", "workspace": "options", "subview": "gamma", "view": "heatmap", "expiry": None,
             "strike": None, "strike_expiry": None, "contract": None, "scope": "auto", "venue": "NYSE_BOOK",
             "cols": 6, "book_minutes": 60, "tfs": {"chart": "1", "liquidity": "5", "desk": "5"},
             "pans": {k: {"centre": None, "shift": 0} for k in ("heatmap", "gbs", "vanna", "charm", "migration")}}
        assert server._not_live(server._panels(v)["gamma.tape"], now + 1)
    finally:
        ofls.clear_symbol(_SYM)
        no_daemon()


def test_the_candles_and_the_options_tape_are_marked_when_their_feed_is_down():
    """The chart's candles of several minutes are the console's, read from Schwab's CHART_EQUITY,
    and the options tape from each streamed contract's LEVELONE_OPTIONS: with the feed holding
    neither, each panel is marked not live with its reason. Before, both declared no feed and read
    live through any outage. At 1 minute the candles are the daemon's series, marked on the page by
    the daemon's own CHART_EQUITY verdict: the console's panel carries no verdict of its own. Judged
    at the chain's capture, in the 2026-10-13 regular session (an outage while Closed is none)."""
    picks = {"LEVELONE_OPTIONS": [_SYM], "OPTIONS_BOOK": []}
    now = _FX["chain_capture_ts_utc"]
    v = {"ticker": "SPY", "workspace": "options", "subview": "gamma", "view": "chart", "expiry": None,
         "strike": None, "strike_expiry": None, "contract": None, "scope": "auto", "venue": "NYSE_BOOK",
         "cols": 6, "book_minutes": 60, "tfs": {"chart": "5", "liquidity": "5", "desk": "5"},
         "pans": {k: {"centre": None, "shift": 0} for k in ("heatmap", "gbs", "vanna", "charm", "migration")}}
    try:
        # a connection begun after the contract's last message: nothing is posted on it yet
        ofs.apply_heartbeat(_status(now, connected_at=_TRADE["ts_recv"] + 1, picks=picks, ranked=["SPY"],
                                    held={**picks, "LEVELONE_EQUITIES": ["SPY"]}))
        _priced_and_traded()
        panels = server._panels(v)
        assert panels["gamma.chart.bars"].feeds_now() == (("SPY", "CHART_EQUITY"),)
        assert panels["gamma.tape"].feeds_now() == ((_SYM, "LEVELONE_OPTIONS"),)
        down = [server._not_live(panels[n], now) for n in ("gamma.chart.bars", "gamma.tape")]
        assert all(down), down
        one_minute = server._panels({**v, "tfs": {**v["tfs"], "chart": "1"}})["gamma.chart.bars"]
        assert one_minute.source == server.DAEMON_SERIES and one_minute.feeds_now() == ()
        # the price levels and the zones are built from the 1-minute bars: marked by CHART_EQUITY too
        levels = server._panels({**v, "view": "levels"})["gamma.levels"]
        assert ("SPY", "CHART_EQUITY") in levels.feeds_now()
        assert any("CHART_EQUITY" in r for r in server._not_live(levels, now))
    finally:
        ofls.clear_symbol(_SYM)
        no_daemon()
