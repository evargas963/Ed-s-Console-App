"""app.options.order_flow.history.RecentTape (the Options Flow tape, in the console's memory).

Discrete TRADE prints built from the LEVELONE_OPTIONS records the console's intake hands it.
Locked to the operator's own required schema: Time/Symbol/Expiry/Type/Strike/Bid x Size/Ask x
Size/Trade/Size/Premium/Volume/OI/IV/Delta, with Trade/Size/Time/Bid/Ask/BidSize/AskSize/Volume/
OI/IV/Delta read verbatim (never derived) and Premium = Trade x Size x native Multiplier. No
aggressor-side (buy/sell) classification is ever produced -- `classification` states only where
a print landed relative to that SAME tick's own bid/ask.

Every record is Schwab's own, as the capture daemon stored it (tests/fixtures):
real_spy_option_contract_type_2026_10_23.json (a call's and a put's first four records, the first
one whole), real_options_stream_history_samples.json (twelve records in a row of one contract)
and real_spy_2026_10_19_close_capture_and_premarket_zero_volume.json (whole first records).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.options.order_flow import history, state
from app.options.order_flow.engine import read_book
from app.options.order_flow.history import RecentTape
from app.options.order_flow.state import OrderFlowState
from app.options.order_flow.streaming import _ingest_pushed

_FX = Path(__file__).resolve().parent / "fixtures"
CALL = "SPY   261023C00761000"
PUT = "SPY   261023P00762000"
SIZE_ONLY = "SPY   260904C00772000"
INSIDE = "SPY   261019C00764000"


def _load(name: str) -> dict:
    return json.loads((_FX / name).read_text(encoding="utf-8"))


def _sent(contract: str) -> list[tuple[float, dict]]:
    """Return Schwab's first four records of `contract`, each with the time it was received."""
    rows = _load("real_spy_option_contract_type_2026_10_23.json")["contracts"][contract]
    return [(r["ts_recv"], r["item"]) for r in rows]


def _tape(contract: str, rows: list[tuple[float, dict]]) -> RecentTape:
    """Return a fresh tape fed each (ts_recv, LEVELONE_OPTIONS item) as the console's intake does.

    The intake is streaming._ingest_pushed: the live state reads the record first, and the tape
    takes the state's top of book and streamed values with it.
    """
    tape, live = RecentTape(), OrderFlowState()
    for ts_recv, content in rows:
        live.push_level_one(contract, content, ts_recv=ts_recv)
        live.push_option_top(contract, content)
        tape.record(
            contract, content, ts_recv, live.option_top(contract), live.get_stream_greeks(contract)
        )
    return tape


def test_a_genuine_trade_print_is_shaped_to_the_operators_exact_schema():
    rows = _tape(CALL, _sent(CALL)[:1]).rows(CALL, 50)
    assert len(rows) == 1
    r = rows[0]
    assert r["symbol"] == CALL and r["underlying"] == "SPY"
    assert r["expiry"] == "2026-10-23" and r["type"] == "CALL" and r["strike"] == 761
    assert r["bid"] == 2.03 and r["bid_size"] == 65
    assert r["ask"] == 2.04 and r["ask_size"] == 74
    assert r["trade"] == 2.04 and r["size"] == 1
    assert r["premium"] == 2.04 * 1 * 100
    assert r["volume"] == 4391 and r["oi"] == 1888
    assert r["iv"] == 27.10704925 and r["delta"] == 0.45935825
    assert r["classification"] == "at_ask"


def test_a_re_emitted_duplicate_of_the_same_trade_is_not_counted_twice():
    """The vendor re-sends the SAME (TRADE_TIME_MILLIS, LAST_PRICE, LAST_SIZE) trade.

    It comes alongside an unrelated field update (e.g. a fresh Greek recompute) -- this must
    collapse to ONE tape row, not one per re-emission. Induced: Schwab's first record is received
    again, carrying the delta and then the volatility Schwab sent two records later.
    """
    (at, first), _, (_, third), _ = _sent(CALL)
    assert first["DELTA"] != third["DELTA"] and first["VOLATILITY"] != third["VOLATILITY"]
    tape = _tape(
        CALL,
        [
            (at, first),
            (at + 5, dict(first, DELTA=third["DELTA"])),
            (at + 10, dict(first, VOLATILITY=third["VOLATILITY"])),
        ],
    )
    assert len(tape.rows(CALL, 50)) == 1


def test_a_partial_update_with_size_but_no_price_never_produces_a_null_trade_row():
    """Twelve records in a row of SPY 260904C00772000, as Schwab sent them.

    A partial LEVELONE_OPTIONS tick can carry a fresh LAST_SIZE with NO LAST_PRICE on the same
    packet (a size-only field bumping TOTAL_VOLUME on its own); two of the twelve do. A trade
    print requires its OWN price on the SAME tick; this shape is excluded.
    """
    contract = next(
        c
        for c in _load("real_options_stream_history_samples.json")["contracts"]
        if c["symbol"] == SIZE_ONLY
    )
    sent = [(e["ts_recv"], e["content"]) for e in contract["events"] if e["kind"] == "l1"]
    size_only = [c for _, c in sent if "LAST_SIZE" in c and "LAST_PRICE" not in c]
    assert [(c["LAST_SIZE"], c["TOTAL_VOLUME"]) for c in size_only] == [(4, 486829), (1, 486836)]
    rows = _tape(SIZE_ONLY, sent).rows(SIZE_ONLY, 50)
    assert len(rows) == 2, "the size-only partials must not be counted as trade prints"
    assert all(r["trade"] is not None for r in rows), "no row may ever report trade=None"
    assert [(r["trade"], r["size"]) for r in rows] == [(0.02, 1), (0.03, 5)]


def test_context_is_carried_forward_from_the_most_recent_full_tick():
    """The vendor does not repeat expiry/strike/type/multiplier on every partial update.

    A LATER genuine trade print that arrives on a tick carrying ONLY price/size/bid/ask must still
    resolve its own contract identity from the most recent tick that reported it, not read as if
    that identity were unknown.
    """
    sent = _sent(CALL)[:3]
    assert "STRIKE_TYPE" in sent[0][1] and "STRIKE_TYPE" not in sent[2][1]
    rows = _tape(CALL, sent).rows(CALL, 50)
    assert len(rows) == 3
    newest = rows[0]  # newest-first
    assert newest["trade"] == 2.02 and newest["size"] == 10
    assert newest["expiry"] == "2026-10-23" and newest["type"] == "CALL"
    assert newest["strike"] == 761 and newest["premium"] == 2.02 * 10 * 100


def test_classification_at_bid_at_ask_and_outside_spread_are_mechanical_not_aggressor():
    whole = next(
        m
        for m in _load("real_spy_2026_10_19_close_capture_and_premarket_zero_volume.json")[
            "zero_volume_messages"
        ]
        if m["symbol"] == INSIDE
    )
    prints = (
        _tape(CALL, _sent(CALL)).rows(CALL, 50)
        + _tape(PUT, _sent(PUT)).rows(PUT, 50)
        + _tape(INSIDE, [(whole["ts_recv"], whole["native"])]).rows(INSIDE, 50)
    )
    landed = {(r["bid"], r["trade"], r["ask"]): r["classification"] for r in prints}
    assert landed[(3.04, 3.04, 3.05)] == "at_bid"
    assert landed[(2.03, 2.04, 2.04)] == landed[(2.02, 2.03, 2.03)] == "at_ask"
    assert landed[(2.97, 3, 2.99)] == "outside_spread_high"
    assert landed[(2.03, 2.02, 2.04)] == landed[(2.08, 2.07, 2.09)] == "outside_spread_low"
    assert landed[(2.5, 2.51, 2.52)] == "inside_spread"
    assert len(landed) == 7


def test_newest_first_ordering_and_limit_bound():
    sent = _sent(CALL)
    received = [at for at, _ in sent]
    rows = _tape(CALL, sent).rows(CALL, 3)
    assert len(rows) == 3
    assert [r["ts_recv"] for r in rows] == [received[3], received[2], received[1]]
    assert rows[0]["trade"] == 2.03  # the LAST (newest) genuine trade recorded


def test_a_contract_never_recorded_and_a_blank_symbol_serve_no_prints():
    (at, first), (later, second) = _sent(CALL)[:2]
    tape = _tape(CALL, [(at, first)])
    tape.record("", second, later, None, None)
    assert tape.rows(PUT, 50) == []
    assert tape.rows("", 50) == []
    assert len(tape.rows(CALL, 50)) == 1


def test_a_contract_the_console_stops_streaming_leaves_no_prints_in_memory():
    """The console's intake records a print, then clear_symbol is called for that contract.

    Its prints and its books are gone from memory. The release path does not call it. The book is
    Schwab's SPY NYSE_BOOK message of real_spy_nyse_nasdaq_books.json.
    """
    at, first = _sent(CALL)[0]
    _ingest_pushed(f"optquote.{CALL}", {"symbol": CALL, "ts_recv": at, "content": first})
    book = _load("real_spy_nyse_nasdaq_books.json")["books"]["NYSE_BOOK"]
    history.BOOKS.record(
        "SPY", "NYSE_BOOK", read_book(book["content"], "NYSE_BOOK"), book["ts_recv"]
    )
    assert len(history.TAPE.rows(CALL, 50)) == 1 and history.BOOKS.window("SPY", "NYSE_BOOK", 5)
    state.clear_symbol(CALL)
    state.clear_symbol("SPY")
    assert history.TAPE.rows(CALL, 50) == [] and history.BOOKS.window("SPY", "NYSE_BOOK", 5) == []
