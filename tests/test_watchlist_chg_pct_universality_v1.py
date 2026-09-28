"""The streamed percent change (live_market_plane.streamed_chg_pct, NET_CHANGE_PERCENT from a
fresh streamed row), the same rule for every ticker."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))





























def test_streamed_chg_pct_serves_only_a_fresh_streamed_row(monkeypatch):
    import time as _t

    from live_market_plane import streamed_chg_pct

    from tests.feed_live_helper import mark_feed_live
    mark_feed_live("ZZTEST")
    fresh = {"ticker": "ZZTEST", "spot": 10.0, "chg_pct": 3.33, "server_received_ts": _t.time(), "spot_received_ts": _t.time(),
             "quote_source_detail": {"spot": "LAST_PRICE"},
             "quote_ingestion": "schwab_streaming_level_one"}
    assert streamed_chg_pct(fresh) == 3.33
    assert streamed_chg_pct(dict(fresh, chg_pct=0.0)) == 0.0          # a flat day is a value
    assert streamed_chg_pct(dict(fresh, quote_ingestion="rest_tier_a")) is None
    assert streamed_chg_pct(dict(fresh, ticker="ZZNOTHELD")) is None   # the daemon does not hold it
    assert streamed_chg_pct(None) is None




