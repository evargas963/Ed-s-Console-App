"""RC-191 / zero-debt clear: session-safe thresholds, calendar session label."""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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

