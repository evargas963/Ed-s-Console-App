"""ORDER_FLOW_TRUSTED_VERTICAL_SLICE_1 — L1 identity, receive order, Lee and Ready PROXY.

Each trade is one LEVELONE message as Schwab sends it (LAST_PRICE, LAST_SIZE, TRADE_TIME_MILLIS),
taken through the live state (state.push_level_one: the one reader, l1.extract_vendor_print, and
the restatement rule) in receive order; the engine reads what the state recorded.

Real data: SPY's LEVELONE_EQUITIES message of 2026-11-11 as Schwab sent it
(tests/fixtures/real_premarket_first_prints_2026_11_11.json). INDUCED CONDITIONS: each case's
prints are that message with its LAST_PRICE (`P`, its own last price, and a tick or two from it),
LAST_SIZE and TRADE_TIME_MILLIS set to the case's, and its quote timed at the trade. The window's
boundary is that file's messages of SPY, TSLA and IWM as sent, unchanged.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import app.options.order_flow.state as live_state
import calc.l1_trade_observation as l1
import time_et
from app.options.order_flow.state import OrderFlowState
from calc import order_flow as ofe
from stream_spine import MessageBus
from tests.feed_live_helper import apply_record, on_the_bus

EQ = "LEVELONE_EQUITIES"

#: each ticker's last print of 2026-11-10's evening, then its first of 2026-11-11, as sent
_MESSAGES = json.loads(
    (Path(__file__).parent / "fixtures" / "real_premarket_first_prints_2026_11_11.json").read_text(
        encoding="utf-8"
    )
)["messages"]
_SENT = next(m["item"] for m in _MESSAGES if m["ticker"] == "SPY")
#: SPY's last price in that message: every case's prices are it and a tick or two from it
P = _SENT["LAST_PRICE"]


def _sent(sym: str, price: float | None, size: float | None, trade_ms: int) -> dict:
    """SPY's real message, keyed `sym`, with the case's print: its bid and ask at that price.

    The quote is timed at the trade (QUOTE_TIME_MILLIS = the trade's time), so it is the quote in
    force when the print traded (l1.quote_in_force).
    """
    return {
        **_SENT,
        "key": sym,
        "LAST_PRICE": price,
        "LAST_SIZE": size,
        "TRADE_TIME_MILLIS": trade_ms,
        "BID_PRICE": price,
        "ASK_PRICE": price,
        "QUOTE_TIME_MILLIS": trade_ms,
    }


def _tape(sym: str, *rows, state=None) -> list:
    """Each (price, size, trade time) as one LEVELONE message, through a bus to the live state.

    Each goes on a bus of its own, as the daemon puts it, and its record to the live state (or
    `state`), as the console applies it, in receive order: the content the engine reads. Each
    message's bid and ask are at its price, so Lee and Ready's midpoint is the price and the tick
    test signs it (Lee and Ready on a real quote: tests/test_tape_lee_ready_v1.py).
    """
    st = live_state._LIVE_STATE if state is None else state
    st.clear_all()
    bus = MessageBus()
    st.current = bus.current
    for i, (price, size, trade_ms) in enumerate(rows):
        msg = _sent(sym, price, size, trade_ms)
        apply_record(st, EQ, on_the_bus(bus, EQ, msg, 1000.0 + i))
    return st.prints(sym)


def _cvd(content: list) -> float | None:
    """Return the cumulative delta of the tape `content`, as the engine computes it."""
    return l1.compute_cum_delta_proxy(content)


def test_distinct_same_ms_price_change_retained():
    content = _tape("L1A", (P, 10, 1000), (P + 0.1, 10, 1000))
    out = content
    assert len(out) == 2
    assert [p.price for p in out] == [P, P + 0.1]
    assert _cvd(content) == 10


def test_distinct_same_ms_size_change_retained():
    content = _tape("L1B", (P, 10, 1000), (P, 4, 1000))
    out = content
    assert len(out) == 2
    assert [p.size for p in out] == [10, 4]


def test_adjacent_identical_restatement_suppressed():
    content = _tape("L1C", (P, 10, 1000), (P + 0.1, 10, 2000), (P + 0.1, 10, 2000))
    assert len(content) == 2
    assert _cvd(content) == 10


def test_schwabs_whole_record_restating_the_held_trade_is_no_second_print():
    """AMD's LEVELONE_EQUITIES messages of 2026-11-18 06:53:20-06:53:53 ET, as Schwab sent them.

    Real data (tests/fixtures/real_amd_levelone_restated_2026_11_18.json). Schwab streams only
    the fields that changed (Streamer API §1.5, delivery Change): a trade at the held price and
    size carries its new TRADE_TIME_MILLIS alone; a quote's change carries no trade field. At
    06:53:47 the subscription's whole record (it carries assetMainType, as a delta never does)
    restates the held trade, every field equal. The tape keeps each trade once: four, each a step
    of Schwab's TOTAL_VOLUME by its size (worked out here from the messages), and the restating
    record and the quote changes none.
    """
    sent = json.loads(
        (
            Path(__file__).parent / "fixtures" / "real_amd_levelone_restated_2026_11_18.json"
        ).read_text(encoding="utf-8")
    )["messages"]
    trades = [m["item"] for m in sent if "TRADE_TIME_MILLIS" in m["item"]]
    whole = [m["item"] for m in sent if "assetMainType" in m["item"]]
    assert len(whole) == 1 and whole[0] in trades
    volumes = [t["TOTAL_VOLUME"] for t in trades if t is not whole[0]]
    bus, state = MessageBus(), OrderFlowState()
    state.current = bus.current
    for m in sent:
        apply_record(state, EQ, on_the_bus(bus, EQ, m["item"], m["ts_recv"], m["schwab_ts"]))
    tape = state.prints("AMD")
    assert [(p.time_millis, p.price, p.size) for p in tape] == [
        (1795002799757, 513.5, 1),
        (1795002815201, 513.5, 1),
        (1795002816236, 513.57, 1),
        (1795002832692, 513.4874, 100),
    ]
    assert [b - a for a, b in zip(volumes, volumes[1:], strict=False)] == [p.size for p in tape[1:]]


def test_non_adjacent_identical_triple_retained():
    content = _tape("L1D", (P, 10, 1000), (P + 0.1, 4, 1000), (P, 10, 1000))
    out = content
    assert len(out) == 3


def test_out_of_order_vendor_timestamps_preserve_receive_order():
    content = _tape("L1E", (P, 10, 2000), (P + 0.2, 5, 1000))
    prints = content
    assert [p.time_millis for p in prints] == [2000, 1000]
    assert _cvd(content) == 5


def test_tick_rule_bullish_bearish_sign_mutation():
    """Up-tick +1, down-tick -1; a zero tick takes the last change's sign (Lee and Ready 1991)."""
    up = P + 0.1
    assert l1.tick_rule_sign(P, up, None) == 1
    assert l1.tick_rule_sign(up, P, None) == -1
    assert l1.tick_rule_sign(P, P, 1) == 1 and l1.tick_rule_sign(P, P, -1) == -1
    assert l1.tick_rule_sign(P, P, None) is None  # no change seen yet
    flipped = l1.tick_rule_sign(P, up, None)
    assert flipped != l1.tick_rule_sign(up, P, None)


def test_a_zero_tick_is_signed_by_the_last_price_change():
    """P, P + 0.10 (+4), the same (+6, zero up-tick), P (-2), P (-3): 4 + 6 - 2 - 3."""
    content = _tape(
        "L1Z",
        (P, 10, 1000),
        (P + 0.1, 4, 2000),
        (P + 0.1, 6, 3000),
        (P, 2, 4000),
        (P, 3, 5000),
    )
    prints = content
    assert [c for _t, c in l1.iter_signed_cum_points(prints, 1000.0)] == [0, 4, 10, 8, 5]
    # the first print is unsigned (no change seen): pressure is over the signed size, and the
    # unsigned share is served beside it
    assert l1.compute_tape_pressure(prints, window_sec=60.0, now_ms=5000.0) == 5 / 15
    assert l1.unsigned_share(prints, 5000.0 - 60000) == 10 / 25


def test_a_zero_tick_before_any_price_change_is_unsigned():
    """Two prints at one price, each at its quote's midpoint, before any price change: unsigned.

    INDUCED (the module's cases): at the midpoint the tick test signs, and a zero tick with no
    change seen has no sign (Lee and Ready 1991), so nothing is signed: no cumulative delta.
    """
    content = _tape("L1U", (P, 10, 1000), (P, 5, 2000))
    assert [signed for _t, _size, signed in l1._signed_walk(content, None)] == [None, None]
    assert _cvd(content) is None
    assert l1.unsigned_share(content) == 1.0


def test_the_days_first_print_is_its_windows_whole_pressure():
    """Each ticker's first print of 2026-11-11 alone in a 30 s window that begins at its trade.

    The evening's print traded hours before it. The first print is signed by Lee and Ready against
    the quote in force when it traded, worked out here from Schwab's own times. TSLA's own quote
    was timed before its trade: pressure is its sign whatever its size (one share), and none of
    its size is unsigned. SPY's and IWM's own quotes were timed after their trades, and the quote
    before each is the evening's, of the ET date before: no quote in force is known, so the print
    is unsigned, the window has no pressure and all of its size is unsigned. A window that begins
    one millisecond after the print holds no print: no value.
    """
    own: dict[str, bool] = {}
    for ticker in ("SPY", "TSLA", "IWM"):
        msgs = [m for m in _MESSAGES if m["ticker"] == ticker]
        bus, state = MessageBus(), OrderFlowState()
        state.current = bus.current
        for m in msgs:
            apply_record(state, EQ, on_the_bus(bus, EQ, m["item"], m["ts_recv"]))
        tape = state.prints(ticker)
        evening, first = msgs[0]["item"], msgs[-1]["item"]
        t = first["TRADE_TIME_MILLIS"]
        assert evening["TRADE_TIME_MILLIS"] < t - 30_000
        mid = (first["BID_PRICE"] + first["ASK_PRICE"]) / 2
        assert first["LAST_PRICE"] != mid
        # the evening's quote is the one before the first print's own, and of the date before
        assert time_et.et_date_str_from_ts_utc(evening["QUOTE_TIME_MILLIS"] / 1000) == "2026-11-10"
        assert time_et.et_date_str_from_ts_utc(t / 1000) == "2026-11-11"
        own[ticker] = first["QUOTE_TIME_MILLIS"] <= t
        sign = (1 if first["LAST_PRICE"] > mid else -1) if own[ticker] else None
        assert l1.compute_tape_pressure(tape, 30.0, t + 30_000) == sign
        assert l1.unsigned_share(tape, t) == (0.0 if own[ticker] else 1.0)
        assert l1.compute_tape_pressure(tape, 30.0, t + 30_001) is None
        assert l1.unsigned_share(tape, t + 1) is None
    assert own == {"SPY": False, "TSLA": True, "IWM": False}


def test_missing_size_remains_unavailable():
    assert l1.tick_rule_sign(P, None, 1) is None
    # the real message with no LAST_PRICE is no trade
    assert l1.extract_vendor_print({k: v for k, v in _SENT.items() if k != "LAST_PRICE"}) is None
    assert l1.compute_cum_delta_proxy(_tape("L1NOSIZE", (P, None, 1))) is None


def test_reconnect_clear_resets_restatement_identity():
    sym = "RECON"
    live_state.clear_all_live_state()
    bus = MessageBus()
    live_state.bind_bus(bus.current)
    st = live_state._LIVE_STATE
    apply_record(st, EQ, on_the_bus(bus, EQ, _sent(sym, P, 1, 5), 100.0))
    live_state.clear_all_live_state()
    apply_record(st, EQ, on_the_bus(bus, EQ, _sent(sym, P, 1, 5), 105.0))
    tape = live_state.prints(sym)
    assert len(tape) == 1


def test_live_state_equals_replay_of_same_receive_order_observations():
    rows = [(P, 1, 30), (P + 0.1, 2, 10)]
    live_cvd = _cvd(_tape("REPLAY1", *rows))
    replay_cvd = _cvd(_tape("REPLAY1", *rows, state=OrderFlowState()))
    assert live_cvd == replay_cvd == 2


def test_mutation_first_per_ms_fails_current_keep():
    content = _tape("L1F", (P, 10, 1000), (P + 0.1, 4, 1000))
    current = content
    seen: set[int] = set()
    old = []
    for p in current:
        ms = p.time_millis
        if ms in seen:
            continue
        seen.add(ms)
        old.append(p)
    assert len(current) == 2
    assert len(old) == 1
    assert _cvd(content) == 4
    assert l1.compute_cum_delta_proxy(old) is None  # its one print is unsigned: no value


def test_mutation_vendor_time_sort_fails_receive_order():
    rows = [(P, 10, 2000), (P + 0.2, 5, 1000)]
    receive_cvd = _cvd(_tape("L1G", *rows))
    vendor_sorted = sorted(rows, key=lambda r: r[2])
    sorted_cvd = _cvd(_tape("L1H", *vendor_sorted))
    assert receive_cvd == 5
    assert sorted_cvd != receive_cvd


def test_slope_uses_same_signed_size_walk():
    content = _tape("L1I", (P, 10, 1000), (P + 0.1, 4, 2000), (P - 0.1, 6, 3000))
    prints = content
    points = l1.iter_signed_cum_points(prints, 1000.0)  # from the first print
    assert points[-1][1] == l1.compute_cum_delta_proxy(prints) == 4 - 6
    assert [(round(t, 6), c) for t, c in points] == [(1.0, 0.0), (2.0, 4.0), (3.0, -2.0)]
    slope = ofe._compute_cum_delta_slope(prints, now=3.0, window_sec=60.0)
    assert slope is not None
    assert math.isclose(slope, -1.0, rel_tol=0.0, abs_tol=1e-9)


def test_a_window_keeps_only_the_prints_traded_at_or_after_its_start():
    """A 1.5 s window ending at 3 s: the print at 1 s is left out; its tick still signs the next."""
    content = _tape("L1W", (P, 10, 1000), (P + 0.1, 4, 2000), (P - 0.1, 6, 3000))
    prints = content
    assert [(round(t, 6), c) for t, c in l1.iter_signed_cum_points(prints, 1500.0)] == [
        (2.0, 4.0),
        (3.0, -2.0),
    ]
    slope = ofe._compute_cum_delta_slope(prints, now=3.0, window_sec=1.5)
    assert slope is not None
    assert math.isclose(slope, -6.0, rel_tol=0.0, abs_tol=1e-9)
