"""The Options Flow tape: the live state's prints (state.push_level_one), as history names them.

Discrete TRADE prints built from the LEVELONE_OPTIONS records the console's intake hands it.
Locked to the operator's own required schema: Time/Symbol/Expiry/Type/Strike/Bid x Size/Ask x
Size/Trade/Size/Premium/Volume/OI/IV/Delta, with Trade/Size/Time/Bid/Ask/BidSize/AskSize/Volume/
IV/Delta the stream's as sent, Expiry/Type/Strike/OI the contract's chain record's (the one
reader of them, option_contract.read_contract) and Premium = Trade x Size x that record's
multiplier. No aggressor-side (buy/sell) classification is ever produced -- `classification`
states only where a print landed relative to that SAME tick's own bid/ask.

Every record is Schwab's own, as the capture daemon stored it (tests/fixtures):
real_spy_option_contract_type_2026_10_23.json (a call's and a put's first four records, the first
one whole, and the two contracts' /chains rows of the stored capture before them),
real_options_stream_history_samples.json (twelve records in a row of one contract),
real_spy_2026_10_19_close_capture_and_premarket_zero_volume.json (whole first records) and
real_spy_2026_10_23_expiry_two_closes_2026_10_21_22.json (SPY's 2026-10-22 close capture, the
chain that lists the call and the put).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import live_market_plane as lmp
import server
from app.options.order_flow import history, state
from app.options.order_flow.engine import read_book
from app.options.order_flow.history import recent_prints, tape_row
from app.options.order_flow.state import OrderFlowState
from app.options.order_flow.streaming import _ingest_pushed
from option_contract import read_chain, read_contract
from stream_spine import verbatim_msg
from time_et import ET

_FX = Path(__file__).resolve().parent / "fixtures"
CALL = "SPY   261023C00761000"
PUT = "SPY   261023P00762000"
SIZE_ONLY = "SPY   260904C00772000"
INSIDE = "SPY   261019C00764000"


def _load(name: str) -> dict:
    return json.loads((_FX / name).read_text(encoding="utf-8"))


#: the call's and the put's /chains rows, as Schwab sent them in the capture before their messages
LISTED = {
    c["symbol"]: read_contract(c)
    for c in _load("real_spy_option_contract_type_2026_10_23.json")["chain"]["contracts"]
}


def _sent(contract: str) -> list[tuple[float, dict]]:
    """Return Schwab's first four records of `contract`, each with the time it was received."""
    rows = _load("real_spy_option_contract_type_2026_10_23.json")["contracts"][contract]
    return [(r["ts_recv"], r["item"]) for r in rows]


def _fed(contract: str, rows: list[tuple[float, dict]]) -> OrderFlowState:
    """Return a fresh live state fed each (ts_recv, LEVELONE_OPTIONS item) as the intake does.

    The intake is streaming._ingest_pushed: the record's top of book first, then the record, so
    a print is kept with the bid and ask its own message brought.
    """
    live = OrderFlowState()
    for ts_recv, content in rows:
        live.push_option_top(contract, content)
        live.push_level_one(contract, content, ts_recv=ts_recv)
    return live


def _tape(contract: str, rows: list[tuple[float, dict]], limit: int = 50) -> list[dict]:
    """Return the tape's newest `limit` prints of `contract` after `rows`, newest first."""
    return recent_prints(contract, _fed(contract, rows).get_content_for_symbol(contract), limit)


def test_a_genuine_trade_print_is_shaped_to_the_operators_exact_schema():
    """The print is the stream's; the contract's terms and open interest are its chain record's.

    The stream's own message carries OPEN_INTEREST 1888 where the chain record holds 843: the
    tape shows the chain's, as every other screen does.
    """
    sent = _sent(CALL)[:1]
    rows = _tape(CALL, sent)
    assert len(rows) == 1
    assert sent[0][1]["OPEN_INTEREST"] == 1888
    r = tape_row(rows[0], LISTED[CALL])
    assert r["symbol"] == CALL
    assert r["expiry"] == "2026-10-23" and r["type"] == "CALL" and r["strike"] == 761
    assert r["bid"] == 2.03 and r["bid_size"] == 65
    assert r["ask"] == 2.04 and r["ask_size"] == 74
    assert r["trade"] == 2.04 and r["size"] == 1
    assert r["premium"] == 2.04 * 1 * 100
    assert r["volume"] == 4391 and r["oi"] == 843
    assert r["iv"] == 27.10704925 and r["delta"] == 0.45935825
    assert r["classification"] == "at_ask"
    assert r["trade_time_ms"] == sent[0][1]["TRADE_TIME_MILLIS"] == 1792762334664  # Schwab's own
    assert set(r) == {"trade_time_ms", "symbol", "expiry", "type", "strike", "bid", "bid_size"} | {
        "ask",
        "ask_size",
        "trade",
        "size",
        "premium",
        "volume",
        "oi",
        "iv",
        "delta",
        "classification",
    }


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
    assert len(tape) == 1


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
    rows = _tape(SIZE_ONLY, sent)
    assert len(rows) == 2, "the size-only partials must not be counted as trade prints"
    assert all(r["trade"] is not None for r in rows), "no row may ever report trade=None"
    assert [(r["trade"], r["size"]) for r in rows] == [(0.02, 1), (0.03, 5)]


def test_context_is_carried_forward_from_the_most_recent_full_tick():
    """The vendor does not repeat expiry/strike/type/multiplier on every partial update.

    A LATER genuine trade print that arrives on a tick carrying ONLY price/size/bid/ask still
    shows its contract's terms: they are the chain record's, whatever the message carried.
    """
    sent = _sent(CALL)[:3]
    assert "STRIKE_TYPE" in sent[0][1] and "STRIKE_TYPE" not in sent[2][1]
    rows = _tape(CALL, sent)
    assert len(rows) == 3
    newest = tape_row(rows[0], LISTED[CALL])  # newest-first
    assert newest["trade"] == 2.02 and newest["size"] == 10
    assert newest["expiry"] == "2026-10-23" and newest["type"] == "CALL"
    assert newest["strike"] == 761 and newest["premium"] == 2.02 * 10 * 100


def test_a_print_without_a_size_or_a_multiplier_has_no_premium():
    """Schwab's second record of the call carries LAST_PRICE 2.07 and no LAST_SIZE.

    Its premium is unknown, never 0; so is a print's of a contract whose chain record carries no
    multiplier (induced: the call's /chains row without its `multiplier`).
    """
    sent = _sent(CALL)[:2]
    assert sent[1][1]["LAST_PRICE"] == 2.07 and "LAST_SIZE" not in sent[1][1]
    sizeless, sized = _tape(CALL, sent)
    assert tape_row(sizeless, LISTED[CALL])["premium"] is None
    chain = _load("real_spy_option_contract_type_2026_10_23.json")["chain"]["contracts"]
    bare = read_contract({k: v for k, v in chain[0].items() if k != "multiplier"})
    assert bare.symbol == CALL and tape_row(sized, bare)["premium"] is None
    assert tape_row(sized, LISTED[CALL])["premium"] == 2.04 * 1 * 100


def test_the_tape_panel_and_the_flow_panel_show_the_chain_records_terms():
    """Schwab -> the console's intake -> the `tape` panel and the Flow panel's side.

    SPY's 2026-10-22 close capture is published as the chain that lists the call and the put,
    the daemon holds both on LEVELONE_OPTIONS, and their stored messages are applied. Each tape
    row's expiry, side, strike and open interest are that chain's record's, and the Flow panel's
    side is the same record's. Before a chain lists them: no tape, and the side is unknown.
    """
    sent = {sym: _sent(sym) for sym in (CALL, PUT)}
    at = max(ts for rows in sent.values() for ts, _ in rows)
    close = _load("real_spy_2026_10_23_expiry_two_closes_2026_10_21_22.json")["newer"]
    at_close = datetime.fromtimestamp(close["ts_utc"], ET)
    state.clear_all_live_state()
    try:
        lmp.record_feed_heartbeat(
            {"ts": at, "schwab_socket_open": True, "held": {"LEVELONE_OPTIONS": [CALL, PUT]}}
        )
        for sym, rows in sent.items():
            for ts, item in rows:
                _ingest_pushed(
                    f"optquote.{sym}",
                    verbatim_msg(symbol=sym, content=item, src="schwab", ts_recv=ts),
                )
        unlisted = (
            server.tape("SPY", at),
            [server.options_microstructure(sym, at)["put_call"] for sym in (CALL, PUT)],
        )
        server._publish_levels(
            "SPY",
            captures=[
                {
                    "contracts": read_chain(close["chain"]),
                    "ts_utc": close["ts_utc"],
                    "spot": close["spot"],
                    "spot_ts": None,
                    "et_date": at_close.date().isoformat(),
                    "basis": server.CAPTURE_BASIS,
                }
            ],
            now=at_close,
        )
        body = server.tape("SPY", at)
        sides = [server.options_microstructure(sym, at)["put_call"] for sym in (CALL, PUT)]
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop("SPY", None)
        lmp.record_feed_down()
        state.clear_all_live_state()
    assert unlisted[0]["available"] is False and unlisted[0]["rows"] == []
    assert unlisted[1] == [None, None]
    assert sides == ["CALL", "PUT"]
    assert body["available"] is True
    # newest received first, each with Schwab's own trade time of its message (none sent: None)
    newest_first = sorted(
        (
            (ts, sym, item)
            for sym, rows in sent.items()
            for ts, item in rows
            if "LAST_PRICE" in item
        ),
        key=lambda m: m[0],
        reverse=True,
    )
    assert len(body["rows"]) == 6 and [
        (r["symbol"], r["trade"], r["trade_time_ms"]) for r in body["rows"]
    ] == [(sym, item["LAST_PRICE"], item.get("TRADE_TIME_MILLIS")) for _, sym, item in newest_first]
    assert all("ts_recv" not in r for r in body["rows"])
    terms = {(r["symbol"], r["expiry"], r["type"], r["strike"], r["oi"]) for r in body["rows"]}
    assert terms == {
        (CALL, "2026-10-23", "CALL", 761.0, 843),
        (PUT, "2026-10-23", "PUT", 762.0, 8898),
    }
    by_trade = {(r["symbol"], r["trade"]): r["premium"] for r in body["rows"]}
    assert by_trade[(CALL, 2.02)] == 2.02 * 10 * 100 and by_trade[(CALL, 2.07)] is None
    assert by_trade[(PUT, 3.04)] == 3.04 * 1 * 100


def test_classification_at_bid_at_ask_and_outside_spread_are_mechanical_not_aggressor():
    whole = next(
        m
        for m in _load("real_spy_2026_10_19_close_capture_and_premarket_zero_volume.json")[
            "zero_volume_messages"
        ]
        if m["symbol"] == INSIDE
    )
    prints = (
        _tape(CALL, _sent(CALL))
        + _tape(PUT, _sent(PUT))
        + _tape(INSIDE, [(whole["ts_recv"], whole["native"])])
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
    rows = _tape(CALL, sent, 3)
    assert len(rows) == 3
    assert [r["ts_recv"] for r in rows] == [received[3], received[2], received[1]]
    assert rows[0]["trade"] == 2.03  # the LAST (newest) genuine trade recorded


def test_a_contract_never_recorded_and_a_blank_symbol_serve_no_prints():
    (at, first), (later, second) = _sent(CALL)[:2]
    live = _fed(CALL, [(at, first)])
    live.push_level_one("", second, ts_recv=later)
    assert recent_prints(PUT, live.get_content_for_symbol(PUT), 50) == []
    assert recent_prints("", live.get_content_for_symbol(""), 50) == []
    assert len(recent_prints(CALL, live.get_content_for_symbol(CALL), 50)) == 1


def test_a_contract_the_console_stops_streaming_leaves_no_prints_in_memory():
    """The console's intake records a print, then clear_symbol is called for that contract.

    Its prints and its books are gone from memory. The release path does not call it. The book is
    Schwab's SPY NYSE_BOOK message of real_spy_nyse_nasdaq_books.json.
    """
    at, first = _sent(CALL)[0]
    _ingest_pushed(f"optquote.{CALL}", {"symbol": CALL, "ts_recv": at, "content": first})
    book = _load("real_spy_nyse_nasdaq_books.json")["books"]["NYSE_BOOK"]
    history.BOOKS.record("SPY", "NYSE_BOOK", read_book(book["content"], "NYSE_BOOK"))
    kept = recent_prints(CALL, state.get_content_for_symbol(CALL), 50)
    assert len(kept) == 1 and history.BOOKS.window("SPY", "NYSE_BOOK", 5)
    state.clear_symbol(CALL)
    state.clear_symbol("SPY")
    gone = recent_prints(CALL, state.get_content_for_symbol(CALL), 50)
    assert gone == [] and history.BOOKS.window("SPY", "NYSE_BOOK", 5) == []
