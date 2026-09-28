"""RC-183 — the operator Collect-window law: 08:15–15:15 CT at the ONE write seam.

Named check: collect_window_single_law (negative control per RC-95 — these tests drive the
REAL `EdDB.upsert_1m_bars` with violating writes and assert they are BLOCKED, and break the
law's clauses to prove the institutional check fires).

The law (operator, non-negotiable 2026-08-01): `price_bars_1m` persists ET bar-end minutes
(555, min(975, cash_close+15)] on trading days only — the app gathers from 08:15 CT because it
must be ready before the open, and SPY/QQQ-class ETFs trade to 16:15 ET. This is neither
classic cash RTH [570,960) nor vendor extended hours. MEASURED before the lock: 1,224,370 of
2,537,437 rows (48.25%) violated it, written by three different windows that never shared a law.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("PYTEST_CURRENT_TEST", "boot")

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from time_et import (  # noqa: E402
    COLLECT_WINDOW_END_MINS,
    COLLECT_WINDOW_START_MINS,
    ET,
    collect_window_end_mins_for_et_date,
    is_collect_window_bar_end_ts_utc,
)

from micro_structure import Candle  # noqa: E402


def _bar(ts_end: float, px: float = 100.0, vol: float = 10.0) -> Candle:
    return Candle(ts=ts_end - 60.0, open=px, high=px, low=px, close=px, volume=vol)


def test_the_authority_boundary_table():
    """Every boundary the law names, judged on the bar's END minute."""
    mon = lambda h, m: datetime(2026, 8, 3, h, m, tzinfo=ET).timestamp()  # noqa: E731
    assert COLLECT_WINDOW_START_MINS == 555 and COLLECT_WINDOW_END_MINS == 975
    assert is_collect_window_bar_end_ts_utc(mon(9, 15)) is False, "covers 09:14 — pre-window"
    assert is_collect_window_bar_end_ts_utc(mon(9, 16)) is True, "first legal bar"
    assert is_collect_window_bar_end_ts_utc(mon(16, 15)) is True, "last legal bar (ETF tail)"
    assert is_collect_window_bar_end_ts_utc(mon(16, 16)) is False
    assert is_collect_window_bar_end_ts_utc(mon(5, 0)) is False, "premarket"
    assert is_collect_window_bar_end_ts_utc(mon(20, 0)) is False, "afterhours"
    sat = datetime(2026, 8, 1, 11, 0, tzinfo=ET).timestamp()
    assert is_collect_window_bar_end_ts_utc(sat) is False, "Saturday is never a session"
    # early close: window ends cash close + 15, never 975 on a half day
    assert collect_window_end_mins_for_et_date("2026-08-03") == 975


def test_the_seam_blocks_outside_window_writes(tmp_path):
    """The lock itself: violating bars die at `upsert_1m_bars`; legal bars land. This is the
    negative control for collect_window_single_law — the write path, not a string."""
    from db import EdDB

    db = EdDB(str(tmp_path / "law.db"))
    mon = lambda h, m: datetime(2026, 8, 3, h, m, tzinfo=ET).timestamp()  # noqa: E731
    bars = [
        _bar(mon(5, 0)),      # premarket — must die
        _bar(mon(9, 15)),     # covers 09:14 — must die
        _bar(mon(9, 16)),     # first legal — must land
        _bar(mon(12, 0)),     # mid-session — must land
        _bar(mon(16, 15)),    # last legal — must land
        _bar(mon(16, 30)),    # post-window — must die
        _bar(datetime(2026, 8, 1, 11, 0, tzinfo=ET).timestamp()),  # Saturday — must die
    ]
    written = db.upsert_1m_bars("SPY", bars)
    assert written == 3, f"seam wrote {written} of 7 — the law admits exactly 3 of these bars"
    con = sqlite3.connect(str(tmp_path / "law.db"))
    got = sorted(r[0] for r in con.execute(
        "SELECT bar_end_ts_utc FROM price_bars_1m WHERE ticker='SPY'"))
    con.close()
    assert got == sorted([mon(9, 16), mon(12, 0), mon(16, 15)]), (
        "an outside-window bar reached the table through the seam"
    )


def test_the_seam_refuses_and_counts_off_grid_bars(tmp_path, caplog):
    """A bar whose start is off the minute grid is refused and counted, never snapped to the
    nearest minute. Stand-in: the first real SPY bar of
    tests/fixtures/real_spy_1m_bars_2026_09_24_25.json with its start shifted by 7 seconds."""
    from db import EdDB

    fx = json.loads((REPO / "tests" / "fixtures" / "real_spy_1m_bars_2026_09_24_25.json")
                    .read_text(encoding="utf-8"))
    b = fx["bars"][0]
    real = Candle(ts=b["timestamp"] / 1000.0, open=b["open"], high=b["high"], low=b["low"],
                  close=b["close"], volume=b["volume"])
    shifted = Candle(ts=real.ts + 7.0, open=real.open, high=real.high, low=real.low,
                     close=real.close, volume=real.volume)
    db = EdDB(str(tmp_path / "grid.db"))
    with caplog.at_level("WARNING", logger="db"):
        assert db.upsert_1m_bars("SPY", [shifted]) == 0, "an off-grid bar was written"
    assert any("1 bar(s) off the minute grid refused" in r.getMessage() for r in caplog.records)
    con = sqlite3.connect(str(tmp_path / "grid.db"))
    assert con.execute("SELECT COUNT(*) FROM price_bars_1m").fetchone()[0] == 0
    con.close()
    assert db.upsert_1m_bars("SPY", [real]) == 1, "the same bar on the grid is in the window"
