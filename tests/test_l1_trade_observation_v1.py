"""ORDER_FLOW_TRUSTED_VERTICAL_SLICE_1 — L1 identity, receive order, tick-rule PROXY.

# next-rth-ok: identity/ordering substrate; not a live-session residual
# universal-scope-ok: enrolled-universe contract, not a SPY sample
# chart-intent-ok: does not claim Chart Done
"""

from __future__ import annotations

import math

import l1_trade_observation as l1
import app.options.order_flow.engine as ofe
import app.options.order_flow.state as live_state


def _prints(*rows):
    return [
        {"LAST_PRICE": p, "LAST_SIZE": s, "TRADE_TIME_MILLIS": t}
        for p, s, t in rows
    ]


def test_distinct_same_ms_price_change_retained():
    content = _prints((500.0, 10, 1000), (500.1, 10, 1000))
    out = l1.canonical_tape_prints(content)
    assert len(out) == 2
    assert [p["price"] for p in out] == [500.0, 500.1]
    assert ofe._compute_cum_delta_proxy({"content": content}) == 10


def test_distinct_same_ms_size_change_retained():
    content = _prints((500.0, 10, 1000), (500.0, 4, 1000))
    out = l1.canonical_tape_prints(content)
    assert len(out) == 2
    assert [p["size"] for p in out] == [10, 4]


def test_adjacent_identical_restatement_suppressed():
    content = _prints((500.0, 10, 1000), (500.1, 10, 2000), (500.1, 10, 2000))
    assert len(l1.canonical_tape_prints(content)) == 2
    assert ofe._compute_cum_delta_proxy({"content": content}) == 10


def test_non_adjacent_identical_triple_retained():
    content = _prints((500.0, 10, 1000), (500.1, 4, 1000), (500.0, 10, 1000))
    out = l1.canonical_tape_prints(content)
    assert len(out) == 3


def test_out_of_order_vendor_timestamps_preserve_receive_order():
    content = _prints((500.0, 10, 2000), (500.2, 5, 1000))
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
    assert l1.NATIVE_AGGRESSOR_AVAILABLE is False
    assert l1.NATIVE_TIME_AND_SALES_AVAILABLE is False
    assert l1.TIMESALE_SERVICE_STATUS == "UNAVAILABLE"
    assert l1.TAPE_CLASSIFICATION == "PROXY_RECONSTRUCTED_L1_TICK"


def test_reconnect_clear_resets_restatement_identity():
    sym = "RECON"
    live_state.clear_symbol(sym)
    live_state.push_level_one(sym, {"key": sym, "LAST_PRICE": 10.0, "LAST_SIZE": 1, "TRADE_TIME_MILLIS": 5})
    live_state.clear_all_live_state()
    live_state.push_level_one(sym, {"key": sym, "LAST_PRICE": 10.0, "LAST_SIZE": 1, "TRADE_TIME_MILLIS": 5})
    tape = [i for i in live_state.get_content_for_symbol(sym) if i.get("LAST_PRICE") is not None]
    assert len(tape) == 1
    assert tape[0]["receive_seq"] == 1
    assert tape[0]["native_event_id"] is False


def test_live_state_equals_replay_of_same_receive_order_observations():
    sym = "REPLAY1"
    live_state.clear_symbol(sym)
    rows = [
        {"key": sym, "LAST_PRICE": 1.0, "LAST_SIZE": 1, "TRADE_TIME_MILLIS": 30},
        {"key": sym, "LAST_PRICE": 1.1, "LAST_SIZE": 2, "TRADE_TIME_MILLIS": 10},
    ]
    for r in rows:
        live_state.push_level_one(sym, r)
    live_cvd = ofe._compute_cum_delta_proxy({"content": live_state.get_content_for_symbol(sym)})
    replay_cvd = ofe._compute_cum_delta_proxy({"content": rows})
    assert live_cvd == replay_cvd == 2


def test_mutation_first_per_ms_fails_current_keep():
    content = _prints((500.0, 10, 1000), (500.1, 4, 1000))
    current = l1.canonical_tape_prints(content)
    seen: set[int] = set()
    old = []
    for p in l1.iter_content_prints(content):
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
    content = _prints((500.0, 10, 2000), (500.2, 5, 1000))
    receive_cvd = ofe._compute_cum_delta_proxy({"content": content})
    vendor_sorted = sorted(content, key=lambda r: r["TRADE_TIME_MILLIS"])
    sorted_cvd = ofe._compute_cum_delta_proxy({"content": vendor_sorted})
    assert receive_cvd == 5
    assert sorted_cvd != receive_cvd
    src = open("app/options/order_flow/engine.py", encoding="utf-8").read()
    assert "sorted(prints" not in src
    assert 'key=lambda x: x.get("time_millis")' not in src


def test_source_contract_is_proxy_not_native_tns():
    c = l1.source_contract()
    assert c["native_aggressor_available"] is False
    assert c["native_time_and_sales_available"] is False
    assert c["timesale_service_status"] == "UNAVAILABLE"
    assert c["tape_pressure_classification"] == "PROXY_RECONSTRUCTED_L1_TICK"
    engine = ofe.OrderFlowEngine().compute({"content": _prints((500.0, 10, 1), (500.1, 10, 2))})
    assert engine["native_aggressor_available"] is False
    assert engine["timesale_service_status"] == "UNAVAILABLE"
    assert engine["tape_completeness"] == "INCOMPLETE_OBSERVATION"


def test_slope_uses_same_signed_size_walk():
    content = _prints((500.0, 10, 1000), (500.1, 4, 2000), (499.9, 6, 3000))
    prints = l1.canonical_tape_prints(content)
    points = l1.iter_signed_cum_points(prints)
    assert points[-1][1] == l1.compute_cum_delta_proxy(prints) == 4 - 6
    assert [(round(t, 6), c) for t, c in points] == [(1.0, 0.0), (2.0, 4.0), (3.0, -2.0)]
    slope = ofe._compute_cum_delta_slope({"content": content}, window_sec=60.0)
    assert slope is not None
    assert math.isclose(slope, -1.0, rel_tol=0.0, abs_tol=1e-9)


def test_receive_seq_is_monotonic_and_not_a_native_id():
    sym = "RECV1"
    live_state.clear_symbol(sym)
    live_state.push_level_one(sym, {"key": sym, "LAST_PRICE": 10.0, "LAST_SIZE": 1, "TRADE_TIME_MILLIS": 5})
    live_state.push_level_one(sym, {"key": sym, "LAST_PRICE": 10.0, "LAST_SIZE": 1, "TRADE_TIME_MILLIS": 5})
    live_state.push_level_one(sym, {"key": sym, "LAST_PRICE": 10.1, "LAST_SIZE": 2, "TRADE_TIME_MILLIS": 5})
    tape = [i for i in live_state.get_content_for_symbol(sym) if "receive_seq" in i]
    log = live_state.get_receive_log(sym)
    assert [x["receive_seq"] for x in log] == [1, 2, 3]
    assert len(tape) == 2
    assert tape[0]["native_event_id"] is False
