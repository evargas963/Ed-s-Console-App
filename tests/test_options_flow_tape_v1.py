"""app.options.order_flow.history.RecentTape (the Options Flow tape, in the console's memory):
discrete TRADE prints built from the LEVELONE_OPTIONS records the console's intake hands it.
Locked to the operator's own required schema: Time/Symbol/Expiry/Type/Strike/Bid x Size/Ask x
Size/Trade/Size/Premium/Volume/OI/IV/Delta, with Trade/Size/Time/Bid/Ask/BidSize/AskSize/Volume/
OI/IV/Delta read verbatim (never derived) and Premium = Trade x Size x native Multiplier. No
aggressor-side (buy/sell) classification is ever produced -- `classification` states only where
a print landed relative to that SAME tick's own bid/ask."""
from __future__ import annotations

from app.options.order_flow.history import RecentTape

SYM = "SPY   260918C00600000"


def _tape(rows: list[tuple[float, dict]]) -> RecentTape:
    """A fresh tape fed each (ts_recv, LEVELONE_OPTIONS item) as the console's intake does."""
    tape = RecentTape()
    for ts_recv, content in rows:
        tape.record(SYM, content, ts_recv)
    return tape


def _full_context(**overrides) -> dict:
    base = {
        "key": SYM, "STRIKE_TYPE": 600, "CONTRACT_TYPE": "C",
        "EXPIRATION_YEAR": 2026, "EXPIRATION_MONTH": 9, "EXPIRATION_DAY": 18,
        "MULTIPLIER": 100, "UNDERLYING": "SPY",
    }
    base.update(overrides)
    return base


def test_a_genuine_trade_print_is_shaped_to_the_operators_exact_schema():
    tape = _tape([
        (1000.0, _full_context(TRADE_TIME_MILLIS=999000, LAST_PRICE=1.18, LAST_SIZE=1,
                                BID_PRICE=1.17, BID_SIZE=187, ASK_PRICE=1.19, ASK_SIZE=180,
                                TOTAL_VOLUME=70984, OPEN_INTEREST=901, VOLATILITY=7.16, DELTA=0.357)),
    ])
    rows = tape.rows(SYM, 50)
    assert len(rows) == 1
    r = rows[0]
    assert r["symbol"] == SYM and r["underlying"] == "SPY"
    assert r["expiry"] == "2026-09-18" and r["type"] == "CALL" and r["strike"] == 600
    assert r["bid"] == 1.17 and r["bid_size"] == 187
    assert r["ask"] == 1.19 and r["ask_size"] == 180
    assert r["trade"] == 1.18 and r["size"] == 1
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
    assert all(r["trade"] is not None for r in rows), "no row may ever report trade=None"


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
    assert newest["trade"] == 1.25 and newest["size"] == 3
    assert newest["expiry"] == "2026-09-18" and newest["type"] == "CALL" and newest["strike"] == 600


def test_classification_at_bid_at_ask_and_outside_spread_are_mechanical_not_aggressor():
    tape = _tape([
        (1000.0, _full_context(TRADE_TIME_MILLIS=1000, LAST_PRICE=1.17, LAST_SIZE=1, BID_PRICE=1.17, ASK_PRICE=1.19)),
        (1001.0, _full_context(TRADE_TIME_MILLIS=1001, LAST_PRICE=1.19, LAST_SIZE=1, BID_PRICE=1.17, ASK_PRICE=1.19)),
        (1002.0, _full_context(TRADE_TIME_MILLIS=1002, LAST_PRICE=1.20, LAST_SIZE=1, BID_PRICE=1.17, ASK_PRICE=1.19)),
        (1003.0, _full_context(TRADE_TIME_MILLIS=1003, LAST_PRICE=1.10, LAST_SIZE=1, BID_PRICE=1.17, ASK_PRICE=1.19)),
    ])
    by_trade = {r["trade"]: r["classification"] for r in tape.rows(SYM, 50)}
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
    assert rows[0]["trade"] == 1.04   # the LAST (newest) genuine trade recorded


def test_a_contract_never_recorded_and_a_blank_symbol_serve_no_prints():
    tape = _tape([(1000.0, _full_context(TRADE_TIME_MILLIS=1000, LAST_PRICE=1.17, LAST_SIZE=1))])
    tape.record("", _full_context(TRADE_TIME_MILLIS=2000, LAST_PRICE=1.5, LAST_SIZE=1), 2000.0)
    assert tape.rows("SPY   260918P00600000", 50) == []
    assert tape.rows("", 50) == []
    assert len(tape.rows(SYM, 50)) == 1


def test_a_contract_the_console_stops_streaming_leaves_no_prints_in_memory():
    """The console's intake records a print, then the contract leaves the stream (the state's
    clear_symbol, as streaming calls it): its prints and its books are gone from memory."""
    from app.options.order_flow import history, state
    from app.options.order_flow.streaming import _ingest_pushed
    _ingest_pushed(f"optquote.{SYM}", {"symbol": SYM, "ts_recv": 1000.0, "content": _full_context(
        TRADE_TIME_MILLIS=1000, LAST_PRICE=1.17, LAST_SIZE=1)})
    history.BOOKS.record("SPY", "NYSE_BOOK", {"BIDS": [{"BID_PRICE": 600.0, "TOTAL_VOLUME": 5}]}, 1000.0)
    assert len(history.TAPE.rows(SYM, 50)) == 1 and history.BOOKS.window("SPY", "NYSE_BOOK", 5)
    state.clear_symbol(SYM)
    state.clear_symbol("SPY")
    assert history.TAPE.rows(SYM, 50) == [] and history.BOOKS.window("SPY", "NYSE_BOOK", 5) == []
