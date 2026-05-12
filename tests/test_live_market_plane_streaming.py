"""live_market_plane: streaming Level One ingestion vs REST."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import live_market_plane as lmp


def test_record_from_level_one_equity_updates_plane():
    lmp.record_quote(
        "ZZZ",
        {
            "ticker": "ZZZ",
            "spot": 1.0,
            "bid": 0.9,
            "ask": 1.1,
            "spot_disp": "1.00",
            "bid_disp": "0.90",
            "ask_disp": "1.10",
            "spread": 0.2,
            "fast_generation_id": lmp.next_fast_generation("ZZZ"),
            "fast_server_ts": 100.0,
            "quote_ingestion": "rest_fast_quote",
        },
    )
    ok = lmp.record_from_level_one_equity(
        "ZZZ",
        {"key": "ZZZ", "LAST_PRICE": 101.0, "BID_PRICE": 100.9, "ASK_PRICE": 101.1},
    )
    assert ok is True
    row = lmp.get_quote("ZZZ")
    assert row is not None
    assert row["quote_ingestion"] == "schwab_streaming_level_one"
    assert abs(row["spot"] - 101.0) < 1e-6
    assert row["quote_source_detail"]["spot"] == "LAST_PRICE"
    assert row["quote_source_detail"]["spread"] == "schwab_bid_ask"
    assert row["quote_source_detail"]["carried_forward"] is False


def test_record_from_level_one_uses_schwab_quote_timestamp_for_fast_ts():
    ok = lmp.record_from_level_one_equity(
        "TIMEAUTH",
        {
            "key": "TIMEAUTH",
            "LAST_PRICE": 101.0,
            "BID_PRICE": 100.9,
            "ASK_PRICE": 101.1,
            "QUOTE_TIME_MILLIS": 1_778_018_399_000,
        },
    )

    assert ok is True
    row = lmp.get_quote("TIMEAUTH")
    assert row is not None
    assert row["fast_server_ts"] == 1_778_018_399.0
    assert row["quote_time_source"] == "schwab_streaming_level_one"
    assert isinstance(row["server_received_ts"], float)


def test_record_from_level_one_new_schwab_timestamp_not_suppressed_as_duplicate():
    lmp.record_from_level_one_equity(
        "TIMEDUP",
        {
            "key": "TIMEDUP",
            "LAST_PRICE": 50.0,
            "BID_PRICE": 49.9,
            "ASK_PRICE": 50.1,
            "QUOTE_TIME_MILLIS": 1_778_018_399_000,
        },
    )
    g0 = lmp.get_quote("TIMEDUP")["fast_generation_id"]

    ok = lmp.record_from_level_one_equity(
        "TIMEDUP",
        {
            "key": "TIMEDUP",
            "LAST_PRICE": 50.0,
            "BID_PRICE": 49.9,
            "ASK_PRICE": 50.1,
            "QUOTE_TIME_MILLIS": 1_778_018_400_000,
        },
    )

    assert ok is True
    row = lmp.get_quote("TIMEDUP")
    assert row["fast_generation_id"] > g0
    assert row["fast_server_ts"] == 1_778_018_400.0


def test_record_from_level_one_does_not_carry_forward_missing_bid_ask():
    lmp.record_quote(
        "NOCARRY",
        {
            "ticker": "NOCARRY",
            "spot": 10.0,
            "bid": 9.9,
            "ask": 10.1,
            "spot_disp": "10.00",
            "bid_disp": "9.90",
            "ask_disp": "10.10",
            "spread": 0.02,
            "fast_generation_id": lmp.next_fast_generation("NOCARRY"),
            "fast_server_ts": 100.0,
            "quote_ingestion": "rest_fast_quote",
        },
    )

    ok = lmp.record_from_level_one_equity(
        "NOCARRY",
        {"key": "NOCARRY", "LAST_PRICE": 11.0},
    )

    assert ok is True
    row = lmp.get_quote("NOCARRY")
    assert row is not None
    assert row["spot"] == 11.0
    assert row["bid"] is None
    assert row["ask"] is None
    assert row["spread"] is None
    assert row["spread_pts"] is None
    assert row["quote_source_detail"]["spread"] == "unavailable_missing_bid_or_ask"
    assert row["quote_source_detail"]["previous_bid_available"] is True
    assert row["quote_source_detail"]["carried_forward"] is False


def test_record_from_level_one_uses_mark_but_not_midpoint_for_spot():
    ok = lmp.record_from_level_one_equity(
        "MARKONLY",
        {"key": "MARKONLY", "MARK": 20.95, "BID_PRICE": 20.9, "ASK_PRICE": 21.1},
    )

    assert ok is True
    row = lmp.get_quote("MARKONLY")
    assert row is not None
    assert row["spot"] == 20.95
    assert row["quote_source_detail"]["spot"] == "MARK"
    # Wire-first: quote_mid follows Schwab MARK, not (bid+ask)/2 (which would be 21.0).
    assert row["quote_mid"] == 20.95
    assert row["mid_source"] == "schwab_streaming_mark"
    assert row["spread_source"] == "derived_bid_ask_fraction_schwab_mark_denom"
    assert row["quote_source_detail"]["mid"] == "schwab_streaming_mark"


def test_record_from_level_one_rejects_midpoint_spot_fabrication():
    ok = lmp.record_from_level_one_equity(
        "MIDONLY",
        {"key": "MIDONLY", "BID_PRICE": 30.0, "ASK_PRICE": 30.2},
    )

    assert ok is False
    assert lmp.get_quote("MIDONLY") is None


def test_record_from_level_one_skips_duplicate_sig():
    lmp.record_from_level_one_equity(
        "AAA",
        {"key": "AAA", "LAST_PRICE": 50.0, "BID_PRICE": 49.9, "ASK_PRICE": 50.1},
    )
    g0 = lmp.get_quote("AAA")["fast_generation_id"]
    ok = lmp.record_from_level_one_equity(
        "AAA",
        {"key": "AAA", "LAST_PRICE": 50.0, "BID_PRICE": 49.9, "ASK_PRICE": 50.1},
    )
    assert ok is False
    g1 = lmp.get_quote("AAA")["fast_generation_id"]
    assert g0 == g1


def test_next_fast_generation_monotonic():
    a = lmp.next_fast_generation("M")
    b = lmp.next_fast_generation("M")
    assert b > a
