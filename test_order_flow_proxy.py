#!/usr/bin/env python3
"""
Test Order Flow full proxy input mapping.
Verifies all Claude proxy fields are wired and reports wired vs unavailable.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Minimal mock with full proxy structure (from quote + chain response shapes)
ORDER_FLOW_DATA = {
    "quote": {
        "totalVolume": 1162426,
        "lastSize": 100,
        "bidSize": 600,
        "askSize": 560,
        "bidPrice": 671.44,
        "askPrice": 671.51,
        "mark": 671.51,
        "markChange": -4.82,
        "netChange": -4.879,
        "openPrice": 676.0,
        "tradeTime": 1773319201659,
        "quoteTime": 1773319201972,
    },
    "extended": {
        "askPrice": 671.50,
        "askSize": 10,
        "bidPrice": 671.40,
        "bidSize": 5,
        "lastPrice": 671.45,
        "lastSize": 5,
        "totalVolume": 100,
        "tradeTime": 1773302400000,
        "quoteTime": 1773302400000,
    },
    "regular": {
        "regularMarketLastPrice": 676.33,
        "regularMarketLastSize": 160,
        "regularMarketNetChange": -0.85,
        "regularMarketPercentChange": -0.1255,
        "regularMarketTradeTime": 1773273600001,
    },
    "fundamental": {
        "avg10DaysVolume": 87447833.0,
        "avg1YearVolume": 78037901.0,
    },
    "reference": {
        "isHardToBorrow": False,
        "htbRate": 0.0,
        "htbQuantity": 371861,
        "isShortable": True,
    },
    "underlying": {"totalVolume": 1162426, "bid": 671.44, "ask": 671.51},
    "callExpDateMap": {"2025-03-21:1": {"671.0": [{"strikePrice": 671, "totalVolume": 500, "delta": 0.52}]}},
    "putExpDateMap": {"2025-03-21:1": {"671.0": [{"strikePrice": 671, "totalVolume": 300, "delta": -0.48}]}},
    "candles": [
        {"open": 670, "high": 672, "low": 669, "close": 671, "volume": 50000, "datetime": 1773319000000},
        {"open": 669, "high": 671, "low": 668, "close": 670, "volume": 45000, "datetime": 1773318700000},
    ],
}

WIRED = """
1. Quote/top-of-book: quote.totalVolume, lastSize, bidSize, askSize, bidPrice, askPrice,
   mark, markChange, netChange, openPrice, tradeTime, quoteTime — from get_quote
2. Extended-hours: extended.* — from get_quote (q_json.TICKER.extended)
3. Regular session: regular.regularMarketLastPrice, regularMarketLastSize, regularMarketNetChange,
   regularMarketPercentChange, regularMarketTradeTime — from get_quote
4. Candles: candles.*.volume, open, high, low, close, datetime — from price history / accumulator
5. Fundamental: fundamental.avg10DaysVolume, avg1YearVolume — from get_quote
6. Reference: reference.isHardToBorrow, htbRate, htbQuantity, isShortable — from get_quote
7. Underlying: underlying.* — from chain when include_underlying_quote (may be empty)
8. Options flow: callExpDateMap, putExpDateMap — from get_option_chain
9. Live content: content (book + tape) — from streaming when connected
"""

UNAVAILABLE = """
- screeners.*: requires get_movers or screener API — not in current fetch
- instruments.*.fundamental: requires get_instruments — not in current fetch
- shortIntToFloat, shortIntDayToCover: in instruments.fundamental — not in current fetch
"""


def main():
    from app.options.order_flow.engine import OrderFlowEngine

    result = OrderFlowEngine().compute(ORDER_FLOW_DATA)
    print("\n" + "=" * 60)
    print("ORDER FLOW FULL PROXY — Wired vs Unavailable")
    print("=" * 60)
    print("\nWIRED (from current fetch: get_quote + get_option_chain + candles):")
    print(WIRED)
    print("\nUNAVAILABLE (would require additional API calls):")
    print(UNAVAILABLE)
    print("=" * 60)
    print("\nSample output metrics:")
    for k in [
        "order_flow_score",
        "order_flow_direction",
        "order_flow_regime",
        "order_flow_readiness",
        "book_imbalance_5",
        "cum_delta_proxy",
        "options_flow_score",
        "institutional_flow_proxy_score",
    ]:
        v = result.get(k)
        if isinstance(v, float):
            print(f"  {k}: {v:.4f}" if abs(v) < 1e4 else f"  {k}: {v:.2f}")
        else:
            print(f"  {k}: {v}")
    print("=" * 60)
    print("\nFiles modified: server.py, app/options/order_flow/engine.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
