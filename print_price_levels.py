"""
print_price_levels.py
Print price action levels (PDH/PDL/PDC, POC/VAH/VAL, VWAP bands, ORB, etc.) for any ticker.

Usage:
  python print_price_levels.py [ticker]
  python print_price_levels.py SPY
  python print_price_levels.py QQQ

Requires: Schwab client (schwab_token.json) and config.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = str(Path(__file__).parent.resolve())
sys.path.insert(0, APP_DIR)

from config import build_config
from schwab_client import build_client_from_token
from market_context import fetch_price_levels


def _fmt(v, decimals=2):
    if v is None:
        return "-"
    try:
        return f"{float(v):.{decimals}f}"
    except (TypeError, ValueError):
        return "-"


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python print_price_levels.py TICKER   (there is no default ticker)")
    ticker = sys.argv[1].upper()
    cfg = build_config(APP_DIR)

    state = build_client_from_token(
        api_key=cfg.api_key,
        app_secret=cfg.app_secret,
        token_path=cfg.token_path,
    )
    if not state.ok or state.client is None:
        print(f"❌ Schwab auth failed: {state.message}")
        sys.exit(1)

    client = state.client

    # Today's open/high/low come from the STREAM (the running console's live plane row) --
    # never a REST quote. Console not running / not streaming this ticker -> absent.
    import json as _json
    import urllib.request as _ur
    stream_row = None
    try:
        with _ur.urlopen(f"http://127.0.0.1:8000/api/fast-quote?ticker={ticker}", timeout=5) as r:
            _body = _json.loads(r.read().decode("utf-8"))
            stream_row = _body if _body.get("ok") else None
    except OSError:
        stream_row = None

    pl = fetch_price_levels(
        client,
        symbol=ticker,
        stream_quote=stream_row,
        orb_minutes=15,
        include_extended_hours=True,
    )

    if pl.error:
        print(f"⚠️  Partial error: {pl.error}\n")

    from time_et import now_et

    today = now_et().strftime("%Y-%m-%d")

    print(f"Date: {today}")
    print(f"Ticker: {ticker}")
    print()
    print("Previous Day High:      ", _fmt(pl.pdh))
    print("Previous Day Low:       ", _fmt(pl.pdl))
    print("Previous Day Close:     ", _fmt(pl.pdc))
    print()
    print("Previous Day POC:       ", _fmt(pl.pd_poc))
    print("Previous Day VAH:       ", _fmt(pl.pd_vah))
    print("Previous Day VAL:       ", _fmt(pl.pd_val))
    print()
    print("Overnight High:         ", _fmt(pl.overnight_high))
    print("Overnight Low:          ", _fmt(pl.overnight_low))
    print()
    print("Opening Range High:     ", _fmt(pl.orb_high))
    print("Opening Range Low:      ", _fmt(pl.orb_low))
    print("Opening Range Midpoint: ", _fmt(pl.orb_midpoint))
    print()
    print("VWAP:                   ", _fmt(pl.vwap))
    print("VWAP +1sigma:           ", _fmt(pl.vwap_p1))
    print("VWAP -1sigma:           ", _fmt(pl.vwap_m1))
    print("VWAP +2sigma:           ", _fmt(pl.vwap_p2))
    print("VWAP -2sigma:           ", _fmt(pl.vwap_m2))
    print()
    print("Current Day POC:        ", _fmt(pl.today_poc))
    print("Current Day VAH:        ", _fmt(pl.today_vah))
    print("Current Day VAL:        ", _fmt(pl.today_val))


if __name__ == "__main__":
    main()
