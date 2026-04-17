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
