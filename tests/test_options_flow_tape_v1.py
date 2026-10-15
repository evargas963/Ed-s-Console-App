"""app.options.order_flow.history.RecentTape (the Options Flow tape, in the console's memory):
discrete TRADE prints built from each contract's record (option_ledger: its terms from the chain,
each LEVELONE_OPTIONS message posted to it) as the console's intake hands it.
Locked to the operator's own required schema: Time/Symbol/Expiry/Type/Strike/Bid x Size/Ask x
Size/Trade/Size/Premium/Volume/OI/IV/Delta, with Trade/Size/Time/Bid/Ask/BidSize/AskSize/Volume/
OI/IV/Delta read verbatim (never derived) and Premium = Trade x Size x native Multiplier. No
aggressor-side (buy/sell) classification is ever produced -- `classification` states only where
a print landed relative to that SAME tick's own bid/ask."""
from __future__ import annotations

import option_ledger
from app.options.order_flow.history import RecentTape
from stream_spine import MessageBus, current_key

SYM = "SPY   260918C00600000"
#: the contract's terms and open interest, as its record opens from the chain (option_ledger.opening;
#: the stream's open interest is not posted)
_TERMS = {"symbol": SYM, "strikePrice": 600.0, "putCall": "CALL", "openInterest": 901,
          "expirationDate": "2026-09-18T20:00:00.000+00:00", "multiplier": 100.0, "ticker": "SPY"}


def _tape(rows: list[tuple[float, dict]], sym: str = SYM) -> RecentTape:
    """A fresh tape fed `sym`'s record on the daemon's bus after each (ts_recv, LEVELONE_OPTIONS
    item) is posted to it, as the console's intake hands it (each field the newest Schwab sent,
    with the time of the message that sent it). STAND-IN: each message's Schwab time is its
    receive time."""
    tape, bus = RecentTape(), MessageBus()
    bus.publish(*option_ledger.posting(sym, {**_TERMS, "symbol": sym}, 1, 0.5))
    for ts_recv, item in rows:
        ms = int(ts_recv * 1000)
        topic, msg = option_ledger.posting(sym, option_ledger.from_stream(item, ms), ms, ts_recv)
        bus.publish(topic, msg)
        record = bus.current[current_key(topic, msg)][1]
        tape.record_option(sym, record["fields"], record["field_ts"], ts_recv)
    return tape


def _full_context(**overrides) -> dict:
    return {"key": SYM, **overrides}


def test_a_genuine_trade_print_is_shaped_to_the_operators_exact_schema():
    tape = _tape([
        (1000.0, _full_context(TRADE_TIME_MILLIS=999000, LAST_PRICE=1.18, LAST_SIZE=1,
                                BID_PRICE=1.17, BID_SIZE=187, ASK_PRICE=1.19, ASK_SIZE=180,
                                TOTAL_VOLUME=70984, VOLATILITY=7.16, DELTA=0.357)),
    ])
    rows = tape.rows(SYM, 50)
    assert len(rows) == 1
    r = rows[0]
    assert r["symbol"] == SYM and r["underlying"] == "SPY"
    assert r["expiry"] == "2026-09-18" and r["type"] == "CALL" and r["strike"] == 600
    assert r["bid"] == 1.17 and r["bid_size"] == 187
    assert r["ask"] == 1.19 and r["ask_size"] == 180
    assert r["price"] == 1.18 and r["size"] == 1
    assert r["premium"] == 1.18 * 1 * 100
    assert r["volume"] == 70984 and r["oi"] == 901 and r["iv"] == 7.16 and r["delta"] == 0.357
    assert r["classification"] == "inside_spread"


def test_a_re_emitted_duplicate_of_the_same_trade_is_not_counted_twice():
    """The vendor re-sends the SAME (TRADE_TIME_MILLIS, LAST_PRICE, LAST_SIZE) trade
    alongside an unrelated field update (e.g. a fresh Greek recompute) -- this must collapse
    to ONE tape row, not one per re-emission."""
    tick = _full_context(TRADE_TIME_MILLIS=999000, LAST_PRICE=1.18, LAST_SIZE=1,
                         BID_PRICE=1.17, ASK_PRICE=1.19, TOTAL_VOLUME=70984)
    tape = _tape([
        (1000.0, tick),
        (1005.0, dict(tick, DELTA=0.360)),   # same trade, only a Greek changed
        (1010.0, dict(tick, VOLATILITY=7.2)),
    ])
    assert len(tape.rows(SYM, 50)) == 1


def test_a_partial_update_with_size_but_no_price_never_produces_a_null_trade_row():
    """Reproduced against real captured data (SPY 260909C00767000): a partial
    LEVELONE_OPTIONS tick can carry a fresh LAST_SIZE with NO LAST_PRICE on the same packet (a
    size-only field bumping TOTAL_VOLUME on its own). A trade print requires its OWN price AND
    its OWN trade timestamp on the SAME tick; this shape is excluded."""
    tape = _tape([
        (1000.0, _full_context(TRADE_TIME_MILLIS=999000, LAST_PRICE=0.01, LAST_SIZE=1,
                                BID_PRICE=0.0, ASK_PRICE=0.01, TOTAL_VOLUME=108925)),
        # partial: LAST_SIZE bumped, no LAST_PRICE, no TRADE_TIME_MILLIS at all
        (1002.0, {"key": SYM, "LAST_SIZE": 2, "TOTAL_VOLUME": 108926}),
    ])
    rows = tape.rows(SYM, 50)
    assert len(rows) == 1, "the size-only partial must not be counted as a second trade print"
    assert all(r["price"] is not None for r in rows), "no row may ever report price=None"


def test_context_is_carried_forward_from_the_most_recent_full_tick():
    """The vendor does not repeat expiry/strike/type/multiplier on every partial update --
    a LATER genuine trade print that arrives on a tick carrying ONLY price/size/bid/ask
    must still resolve its own contract identity from the most recent tick that reported
    it, not read as if that identity were unknown."""
    tape = _tape([
        (1000.0, _full_context(TRADE_TIME_MILLIS=999000, LAST_PRICE=1.18, LAST_SIZE=1,
                                BID_PRICE=1.17, ASK_PRICE=1.19)),
        # a later genuine trade with NO strike/type/expiry/multiplier fields on this tick
        (2000.0, {"key": SYM, "TRADE_TIME_MILLIS": 1999000, "LAST_PRICE": 1.25, "LAST_SIZE": 3,
                  "BID_PRICE": 1.24, "ASK_PRICE": 1.26}),
    ])
    rows = tape.rows(SYM, 50)
    assert len(rows) == 2
    newest = rows[0]   # newest-first
    assert newest["price"] == 1.25 and newest["size"] == 3
    assert newest["expiry"] == "2026-09-18" and newest["type"] == "CALL" and newest["strike"] == 600


def test_classification_at_bid_at_ask_and_outside_spread_are_mechanical_not_aggressor():
    tape = _tape([
        (1000.0, _full_context(TRADE_TIME_MILLIS=1000, LAST_PRICE=1.17, LAST_SIZE=1, BID_PRICE=1.17, ASK_PRICE=1.19)),
        (1001.0, _full_context(TRADE_TIME_MILLIS=1001, LAST_PRICE=1.19, LAST_SIZE=1, BID_PRICE=1.17, ASK_PRICE=1.19)),
        (1002.0, _full_context(TRADE_TIME_MILLIS=1002, LAST_PRICE=1.20, LAST_SIZE=1, BID_PRICE=1.17, ASK_PRICE=1.19)),
        (1003.0, _full_context(TRADE_TIME_MILLIS=1003, LAST_PRICE=1.10, LAST_SIZE=1, BID_PRICE=1.17, ASK_PRICE=1.19)),
    ])
    by_trade = {r["price"]: r["classification"] for r in tape.rows(SYM, 50)}
    assert by_trade[1.17] == "at_bid"
    assert by_trade[1.19] == "at_ask"
    assert by_trade[1.20] == "outside_spread_high"
    assert by_trade[1.10] == "outside_spread_low"


def test_newest_first_ordering_and_limit_bound():
    tape = _tape([
        (float(1000 + i), _full_context(TRADE_TIME_MILLIS=1000 + i, LAST_PRICE=1.0 + i * 0.01, LAST_SIZE=1,
                                        BID_PRICE=1.0, ASK_PRICE=2.0))
        for i in range(5)
    ])
    rows = tape.rows(SYM, 3)
    assert len(rows) == 3
    assert [r["ts_recv"] for r in rows] == [1004.0, 1003.0, 1002.0]
    assert rows[0]["price"] == 1.04   # the LAST (newest) genuine trade recorded


def test_each_message_carrying_a_trade_time_is_a_print_at_the_records_price_and_size():
    """Real messages (TSLA 2026-08-31 367.5 call, tests/fixtures/real_options_stream_history_samples.json):
    Schwab sends only what changed (Streamer API §1.1, Change). The 0.57 trades come without
    LAST_SIZE (unchanged: 2), and one trade comes as its TRADE_TIME_MILLIS alone (price and size
    unchanged: 0.61 x 1); each is a print at the record's price and size. A message carrying no
    trade time is none."""
    import json
    from pathlib import Path
    events = next(c for c in json.loads((Path(__file__).parent / "fixtures" / "real_options_stream_history_samples.json")
                                        .read_text(encoding="utf-8"))["contracts"]
                  if c["symbol"] == "TSLA  260831C00367500")["events"]
    l1 = sorted((e for e in events if e["kind"] != "book"), key=lambda e: e["ts_recv"])
    sym = "TSLA  260831C00367500"
    tape = _tape([(e["ts_recv"], e["content"]) for e in l1], sym)
    prints = [(r["price"], r["size"]) for r in tape.rows(sym, 50)][::-1]
    assert sum(1 for e in l1 if "TRADE_TIME_MILLIS" in e["content"]) == len(prints) == 9
    assert prints == [(0.58, 2), (0.57, 2), (0.59, 1), (0.58, 2), (0.57, 2), (0.56, 3), (0.61, 1), (0.61, 1),
                      (0.62, 4)]


def test_a_contract_never_recorded_and_a_blank_symbol_serve_no_prints():
    tape = _tape([(1000.0, _full_context(TRADE_TIME_MILLIS=1000, LAST_PRICE=1.17, LAST_SIZE=1))])
    stamp = (2_000_000, 2000.0)
    tape.record_option("", {**_TERMS, "last": 1.5, "lastSize": 1, "tradeTimeInLong": 2000},
                {"last": stamp, "lastSize": stamp, "tradeTimeInLong": stamp, "streamTime": stamp}, 2000.0)
    assert tape.rows("SPY   260918P00600000", 50) == []
    assert tape.rows("", 50) == []
    assert len(tape.rows(SYM, 50)) == 1


def test_a_contract_the_console_stops_streaming_leaves_no_prints_in_memory():
    """The console's intake records a print, then the contract leaves the stream (the state's
    clear_symbol, as streaming calls it): its prints and its books are gone from memory."""
    from app.options.order_flow import history, state
    from tests.feed_live_helper import through_the_daemons_bus
    bus = MessageBus()
    bus.publish(*option_ledger.posting(SYM, _TERMS, 999_000, 999.0))
    through_the_daemons_bus(bus, SYM, [{"TRADE_TIME_MILLIS": 1000, "LAST_PRICE": 1.17, "LAST_SIZE": 1}],
                            [1000.0])
    history.BOOKS.record("SPY", "NYSE_BOOK", {"BIDS": [{"BID_PRICE": 600.0, "TOTAL_VOLUME": 5}]}, 1000.0)
    assert len(history.TAPE.rows(SYM, 50)) == 1 and history.BOOKS.window("SPY", "NYSE_BOOK", 5)
    state.clear_symbol(SYM)
    state.clear_symbol("SPY")
    assert history.TAPE.rows(SYM, 50) == [] and history.BOOKS.window("SPY", "NYSE_BOOK", 5) == []
