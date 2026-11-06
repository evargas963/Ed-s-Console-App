"""ORDER_FLOW_TRUSTED_VERTICAL_SLICE_1 — L1 identity, receive order, tick-rule PROXY.

Each trade is one LEVELONE message as Schwab sends it (LAST_PRICE, LAST_SIZE, TRADE_TIME_MILLIS),
taken through the live state (state.push_level_one: the one reader, l1.extract_vendor_print, and
the restatement rule) in receive order; the engine reads what the state recorded.

# next-rth-ok: identity/ordering substrate; not a live-session residual
# universal-scope-ok: enrolled-universe contract, not a SPY sample
# chart-intent-ok: does not claim Chart Done
"""

from __future__ import annotations

import math

import app.options.order_flow.engine as ofe
import app.options.order_flow.state as live_state
import l1_trade_observation as l1
import time_et
from app.options.order_flow.state import OrderFlowState


def _tape(sym: str, *rows, state=None) -> list:
    """Each (price, size, trade time) as one LEVELONE message, pushed through the live state (or
    `state`) in receive order: the content the engine reads."""
    st = live_state._LIVE_STATE if state is None else state
    st.clear_symbol(sym)
    for i, (price, size, trade_ms) in enumerate(rows):
        st.push_level_one(
            sym,
            {"key": sym, "LAST_PRICE": price, "LAST_SIZE": size, "TRADE_TIME_MILLIS": trade_ms},
            ts_recv=1000.0 + i,
        )
    return st.get_content_for_symbol(sym)


def test_distinct_same_ms_price_change_retained():
    content = _tape("L1A", (500.0, 10, 1000), (500.1, 10, 1000))
    out = l1.canonical_tape_prints(content)
    assert len(out) == 2
    assert [p["price"] for p in out] == [500.0, 500.1]
    assert ofe._compute_cum_delta_proxy({"content": content}) == 10


def test_distinct_same_ms_size_change_retained():
    content = _tape("L1B", (500.0, 10, 1000), (500.0, 4, 1000))
    out = l1.canonical_tape_prints(content)
    assert len(out) == 2
    assert [p["size"] for p in out] == [10, 4]


def test_adjacent_identical_restatement_suppressed():
    content = _tape("L1C", (500.0, 10, 1000), (500.1, 10, 2000), (500.1, 10, 2000))
    assert len(l1.canonical_tape_prints(content)) == 2
    assert ofe._compute_cum_delta_proxy({"content": content}) == 10


def test_non_adjacent_identical_triple_retained():
    content = _tape("L1D", (500.0, 10, 1000), (500.1, 4, 1000), (500.0, 10, 1000))
    out = l1.canonical_tape_prints(content)
    assert len(out) == 3


def test_out_of_order_vendor_timestamps_preserve_receive_order():
    content = _tape("L1E", (500.0, 10, 2000), (500.2, 5, 1000))
    prints = l1.canonical_tape_prints(content)
    assert [p["time_millis"] for p in prints] == [2000, 1000]
    assert ofe._compute_cum_delta_proxy({"content": content}) == 5


def test_tick_rule_bullish_bearish_sign_mutation():
    assert l1.tick_rule_signed_size(500.0, 500.1, 10) == 10.0
    assert l1.tick_rule_signed_size(500.1, 500.0, 10) == -10.0
    assert l1.tick_rule_signed_size(500.0, 500.0, 10) == 0.0
    flipped = l1.tick_rule_signed_size(500.0, 500.1, 10)
    assert flipped != l1.tick_rule_signed_size(500.1, 500.0, 10)


def test_missing_size_remains_unavailable():
    assert l1.tick_rule_signed_size(500.0, 500.1, None) is None
    assert l1.extract_vendor_print({"LAST_SIZE": 10, "TRADE_TIME_MILLIS": 1}) is None
    assert l1.compute_cum_delta_proxy([{"price": 1.0, "size": None, "time_millis": 1}]) is None


def test_reconnect_clear_resets_restatement_identity():
    sym = "RECON"
    live_state.clear_symbol(sym)
    live_state.push_level_one(
        sym,
        {"key": sym, "LAST_PRICE": 10.0, "LAST_SIZE": 1, "TRADE_TIME_MILLIS": 5},
        ts_recv=time_et.now(),
    )
    live_state.clear_all_live_state()
    live_state.push_level_one(
        sym,
        {"key": sym, "LAST_PRICE": 10.0, "LAST_SIZE": 1, "TRADE_TIME_MILLIS": 5},
        ts_recv=time_et.now(),
    )
    tape = l1.canonical_tape_prints(live_state.get_content_for_symbol(sym))
    assert len(tape) == 1
    assert tape[0]["receive_seq"] == 1
    assert tape[0]["native_event_id"] is False


def test_live_state_equals_replay_of_same_receive_order_observations():
    rows = [(1.0, 1, 30), (1.1, 2, 10)]
    live_cvd = ofe._compute_cum_delta_proxy({"content": _tape("REPLAY1", *rows)})
    replay_cvd = ofe._compute_cum_delta_proxy(
        {"content": _tape("REPLAY1", *rows, state=OrderFlowState())}
    )
    assert live_cvd == replay_cvd == 2


def test_mutation_first_per_ms_fails_current_keep():
    content = _tape("L1F", (500.0, 10, 1000), (500.1, 4, 1000))
    current = l1.canonical_tape_prints(content)
    seen: set[int] = set()
    old = []
    for p in current:
        ms = p["time_millis"]
        if ms in seen:
            continue
        seen.add(ms)
        old.append(p)
    assert len(current) == 2
    assert len(old) == 1
    assert ofe._compute_cum_delta_proxy({"content": content}) == 4
    assert l1.compute_cum_delta_proxy(old) == 0.0


def test_mutation_vendor_time_sort_fails_receive_order():
    rows = [(500.0, 10, 2000), (500.2, 5, 1000)]
    receive_cvd = ofe._compute_cum_delta_proxy({"content": _tape("L1G", *rows)})
    vendor_sorted = sorted(rows, key=lambda r: r[2])
    sorted_cvd = ofe._compute_cum_delta_proxy({"content": _tape("L1H", *vendor_sorted)})
    assert receive_cvd == 5
    assert sorted_cvd != receive_cvd


def test_slope_uses_same_signed_size_walk():
    content = _tape("L1I", (500.0, 10, 1000), (500.1, 4, 2000), (499.9, 6, 3000))
    prints = l1.canonical_tape_prints(content)
    points = l1.iter_signed_cum_points(prints)
    assert points[-1][1] == l1.compute_cum_delta_proxy(prints) == 4 - 6
    assert [(round(t, 6), c) for t, c in points] == [(1.0, 0.0), (2.0, 4.0), (3.0, -2.0)]
    slope = ofe._compute_cum_delta_slope({"content": content}, now=3.0, window_sec=60.0)
    assert slope is not None
    assert math.isclose(slope, -1.0, rel_tol=0.0, abs_tol=1e-9)
