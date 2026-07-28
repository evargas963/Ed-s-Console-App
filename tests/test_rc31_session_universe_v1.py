# institutional-synthetic-ok: the bars here are hand-built ON PURPOSE — the test needs a weekend
# gap at an exact seam to prove an overnight return cannot enter a feature window (RC-31).
"""RC-31: the bar-path loaders name their session universe, and overnight returns cannot enter.

`_load_closes` selected ALL of price_bars_1m with no time predicate, while price_bars_1m carries
extended hours BY DESIGN — thirteen study runners inherited overnight and extended-hours bars.
And even on filtered bars, np.diff at a day boundary fabricates one giant "one-minute" return
spanning the whole gap. The subtle case this file exists for: a window starting at Monday's FIRST
bar has same-day endpoints while its first return IS the weekend — the boundary check must reach
back to lo-1, and the first version of the fix did not.
"""
from __future__ import annotations

import datetime
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.tcn_eval_v1.runner import _build_xy, _load_closes  # noqa: E402

ET_UTC = datetime.timezone.utc


def _ts(y, m, d, hh, mm):
    """UTC timestamp for an ET wall-clock in July (EDT = UTC-4)."""
    return datetime.datetime(y, m, d, hh + 4, mm, tzinfo=ET_UTC).timestamp()


def _mk_db(tmp_path: Path) -> Path:
    db = tmp_path / "bars.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE price_bars_1m (ticker TEXT, bar_end_ts_utc REAL, close REAL)")
    rows = [
        # Friday 2026-07-24 RTH tail
        ("SPY", _ts(2026, 7, 24, 15, 58), 100.0),
        ("SPY", _ts(2026, 7, 24, 15, 59), 100.1),
        # Friday EXTENDED hours — must be excluded by session="rth"
        ("SPY", _ts(2026, 7, 24, 17, 30), 99.0),
        # Saturday — a frozen weekend bar, must be excluded
        ("SPY", _ts(2026, 7, 25, 10, 0), 99.5),
        # Monday 2026-07-27 RTH open
        ("SPY", _ts(2026, 7, 27, 9, 31), 102.0),
        ("SPY", _ts(2026, 7, 27, 9, 32), 102.1),
        ("SPY", _ts(2026, 7, 27, 9, 33), 102.2),
    ]
    con.executemany("INSERT INTO price_bars_1m VALUES (?,?,?)", rows)
    con.commit()
    con.close()
    return db


def test_rth_universe_excludes_extended_and_weekend(tmp_path):
    ends, closes = _load_closes(_mk_db(tmp_path), "SPY", session="rth")
    assert len(ends) == 5, f"expected 5 RTH bars, got {len(ends)}"
    assert 99.0 not in closes, "a 17:30 extended-hours bar entered the RTH universe"
    assert 99.5 not in closes, "a SATURDAY bar entered the RTH universe"


def test_all_universe_must_be_asked_for_and_unknown_refuses(tmp_path):
    db = _mk_db(tmp_path)
    ends, _ = _load_closes(db, "SPY", session="all")
    assert len(ends) == 7, "session='all' should return every bar, explicitly"
    with pytest.raises(ValueError):
        _load_closes(db, "SPY", session="overnight")  # unknown universe: refuse, never guess


def test_overnight_return_cannot_enter_a_feature_window(tmp_path):
    """The seam case: a window starting at Monday's FIRST bar. Its endpoints are same-day, but
    its first return is Friday-close -> Monday-open — the whole weekend as one 'minute'."""
    ends, closes = _load_closes(_mk_db(tmp_path), "SPY", session="rth")
    # label at Monday 09:33, lookback 3 -> window = returns at [09:31, 09:32, 09:33];
    # rets[09:31] = log(102.0/100.1) is the WEEKEND. Must be excluded.
    labeled = [(_ts(2026, 7, 27, 9, 33), "up")]
    X, y, dates = _build_xy(ends, closes, labeled, lookback=3)
    assert len(X) == 0, (
        "a feature window whose first return spans the weekend was admitted — the boundary "
        "check is not reaching back to lo-1"
    )
    # Control: with lookback 2 the window is [09:32, 09:33], entirely intra-Monday — admitted,
    # and every return in it must be small (no gap-sized return smuggled in).
    X2, y2, d2 = _build_xy(ends, closes, labeled, lookback=2)
    assert len(X2) == 1, "a clean intra-day window was wrongly excluded"
    assert float(np.abs(X2).max()) < 0.01, f"a gap-sized return entered: {X2}"
