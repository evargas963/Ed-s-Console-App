"""P0.1-A adversarial controls: L1 observation identity, receive order, source class."""

from __future__ import annotations

from pathlib import Path

import l1_trade_observation as l1
import order_flow_engine as ofe
import order_flow_live_state as live_state


def _prints(*rows):
    return [
        {"LAST_PRICE": p, "LAST_SIZE": s, "TRADE_TIME_MILLIS": t}
        for p, s, t in rows
    ]


def test_distinct_same_ms_price_and_size_are_both_retained():
    content = _prints((500.0, 10, 1000), (500.1, 4, 1000))
    out = l1.canonical_tape_prints(content)
    assert len(out) == 2
    assert ofe._compute_cum_delta_proxy({"content": content}) == 4


def test_identical_adjacent_restatement_does_not_double_count():
    content = _prints((500.0, 10, 1000), (500.1, 10, 2000), (500.1, 10, 2000))
    assert len(l1.canonical_tape_prints(content)) == 2
    assert ofe._compute_cum_delta_proxy({"content": content}) == 10


def test_non_adjacent_identical_triple_is_kept():
    """A later reprint after a different observation is not a restatement."""
    content = _prints((500.0, 10, 1000), (500.1, 4, 1000), (500.0, 10, 1000))
    out = l1.canonical_tape_prints(content)
    assert len(out) == 3


def test_out_of_order_vendor_time_does_not_reorder_receive_sequence():
    content = _prints((500.0, 10, 2000), (500.2, 5, 1000))
    prints = l1.canonical_tape_prints(content)
    assert [p["time_millis"] for p in prints] == [2000, 1000]
    # Receive order: first print anchors, second is an uptick vs 500.0.
    assert ofe._compute_cum_delta_proxy({"content": content}) == 5


def test_missing_side_is_never_native_or_zero_aggressor():
    assert l1.NATIVE_AGGRESSOR_AVAILABLE is False
    assert l1.tick_rule_signed_size(None, 500.1, 10) is None
    signed = l1.tick_rule_signed_size(500.0, 500.0, 10)
    assert signed == 0.0  # unchanged price is not a buy/sell side


def test_source_contract_timesale_and_aggressor_unavailable():
    c = l1.source_contract()
    assert c["native_aggressor_available"] is False
    assert c["native_time_and_sales_available"] is False
    assert c["timesale_service_status"] == "UNAVAILABLE"
    assert c["tape_completeness"] == "INCOMPLETE_OBSERVATION"
    assert "not native time-and-sales" in c["tape_limitations"].lower()
    engine = ofe.OrderFlowEngine().compute({"content": _prints((500.0, 10, 1), (500.1, 10, 2))})
    assert engine["native_aggressor_available"] is False
    assert engine["timesale_service_status"] == "UNAVAILABLE"
    assert engine["tape_completeness"] == "INCOMPLETE_OBSERVATION"
    assert "native" not in str(engine["cum_delta_classification"]).lower() or "proxy" in str(engine["cum_delta_classification"]).lower()


def test_live_receive_seq_is_monotonic_and_not_a_native_id():
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
    assert tape[0]["completeness"] == "INCOMPLETE_OBSERVATION"


def test_reconnect_clear_does_not_treat_new_session_as_restatement():
    sym = "RECON"
    live_state.clear_symbol(sym)
    live_state.push_level_one(sym, {"key": sym, "LAST_PRICE": 10.0, "LAST_SIZE": 1, "TRADE_TIME_MILLIS": 5})
    live_state.clear_all_live_state()
    live_state.push_level_one(sym, {"key": sym, "LAST_PRICE": 10.0, "LAST_SIZE": 1, "TRADE_TIME_MILLIS": 5})
    tape = [i for i in live_state.get_content_for_symbol(sym) if i.get("LAST_PRICE") is not None]
    assert len(tape) == 1


def test_slope_uses_same_signed_size_walk():
    content = _prints((500.0, 10, 1000), (500.1, 4, 2000), (499.9, 6, 3000))
    prints = l1.canonical_tape_prints(content)
    points = l1.iter_signed_cum_points(prints)
    # Independent walk: first print anchors (signed None), then +4, then -6.
    assert points[-1][1] == l1.compute_cum_delta_proxy(prints) == 4 - 6
    # Points at t=1,2,3s with cum 0, +4, -2. Least-squares slope is -1.0.
    assert [(round(t, 6), c) for t, c in points] == [(1.0, 0.0), (2.0, 4.0), (3.0, -2.0)]
    slope = ofe._compute_cum_delta_slope({"content": content}, window_sec=60.0)
    assert slope == -1.0


def test_replay_matches_live_receive_order_semantics():
    """Live push path and engine replay of the same receive-order list must agree.

    Comparing ``_compute_cum_delta_proxy`` to itself on ``list(rows)`` is a
    tautology — it cannot detect a live/replay split. Drive live_state, then
    replay the original vendor rows through the engine faucet.
    """
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
    # Vendor-time sort would flip receive order and change the signed walk.
    vendor_sorted = sorted(rows, key=lambda r: r["TRADE_TIME_MILLIS"])
    assert ofe._compute_cum_delta_proxy({"content": vendor_sorted}) != live_cvd


def test_engine_does_not_sort_by_vendor_time():
    src = Path("order_flow_engine.py").read_text(encoding="utf-8")
    assert "sorted(prints" not in src
    assert "key=lambda x: x.get(\"time_millis\")" not in src
    assert "iter_signed_cum_points" in src
    assert "if price > prev_price:" not in src


def test_rest_second_cvd_producer_is_retired():
    src = Path("server.py").read_text(encoding="utf-8")
    assert "last_price >= ask_price" not in src
    assert "ms.cum_delta_proxy = _rest_cum_delta" not in src
    assert "Retired second CVD producer. Always None." in src


def test_frontend_does_not_reconstruct_trade_semantics():
    html = Path("static/index.html").read_text(encoding="utf-8")
    assert "TRADE_TIME_MILLIS" not in html
    assert "LAST_SIZE" not in html
    assert "timesale_service_status" in html
    assert "native_aggressor_available" in html
    assert "not native time-and-sales" in html


def test_old_rule_quantifies_lost_same_ms_size_and_price():
    """Old first-per-ms drops the second distinct same-ms print; current keeps it."""
    content = _prints((500.0, 10, 1000), (500.1, 4, 1000))
    q = l1.quantify_same_ms_old_rule_loss(content)
    assert q["total_observations"] == 2
    assert q["same_ms_groups"] == 1
    assert q["distinct_observations_inside_same_ms_groups"] == 2
    assert q["old_rule_suppressed_count"] == 1
    assert q["old_rule_suppressed_reported_size"] == 4
    assert q["old_rule_suppressed_price_transitions"] == 1
    assert q["is_live_rate"] is False
    assert l1.canonical_tape_prints(content)[1]["price"] == 500.1


def test_old_rule_does_not_count_adjacent_restatement_as_loss():
    content = _prints((500.0, 10, 1000), (500.0, 10, 1000))
    q = l1.quantify_same_ms_old_rule_loss(content)
    assert q["old_rule_suppressed_count"] == 0
    assert q["old_rule_suppressed_reported_size"] == 0
    assert q["old_rule_suppressed_price_transitions"] == 0
    assert q["same_ms_groups"] == 1
    assert q["distinct_observations_inside_same_ms_groups"] == 1


def test_source_contract_names_production_l1_service():
    c = l1.source_contract()
    assert c["production_l1_service"] == "LEVELONE_EQUITIES"
    assert c["production_l1_subscribe"] == "level_one_equity_subs"
    assert c["silent_source_fallback"] is False


def test_contract_identical_across_symbols():
    a = l1.canonical_tape_prints(_prints((100.0, 1, 1), (100.1, 2, 1)))
    b = l1.canonical_tape_prints(_prints((200.0, 1, 1), (200.1, 2, 1)))
    assert len(a) == len(b) == 2
    assert ofe._compute_cum_delta_proxy({"content": _prints((100.0, 1, 1), (100.1, 2, 1))}) == 2
    assert ofe._compute_cum_delta_proxy({"content": _prints((200.0, 1, 1), (200.1, 2, 1))}) == 2


def test_tick_rule_sign_flip_and_missing_size_are_detected():
    """BREAK THE INVARIANT: bullish/bearish swap or missing→0 must fail these."""
    assert l1.tick_rule_signed_size(500.0, 500.1, 10) == 10.0
    assert l1.tick_rule_signed_size(500.1, 500.0, 10) == -10.0
    assert l1.tick_rule_signed_size(500.0, 500.0, 10) == 0.0
    assert l1.tick_rule_signed_size(500.0, 500.1, None) is None
    assert l1.tick_rule_signed_size(None, 500.1, 10) is None
    assert l1.extract_vendor_print({"LAST_SIZE": 10, "TRADE_TIME_MILLIS": 1}) is None
    assert l1.compute_cum_delta_proxy([]) is None
    assert l1.compute_cum_delta_proxy([{"price": 1.0, "size": None, "time_millis": 1}]) is None


def test_mutation_first_per_ms_disagrees_with_current_same_ms_keep():
    """Old first-per-TRADE_TIME_MILLIS is a surviving mutation of the identity rule."""
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
    assert l1.compute_cum_delta_proxy(old) == 0.0  # lone first print has no prev side
