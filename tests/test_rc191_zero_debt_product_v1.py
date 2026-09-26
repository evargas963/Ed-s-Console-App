"""RC-191 / zero-debt clear: session-safe thresholds, calendar session label, vol gap reset."""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ts(y, m, d, hh, mm) -> float:
    return datetime.datetime(y, m, d, hh, mm, tzinfo=datetime.timezone.utc).timestamp()


def test_market_session_saturday_is_closed_not_rth():
    from db import market_session
    from ml_data_common import market_session_from_ts_utc

    # Saturday 2026-08-01 10:00 ET = 14:00 UTC
    assert market_session(10, 0, et_date="2026-08-01") == "closed"
    assert market_session(10, 0, et_date="2026-07-31") == "rth"  # Friday
    sat = datetime.datetime(2026, 8, 1, 14, 0, tzinfo=datetime.timezone.utc).timestamp()
    assert market_session_from_ts_utc(sat) == "closed"
    fri = datetime.datetime(2026, 7, 31, 14, 0, tzinfo=datetime.timezone.utc).timestamp()
    assert market_session_from_ts_utc(fri) == "rth"


def test_bar_accumulator_gap_resets_volume_delta():
    from server import _CandleAccumulator

    acc = _CandleAccumulator(bar_seconds=60, max_bars=10)
    t0 = _ts(2026, 7, 31, 14, 0)  # 10:00 ET
    acc.tick("MSFT", 500.0, t0, total_volume=1_000_000.0)
    # Same minute, +5k shares — should accumulate
    acc.tick("MSFT", 500.1, t0 + 10, total_volume=1_005_000.0)
    assert acc._current["MSFT"]["v"] == pytest.approx(5_000.0)
    # 5-minute gap with +25M shares — must NOT land on the next bar
    t_gap = t0 + 300
    acc.tick("MSFT", 501.0, t_gap, total_volume=26_005_000.0)
    cur = acc._current["MSFT"]
    assert cur["ts"] == acc._bar_start(t_gap)
    assert cur.get("v") is None
    # RC-278: two tests disagreed on this label and production shipped one of them.
    # server.py:3672 emits "..._gap_unattributable" and the COMMITTED, passing
    # tests/test_horizon_bar_outcomes.py:411 asserts that exact string. "gap_reset" says the
    # counter restarted; "gap_unattributable" says the span's volume cannot be assigned to any
    # one bar, which is the RC-168 finding this branch exists for. The accurate word wins.
    assert cur.get("volume_source") == "schwab_quote_totalVolume_gap_unattributable"

