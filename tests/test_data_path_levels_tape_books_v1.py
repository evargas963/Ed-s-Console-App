"""/api/levels, /api/options/tape and /api/order-flow/book-heatmap, each from Schwab's captured data
through the real path to the route, SPY and TSLA.

Real data, captured read-only from production (each fixture's `provenance`): the capture daemon's
record of Schwab's CHART_EQUITY bars, LEVELONE_EQUITIES quotes, LEVELONE_OPTIONS quotes and
NYSE_BOOK / NASDAQ_BOOK books, and the chain sweep's stored chains. The path:
  - streamed messages: the daemon's message builders (stream_spine) on the daemon's bus
    (MessageBus, the LATEST reader the push serves), the push's wire frames (live_push.frames),
    the console's intake (streaming._ingest_pushed). The daemon's record keeps each message's
    receive time (ts_recv), which the books and the tape are kept by, so the recorded one is used.
  - the price: Schwab's item into the daemon's handler (capture._publisher), its bus, the daemon's
    price-row plane (live_ui.LiveUiServer.ingest), the daemon's row (live_price_rows.price_row) as
    the console's push intake keeps it (tests/feed_live_helper.publish_daemon_rows).
  - bars: the daemon's writer, the console's startup load (server._load_bars); levels at a given
    time (server._publish_price_levels / levels_payload take `now`).
  - chains: the sweep's writer (persist_complete_chain_capture), the producer's stored-capture path
    (server._price_chain STORED).
Expected values are Schwab's fields as sent, or for a derived value the definition its producer
states, computed here from the captured data."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

import app.options.order_flow.streaming as ofs
import live_market_plane as lmp
import server
from app.market_data.schwab.streaming import capture, live_push
from app.market_data.schwab.streaming.live_ui import LiveUiServer
from app.options.order_flow.history import BOOKS, TAPE
from calibration.complete_chain_capture import ensure_schema, persist_complete_chain_capture
from db import get_db
from instrument_identity import ticker_storage_key
from stream_spine import LATEST, HealthRegistry, MessageBus, book_msg, options_quote_msg
from tests.feed_live_helper import (daemon_bars, forget_daemon_bars, mark_feed_live, publish_daemon_rows,
                                    record_daemon_bars)
from time_et import ET

_FX = Path(__file__).resolve().parent / "fixtures"


def _rows(name: str) -> list[dict]:
    return json.loads((_FX / name).read_text(encoding="utf-8"))["rows"]


_OPTION_QUOTES = _rows("real_daemon_option_quotes_spy_tsla_2026_10_02.json")
_BOOKS = _rows("real_daemon_books_spy_tsla_2026_10_02.json")
_EQUITY_QUOTES = _rows("real_daemon_equity_quotes_spy_tsla_2026_10_02.json")
_CAPTURES = _rows("real_chain_captures_spy_tsla_2027_03_19_on_2026_10_01_02.json")
_BARS = daemon_bars("real_daemon_bars_spy_tsla_spx_2026_10_01_02.json")


# ── the daemon's bus and push, to the console's intake ─────────────────────────────────────────

async def _through_push(msgs: list[tuple[str, dict]]) -> list[dict]:
    """Each message published on the daemon's bus, then every record its LATEST reader hands the
    push, as wire frames."""
    bus = MessageBus()
    sub = bus.subscribe("", policy=LATEST)
    frames = []
    for topic, msg in msgs:
        bus.publish(topic, msg)
        while sub.changed:
            t, record = await sub.get()
            if live_push.is_forwarded(t, record):
                frames.extend(json.loads(f) for f in live_push.frames(t, record))
    return frames


def _deliver(msgs: list[tuple[str, dict]]) -> None:
    for frame in asyncio.run(_through_push(msgs)):
        ofs._ingest_pushed(frame["topic"], frame["msg"])


# ── /api/options/tape ─────────────────────────────────────────────────────────────────────────

def _tape_by_definition(rows: list[dict]) -> list[dict]:
    """The options tape from Schwab's LEVELONE_OPTIONS messages: Schwab sends a field only when it
    changes, so each field is the last value sent; a print is a new (TRADE_TIME_MILLIS, LAST_PRICE,
    LAST_SIZE) last-trade triple; premium = LAST_PRICE x LAST_SIZE x MULTIPLIER; the trade placed
    against the same record's BID_PRICE / ASK_PRICE. Newest first."""
    state: dict = {}
    prev = None
    out = []
    for r in rows:
        state.update(r["native"])
        if "LAST_PRICE" not in state:
            continue
        triple = (state.get("TRADE_TIME_MILLIS"), state["LAST_PRICE"], state.get("LAST_SIZE"))
        if triple == prev:
            continue
        prev = triple
        trade, size, bid, ask, mult = (state["LAST_PRICE"], state.get("LAST_SIZE"), state.get("BID_PRICE"),
                                       state.get("ASK_PRICE"), state.get("MULTIPLIER"))
        where = ("unknown" if bid is None or ask is None else
                 "at_bid" if trade == bid else "outside_spread_low" if trade < bid else
                 "at_ask" if trade == ask else "outside_spread_high" if trade > ask else "inside_spread")
        out.append({
            "ts_recv": r["ts_recv"], "symbol": r["symbol"], "underlying": state["UNDERLYING"],
            "expiry": f"{state['EXPIRATION_YEAR']:04d}-{state['EXPIRATION_MONTH']:02d}-{state['EXPIRATION_DAY']:02d}",
            "type": {"C": "CALL", "P": "PUT"}[state["CONTRACT_TYPE"]], "strike": state["STRIKE_TYPE"],
            "bid": bid, "bid_size": state.get("BID_SIZE"), "ask": ask, "ask_size": state.get("ASK_SIZE"),
            "trade": trade, "size": size, "premium": trade * size * mult,
            "volume": state.get("TOTAL_VOLUME"), "oi": state.get("OPEN_INTEREST"),
            "iv": state.get("VOLATILITY"), "delta": state.get("DELTA"), "multiplier": mult,
            "classification": where,
        })
    return out[::-1]


@pytest.mark.parametrize("contract", sorted({r["symbol"] for r in _OPTION_QUOTES}))
def test_options_tape_serves_schwab_prints_as_sent(contract):
    rows = [r for r in _OPTION_QUOTES if r["symbol"] == contract]
    tk = rows[0]["native"]["UNDERLYING"]
    TAPE.forget(contract)
    try:
        before = json.loads(server.get_options_tape(ticker=tk, contract=contract, limit=500).body)
        _deliver([(f"optquote.{contract}", options_quote_msg(
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
    assert body["rows"] == want


# ── /api/order-flow/book-heatmap ──────────────────────────────────────────────────────────────

def _levels(book: dict, leaf: str, price: str) -> list[tuple]:
    return [(lvl[price], lvl["TOTAL_VOLUME"]) for lvl in book.get(leaf) or []]


@pytest.mark.parametrize("tk, venue", sorted({(r["symbol"], r["service"]) for r in _BOOKS}))
def test_book_heatmap_serves_schwab_book_levels_as_sent(tk, venue):
    """Every cell is a price and size Schwab sent in that venue's book; the newest book's every
    level is in the newest column at Schwab's size; the window ends at the newest book Schwab sent
    (one kept per second). The other venue, never sent here, is absent with its reason."""
    rows = [r for r in _BOOKS if r["symbol"] == tk and r["service"] == venue]
    other = {"NYSE_BOOK": "NASDAQ_BOOK", "NASDAQ_BOOK": "NYSE_BOOK"}[venue]
    BOOKS.forget(tk)
    try:
        _deliver([(f"book.{tk}", book_msg(symbol=tk, service=venue, content=r["native"], src=r["src"],
                                          ts_recv=r["ts_recv"], schwab_ts=r["schwab_ts"])) for r in rows])
        body = json.loads(server.get_order_flow_book_heatmap(ticker=tk, venue=venue, minutes=5).body)
        absent = json.loads(server.get_order_flow_book_heatmap(ticker=tk, venue=other, minutes=5).body)
    finally:
        BOOKS.forget(tk)
    per_second = {}
    for r in rows:
        if r["native"].get("BIDS") or r["native"].get("ASKS"):
            per_second[int(r["ts_recv"])] = r
    kept = [per_second[s] for s in sorted(per_second)]
    newest = kept[-1]["native"]
    sent = {(px, side, v) for r in kept for side, leaf, price in (("bid", "BIDS", "BID_PRICE"), ("ask", "ASKS", "ASK_PRICE"))
            for px, v in _levels(r["native"], leaf, price)}
    assert body["available"] is True and body["venue"] == venue
    assert (body["since_ts"], body["until_ts"], body["rows_scanned"]) == (kept[0]["ts_recv"], kept[-1]["ts_recv"], len(kept))
    served = {(c["price"], side, c[side]) for c in body["cells"] for side in ("bid", "ask") if c[side] is not None}
    assert served <= sent
    last = max(c["t"] for c in body["cells"])
    in_last = {(c["price"], side): c[side] for c in body["cells"] if c["t"] == last for side in ("bid", "ask")}
    for side, leaf, price in (("bid", "BIDS", "BID_PRICE"), ("ask", "ASKS", "ASK_PRICE")):
        for px, v in _levels(newest, leaf, price):
            assert in_last[(px, side)] == v, (px, side)
    prices = [px for px, _s, _v in sent]
    assert (body["price_min"], body["price_max"]) == (min(prices), max(prices))
    assert (absent["available"], absent["reason"]) == (
        False, f"no {other} book with a price level since the console started")


# ── /api/levels ───────────────────────────────────────────────────────────────────────────────

NOW = datetime(2026, 10, 2, 17, 0, tzinfo=ET)        # the levels are asked for after 2026-10-02's close


def _schwab_rth(symbol: str, day) -> list[dict]:
    """Schwab's newest bar of each regular-session minute of `day`, as the daemon recorded them."""
    newest = {}
    for r in sorted(_BARS, key=lambda r: r["ts_recv"]):
        if r["symbol"] == symbol:
            newest[r["bar_start_ms"]] = r
    out = []
    for ms, r in sorted(newest.items()):
        t = datetime.fromtimestamp(ms / 1000, ET)
        if t.date() == day and (9, 30) <= (t.hour, t.minute) < (16, 0):
            out.append(r)
    return out


def _vwap_by_definition(bars: list[dict]) -> list[list]:
    """liquidity_value_engine.compute_session_vwap_series's stated definition: running
    sum(tp * v) / sum(v), tp = (high + low + close) / 3, with +-1 and +-2 standard deviations."""
    out, tpv, v, tp2v = [], 0.0, 0.0, 0.0
    for b in bars:
        if b["volume"] is None:
            continue
        tp = (b["high"] + b["low"] + b["close"]) / 3.0
        tpv, v, tp2v = tpv + tp * b["volume"], v + b["volume"], tp2v + tp * tp * b["volume"]
        if v > 0:
            w = tpv / v
            sd = max(0.0, tp2v / v - w * w) ** 0.5
            out.append([b["bar_start_ms"] / 1000, w, w + sd, w - sd, w + 2 * sd, w - 2 * sd])
    return out


def _forget_ticker(tk: str) -> None:
    key = ticker_storage_key(tk)
    server._bars.pop(key, None)
    ofs._price_rows.pop(key, None)
    lmp._by_ticker.pop(key, None)
    lmp._fields_by_ticker.pop(key, None)
    with server._terrain_cache_lock:
        server._terrain_cache.pop(key, None)
    with sqlite3.connect(str(get_db().db_path)) as con:
        ensure_schema(con)
        con.executemany("DELETE FROM complete_chain_captures WHERE ticker=? AND ts_utc=?",
                        [(key, r["ts_utc"]) for r in _CAPTURES if r["ticker"] == key])


@pytest.fixture
def published():
    """SPY and TSLA as the console holds them after Schwab's captured data arrives: the recorded
    bars loaded, 2026-10-02's last chain capture priced, and the last quotes of 2026-10-02's
    session made the daemon's price rows."""
    tickers = ("SPY", "TSLA", "$SPX")
    for tk in tickers:
        _forget_ticker(tk)
    record_daemon_bars(_BARS)
    try:
        server._load_bars()
        for row in _CAPTURES:
            if row["ts_utc"] == max(r["ts_utc"] for r in _CAPTURES if r["ticker"] == row["ticker"]):
                assert persist_complete_chain_capture(
                    get_db().db_path, ticker=row["ticker"], expiry=row["expiry"], contracts=row["chain"],
                    spot=row["spot"], completeness_basis=row["completeness_basis"], ts_utc=row["ts_utc"],
                    source=row["source"])["status"] == "written"
                server._price_chain(row["ticker"], server.STORED, None, None)
        bus, ui = MessageBus(), None
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
        for tk in tickers:
            _forget_ticker(tk)


def _levels_now(tk: str) -> dict:
    mark_feed_live(tk)                        # the daemon's heartbeat holding the ticker
    publish_daemon_rows(tk)
    return server.levels_payload(ticker_storage_key(tk), "1", NOW)


@pytest.mark.parametrize("tk", ["SPY", "TSLA"])
def test_levels_serve_schwab_price_and_the_producers_levels(published, tk):
    body = _levels_now(tk)
    last = [r["native"] for r in _EQUITY_QUOTES if r["symbol"] == tk and "LAST_PRICE" in r["native"]][-1]
    # the live price: Schwab's LAST_PRICE as sent, at Schwab's TRADE_TIME_MILLIS
    assert (body["spot"], body["spot_as_of_ts_utc"]) == (last["LAST_PRICE"], last["TRADE_TIME_MILLIS"] / 1000)
    by_id = {r["id"]: r for r in body["levels"]}
    # session VWAP and its bands (2026-10-02, the minutes the daemon recorded), the served curve
    want = _vwap_by_definition(_schwab_rth(tk, NOW.date()))
    assert [p[0] for p in body["vwap_series"]] == [p[0] for p in want]
    for got, exp in zip(body["vwap_series"], want):
        assert got[1:] == pytest.approx(exp[1:], abs=1e-4)
    for lid, i in (("VWAP", 1), ("VWAP_P1", 2), ("VWAP_M1", 3), ("VWAP_P2", 4), ("VWAP_M2", 5)):
        assert by_id[lid]["price"] == pytest.approx(want[-1][i], abs=1e-4), lid
    # the prior session's high, low and close (2026-10-01's regular-session bars)
    prior = _schwab_rth(tk, datetime(2026, 10, 1).date())
    assert (by_id["PDH"]["price"], by_id["PDL"]["price"], by_id["PDC"]["price"]) == (
        max(b["high"] for b in prior), min(b["low"] for b in prior), prior[-1]["close"])
    # the gamma levels carried from the levels producer's publication, as it published them
    terrain = server.terrain_cache_get(ticker_storage_key(tk))
    carried = [gid for gid, _label in server.GAMMA_LEVELS if terrain.get(gid) is not None]
    assert carried
    for gid in carried:
        assert by_id[gid]["price"] == terrain[gid] and by_id[gid]["provenance"]["carried"] is True
    # each level's distance from Schwab's price
    for r in body["levels"]:
        assert r["distance"] == r["price"] - body["spot"], r["id"]


def test_levels_say_why_a_value_is_absent(published):
    """$SPX: Schwab sends its bars with volume 0, so there is no session VWAP, said with the reason.
    A ticker Schwab sent nothing for (induced: a symbol never streamed) has no levels, with the
    reason."""
    spx = _levels_now("$SPX")
    assert "VWAP" not in {r["id"] for r in spx["levels"]}
    assert {"family": "vwap", "reason": "no RTH volume for session VWAP in available bars"} in spx["families_absent"]
    none = server.levels_payload("ZZNEVERSENT", "1", NOW)
    assert none["levels"] == [] and none["spot"] is None
    assert {"family": "price_levels", "reason": server.NO_PRICE_LEVELS_REASON} in none["families_absent"]
