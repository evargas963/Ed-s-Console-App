"""Session VWAP semantic fidelity — RTH availability.

Inside the regular session Schwab's /markets sent (tests/conftest.py holds the answers captured
2026-10-07).
"""

from __future__ import annotations

from datetime import date, timedelta

from calc.liquidity_value_engine import (
    bars_from_candles,
    build_price_level_snapshot,
    compute_session_vwap_series,
    count_session_rth_positive_volume_bars,
)
from calc.micro_structure import Candle
from time_et import session, sessions

FRIDAY = date(2026, 10, 2)


def _rth_bar(
    day: date, minutes_after_open: int, close: float, volume: float | None = 1_000.0
) -> Candle:
    dt = session(day.isoformat()).regular[0][0] + timedelta(minutes=minutes_after_open)
    return Candle(
        ts=dt.timestamp(),
        open=close - 0.05,
        high=close + 0.10,
        low=close - 0.10,
        close=close,
        volume=volume,
    )


def test_first_positive_volume_rth_bar_produces_session_vwap() -> None:
    """After the first valid +volume RTH bar, canonical session VWAP exists.

    The rule names no ticker.
    """
    bars = bars_from_candles([_rth_bar(FRIDAY, 0, 100.0, volume=2_500.0)])
    held = sessions()
    assert compute_session_vwap_series(bars, FRIDAY, sessions=held), (
        "VWAP absent after the first +volume RTH bar"
    )
    assert count_session_rth_positive_volume_bars(bars, FRIDAY, sessions=held) == 1


def test_zero_volume_rth_bar_does_not_create_session_vwap() -> None:
    bars = bars_from_candles([_rth_bar(FRIDAY, 0, 100.0, volume=0.0)])
    held = sessions()
    assert compute_session_vwap_series(bars, FRIDAY, sessions=held) == []
    assert count_session_rth_positive_volume_bars(bars, FRIDAY, sessions=held) == 0


def test_the_vwap_starts_at_the_first_rth_bar_with_volume_above_zero() -> None:
    """INDUCED: the session's first minutes with no volume (absent as sent, then 0), then 1 share.

    Those minutes add nothing and the session goes on: the one point is the third bar's, its
    typical price with no spread.
    """
    absent, zero, one = (
        _rth_bar(FRIDAY, i, 100.0 + i, volume=v) for i, v in enumerate((None, 0.0, 1.0))
    )
    series = compute_session_vwap_series(
        bars_from_candles([absent, zero, one]), FRIDAY, sessions=sessions()
    )
    tp = (one.high + one.low + one.close) / 3.0
    assert series == [(one.ts, tp, tp, tp, tp, tp)]


def test_rth_volume_with_no_range_to_spread_it_over_makes_no_value_area_and_says_why() -> None:
    """INDUCED: one RTH bar of 1 share whose high is under its low (none of 2,166,115 measured).

    Its volume makes the VWAP; the volume profile has no range to spread it over, and the value
    area is absent with that reason, not as if there were no volume.
    """
    bar = _rth_bar(FRIDAY, 0, 100.0, volume=1.0)
    upside_down = Candle(bar.ts, bar.open, bar.low, bar.high, bar.close, bar.volume)
    snap = build_price_level_snapshot(
        FRIDAY,
        bars_from_candles([upside_down]),
        prior=None,
        bar_source="induced",
        sessions=sessions(),
    )
    absent = {f["family"]: f["reason"] for f in snap.families_absent}
    assert absent["value_area"] == (
        "RTH volume bars present but the volume profile did not materialize"
    )
    assert "vwap" not in absent and snap.volume_profile is None
