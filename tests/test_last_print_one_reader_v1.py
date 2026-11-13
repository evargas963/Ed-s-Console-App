"""The last trade Schwab streams (LAST_PRICE, LAST_SIZE, TRADE_TIME_MILLIS) has one reader.

`l1_trade_observation.last_print` reads the three fields of a LEVELONE message; the price store
(`live_market_plane`) and the tape (`order_flow.state`) both take them from it.

Real data: every LEVELONE_EQUITIES message Schwab sent in three seconds of 2026-10-05, 14:00 CT
(real_stream_mix_2026_10_05_1400ct.json), each as stored, in receive order.
"""

from __future__ import annotations

import json
from pathlib import Path

import l1_trade_observation as l1
import live_market_plane as lmp
from app.options.order_flow import state
from tools.check_one_reader import fields_read

ROOT = Path(__file__).resolve().parent.parent
PRINT_FIELDS = {"LAST_PRICE", "LAST_SIZE", "TRADE_TIME_MILLIS"}
MESSAGES = [
    m
    for m in json.loads(
        (ROOT / "tests/fixtures/real_stream_mix_2026_10_05_1400ct.json").read_text(encoding="utf-8")
    )["messages"]
    if m["service"] == "LEVELONE_EQUITIES"
]


def test_only_the_one_reader_takes_the_last_trades_fields_out_of_a_message():
    def read_by(path: str) -> set[str]:
        return fields_read((ROOT / path).read_text(encoding="utf-8"), PRINT_FIELDS)

    assert read_by("l1_trade_observation.py") == PRINT_FIELDS
    assert read_by("live_market_plane.py") == set()
    assert read_by("app/options/order_flow/state.py") == set()
    own = lmp._PRICE_FIELDS + lmp._COUNT_FIELDS + lmp._CLOCK_FIELDS
    assert PRINT_FIELDS.isdisjoint(own)


def test_the_price_row_and_the_tape_hold_the_same_last_trade_as_schwab_sent_it():
    tickers = sorted({m["item"]["key"] for m in MESSAGES})
    sent: dict[str, dict] = {tk: {} for tk in tickers}
    prints: dict[str, list] = {tk: [] for tk in tickers}
    assert len(MESSAGES) > 100
    live = state.OrderFlowState()
    try:
        for m in MESSAGES:
            item, tk = m["item"], m["item"]["key"]
            lmp.record_from_level_one_equity(tk, item, received_ts=m["ts_recv"])
            live.push_level_one(tk, item, ts_recv=m["ts_recv"])
            sent[tk].update({f: item[f] for f in PRINT_FIELDS if f in item})
            if "LAST_PRICE" in item:
                triple = (item.get("TRADE_TIME_MILLIS"), item["LAST_PRICE"], item.get("LAST_SIZE"))
                if prints[tk][-1:] != [triple]:
                    prints[tk].append(triple)
        for tk in tickers:
            row, last = lmp.get_quote(tk), sent[tk]
            millis = last.get("TRADE_TIME_MILLIS")
            assert row["spot"] == last.get("LAST_PRICE")
            assert row["last_size"] == last.get("LAST_SIZE")
            assert row["trade_ts"] == (None if millis is None else millis / 1000)
            tape = live.get_content_for_symbol(tk)
            assert [(p["time_millis"], p["price"], p["size"]) for p in tape] == prints[tk]
        assert any(prints.values())
    finally:
        for tk in tickers:
            lmp._by_ticker.pop(tk, None)
            lmp._fields_by_ticker.pop(tk, None)


def test_a_last_price_schwab_sends_as_no_number_clears_the_price_and_makes_no_print():
    item = next(m["item"] for m in MESSAGES if set(m["item"]) >= PRINT_FIELDS)
    assert l1.last_print({**item, "LAST_PRICE": -999}) == {
        "LAST_PRICE": None,
        "LAST_SIZE": item["LAST_SIZE"],
        "TRADE_TIME_MILLIS": item["TRADE_TIME_MILLIS"],
    }
    assert l1.extract_vendor_print({**item, "LAST_PRICE": -999}) is None
    assert l1.last_print({"BID_PRICE": 1.0}) == {}
