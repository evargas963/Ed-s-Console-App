"""The daemon's status is current at a time only when its stamp is not older than the live
limit (live_market_plane.daemon_status). A stamp after that time is a later moment.

End to end through the real code: the daemon's status (record_feed_heartbeat), Schwab's SPY quote
through the daemon's plane and its price row (record_from_level_one_equity, live_price_rows.price_row),
the pushed option message (streaming._ingest_pushed), the levels producer (server._publish_levels)
and the heatmap route (server.gamma_surface_payload).
Real data: SPY's 2026-11-20 chain captured 2026-09-30 15:31:57 ET
(tests/fixtures/real_spy_2026_11_20_chain_and_quotes.json, fetched at its capture), and
Schwab's LEVELONE_EQUITIES SPY quote and LEVELONE_OPTIONS message for one of the chain's
contracts received 2026-10-05 14:00 CT (tests/fixtures/real_stream_mix_2026_10_05_1400ct.json),
priced and judged a second after that message. The daemon's status is the console's own message, built here
in its shape (no status is captured).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import live_price_rows
import server
from stream_spine import options_quote_msg
from time_et import ET, INDEX_OPTIONS

_FX = Path(__file__).resolve().parent / "fixtures"
_CAPTURE = json.loads((_FX / "real_spy_2026_11_20_chain_and_quotes.json").read_text(encoding="utf-8"))
_LISTED = {c["symbol"] for c in _CAPTURE["chain"]}
_MIX = json.loads((_FX / "real_stream_mix_2026_10_05_1400ct.json").read_text(encoding="utf-8"))["messages"]
_MSG = next(m for m in _MIX if m["service"] == "LEVELONE_OPTIONS" and m["item"]["key"] in _LISTED
            and {"GAMMA", "DELTA", "OPEN_INTEREST", "TOTAL_VOLUME"} & set(m["item"]))
_QUOTE = next(m for m in _MIX if m["service"] == "LEVELONE_EQUITIES" and m["item"]["key"] == "SPY"
              and "LAST_PRICE" in m["item"])
SYM = _MSG["item"]["key"]
TK = server.ticker_storage_key("SPY")
_AT = _MSG["ts_recv"] + 1.0


@pytest.fixture(autouse=True)
def _clean():
    ofls.clear_all_live_state()
    lmp.record_feed_down()
    yield
    ofls.clear_all_live_state()
    lmp.record_feed_down()
    for kept in (lmp._by_ticker, lmp._fields_by_ticker, ofs._price_rows):
        kept.pop(TK, None)
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)
    server._last_feed_stamp = None


def _beat(ts: float, *, socket_open: bool = True, options: "list[str] | None" = None) -> None:
    lmp.record_feed_heartbeat({"ts": ts, "schwab_socket_open": socket_open,
                               "held": {"LEVELONE_EQUITIES": [TK],
                                        "LEVELONE_OPTIONS": [SYM] if options is None else options}})


def _states_when_the_status_was_sent(offset: float) -> list[str]:
    """SPY's chain priced and its heatmap served at `_AT`, the daemon's status stamped `offset`
    seconds from `_AT` (negative: earlier). The states of SYM's heatmap legs."""
    _beat(_AT + offset)
    lmp.record_from_level_one_equity(TK, _QUOTE["item"], received_ts=_QUOTE["ts_recv"])
    row = ofs._price_rows[TK] = live_price_rows.price_row(TK, _AT)
    ofs._ingest_pushed(f"optquote.{SYM}", options_quote_msg(
        symbol=SYM, content=_MSG["item"], src="schwab_options_l1", ts_recv=_MSG["ts_recv"]))
    at = datetime.fromtimestamp(_AT, ET)
    server._publish_levels(TK, [dict(c) for c in _CAPTURE["chain"]], _CAPTURE["capture_ts_utc"],
                           chain_spot=(row["spot"], row["trade_ts"]), now=at)
    body = server.gamma_surface_payload(TK, "all", None, 0, None, None, at)
    return [col[side]["state"] for cell in body["cells"] for col, pair in zip(cell["stream"], cell["contracts"])
            for side in ("call", "put") if col and pair.get(side) == SYM]


@pytest.mark.parametrize("before", [0.001, 0.5, 2.9])
def test_a_status_stamped_before_the_time_judged_keeps_the_streamed_cell_live(before):
    assert _states_when_the_status_was_sent(-before) == ["live"]


@pytest.mark.parametrize("after", [0.001, 0.5, 2.9])
def test_a_status_stamped_after_the_time_judged_is_not_that_time(after):
    """A stamp after `_AT` is not `_AT`. The last price still stands, and the cell is not live."""
    _beat(_AT + after)
    lmp.record_from_level_one_equity(TK, _QUOTE["item"], received_ts=_QUOTE["ts_recv"])
    row = ofs._price_rows[TK] = live_price_rows.price_row(TK, _AT)
    ofs._ingest_pushed(f"optquote.{SYM}", options_quote_msg(
        symbol=SYM, content=_MSG["item"], src="schwab_options_l1", ts_recv=_MSG["ts_recv"]))
    at = datetime.fromtimestamp(_AT, ET)
    server._publish_levels(TK, [dict(c) for c in _CAPTURE["chain"]], _CAPTURE["capture_ts_utc"],
                           chain_spot=(row["spot"], row["trade_ts"]), now=at)
    body = server.gamma_surface_payload(TK, "all", None, 0, None, None, at)
    states = [col[side]["state"] for cell in body["cells"]
              for col, pair in zip(cell["stream"], cell["contracts"])
              for side in ("call", "put") if col and pair.get(side) == SYM]
    assert lmp.daemon_status(_AT) is None
    assert states and "live" not in states


def test_a_streamed_cell_is_not_live_after_its_own_option_close():
    """SPY's chain priced at `_AT` (2026-10-05, regular hours) with SYM streaming: its legs are live.
    At 16:20 ET that day, the feed up and the daemon still holding SYM, SPY's own option market
    (index-close options, 16:15 in Schwab's /markets answer) has closed: no leg reads live, and the
    heatmap's answer does not call itself live."""
    assert _states_when_the_status_was_sent(-0.5) == ["live"]
    after_close = datetime.fromisoformat("2026-10-05T16:20:00-04:00").timestamp()
    _beat(after_close - 0.5)
    server.restamp_open_surfaces(after_close)
    body = server.gamma_surface_payload(TK, "all", None, 0, None, None, datetime.fromtimestamp(after_close, ET))
    states = [col[side]["state"] for cell in body["cells"] for col, pair in zip(cell["stream"], cell["contracts"])
              for side in ("call", "put") if col and pair.get(side) == SYM]
    assert states and "live" not in states
    assert body["live"] is False and body["levels_state"] != "LIVE"


def test_a_status_sent_past_the_live_limit_is_not_current():
    _beat(_AT - lmp.FEED_HEARTBEAT_MAX_AGE_SEC)
    assert lmp.daemon_status(_AT) is None and not lmp.feed_live_for(SYM, "LEVELONE_OPTIONS", _AT, INDEX_OPTIONS)
    _beat(_AT - 1.0)
    assert lmp.feed_live_for(SYM, "LEVELONE_OPTIONS", _AT, INDEX_OPTIONS)


def test_a_closed_socket_keeps_the_last_option_value_and_names_its_time():
    """Schwab's socket drops and the daemon's held set empties: the last streamed gamma stays,
    the cell is stale, and its tooltip carries Schwab's time and the age."""
    _beat(_AT - 0.5)
    lmp.record_from_level_one_equity(TK, _QUOTE["item"], received_ts=_QUOTE["ts_recv"])
    row = ofs._price_rows[TK] = live_price_rows.price_row(TK, _AT)
    ofs._ingest_pushed(f"optquote.{SYM}", options_quote_msg(
        symbol=SYM, content=_MSG["item"], src="schwab_options_l1", ts_recv=_MSG["ts_recv"]))
    ofs._drop_released_options(_AT)
    at = datetime.fromtimestamp(_AT, ET)
    server._publish_levels(TK, [dict(c) for c in _CAPTURE["chain"]], _CAPTURE["capture_ts_utc"],
                           chain_spot=(row["spot"], row["trade_ts"]), now=at)
    with server._terrain_cache_lock:
        gex = [cell["gex"] for cell in server._terrain_cache[TK]["_gamma_surface"]["cells"]]
    kept = ofls.get_stream_greeks(SYM)
    _beat(_AT, socket_open=False, options=[])
    ofs._drop_released_options(_AT)
    server.restamp_open_surfaces(_AT)
    body = server.gamma_surface_payload(TK, "all", None, 0, None, None, at)
    cells = [col for cell in body["cells"] for col, pair in zip(cell["stream"], cell["contracts"])
             if col and (pair.get("call") == SYM or pair.get("put") == SYM)]
    with server._terrain_cache_lock:
        after = [cell["gex"] for cell in server._terrain_cache[TK]["_gamma_surface"]["cells"]]
    assert kept and ofls.get_stream_greeks(SYM) == kept
    assert after == gex
    assert cells and all(col["state"] == "stale" for col in cells)
    title = cells[0]["title"]
    assert title.startswith("this cell has stopped streaming")
    assert "CT" in title and title.endswith("s")


def _et(day: str, hh: int, mm: int = 0) -> float:
    return datetime.fromisoformat(f"{day}T{hh:02d}:{mm:02d}:00").replace(tzinfo=ET).timestamp()


def _all_held(now: float, *tickers: str) -> None:
    """The daemon's status at `now`: the Schwab socket open, every service holding these."""
    lmp.record_feed_heartbeat({"ts": now, "schwab_socket_open": True,
                               "held": {"LEVELONE_EQUITIES": list(tickers), "NYSE_BOOK": list(tickers),
                                        "LEVELONE_OPTIONS": [SYM], "OPTIONS_BOOK": [SYM]}})


@pytest.mark.parametrize("at, equities, options, why", [
    (_et("2026-10-07", 8), True, False, "outside Schwab's option market hours"),  # Pre-Market
    (_et("2026-10-07", 11), True, True, None),                                    # RTH
    (_et("2026-10-07", 17), True, False, "outside Schwab's option market hours"), # After-Hours
    (_et("2026-10-03", 12), False, False, "outside Schwab's market hours"),       # Saturday
    (_et("2026-09-20", 11), False, False, "the market session is unknown"),       # no /markets answer held
])
def test_a_value_is_live_only_while_its_market_trades(at, equities, options, why):
    """The daemon's socket is open and it holds SPY and SYM at every instant (Schwab's /markets
    answers captured 2026-10-07 say which sessions those are): SPY's quote and book are live only
    in a session the stock market trades, SYM's only while an option market is open, and each
    names why not."""
    lmp.record_from_level_one_equity(TK, _QUOTE["item"], received_ts=_QUOTE["ts_recv"])
    _all_held(at, TK)
    assert lmp.feed_live_for(TK, "LEVELONE_EQUITIES", at) is equities
    assert lmp.feed_live_for(TK, "NYSE_BOOK", at) is equities
    assert lmp.feed_live_for(SYM, "LEVELONE_OPTIONS", at, INDEX_OPTIONS) is options      # an SPY option
    assert lmp.feed_live_for(SYM, "OPTIONS_BOOK", at, INDEX_OPTIONS) is options
    assert lmp.outage(TK, "LEVELONE_EQUITIES", at) == (None if equities else why)
    assert lmp.outage(SYM, "LEVELONE_OPTIONS", at, INDEX_OPTIONS) == (None if options else why)
    row = live_price_rows.price_row(TK, at)
    assert (row["feed_live"], row["feed_label"]) == ((True, "LIVE") if equities else (False, "NOT LIVE"))


def test_a_feed_down_in_a_trading_session_reads_offline():
    """Regular hours, the Schwab socket closed: not live, OFFLINE, and the feed is named."""
    at = _et("2026-10-07", 11)
    lmp.record_from_level_one_equity(TK, _QUOTE["item"], received_ts=_QUOTE["ts_recv"])
    _beat(at, socket_open=False)
    row = live_price_rows.price_row(TK, at)
    assert (row["feed_live"], row["feed_label"]) == (False, "OFFLINE")
    assert row["outage"] == "Schwab LEVELONE_EQUITIES feed down during RTH"


def test_a_symbol_the_daemon_does_not_hold_reads_not_live_not_offline():
    """Regular hours, the Schwab socket open, SPY not held on LEVELONE_EQUITIES: the feed is up, so
    the header word is NOT LIVE, and the reason names the symbol, not a feed outage."""
    at = _et("2026-10-07", 11)
    lmp.record_from_level_one_equity(TK, _QUOTE["item"], received_ts=_QUOTE["ts_recv"])
    _all_held(at)
    row = live_price_rows.price_row(TK, at)
    assert (row["feed_live"], row["feed_label"]) == (False, "NOT LIVE")
    assert row["outage"] == f"{TK} is not streamed on Schwab LEVELONE_EQUITIES"


_STATUS = json.loads((_FX / "real_security_status_2026_10_19.json").read_text(encoding="utf-8"))["messages"]


def test_a_symbol_schwab_marks_closed_is_not_live_in_an_open_session():
    """$SPX as Schwab streamed it 2026-10-19: SECURITY_STATUS Normal at the 09:30 open, Closed at
    the 16:00 close. At 17:00 ET (After-Hours, the stock market still trading) $SPX is not live
    and says Schwab marks it Closed. NVDA, Normal from 04:00, is not live at 04:30, before the
    07:00 pre-market Schwab's /markets sent, and live at 07:30."""
    spx_open, spx_close = (m for m in _STATUS if m["symbol"] == "$SPX")
    nvda_normal = next(m for m in _STATUS if m["symbol"] == "NVDA" and m["item"]["SECURITY_STATUS"] == "Normal")
    try:
        lmp.record_from_level_one_equity("$SPX", spx_open["item"], received_ts=spx_open["ts_recv"])
        at = _et("2026-10-19", 10)
        _all_held(at, "$SPX", "NVDA")
        assert lmp.feed_live_for("$SPX", "LEVELONE_EQUITIES", at) is True
        lmp.record_from_level_one_equity("$SPX", spx_close["item"], received_ts=spx_close["ts_recv"])
        at = _et("2026-10-19", 17)
        _all_held(at, "$SPX", "NVDA")
        assert lmp.feed_live_for("$SPX", "LEVELONE_EQUITIES", at) is False
        assert lmp.outage("$SPX", "LEVELONE_EQUITIES", at) == "Schwab marks $SPX Closed"
        assert live_price_rows.price_row("$SPX", at)["feed_label"] == "NOT LIVE"
        lmp.record_from_level_one_equity("NVDA", nvda_normal["item"], received_ts=nvda_normal["ts_recv"])
        at = _et("2026-10-19", 4, 30)
        _all_held(at, "$SPX", "NVDA")
        assert lmp.feed_live_for("NVDA", "LEVELONE_EQUITIES", at) is False
        assert lmp.outage("NVDA", "LEVELONE_EQUITIES", at) == "outside Schwab's market hours"
        at = _et("2026-10-19", 7, 30)
        _all_held(at, "$SPX", "NVDA")
        assert lmp.feed_live_for("NVDA", "LEVELONE_EQUITIES", at) is True
    finally:
        for kept in (lmp._by_ticker, lmp._fields_by_ticker):
            kept.pop("$SPX", None)
            kept.pop("NVDA", None)


def test_the_console_serves_the_daemons_verdict_on_a_price_schwab_marks_closed():
    """The daemon alone holds Schwab's SECURITY_STATUS (its plane); the console holds the daemon's
    price row. At 17:00 ET on 2026-10-19 (After-Hours, the feed up and holding $SPX) the daemon's
    row says NOT LIVE, "Schwab marks $SPX Closed"; served by the console from an empty plane, the
    levels' price mark, the equity book's top and its book, the spot's reason (a row with no price)
    and the not-live refresh (a page open on $SPX is told to read its levels again) say the same."""
    import asyncio

    import push_changes

    spx_close = next(m for m in _STATUS if m["symbol"] == "$SPX" and m["item"]["SECURITY_STATUS"] == "Closed")
    at = _et("2026-10-19", 17)
    try:
        lmp.record_from_level_one_equity("$SPX", spx_close["item"], received_ts=spx_close["ts_recv"])
        _all_held(at, "$SPX")
        row = live_price_rows.price_row("$SPX", at)                  # the daemon's
        for kept in (lmp._by_ticker, lmp._fields_by_ticker):          # the console's plane holds no quote
            kept.pop("$SPX", None)
        ofs._price_rows["$SPX"] = row
        assert (row["feed_label"], row["outage"]) == ("NOT LIVE", "Schwab marks $SPX Closed")
        mark = server.price_mark("$SPX", row["trade_ts"], at)
        assert (mark["spot_feed_live"], mark["spot_feed_label"], mark["spot_outage"]) == (
            False, "NOT LIVE", "Schwab marks $SPX Closed")
        book = server.order_flow_microstructure("$SPX", "NYSE_BOOK", at)
        assert (book["top_feed_label"], book["top_outage"]) == ("NOT LIVE", "Schwab marks $SPX Closed")
        assert book["book_feed_label"] == "NOT LIVE"

        async def told():
            push_changes.bind(asyncio.get_running_loop())
            page = push_changes.subscribe("$SPX")
            try:
                server.refresh_not_live_pages(at)
                return await push_changes.next_changes(page, 0.3)
            finally:
                push_changes.unsubscribe("$SPX", page)
                push_changes.bind(None)
        assert asyncio.run(told()) == {push_changes.LEVELS}
        ofs._price_rows["$SPX"] = {**row, "spot": None}
        assert server.resolve_spot("$SPX", now=at) == (None, "Schwab marks $SPX Closed", None)
    finally:
        ofs._price_rows.pop("$SPX", None)
        for kept in (lmp._by_ticker, lmp._fields_by_ticker):
            kept.pop("$SPX", None)


def test_a_row_the_daemon_no_longer_holds_is_not_live_and_no_row_is_not_live():
    """Regular hours, the feed up. SPY's last row from the daemon said LIVE; the daemon then stops
    holding SPY, so its rows stop. The console serves NOT LIVE with the reason, not the last row's
    LIVE. And before the daemon's first row for a held symbol, the console serves NOT LIVE."""
    at = _et("2026-10-07", 11)
    lmp.record_from_level_one_equity(TK, _QUOTE["item"], received_ts=_QUOTE["ts_recv"])
    _all_held(at, TK)
    ofs._price_rows[TK] = live_price_rows.price_row(TK, at)
    assert ofs._price_rows[TK]["feed_label"] == "LIVE"
    _all_held(at)                                                   # SPY no longer held
    assert ofs.price_state(TK, at) == ("NOT LIVE", f"{TK} is not streamed on Schwab LEVELONE_EQUITIES")
    mark = server.price_mark(TK, None, at)
    assert (mark["spot_feed_live"], mark["spot_feed_label"]) == (False, "NOT LIVE")
    _all_held(at, TK)
    ofs._price_rows.pop(TK, None)                                   # held, no row from the daemon yet
    assert ofs.price_state(TK, at) == ("NOT LIVE", f"no price row from the daemon for {TK} yet")
    assert server.price_mark(TK, None, at)["spot_feed_live"] is False
