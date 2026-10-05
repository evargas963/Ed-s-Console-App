"""/api/levels, /api/options/tape and /api/order-flow/book-heatmap, each from Schwab's captured data
through the real path to the route.

Real data, captured read-only from production (each fixture's `provenance` re-queries its rows): the
capture daemon's record of Schwab's CHART_EQUITY bars, LEVELONE_EQUITIES quotes, LEVELONE_OPTIONS
quotes and NYSE_BOOK / NASDAQ_BOOK books, and the chain sweep's stored chains. The path:
  - streamed messages: stream_spine's builders, the daemon's bus, the push's frames, the console's
    intake (tests/feed_live_helper.deliver_through_push). The daemon's record keeps each message's
    receive time (ts_recv), which the console keeps books and prints by, so the recorded one is
    passed; no receive time is asserted.
  - the price: Schwab's item into the daemon's handler (capture._publisher), its bus, the daemon's
    price-row plane (live_ui.LiveUiServer.ingest) and row (live_price_rows.price_row), as the
    console's push intake keeps it (feed_live_helper.publish_daemon_rows).
  - bars: the daemon's writer, the console's startup load (server._load_bars); levels at a given
    time (server._publish_price_levels / levels_payload take `now`).
  - chains: the sweep's writer, the producer's stored-capture path (server._price_chain STORED).
Expected values are Schwab's fields as sent, or a derived value by the definition cited where it is
computed here."""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime

import pytest

import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import server
from app.market_data.schwab.streaming import capture
from app.market_data.schwab.streaming.live_ui import LiveUiServer
from app.options.order_flow.history import BOOKS, TAPE
from instrument_identity import ticker_storage_key
from stream_spine import LATEST, HealthRegistry, MessageBus, book_msg, options_quote_msg
from tests.feed_live_helper import (daemon_bars, deliver_through_push, fixture_rows, forget_chain_captures,
                                    forget_daemon_bars, mark_feed_live, publish_daemon_rows, record_daemon_bars,
                                    schwab_rth_bars, store_chain_capture, vwap_by_definition)
from time_et import ET

_OPTION_QUOTES = {f: fixture_rows(f) for f in ("real_daemon_option_quotes_spy_2026_10_02.json",
                                                 "real_daemon_option_quotes_tsla_2026_10_02.json")}
_BOOKS = {f: fixture_rows(f) for f in ("real_daemon_books_spy_2026_10_02.json", "real_daemon_books_tsla_2026_10_02.json",
                                         "real_daemon_books_iwm_2026_09_28.json")}
_EQUITY_QUOTES = fixture_rows("real_daemon_equity_quotes_spy_tsla_2026_10_02.json")
_CAPTURES = fixture_rows("real_chain_captures_spy_tsla_2027_03_19_2026_10_02_close.json")
_BARS = (daemon_bars("real_daemon_bars_spy_tsla_spx_2026_10_01_02.json")
         + fixture_rows("real_daemon_bars_ndx_vix_2026_10_01.json"))


# ── /api/options/tape ─────────────────────────────────────────────────────────────────────────

def _tape_by_definition(rows: list[dict]) -> list[dict]:
    """The prints in Schwab's LEVELONE_OPTIONS messages, newest first, each with Schwab's fields.
    LEVELONE_OPTIONS is a "Change" service: only fields that changed are streamed (Streamer Guide
    §1.1, §1.5), so each field is the last value sent. Schwab sends no trade id (the Guide lists no
    time-and-sales service), so a print is a new (TRADE_TIME_MILLIS, LAST_PRICE, LAST_SIZE) last-trade
    triple (l1_trade_observation). Premium = LAST_PRICE x LAST_SIZE x MULTIPLIER (the producer's
    definition, history._print_row; its source is NOT_PROVEN)."""
    state: dict = {}
    prev = None
    out = []
    for r in rows:
        state.update(r["native"])
        triple = (state.get("TRADE_TIME_MILLIS"), state.get("LAST_PRICE"), state.get("LAST_SIZE"))
        if triple[1] is None or triple == prev:
            continue
        prev = triple
        out.append({
            "symbol": r["symbol"], "underlying": state["UNDERLYING"],
            "expiry": f"{state['EXPIRATION_YEAR']:04d}-{state['EXPIRATION_MONTH']:02d}-{state['EXPIRATION_DAY']:02d}",
            "type": {"C": "CALL", "P": "PUT"}[state["CONTRACT_TYPE"]], "strike": state["STRIKE_TYPE"],
            "bid": state.get("BID_PRICE"), "bid_size": state.get("BID_SIZE"),
            "ask": state.get("ASK_PRICE"), "ask_size": state.get("ASK_SIZE"),
            "trade": state["LAST_PRICE"], "size": state.get("LAST_SIZE"),
            "premium": state["LAST_PRICE"] * state["LAST_SIZE"] * state["MULTIPLIER"],
            "volume": state.get("TOTAL_VOLUME"), "oi": state.get("OPEN_INTEREST"),
            "iv": state.get("VOLATILITY"), "delta": state.get("DELTA"), "multiplier": state.get("MULTIPLIER"),
        })
    return out[::-1]


@pytest.mark.parametrize("name", sorted(_OPTION_QUOTES))
def test_options_tape_serves_schwab_prints_as_sent(name):
    rows = _OPTION_QUOTES[name]
    contract = rows[0]["symbol"]
    tk = rows[0]["native"]["UNDERLYING"]
    TAPE.forget(contract)
    try:
        before = json.loads(server.get_options_tape(ticker=tk, contract=contract, limit=500).body)
        deliver_through_push([(f"optquote.{contract}", options_quote_msg(
            symbol=contract, content=r["native"], src=r["src"], ts_recv=r["ts_recv"], schwab_ts=r["schwab_ts"]))
            for r in rows])
        body = json.loads(server.get_options_tape(ticker=tk, contract=contract, limit=500).body)
    finally:
        TAPE.forget(contract)
    # absent before Schwab sent a print, with the reason
    assert (before["available"], before["rows"]) == (False, [])
    assert before["reason"] == "no trade prints for the selected contract(s) since the console started"
    want = _tape_by_definition(rows)
    assert len(want) > 1
    assert body["available"] is True and body["symbols"] == [contract]
    assert [{k: row[k] for k in want[0]} for row in body["rows"]] == want


# ── /api/order-flow/book-heatmap ──────────────────────────────────────────────────────────────

def _levels(book: dict) -> set[tuple]:
    """A Schwab book's levels as (price, side, size): BID_PRICE / ASK_PRICE with TOTAL_VOLUME."""
    return ({(lvl["BID_PRICE"], "bid", lvl["TOTAL_VOLUME"]) for lvl in book.get("BIDS") or []}
            | {(lvl["ASK_PRICE"], "ask", lvl["TOTAL_VOLUME"]) for lvl in book.get("ASKS") or []})


_VENUES = sorted({(f, r["symbol"], r["service"]) for f, rows in _BOOKS.items() for r in rows})


@pytest.mark.parametrize("name, tk, venue", _VENUES, ids=[f"{tk}-{v}" for _f, tk, v in _VENUES])
def test_book_heatmap_serves_schwab_book_levels_as_sent(name, tk, venue):
    """Every cell is a price and size Schwab sent in that venue's books; the newest book Schwab sent
    is in the newest column, every level at Schwab's size (a book is delivered whole: Streamer Guide
    §1.1, §1.5); the served price range is the range of the cells. A venue Schwab sent nothing on
    is absent with its reason. NYSE_BOOK runs on SPY and IWM; DELL (2,999 regular-hours receipts),
    XLE (54) and KO (13, outside regular hours) are the other NYSE_BOOK tickers recorded since
    2026-09-28."""
    rows = [r for r in _BOOKS[name] if r["symbol"] == tk and r["service"] == venue]
    others = sorted({"NYSE_BOOK", "NASDAQ_BOOK"} - {r["service"] for r in _BOOKS[name] if r["symbol"] == tk})
    BOOKS.forget(tk)
    try:
        deliver_through_push([(f"book.{tk}", book_msg(symbol=tk, service=venue, content=r["native"], src=r["src"],
                                                      ts_recv=r["ts_recv"], schwab_ts=r["schwab_ts"])) for r in rows])
        body = json.loads(server.get_order_flow_book_heatmap(ticker=tk, venue=venue, minutes=5).body)
        absent = {v: json.loads(server.get_order_flow_book_heatmap(ticker=tk, venue=v, minutes=5).body) for v in others}
    finally:
        BOOKS.forget(tk)
    sent = set().union(*(_levels(r["native"]) for r in rows))
    newest = _levels([r for r in rows if _levels(r["native"])][-1]["native"])
    assert body["available"] is True and body["venue"] == venue
    served = {(c["price"], side, c[side]) for c in body["cells"] for side in ("bid", "ask") if c[side] is not None}
    assert served and served <= sent
    last = max(c["t"] for c in body["cells"])
    in_last = {(c["price"], side, c[side]) for c in body["cells"] if c["t"] == last for side in ("bid", "ask")}
    assert newest <= in_last
    prices = [c["price"] for c in body["cells"]]
    assert (body["price_min"], body["price_max"]) == (min(prices), max(prices))
    for v, a in absent.items():
        assert (a["available"], a["reason"]) == (False, f"no {v} book with a price level since the console started")


# ── /api/levels ───────────────────────────────────────────────────────────────────────────────

NOW = datetime(2026, 10, 2, 17, 0, tzinfo=ET)        # the levels are asked for after 2026-10-02's close
INDEXES = ("$SPX", "$NDX", "$VIX")


def _forget_ticker(tk: str) -> None:
    key = ticker_storage_key(tk)
    server._bars.pop(key, None)
    ofs._price_rows.pop(key, None)
    lmp._by_ticker.pop(key, None)
    lmp._fields_by_ticker.pop(key, None)


@pytest.fixture
def published():
    """The console after Schwab's captured data arrives: the recorded bars loaded (SPY, TSLA and the
    indexes), 2026-10-02's last chain sweep of SPY and TSLA priced, and the last quotes of
    2026-10-02's session made the daemon's price rows."""
    tickers = ("SPY", "TSLA", *INDEXES)
    for tk in tickers:
        _forget_ticker(tk)
    forget_chain_captures(_CAPTURES)
    record_daemon_bars(_BARS)
    try:
        server._load_bars()
        for row in _CAPTURES:
            store_chain_capture(row)
            server._price_chain(row["ticker"], server.STORED, None, None)
        bus = MessageBus()
        ui = LiveUiServer(bus, heartbeat_fn=lambda: {}, stats={})
        sub = bus.subscribe("quote.", policy=LATEST)
        handler = capture._publisher("LEVELONE_EQUITIES", bus, HealthRegistry())

        async def quotes():
            for r in _EQUITY_QUOTES:
                handler({"service": "LEVELONE_EQUITIES", "timestamp": r["schwab_ts"], "command": "SUBS",
                         "content": [r["native"]]})
                while sub.changed:
                    ui.ingest((await sub.get())[1])
        asyncio.run(quotes())
        for tk in tickers:
            server._publish_price_levels(tk, NOW)
        yield
    finally:
        forget_daemon_bars(_BARS)
        forget_chain_captures(_CAPTURES)
        for tk in tickers:
            _forget_ticker(tk)


def _levels_now(tk: str) -> dict:
    mark_feed_live(tk)                        # induced: the daemon's heartbeat holding the ticker
    publish_daemon_rows(tk)
    return server.levels_payload(ticker_storage_key(tk), "1", NOW)


@pytest.mark.parametrize("tk", ["SPY", "TSLA"])
def test_levels_serve_schwab_price_and_the_producers_levels(published, tk):
    body = _levels_now(tk)
    last = [r["native"] for r in _EQUITY_QUOTES if r["symbol"] == tk and "LAST_PRICE" in r["native"]][-1]
    # the live price: Schwab's LAST_PRICE as sent, at Schwab's TRADE_TIME_MILLIS
    assert (body["spot"], body["spot_as_of_ts_utc"]) == (last["LAST_PRICE"], last["TRADE_TIME_MILLIS"] / 1000)
    by_id = {r["id"]: r for r in body["levels"]}
    # session VWAP and its bands over the minutes of 2026-10-02 the daemon recorded, and the curve
    want = vwap_by_definition(schwab_rth_bars(_BARS, tk, NOW.date()))
    assert [p[0] for p in body["vwap_series"]] == [p[0] for p in want]
    for got, exp in zip(body["vwap_series"], want):
        assert got[1:] == pytest.approx(exp[1:], abs=1e-4)
    for lid, i in (("VWAP", 1), ("VWAP_P1", 2), ("VWAP_M1", 3), ("VWAP_P2", 4), ("VWAP_M2", 5)):
        assert by_id[lid]["price"] == pytest.approx(want[-1][i], abs=1e-4), lid
    # the gamma levels carried from the levels producer's publication, as it published them
    terrain = server.terrain_cache_get(ticker_storage_key(tk))
    carried = [gid for gid, _label in server.GAMMA_LEVELS if terrain.get(gid) is not None]
    assert carried
    for gid in carried:
        assert by_id[gid]["price"] == terrain[gid] and by_id[gid]["provenance"]["carried"] is True
    # each level's distance from Schwab's price
    for r in body["levels"]:
        assert r["distance"] == r["price"] - body["spot"], r["id"]


@pytest.mark.parametrize("index", INDEXES)
def test_levels_say_why_an_index_has_no_session_vwap(published, index):
    """Schwab sends each index's CHART_EQUITY bars with volume 0 (a reported 0, AGENTS.md rule 2),
    so its session has bars and no VWAP, served absent with the reason."""
    assert all(b["volume"] == 0 for b in schwab_rth_bars(_BARS, index, date(2026, 10, 1)))
    at = datetime(2026, 10, 1, 17, 0, tzinfo=ET)
    server._publish_price_levels(index, at)
    body = server.levels_payload(ticker_storage_key(index), "1", at)
    assert body["levels"] and "VWAP" not in {r["id"] for r in body["levels"]}
    assert {"family": "vwap", "reason": "no RTH volume for session VWAP in available bars"} in body["families_absent"]


def test_levels_of_a_ticker_schwab_sent_nothing_for_are_absent_with_the_reason(published):
    """Induced: a symbol never streamed has no levels, said with the reason."""
    none = server.levels_payload("ZZNEVERSENT", "1", NOW)
    assert none["levels"] == [] and none["spot"] is None
    assert {"family": "price_levels", "reason": server.NO_PRICE_LEVELS_REASON} in none["families_absent"]
