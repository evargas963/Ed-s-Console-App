#!/usr/bin/env python3
"""
Test Order Flow live integration.
Seeds order_flow_live_state with mock streaming data, then runs the engine.
Run: python test_order_flow_live.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from order_flow_live_state import push_book, push_level_one, get_content_for_symbol, clear_symbol
from order_flow_engine import OrderFlowEngine


def main():
    clear_symbol("SPY")

    book_item = {
        "key": "SPY",
        "BIDS": [
            {"BID_PRICE": 600.0, "TOTAL_VOLUME": 200},
            {"BID_PRICE": 599.9, "TOTAL_VOLUME": 150},
            {"BID_PRICE": 599.8, "TOTAL_VOLUME": 100},
            {"BID_PRICE": 599.7, "TOTAL_VOLUME": 80},
            {"BID_PRICE": 599.6, "TOTAL_VOLUME": 120},
        ],
        "ASKS": [
            {"ASK_PRICE": 600.1, "TOTAL_VOLUME": 80},
            {"ASK_PRICE": 600.2, "TOTAL_VOLUME": 120},
            {"ASK_PRICE": 600.3, "TOTAL_VOLUME": 90},
            {"ASK_PRICE": 600.4, "TOTAL_VOLUME": 70},
            {"ASK_PRICE": 600.5, "TOTAL_VOLUME": 100},
        ],
    }
    push_book("SPY", book_item)

    for i, (price, size) in enumerate([(600.05, 50), (600.06, 75), (599.98, 100), (600.02, 25)]):
        push_level_one("SPY", {
            "key": "SPY",
            "LAST_PRICE": price,
            "LAST_SIZE": size,
            "TRADE_TIME_MILLIS": 1700000000000 + i * 1000,
            "BID_PRICE": 600.0, "ASK_PRICE": 600.1, "BID_SIZE": 440, "ASK_SIZE": 80,
        })

    content = get_content_for_symbol("SPY")
    data = {
        "content": content,
        "quote": {"bidPrice": 600.0, "askPrice": 600.1, "totalVolume": 1_200_000},
        "callExpDateMap": {"2025-03-21:1": {"600.0": [{"strikePrice": 600, "totalVolume": 500, "delta": 0.52}]}},
        "putExpDateMap": {"2025-03-21:1": {"600.0": [{"strikePrice": 600, "totalVolume": 300, "delta": -0.48}]}},
        "candles": [{"open": 599.5, "high": 600.2, "low": 599.4, "close": 600.0, "volume": 100000, "datetime": 1700000000}],
    }
    result = OrderFlowEngine().compute(data)

    print("\nOrder Flow Live Integration Test")
    print("=" * 50)
    for k in ["order_flow_score", "order_flow_direction", "order_flow_regime", "order_flow_readiness",
              "book_imbalance_5", "cum_delta_proxy", "options_flow_score", "institutional_flow_proxy_score"]:
        v = result.get(k)
        if isinstance(v, float):
            print(f"  {k}: {v:.4f}" if abs(v) < 1e4 else f"  {k}: {v:.2f}")
        else:
            print(f"  {k}: {v}")
    print("=" * 50)


if __name__ == "__main__":
    main()
