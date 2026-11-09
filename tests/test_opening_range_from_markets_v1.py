"""The opening range is measured from the regular open Schwab's /markets sent for the date.

The sessions are Schwab's captured /markets answers (tests/conftest.py holds them through
time_et.record_markets): 2026-10-05 an open day (regular 09:30-16:00 ET), 2026-10-03 a closed
one. The answers held run from 2026-09-30 to 2027-10-07; none is held for 2025-06-02, so its
open is unknown.
"""

from datetime import datetime

from liquidity_models import PlaybookConfig
from liquidity_value_engine import compute_opening_range
from time_et import ET


def _bar(day: str, hhmm: str, high: float, low: float) -> dict:
    """A normalized one-minute bar (bars_from_candles' shape) starting at `hhmm` ET on `day`."""
    return {
        "_dt": datetime.fromisoformat(f"{day}T{hhmm}").replace(tzinfo=ET),
        "high": high,
        "low": low,
    }


def test_the_range_is_the_bars_from_schwabs_open_for_the_configured_minutes():
    day = "2026-10-05"
    bars = [
        _bar(day, "09:29", 120, 80),  # before the open Schwab sent: not the range
        _bar(day, "09:30", 104, 101),
        _bar(day, "09:44", 106, 100),
        _bar(day, "09:45", 130, 70),  # the 16th minute: not the range
    ]
    assert compute_opening_range(bars, datetime(2026, 10, 5).date(), PlaybookConfig()) == {
        "orb_high": 106,
        "orb_low": 100,
        "orb_mid": 103.0,
    }


def test_a_closed_date_has_no_opening_range():
    bars = [_bar("2026-10-03", "09:35", 104, 101)]
    assert compute_opening_range(bars, datetime(2026, 10, 3).date(), PlaybookConfig()) == {}


def test_a_date_whose_open_is_not_known_has_no_opening_range():
    bars = [_bar("2025-06-02", "09:35", 104, 101)]
    assert compute_opening_range(bars, datetime(2025, 6, 2).date(), PlaybookConfig()) == {}
