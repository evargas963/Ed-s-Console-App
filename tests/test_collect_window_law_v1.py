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

import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("PYTEST_CURRENT_TEST", "boot")

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from app.domain.time_et import (  # noqa: E402
    COLLECT_WINDOW_END_MINS,
    COLLECT_WINDOW_START_MINS,
    ET,
    collect_window_end_mins_for_et_date,
    is_collect_window_bar_end_ts_utc,
)

from tests.conftest import most_recent_trading_day_et  # noqa: E402


def _bar(ts_end: float, px: float = 100.0, vol: float = 10.0) -> dict:
    return {"datetime": (ts_end - 60.0) * 1000.0, "open": px, "high": px, "low": px,
            "close": px, "volume": vol}


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
    written = db.upsert_1m_bars("SPY", bars, refresh_governed_outcomes=False)
    assert written == 3, f"seam wrote {written} of 7 — the law admits exactly 3 of these bars"
    con = sqlite3.connect(str(tmp_path / "law.db"))
    got = sorted(r[0] for r in con.execute(
        "SELECT bar_end_ts_utc FROM price_bars_1m WHERE ticker='SPY'"))
    con.close()
    assert got == sorted([mon(9, 16), mon(12, 0), mon(16, 15)]), (
        "an outside-window bar reached the table through the seam"
    )


def test_completeness_grid_is_the_law_grid(tmp_path):
    """The daily checker must measure the SAME window the writers enforce — a checker on a
    different grid either misses violations or cries holes where no bar belongs."""
    from tools.rth_completeness_check_v1 import RTH_START_MINS, session_completeness

    assert RTH_START_MINS == COLLECT_WINDOW_START_MINS == 555
    db = tmp_path / "d.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE price_bars_1m (ticker TEXT, bar_start_ts_utc REAL, "
                "bar_end_ts_utc REAL, open REAL, high REAL, low REAL, close REAL, "
                "volume REAL, source TEXT)")
    # RC-306/RC-309: a literal session date ages out of the enrolment fallback's lookback and
    # the ticker silently vanishes from the report — the KeyError this line used to raise said
    # nothing about the grid it exists to check. The session comes from the calendar authority.
    day = most_recent_trading_day_et()
    ts = datetime(day.year, day.month, day.day, 9, 20, tzinfo=ET).timestamp()
    con.execute("INSERT INTO price_bars_1m VALUES (?,?,?,?,?,?,?,?,?)",
                ("ZZZ", ts - 60, ts, 1, 1, 1, 100.0, 10.0, "unit"))
    con.commit()
    con.close()
    rep = session_completeness(str(db), day.isoformat())
    assert rep["expected_per_ticker"] == 975 - 555 == 420, (
        f"grid expects {rep['expected_per_ticker']} minutes — not the law's 420"
    )
    assert rep["tickers"]["ZZZ"]["present"] == 1


def test_the_enrolment_fallback_counts_sessions_not_days():
    """RC-309: the fallback universe's lookback is the market calendar, driven directly.

    `WHERE bar_end_ts_utc >= strftime('%s','now') - 5*86400` reached back five 86400-second
    steps from the current instant. That is not five sessions and not a session boundary:
    from a Saturday it clipped the earliest session's first hours, so which tickers qualified
    depended on the hour the checker ran, and from a Monday morning it reached four sessions
    at all. A ticker outside the universe is not reported as a hole — it is simply an absent
    key, which reads as nothing to report.
    """
    from datetime import timedelta

    from app.domain.time_et import is_trading_day_et
    from tools.rth_completeness_check_v1 import (
        ENROLLMENT_FALLBACK_SESSIONS,
        session_lookback_bound_ts_utc,
    )

    bound = datetime.fromtimestamp(session_lookback_bound_ts_utc(
        ENROLLMENT_FALLBACK_SESSIONS), tz=ET)
    assert (bound.hour, bound.minute, bound.second) == (0, 0, 0), (
        f"the bound is {bound:%H:%M:%S} ET — a session starts at midnight ET, so a "
        "mid-session bound admits part of a day and excludes the rest of it")
    assert is_trading_day_et(bound.date().isoformat()), (
        f"{bound.date()} is not a trading day, so the lookback does not end on a session")

    # Exactly N sessions inclusive, counting back from today.
    seen, day = 0, datetime.now(ET).date()
    while day >= bound.date():
        if is_trading_day_et(day.isoformat()):
            seen += 1
        day -= timedelta(days=1)
    assert seen == ENROLLMENT_FALLBACK_SESSIONS, (
        f"the lookback spans {seen} sessions, not {ENROLLMENT_FALLBACK_SESSIONS}")

    # And it is strictly wider than the seconds arithmetic it replaced — the whole point of
    # RC-309. Made deterministic (RC-444): the old form used datetime.now() and pitted a
    # MIDNIGHT-aligned session bound against a NOW-aligned seconds clock, so on some weekdays
    # (e.g. a fresh Friday) 5 sessions span fewer wall-clock hours than 5 calendar days and the
    # assert flipped with the day CI ran. Pin the docstring's own example with a FIXED anchor:
    # the Tuesday after a holiday Monday. Five 86400-second steps back from it reach only THREE
    # sessions (the holiday + the weekend + a mid-day cut), while the calendar bound reaches the
    # full five and strictly further back. Fixed date -> identical result on every CI day.
    after_holiday = datetime(2026, 1, 20, 12, tzinfo=ET)  # Tue after MLK Monday 2026-01-19
    assert is_trading_day_et(after_holiday.date().isoformat()), "anchor must be a session"
    assert not is_trading_day_et("2026-01-19"), "anchor assumes MLK Monday 2026-01-19 is closed"
    sess_bound = session_lookback_bound_ts_utc(
        ENROLLMENT_FALLBACK_SESSIONS, now=after_holiday.timestamp())
    secs_bound = after_holiday.timestamp() - ENROLLMENT_FALLBACK_SESSIONS * 86400

    def _sessions_covered(bound_ts: float) -> int:
        d0 = datetime.fromtimestamp(bound_ts, tz=ET).date()
        end = after_holiday.date()
        return sum(is_trading_day_et((d0 + timedelta(days=i)).isoformat())
                   for i in range((end - d0).days + 1))

    assert _sessions_covered(sess_bound) == ENROLLMENT_FALLBACK_SESSIONS, (
        "the calendar bound must cover exactly N sessions")
    assert _sessions_covered(secs_bound) < ENROLLMENT_FALLBACK_SESSIONS, (
        "the N-day seconds arithmetic under-covers sessions across a holiday — the bound must "
        "count sessions, not days (RC-309)")
    assert sess_bound < secs_bound, (
        "the calendar bound must reach strictly further back than the seconds bound here")


def test_institutional_check_fires_when_the_law_is_unplugged(tmp_path, monkeypatch):
    """Negative control on the static check: strip the seam gate from a shadow db.py and the
    check must SCREAM (green-and-inert is byte-identical to green-and-working, RC-95)."""
    import importlib

    m = importlib.import_module("tools.check_institutional_correctness")
    assert m.check_collect_window_single_law() == [], "baseline must be clean before injection"

    real_db = (REPO / "db.py").read_text(encoding="utf-8", errors="replace")
    stripped = real_db.replace("is_collect_window_bar_end_ts_utc", "GONE_GATE")
    shadow = tmp_path / "db.py"
    shadow.write_text(stripped, encoding="utf-8")
    real_read = Path.read_text

    def fake_read(self, *a, **k):  # only the db.py read is shadowed
        if self.name == "db.py" and self.parent == REPO:
            return stripped
        return real_read(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", fake_read)
    v = m.check_collect_window_single_law()
    assert v, "the gate was stripped from the seam and the institutional check stayed green"
    assert any("lost the operator law" in str(x) for x in v)
