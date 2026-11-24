"""The Options Flow tape: the live state's prints (state.push_level_one), as the tape shows them.

Discrete TRADE prints built from the LEVELONE_OPTIONS records the console's intake hands it.
Locked to the operator's own required schema: Time/Symbol/Expiry/Type/Strike/Bid x Size/Ask x
Size/Trade/Size/Premium/Volume/OI/IV/Delta, with Trade/Size/Time/Bid/Ask/BidSize/AskSize/Volume/
IV/Delta the stream's as sent, Expiry/Type/Strike/OI the contract's chain record's (the one
reader of them, option_contract.read_contract) and Premium = Trade x Size x that record's
multiplier. No aggressor-side (buy/sell) classification is ever produced -- `classification`
states only where a print landed relative to the bid and ask in force when it traded: the newest
quote Schwab timed (QUOTE_TIME_MILLIS) at or before the trade (TRADE_TIME_MILLIS), never the quote
that followed it in the same update.

Every record is Schwab's own, as the capture daemon stored it (tests/fixtures):
real_spy_option_contract_type_2026_10_23.json (a call's and a put's first four records, the first
one whole, and the two contracts' /chains rows of the stored capture before them),
real_options_stream_history_samples.json (twelve records in a row of one contract),
real_spy_2026_10_19_close_capture_and_premarket_zero_volume.json (whole first records),
real_spy_2026_10_23_expiry_two_closes_2026_10_21_22.json (SPY's 2026-10-22 close capture, the
chain that lists the call and the put) and real_spy_option_levelone_2026_11_20_1200et.json (45
records in a row of one contract in a fast market).
"""

from __future__ import annotations

from datetime import datetime

import live_market_plane as lmp
from app.options.order_flow import state
from app.options.order_flow.history import tape_row
from app.options.order_flow.state import OrderFlowState
from app.options.order_flow.streaming import _ingest_pushed
from calc.l1_trade_observation import KeptPrint
from feed import connection
from option_contract import read_contract
from push import contract as push_contract
from push import tape as push_tape
from state import level_store
from stream_spine import HealthRegistry, MessageBus
from tests import feed_live_helper
from tests.feed_live_helper import apply_record, forget_streamed, on_the_bus, publish_capture
from tests.shared_helpers import fixture_json
from time_et import ET

OPT = "LEVELONE_OPTIONS"

CALL = "SPY   261023C00761000"
PUT = "SPY   261023P00762000"
SIZE_ONLY = "SPY   260904C00772000"
INSIDE = "SPY   261019C00764000"

#: the call's and the put's /chains rows, as Schwab sent them in the capture before their messages
LISTED = {
    c["symbol"]: read_contract(c)
    for c in fixture_json("real_spy_option_contract_type_2026_10_23.json")["chain"]["contracts"]
}


def _sent(contract: str) -> list[tuple[float, dict]]:
    """Return Schwab's first four records of `contract`, each with the time it was received."""
    rows = fixture_json("real_spy_option_contract_type_2026_10_23.json")["contracts"][contract]
    return [(r["ts_recv"], r["item"]) for r in rows]


def _fed(contract: str, rows: list[tuple[float, dict]]) -> OrderFlowState:
    """Return a fresh live state fed each (ts_recv, LEVELONE_OPTIONS item) as the console is.

    Each item goes on a bus as the daemon puts it, and its record to the state as the intake
    (streaming._ingest_pushed) applies it, so a print is kept with the bid and ask in force when
    it traded.
    """
    bus, live = MessageBus(), OrderFlowState()
    live.current = bus.current
    for ts_recv, content in rows:
        apply_record(live, OPT, on_the_bus(bus, OPT, {**content, "key": contract}, ts_recv))
    return live


def _tape(contract: str, rows: list[tuple[float, dict]]) -> list[KeptPrint]:
    """Return the prints a fresh live state kept of `contract` after `rows`, newest first."""
    return _fed(contract, rows).prints(contract)[::-1]


def test_a_genuine_trade_print_is_shaped_to_the_operators_exact_schema():
    """The print is the stream's; the contract's terms and open interest are its chain record's.

    The stream's own message carries OPEN_INTEREST 1888 where the chain record holds 843: the
    tape shows the chain's, as every other screen does. The contract's first streamed message is
    a tape row: its trade was made before the message was received. The row read here is the
    fourth message's trade, 2.03 x 1 at ...337329: that message's own quote (2.02 x 16, 2.03 x 79)
    is timed ...338021, after the trade, so the print is kept with the quote in force when it
    traded, the third message's 2.03 x 56 and 2.04 x 34 timed ...336980, and it landed at the bid.
    Its volume is the fourth message's; its volatility and delta are the third's, the newest sent.
    """
    sent = _sent(CALL)
    rows = _tape(CALL, sent)
    assert len(rows) == 4 and len(_tape(CALL, sent[:1])) == 1
    assert sent[0][1]["TRADE_TIME_MILLIS"] < sent[0][0] * 1000
    assert sent[0][1]["OPEN_INTEREST"] == 1888
    r = tape_row(CALL, rows[0], LISTED[CALL])
    assert r["symbol"] == CALL
    assert r["expiry"] == "2026-10-23" and r["type"] == "CALL" and r["strike"] == 761
    assert r["bid"] == 2.03 and r["bid_size"] == 56
    assert r["ask"] == 2.04 and r["ask_size"] == 34
    assert r["trade"] == 2.03 and r["size"] == 1
    assert r["premium"] == 2.03 * 1 * 100
    assert r["volume"] == 4423 and r["oi"] == 843
    assert r["iv"] == 27.03127864 and r["delta"] == 0.4662257
    assert (r["classification"], r["classification_text"]) == ("at_bid", "at bid")
    assert sent[3][1]["QUOTE_TIME_MILLIS"] > sent[3][1]["TRADE_TIME_MILLIS"]
    assert r["trade_time_ms"] == sent[3][1]["TRADE_TIME_MILLIS"] == 1792762337329  # Schwab's own
    # 13:32:17.329 UTC on 2026-10-23 is 08:32:17.329 in Chicago (CDT, UTC-5)
    assert r["trade_time_ct"] == "08:32:17.329 CT"
    assert set(r) == {"trade_time_ms", "symbol", "expiry", "type", "strike", "bid", "bid_size"} | {
        "classification_text",
        "trade_time_ct",
        "ask",
        "ask_size",
        "trade",
        "size",
        "premium",
        "volume",
        "strike_text",
        "bid_text",
        "ask_text",
        "trade_text",
        "delta_text",
        "premium_text",
        "bid_size_text",
        "ask_size_text",
        "size_text",
        "volume_text",
        "oi_text",
        "iv_text",
        "oi",
        "iv",
        "delta",
        "classification",
    }
    # the premium in dollars; the sizes, the day's volume and open interest whole; the IV two
    # decimals, as the screen shows them (operator 2026-11-16)
    assert (r["premium_text"], r["volume_text"], r["iv_text"]) == ("$203", "4,423", "27.03")
    assert (r["bid_size_text"], r["ask_size_text"], r["size_text"]) == ("56", "34", "1")
    assert r["oi_text"] == "843"
    # the strike as listed, the prices two decimals, the delta three
    assert (r["strike_text"], r["bid_text"], r["ask_text"], r["trade_text"]) == (
        "761",
        "2.03",
        "2.04",
        "2.03",
    )
    assert r["delta_text"] == "0.466"


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

    LEVELONE_OPTIONS is delivered on Change: only the fields that changed are streamed (Schwab
    Streamer API §1.5). Two of the twelve carry a new TRADE_TIME_MILLIS and LAST_SIZE with no
    LAST_PRICE: trades at the unchanged price, 0.02, which the contract's record on the bus still
    holds. Each is a print at that price; none reports trade=None.
    """
    contract = next(
        c
        for c in fixture_json("real_options_stream_history_samples.json")["contracts"]
        if c["symbol"] == SIZE_ONLY
    )
    sent = [(e["ts_recv"], e["content"]) for e in contract["events"] if e["kind"] == "l1"]
    size_only = [c for _, c in sent if "LAST_SIZE" in c and "LAST_PRICE" not in c]
    assert [(c["LAST_SIZE"], c["TOTAL_VOLUME"]) for c in size_only] == [(4, 486829), (1, 486836)]
    rows = _tape(SIZE_ONLY, sent)
    assert len(rows) == 4, "each new trade time is a print, its price unchanged"
    assert all(r.price is not None for r in rows), "no row may ever report trade=None"
    assert [(r.price, r.size) for r in rows] == [(0.02, 1), (0.02, 4), (0.02, 1), (0.03, 5)]


def test_context_is_carried_forward_from_the_most_recent_full_tick():
    """The vendor does not repeat expiry/strike/type/multiplier on every partial update.

    A LATER genuine trade print that arrives on a tick carrying ONLY price/size/bid/ask still
    shows its contract's terms: they are the chain record's, whatever the message carried.
    """
    sent = _sent(CALL)[:3]
    assert "STRIKE_TYPE" in sent[0][1] and "STRIKE_TYPE" not in sent[2][1]
    rows = _tape(CALL, sent)
    assert len(rows) == 3
    newest = tape_row(CALL, rows[0], LISTED[CALL])  # newest-first
    assert newest["trade"] == 2.02 and newest["size"] == 10
    assert newest["expiry"] == "2026-10-23" and newest["type"] == "CALL"
    assert newest["strike"] == 761 and newest["premium"] == 2.02 * 10 * 100


def test_a_print_without_a_size_or_a_multiplier_has_no_premium():
    """A print's premium needs its size and its contract's multiplier, never 0 for either.

    Schwab's second record of the call carries LAST_PRICE 2.07, a new trade time and no LAST_SIZE:
    on Change delivery (Schwab Streamer API §1.5) its size is the first record's, unchanged, so
    its premium is 2.07 x 1 x 100. A print of a contract whose chain record carries no multiplier
    has no premium (induced: the call's /chains row without its `multiplier`).
    """
    sent = _sent(CALL)[:2]
    assert sent[1][1]["LAST_PRICE"] == 2.07 and "LAST_SIZE" not in sent[1][1]
    unchanged_size, sized = _tape(CALL, sent)
    assert tape_row(CALL, unchanged_size, LISTED[CALL])["premium"] == 2.07 * 1 * 100
    chain = fixture_json("real_spy_option_contract_type_2026_10_23.json")["chain"]["contracts"]
    bare = read_contract({k: v for k, v in chain[0].items() if k != "multiplier"})
    assert bare.symbol == CALL and tape_row(CALL, sized, bare)["premium"] is None
    assert tape_row(CALL, sized, LISTED[CALL])["premium"] == 2.04 * 1 * 100


def test_the_tape_panel_and_the_flow_panel_show_the_chain_records_terms():
    """Schwab -> the console's intake -> the `tape` panel and the Flow panel's side.

    SPY's 2026-10-22 close capture is published as the chain that lists the call and the put,
    the daemon holds both on LEVELONE_OPTIONS, and their stored messages are applied. Each tape
    row's expiry, side, strike and open interest are that chain's record's, and the Flow panel's
    side is the same record's. Before a chain lists them: no tape, and the side is unknown.
    """
    sent = {sym: _sent(sym) for sym in (CALL, PUT)}
    at = max(ts for rows in sent.values() for ts, _ in rows)
    close = fixture_json("real_spy_2026_10_23_expiry_two_closes_2026_10_21_22.json")["newer"]
    at_close = datetime.fromtimestamp(close["ts_utc"], ET)
    state.clear_all_live_state()
    try:
        lmp.record_feed_heartbeat(
            {"ts": at, "schwab_socket_open": True, "held": {"LEVELONE_OPTIONS": [CALL, PUT]}}
        )
        for sym, rows in sent.items():
            for ts, item in rows:
                _ingest_pushed(*on_the_bus(feed_live_helper.BUS, OPT, {**item, "key": sym}, ts))
        unlisted = (
            push_tape.tape("SPY", at),
            [push_contract.options_microstructure(sym, at)["put_call"] for sym in (CALL, PUT)],
        )
        publish_capture(
            "SPY",
            close["chain"],
            close["ts_utc"],
            close["spot"],
            at_close.date().isoformat(),
            at_close,
        )
        body = push_tape.tape("SPY", at)
        sides = [push_contract.options_microstructure(sym, at)["put_call"] for sym in (CALL, PUT)]
    finally:
        with level_store._lock:
            level_store._levels.pop("SPY", None)
        state.clear_all_live_state()
    assert unlisted[0]["available"] is False and unlisted[0]["rows"] == []
    assert unlisted[1] == [None, None]
    assert sides == ["CALL", "PUT"]
    assert body["available"] is True
    # newest trade first, by Schwab's own trade time of each message (operator 2026-11-12: "yes
    # we should use schwab's data"). The put's two messages were received after calls that
    # traded later (3.04 at ...3027 after the call's ...4664; 3.00 at ...5691 after ...5726):
    # the tape orders them by when they traded, not by when they arrived.
    traded = [
        (sym, item) for sym, rows in sent.items() for ts, item in rows if "LAST_PRICE" in item
    ]
    newest_first = sorted(traded, key=lambda m: m[1]["TRADE_TIME_MILLIS"], reverse=True)
    received_first = sorted(
        ((ts, sym) for sym, rows in sent.items() for ts, item in rows if "LAST_PRICE" in item),
        reverse=True,
    )
    assert [sym for sym, _ in newest_first] != [sym for _, sym in received_first]
    assert len(body["rows"]) == 6 and [
        (r["symbol"], r["trade"], r["trade_time_ms"]) for r in body["rows"]
    ] == [(sym, item["LAST_PRICE"], item["TRADE_TIME_MILLIS"]) for sym, item in newest_first]
    assert all("ts_recv" not in r for r in body["rows"])
    terms = {(r["symbol"], r["expiry"], r["type"], r["strike"], r["oi"]) for r in body["rows"]}
    assert terms == {
        (CALL, "2026-10-23", "CALL", 761.0, 843),
        (PUT, "2026-10-23", "PUT", 762.0, 8898),
    }
    by_trade = {(r["symbol"], r["trade"]): r["premium"] for r in body["rows"]}
    # 2.07 came with no LAST_SIZE: on Change delivery its size is the record's, the first's 1
    assert by_trade[(CALL, 2.02)] == 2.02 * 10 * 100 and by_trade[(CALL, 2.07)] == 2.07 * 1 * 100
    assert by_trade[(PUT, 3.04)] == 3.04 * 1 * 100


def test_classification_at_bid_at_ask_and_outside_spread_are_mechanical_not_aggressor():
    """Each print's label, keyed by the (bid, trade, ask) it is kept with: the quote in force.

    Worked out from the messages. A contract's first message has no quote before it, and its own
    quote is timed after its trade (the call's, the put's and the whole record of 261019C00764000,
    whose own bid 2.50 and ask 2.52 came 3 s after its 2.51 trade): no quote in force, "unknown".
    The call's second trade, 2.07, is read against the first message's 2.03 and 2.04 (its own
    update's 2.08 and 2.09 followed it): above the ask. Its third, 2.02, against the second's 2.08
    and 2.09: below the bid. Its fourth, 2.03, against the third's 2.03 and 2.04: at the bid. The
    put's second, 3.00, against its first message's 3.04 and 3.05: below the bid.
    """
    whole = next(
        m
        for m in fixture_json("real_spy_2026_10_19_close_capture_and_premarket_zero_volume.json")[
            "zero_volume_messages"
        ]
        if m["symbol"] == INSIDE
    )
    prints = (
        _tape(CALL, _sent(CALL))
        + _tape(PUT, _sent(PUT))
        + _tape(INSIDE, [(whole["ts_recv"], whole["native"])])
    )
    landed = {(r.bid, r.price, r.ask): r.landed for r in prints}
    assert landed[(2.03, 2.03, 2.04)] == "at_bid"
    assert landed[(2.03, 2.07, 2.04)] == "outside_spread_high"
    assert landed[(2.08, 2.02, 2.09)] == landed[(3.04, 3, 3.05)] == "outside_spread_low"
    assert landed[(None, 2.04, None)] == landed[(None, 3.04, None)] == "unknown"
    assert landed[(None, 2.51, None)] == "unknown"
    assert len(landed) == 7


#: SPY 261120P00703000's 45 LEVELONE_OPTIONS messages in a row, 2026-11-20 from 12:00:00 ET
FAST = fixture_json("real_spy_option_levelone_2026_11_20_1200et.json")["option"]
#: the quote's fields: a message that changes one replaces the quote the record held
_QUOTE = ("BID_PRICE", "ASK_PRICE", "BID_SIZE", "ASK_SIZE", "QUOTE_TIME_MILLIS")


def _label(trade: float, bid: float | None, ask: float | None) -> str:
    """Where `trade` sits against `bid` and `ask`, as the derived register defines the labels."""
    if bid is None or ask is None:
        return "unknown"
    if trade <= bid:
        return "at_bid" if trade == bid else "outside_spread_low"
    if trade >= ask:
        return "at_ask" if trade == ask else "outside_spread_high"
    return "inside_spread"


def _placed(rows: list[dict]) -> list[tuple]:
    """Each print of `rows`, oldest first, placed here from Schwab's own fields.

    (trade, size, bid, ask, label, label against its own update's quote). The bid and ask are the
    quote in force when it traded: the newest Schwab timed (QUOTE_TIME_MILLIS) at or before the
    trade (TRADE_TIME_MILLIS), the update's own or the one the update replaced; none, no bid and
    no ask.
    """
    held: dict = {}
    before: dict = {}
    out, last = [], None
    for row in rows:
        item = row["item"]
        if any(f in item and f in held and item[f] != held[f] for f in _QUOTE):
            before = {f: held[f] for f in _QUOTE if f in held}
        held.update(item)
        triple = (held["TRADE_TIME_MILLIS"], held["LAST_PRICE"], held.get("LAST_SIZE"))
        if triple == last:
            continue
        last = triple
        bid = ask = None
        for quote in (held, before):
            if "QUOTE_TIME_MILLIS" in quote and quote["QUOTE_TIME_MILLIS"] <= triple[0]:
                bid, ask = quote.get("BID_PRICE"), quote.get("ASK_PRICE")
                break
        own = _label(triple[1], held.get("BID_PRICE"), held.get("ASK_PRICE"))
        out.append((triple[1], triple[2], bid, ask, _label(triple[1], bid, ask), own))
    return out


def test_a_print_is_placed_against_the_quote_in_force_when_it_traded():
    """45 messages in a row of SPY 261120P00703000 in a fast market, as Schwab sent them.

    Schwab's update carries a trade with the quote that followed it: in 44 of the 45 the update's
    QUOTE_TIME_MILLIS is after its TRADE_TIME_MILLIS. Each print is kept with the bid and ask in
    force when it traded, worked out here from Schwab's times: the quote its update replaced (43),
    its own when timed no later than the trade (one: 3.10 and 3.11, both timed ...41192), or none
    (the first message, with no quote before it). Read against its own update's quote, as the tape
    read it before, 36 of the 45 would carry another label.
    """
    rows = FAST["rows"]
    want = _placed(rows)
    tape = _tape(FAST["symbol"], [(r["ts_recv"], r["item"]) for r in rows])[::-1]  # oldest first
    assert len(want) == 45
    assert sum(r["item"]["QUOTE_TIME_MILLIS"] > r["item"]["TRADE_TIME_MILLIS"] for r in rows) == 44
    got = [(r.price, r.size, r.bid, r.ask, r.landed) for r in tape]
    assert got == [w[:5] for w in want]
    # placed by hand from the messages: no quote before the first; the second's 2.50 against the
    # first message's 2.46 and 2.47; a trade at the ask its update's own quote calls at the bid;
    # one inside; one at the bid; the one whose own quote is in force; the last, below the bid
    assert want[0] == (2.46, 1, None, None, "unknown", "at_bid")
    assert want[1] == (2.5, 4, 2.46, 2.47, "outside_spread_high", "at_ask")
    assert want[7] == (2.62, 1, 2.6, 2.62, "at_ask", "at_bid")
    assert want[22] == (2.6, 1, 2.59, 2.61, "inside_spread", "at_bid")
    assert want[24] == (2.64, 20, 2.64, 2.65, "at_bid", "outside_spread_low")
    assert want[39] == (3.11, 1, 3.1, 3.11, "at_ask", "at_ask")
    assert want[44] == (3.1, 1, 3.13, 3.14, "outside_spread_low", "inside_spread")
    assert (tape[1].bid_size, tape[1].ask_size) == (77, 8)  # the first message's sizes
    assert sum(w[4] != w[5] for w in want) == 36


def test_where_a_print_landed_is_served_in_the_tapes_words():
    """The fast contract's 45 real prints as the tape shows them: each place with its words.

    Every place history.quoted names occurs in the capture. The row serves the "vs Market"
    column's words for it, and the page picks none: no words where no quote in force is known.
    """
    nov20 = fixture_json("real_spy_2026_11_20_chain_and_quotes.json")
    contract = read_contract(next(c for c in nov20["chain"] if c["symbol"] == FAST["symbol"]))
    kept = _tape(FAST["symbol"], [(r["ts_recv"], r["item"]) for r in FAST["rows"]])
    shown = [tape_row(FAST["symbol"], p, contract) for p in kept]
    assert {(r["classification"], r["classification_text"]) for r in shown} == {
        ("at_bid", "at bid"),
        ("at_ask", "at ask"),
        ("inside_spread", "inside"),
        ("outside_spread_low", "below bid"),
        ("outside_spread_high", "above ask"),
        ("unknown", None),
    }


def test_the_tape_panel_shows_its_newest_rows_and_a_print_with_no_trade_time_last():
    """Schwab -> the console's intake -> the `tape` panel: newest trade first, TAPE_ROWS at most.

    The fast contract's 45 captured messages, each its own trade, are applied as the console
    takes them, under SPY's 2026-11-20 chain. INDUCED, of the same captured messages: a second
    contract of that chain whose message carries no TRADE_TIME_MILLIS (its print comes after
    every timed one), and the 45 received twice more, each a minute later, so the tape holds
    more prints than it shows.
    """
    nov20 = fixture_json("real_spy_2026_11_20_chain_and_quotes.json")
    fast, rows = FAST["symbol"], FAST["rows"]
    other = next(c["symbol"] for c in nov20["chain"] if c["symbol"] != fast)
    captured = datetime.fromtimestamp(nov20["capture_ts_utc"], ET)
    at = rows[-1]["ts_recv"] + 120.0
    times = [r["item"]["TRADE_TIME_MILLIS"] for r in rows]
    assert times == sorted(set(times)) and times[-1] - times[0] < 60_000
    state.clear_all_live_state()
    forget_streamed()
    bus = feed_live_helper.BUS  # the console's state reads it (tests/conftest.py)
    try:
        publish_capture(
            "SPY",
            nov20["chain"],
            nov20["capture_ts_utc"],
            nov20["spot"],
            captured.date().isoformat(),
            captured,
        )
        lmp.record_feed_heartbeat(
            {"ts": at, "schwab_socket_open": True, "held": {OPT: [fast, other]}}
        )
        for r in rows:
            sent = {**r["item"], "key": fast}
            _ingest_pushed(*on_the_bus(bus, OPT, sent, r["ts_recv"], r["schwab_ts"]))
        untimed = {k: v for k, v in rows[0]["item"].items() if k != "TRADE_TIME_MILLIS"}
        _ingest_pushed(*on_the_bus(bus, OPT, {**untimed, "key": other}, rows[-1]["ts_recv"] + 1.0))
        few = push_tape.tape("SPY", at)["rows"]
        for later in (60_000, 120_000):
            for r in rows:
                sent = {**r["item"], "key": fast}
                for clock in ("TRADE_TIME_MILLIS", "QUOTE_TIME_MILLIS"):
                    if clock in sent:
                        sent[clock] += later
                received = r["ts_recv"] + later / 1000
                _ingest_pushed(*on_the_bus(bus, OPT, sent, received, r["schwab_ts"] + later))
        many = push_tape.tape("SPY", at)["rows"]
    finally:
        with level_store._lock:
            level_store._levels.pop("SPY", None)
        state.clear_all_live_state()
        forget_streamed()
    assert [(r["symbol"], r["trade_time_ms"]) for r in few] == [
        *((fast, t) for t in times[::-1]),
        (other, None),
    ]
    every = sorted((t + later for later in (0, 60_000, 120_000) for t in times), reverse=True)
    assert len(every) == 135 > push_tape.TAPE_ROWS == len(many)
    assert [(r["symbol"], r["trade_time_ms"]) for r in many] == [
        (fast, t) for t in every[: push_tape.TAPE_ROWS]
    ]


def test_prints_are_kept_in_receive_order_each_with_its_messages_receive_time():
    sent = _sent(CALL)
    received = [at for at, _ in sent]
    rows = _tape(CALL, sent)
    assert len(rows) == 4
    assert [r.server_received_ts for r in rows] == received[::-1]
    assert rows[0].price == 2.03  # the LAST (newest) genuine trade recorded


def test_a_contract_never_recorded_and_a_blank_symbol_serve_no_prints():
    """INDUCED: the call's second message with no symbol never reaches the bus or a tape.

    The daemon's stream handler takes no item without a symbol (feed.connection._publisher).
    """
    (at, first), (later, second) = _sent(CALL)[:2]
    live = _fed(CALL, [(at, first)])
    bus = MessageBus()
    frame = {"timestamp": None, "content": [{**second, "key": ""}]}
    connection._publisher(OPT, bus, HealthRegistry(), lambda: later)(frame)
    assert bus.current == {}
    assert live.prints(PUT) == []
    assert live.prints("") == []
    assert len(live.prints(CALL)) == 1
