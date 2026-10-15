"""ORDER_FLOW_TRUSTED_VERTICAL_SLICE_1 — L1 identity, receive order, tick-rule PROXY, through the
one store of prints (history.RecentTape) and the engine that reads it.

# next-rth-ok: identity/ordering substrate; not a live-session residual
# universal-scope-ok: enrolled-universe contract, not a SPY sample
# chart-intent-ok: does not claim Chart Done
"""

from __future__ import annotations
import time

import math

import l1_trade_observation as l1
import app.options.order_flow.engine as ofe
import app.options.order_flow.state as live_state
from app.options.order_flow import history


def _records(*rows):
    """LEVELONE_EQUITIES records, each (LAST_PRICE, LAST_SIZE, TRADE_TIME_MILLIS)."""
    return [{"LAST_PRICE": p, "LAST_SIZE": s, "TRADE_TIME_MILLIS": t} for p, s, t in rows]


def _prints(records, tape=None, sym="L1OBS"):
    """The prints the one store keeps of `records`, received in this order."""
    tape = history.RecentTape() if tape is None else tape
    for r in records:
        tape.record_equity(sym, r, 1.0)
    return tape.prints(sym)


def test_distinct_same_ms_price_change_retained():
    out = _prints(_records((500.0, 10, 1000), (500.1, 10, 1000)))
    assert len(out) == 2
    assert [p["price"] for p in out] == [500.0, 500.1]
    assert ofe._compute_cum_delta_proxy({"prints": out}) == 10


def test_distinct_same_ms_size_change_retained():
    out = _prints(_records((500.0, 10, 1000), (500.0, 4, 1000)))
    assert len(out) == 2
    assert [p["size"] for p in out] == [10, 4]


def test_adjacent_identical_restatement_suppressed():
    out = _prints(_records((500.0, 10, 1000), (500.1, 10, 2000), (500.1, 10, 2000)))
    assert len(out) == 2
    assert ofe._compute_cum_delta_proxy({"prints": out}) == 10


def test_non_adjacent_identical_triple_retained():
    out = _prints(_records((500.0, 10, 1000), (500.1, 4, 1000), (500.0, 10, 1000)))
    assert len(out) == 3


def test_out_of_order_vendor_timestamps_preserve_receive_order():
    prints = _prints(_records((500.0, 10, 2000), (500.2, 5, 1000)))
    assert [p["time_millis"] for p in prints] == [2000, 1000]
    assert ofe._compute_cum_delta_proxy({"prints": prints}) == 5


def test_tick_rule_bullish_bearish_sign_mutation():
    assert l1.tick_rule_signed_size(500.0, 500.1, 10) == 10.0
    assert l1.tick_rule_signed_size(500.1, 500.0, 10) == -10.0
    assert l1.tick_rule_signed_size(500.0, 500.0, 10) == 0.0
    flipped = l1.tick_rule_signed_size(500.0, 500.1, 10)
    assert flipped != l1.tick_rule_signed_size(500.1, 500.0, 10)


def test_missing_size_remains_unavailable():
    assert l1.tick_rule_signed_size(500.0, 500.1, None) is None
    assert _prints([{"LAST_SIZE": 10, "TRADE_TIME_MILLIS": 1}]) == []      # no last price: no print
    assert l1.compute_cum_delta_proxy([{"price": 1.0, "size": None, "time_millis": 1}]) is None


def test_reconnect_clear_resets_restatement_identity():
    sym = "RECON"
    live_state.clear_symbol(sym)
    history.TAPE.record_equity(sym, {"key": sym, "LAST_PRICE": 10.0, "LAST_SIZE": 1, "TRADE_TIME_MILLIS": 5}, time.time())
    live_state.clear_all_live_state()
    history.TAPE.record_equity(sym, {"key": sym, "LAST_PRICE": 10.0, "LAST_SIZE": 1, "TRADE_TIME_MILLIS": 5}, time.time())
    assert len(history.TAPE.prints(sym)) == 1


def test_live_state_equals_replay_of_same_receive_order_observations():
    sym = "REPLAY1"
    live_state.clear_symbol(sym)
    rows = [
        {"key": sym, "LAST_PRICE": 1.0, "LAST_SIZE": 1, "TRADE_TIME_MILLIS": 30},
        {"key": sym, "LAST_PRICE": 1.1, "LAST_SIZE": 2, "TRADE_TIME_MILLIS": 10},
    ]
    for r in rows:
        history.TAPE.record_equity(sym, r, time.time())
    live_cvd = ofe._compute_cum_delta_proxy({"prints": history.TAPE.prints(sym)})
    replay_cvd = ofe._compute_cum_delta_proxy({"prints": _prints(rows, sym=sym)})
    assert live_cvd == replay_cvd == 2


def test_mutation_first_per_ms_fails_current_keep():
    records = _records((500.0, 10, 1000), (500.1, 4, 1000))
    current = _prints(records)
    seen: set[int] = set()
    old = []
    for r in records:                       # the old rule: the first print per trade ms
        ms = r["TRADE_TIME_MILLIS"]
        if ms in seen:
            continue
        seen.add(ms)
        old.append({"price": r["LAST_PRICE"], "size": r["LAST_SIZE"], "time_millis": ms})
    assert len(current) == 2
    assert len(old) == 1
    assert ofe._compute_cum_delta_proxy({"prints": current}) == 4
    assert l1.compute_cum_delta_proxy(old) == 0.0


def test_mutation_vendor_time_sort_fails_receive_order():
    records = _records((500.0, 10, 2000), (500.2, 5, 1000))
    receive_cvd = ofe._compute_cum_delta_proxy({"prints": _prints(records)})
    vendor_sorted = sorted(records, key=lambda r: r["TRADE_TIME_MILLIS"])
    sorted_cvd = ofe._compute_cum_delta_proxy({"prints": _prints(vendor_sorted)})
    assert receive_cvd == 5
    assert sorted_cvd != receive_cvd


def test_slope_uses_same_signed_size_walk():
    prints = _prints(_records((500.0, 10, 1000), (500.1, 4, 2000), (499.9, 6, 3000)))
    points = l1.iter_signed_cum_points(prints)
    assert points[-1][1] == l1.compute_cum_delta_proxy(prints) == 4 - 6
    assert [(round(t, 6), c) for t, c in points] == [(1.0, 0.0), (2.0, 4.0), (3.0, -2.0)]
    slope = ofe._compute_cum_delta_slope({"prints": prints}, now=3.0, window_sec=60.0)
    assert slope is not None
    assert math.isclose(slope, -1.0, rel_tol=0.0, abs_tol=1e-9)
