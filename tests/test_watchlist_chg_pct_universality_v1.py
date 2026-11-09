"""The streamed percent change (NET_CHANGE_PERCENT) on the price row, the same for every ticker.

The rule: Schwab's value as sent, 0 a value, its feed live.

Real data: SPY's LEVELONE_EQUITIES message of 2026-10-23 15:59:01 ET
(real_spy_level_one_2026_10_23.json, NET_CHANGE_PERCENT -0.509189) and $VIX's of 2026-11-07
23:05:37 ET (real_vix_level_one_zero_change_2026_11_07.json, NET_CHANGE_PERCENT sent as 0), each
as Schwab sent it.
"""

from __future__ import annotations

import json
from pathlib import Path

import live_market_plane as lmp
import live_price_rows
import time_et
from tests.feed_live_helper import mark_feed_down, mark_feed_live

_FX = Path(__file__).resolve().parent / "fixtures"
_SPY = json.loads((_FX / "real_spy_level_one_2026_10_23.json").read_text(encoding="utf-8"))[
    "messages"
][1]
(_VIX,) = json.loads(
    (_FX / "real_vix_level_one_zero_change_2026_11_07.json").read_text(encoding="utf-8")
)["messages"]


def _forget(*tickers: str) -> None:
    for tk in tickers:
        lmp._by_ticker.pop(tk, None)
        lmp._fields_by_ticker.pop(tk, None)


def test_the_price_row_serves_schwabs_percent_change_as_sent():
    mark_feed_live("SPY", "$VIX", "ZZNEVER")
    _forget("SPY", "$VIX")
    try:
        lmp.record_from_level_one_equity("SPY", _SPY["item"], received_ts=_SPY["ts_recv"])
        assert (
            live_price_rows.price_row("SPY", time_et.now())["chg_pct"]
            == _SPY["item"]["NET_CHANGE_PERCENT"]
            == -0.509189
        )
        assert _VIX["item"]["NET_CHANGE_PERCENT"] == 0
        lmp.record_from_level_one_equity("$VIX", _VIX["item"], received_ts=_VIX["ts_recv"])
        assert (
            live_price_rows.price_row("$VIX", time_et.now())["chg_pct"] == 0.0
        )  # a flat day is a value
        assert (
            live_price_rows.price_row("ZZNEVER", time_et.now())["chg_pct"] is None
        )  # Schwab sent nothing
    finally:
        _forget("SPY", "$VIX")
        mark_feed_down()
