"""RC-159 — chain accrual window [09:15, 16:15] ET and the spot-independent storm1 score.

The accrual window is an operator MANDATE with named boundaries, so the tests assert the
boundaries themselves, not "roughly the morning". storm1 is asserted against hand-worked ranks
so a passing result cannot be an accident of the data.
"""
from __future__ import annotations

import os
from datetime import datetime

os.environ.setdefault("PYTEST_CURRENT_TEST", "boot")

from calibration.option_chain_accrual import (  # noqa: E402
    ACCRUAL_END_MINS,
    ACCRUAL_START_MINS,
    accrual_window,
    persist_chain_accrual,
)
from time_et import ET  # noqa: E402


# ── accrual window ───────────────────────────────────────────────────────────────────────
def test_accrual_window_matches_the_operator_clock_exactly():
    """08:15 CT == 09:15 ET == 555, and 15:15 CT == 16:15 ET == 975. The exchange calendar is
    America/New_York (the ONE session authority); the CT figures are the operator's wall clock,
    and the equivalence is the market's fixed one-hour offset, not a second clock."""
    assert ACCRUAL_START_MINS == 9 * 60 + 15 == 555
    assert ACCRUAL_END_MINS == 16 * 60 + 15 == 975
    # the ET/CT equivalence, asserted rather than asserted-in-a-comment
    for et_h, et_m, ct_h in ((9, 15, 8), (16, 15, 15)):
        import zoneinfo
        d = datetime(2026, 7, 30, et_h, et_m, tzinfo=ET)
        assert d.astimezone(zoneinfo.ZoneInfo("America/Chicago")).hour == ct_h


def test_accrual_window_includes_both_named_boundaries():
    """The operator named these as times data must EXIST, so both ends are inclusive."""
    assert accrual_window(ACCRUAL_START_MINS) is True, "09:15 ET excluded — the mandated start"
    assert accrual_window(ACCRUAL_END_MINS) is True, "16:15 ET excluded — the mandated end"


def test_accrual_window_rejects_outside_and_covers_the_whole_span():
    assert accrual_window(ACCRUAL_START_MINS - 1) is False       # 09:14 ET
    assert accrual_window(ACCRUAL_END_MINS + 1) is False         # 16:16 ET
    assert accrual_window(0) is False and accrual_window(1439) is False
    for mins in (9 * 60 + 15, 9 * 60 + 29, 9 * 60 + 30, 12 * 60, 15 * 60, 16 * 60 + 15):
        assert accrual_window(mins) is True, f"minute {mins} is inside the mandate but rejected"


def test_premarket_before_the_cash_open_is_in_scope():
    """The gap this closes: 09:15-09:29 ET used to bank nothing, so the first wide chain of the
    day arrived after the open (MEASURED 2026-07-30: SPY 09:53:02 ET)."""
    for mins in range(9 * 60 + 15, 9 * 60 + 30):
        assert accrual_window(mins) is True, f"premarket minute {mins} still excluded"


# ── accrual persistence ──────────────────────────────────────────────────────────────────
def _ts_at(h: int, m: int) -> float:
    return datetime(2026, 7, 30, h, m, tzinfo=ET).timestamp()


def test_accrual_writes_inside_the_window_and_reads_back(tmp_path):
    db = tmp_path / "t.db"
    rows = [[700.0, -1.0e6, 1200.0], [705.0, 2.0e6, 900.0]]
    res = persist_chain_accrual(db, ticker="spy", per_strike_rows=rows, spot=702.0,
                                ts_utc=_ts_at(9, 15))
    assert res["status"] == "written", res
    assert res["n_strikes"] == 2 and res["session_volume"] == 2100.0
    import sqlite3
    con = sqlite3.connect(db)
    row = con.execute("SELECT ticker, et_minute, n_strikes, session_volume, abs_gex_total "
                      "FROM option_chain_accrual").fetchone()
    con.close()
    assert row[0] == "SPY", "ticker was not normalised"
    assert row[1] == 555 and row[2] == 2 and row[3] == 2100.0
    assert row[4] == 3.0e6, "abs gex total must sum MAGNITUDES, not signed values"


def test_accrual_refuses_outside_the_window(tmp_path):
    db = tmp_path / "t.db"
    for h, m in ((9, 14), (16, 16), (3, 0), (20, 0)):
        res = persist_chain_accrual(db, ticker="SPY", per_strike_rows=[[1.0, 1.0, 1.0]],
                                    spot=1.0, ts_utc=_ts_at(h, m))
        assert res["status"] == "skipped" and res["reason"] == "outside_accrual_window", (
            f"{h}:{m:02d} ET was accepted outside the mandate: {res}"
        )
    # TEST_SYSTEM_REHAB_V2: was `assert not db.exists() or True` -- an `X or True`
    # tautology that always passes regardless of X, so it never actually checked the
    # "nothing written" claim the comment made. Traced persist_chain_accrual: every
    # outside-window path returns before any sqlite3.connect, so the file genuinely
    # never gets created here -- the real assertion holds and is now enforced.
    assert not db.exists(), "outside-window calls must not create the db file at all"


def test_accrual_fails_closed_on_unusable_rows(tmp_path):
    """No fabricated observation: NaN/inf/short rows leave no record at all."""
    db = tmp_path / "t.db"
    nan, inf = float("nan"), float("inf")
    for bad in ([], [[nan, 1.0, 1.0]], [[1.0, nan, 1.0]], [[1.0, 1.0, nan]],
                [[inf, 1.0, 1.0]], [["x", 1.0, 1.0]], [[1.0, 2.0]]):
        res = persist_chain_accrual(db, ticker="SPY", per_strike_rows=bad, spot=1.0,
                                    ts_utc=_ts_at(10, 0))
        assert res["status"] == "skipped", f"unusable rows were banked: {bad} -> {res}"


def test_accrual_is_a_time_series_not_one_row_a_day(tmp_path):
    """The defect being fixed: option_chain_morning_full is PRIMARY KEY (ticker, et_date), so it
    can hold ONE observation per day and cannot express accrual."""
    db = tmp_path / "t.db"
    import sqlite3
    for h, m in ((9, 15), (9, 30), (12, 0), (16, 15)):
        r = persist_chain_accrual(db, ticker="SPY", per_strike_rows=[[700.0, 1.0, float(h)]],
                                  spot=700.0, ts_utc=_ts_at(h, m))
        assert r["status"] == "written"
    con = sqlite3.connect(db)
    n, lo, hi = con.execute("SELECT count(*), min(et_minute), max(et_minute) "
                            "FROM option_chain_accrual WHERE ticker='SPY'").fetchone()
    con.close()
    assert n == 4, f"accrual collapsed to {n} row(s) — it is not a time series"
    assert lo == 555 and hi == 975, "span does not reach the mandated boundaries"


def test_accrual_persist_refuses_saturday(tmp_path):
    """RC-193: 10:00 ET is inside the span on a Saturday too; the calendar comes first."""
    ts = datetime(2026, 8, 1, 10, 0, tzinfo=ET).timestamp()
    res = persist_chain_accrual(tmp_path / "ac.db", ticker="SPY",
                                per_strike_rows=[[745.0, 1.0, 10.0]], spot=745.0, ts_utc=ts)
    assert res["status"] == "skipped" and res["reason"] == "non_trading_day", res
