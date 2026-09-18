#!/usr/bin/env python3
"""
Optional live probe: Schwab 1-minute price history window size (evidence only).

Requires working Schwab auth (same as the console). Does not write the database.

Usage:
  python tools/schwab_minute_history_probe_v1.py --symbol SPY --days-back 40

Exits 0 if HTTP 200 and prints candle count + first/last datetimes from payload.
Exits 2 if client init fails (no token / network) — feasibility remains UNCERTAIN.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="SPY")
    ap.add_argument("--days-back", type=int, default=40)
    args = ap.parse_args()

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days_back)

    try:
        from server import get_client
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"import server: {e}"}))
        sys.exit(2)

    try:
        client = get_client()
    except Exception as e:
        print(json.dumps({"ok": False, "error": f"get_client: {e}"}))
        sys.exit(2)

    try:
        import schwab as _schwab

        PH = _schwab.client.Client.PriceHistory
        resp = client.get_price_history(
            args.symbol,
            period_type=None,
            period=None,
            frequency_type=PH.FrequencyType.MINUTE,
            frequency=PH.Frequency.EVERY_MINUTE,
            start_datetime=start,
            end_datetime=end,
            need_extended_hours_data=True,
        )
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(2)

    if resp is None or getattr(resp, "status_code", None) != 200:
        print(
            json.dumps(
                {
                    "ok": False,
                    "status": getattr(resp, "status_code", None),
                    "text": getattr(resp, "text", "")[:500],
                }
            )
        )
        sys.exit(1)

    data = resp.json()
    candles = data.get("candles") or []
    out = {
        "ok": True,
        "symbol": args.symbol,
        "requested_start_utc": start.isoformat(),
        "requested_end_utc": end.isoformat(),
        "n_candles": len(candles),
        "first_candle_datetime_ms": candles[0].get("datetime") if candles else None,
        "last_candle_datetime_ms": candles[-1].get("datetime") if candles else None,
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
