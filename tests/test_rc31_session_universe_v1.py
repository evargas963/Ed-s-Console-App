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


# ── RC-31 REOPENED (operator v6 audit): the fix was a SCOPE close, not a CLASS close ─────────
# TCN's window was fixed while HAR, cost-aware, cross-asset, quantile and survival each ran
# their OWN np.diff over the same closes. Smoking gun, reproduced before accepting the reopen:
# har_features(...)[3,0] equalled log(MonOpen/FriClose)^2 EXACTLY — the whole weekend as one
# bar-to-bar r^2. One shared primitive now exists; these tests fail if any path regresses.

def test_har_never_contains_the_overnight_r2():
    """The operator's directive verbatim: 'test must fail if HAR equals overnight r²'."""
    from research.har_rv_eval_v1.runner import har_features
    ends = np.array([_ts(2026, 7, 24, 15, 58), _ts(2026, 7, 24, 15, 59),
                     _ts(2026, 7, 27, 9, 31), _ts(2026, 7, 27, 9, 32)])
    closes = np.array([100.0, 100.1, 102.0, 102.1])
    F = har_features(ends, closes)
    gap_r2 = (np.log(102.0 / 100.1)) ** 2
    assert not np.any(np.isclose(F, gap_r2)), (
        f"the weekend gap entered HAR as an r^2 again: {F}"
    )
    assert np.isfinite(F).all(), "NaN leaked into HAR features — exclusion must happen inside"


def test_session_safe_returns_nan_at_the_boundary_and_only_there():
    from research.tcn_eval_v1.runner import session_safe_log_returns
    ends = np.array([_ts(2026, 7, 24, 15, 58), _ts(2026, 7, 24, 15, 59),
                     _ts(2026, 7, 27, 9, 31), _ts(2026, 7, 27, 9, 32)])
    closes = np.array([100.0, 100.1, 102.0, 102.1])
    r = session_safe_log_returns(ends, closes)
    assert np.isnan(r[0]), "the prepend self-diff must be NaN, it is not a return"
    assert np.isnan(r[2]), "the Fri->Mon gap must be NaN — it is not a bar return"
    assert np.isfinite(r[1]) and np.isfinite(r[3]), "intra-session returns must survive"


def test_har_ends_is_required_so_a_missed_caller_fails_loudly():
    """An optional `ends` would let a missed caller stay silently session-blind."""
    from research.har_rv_eval_v1.runner import har_features
    with pytest.raises(TypeError):
        har_features(np.array([100.0, 100.1]))  # old single-argument form must be dead


# ── RC-31 REOPENED AGAIN (operator v7 audit): session-filtering the BARS was not enough ──────
# Two survivors of the "class" close: (1) the Kalman FILTER carried state across the weekend —
# at Monday's first bar the innovation measured Friday-close -> Monday-open even on RTH bars;
# (2) the LABELS loader still selected every snapshot row with no session predicate.

def test_kalman_state_never_crosses_a_session_gap():
    from research.kalman_eval_v1.runner import session_safe_kalman
    ends = np.array([_ts(2026, 7, 24, 15, 58), _ts(2026, 7, 24, 15, 59),
                     _ts(2026, 7, 27, 9, 31), _ts(2026, 7, 27, 9, 32),
                     _ts(2026, 7, 27, 9, 33)])
    closes = np.array([100.0, 100.1, 102.0, 102.1, 102.05])
    logp = np.log(closes)
    states = session_safe_kalman(ends, logp, q=1e-6, r=1e-4)
    gap = float(np.log(102.0 / 100.1))
    # Monday's restart bar is EXCLUDED (NaN), not a fabricated-calm zero.
    assert np.isnan(states[2]).all(), "the day-restart bar must be NaN — its state is not an estimate"
    # No innovation anywhere may be the weekend gap (that was the v7 smoking gun).
    innov = states[:, 2]
    finite = innov[np.isfinite(innov)]
    assert not np.any(np.isclose(finite, gap, atol=1e-6)), (
        f"the Fri->Mon gap entered the Kalman innovation: {innov}"
    )
    # Monday's post-restart innovations are intra-day sized, never gap sized.
    assert np.all(np.abs(states[3:, 2][np.isfinite(states[3:, 2])]) < 0.01), states[3:, 2]
    # Friday's rows are ordinary finite estimates (day 1 restart bar aside).
    assert np.isfinite(states[1]).all()


def test_kalman_build_xy_excludes_the_restart_bar_label():
    from research.kalman_eval_v1.runner import _build_xy
    ends = np.array([_ts(2026, 7, 24, 15, 58), _ts(2026, 7, 24, 15, 59),
                     _ts(2026, 7, 27, 9, 31), _ts(2026, 7, 27, 9, 32)])
    closes = np.array([100.0, 100.1, 102.0, 102.1])
    # A label at Monday's FIRST bar rides the restart state -> must be excluded, never imputed.
    X1, y1, d1 = _build_xy(ends, closes, [(_ts(2026, 7, 27, 9, 31), "up")], 1e-6, 1e-4)
    assert len(X1) == 0, "a label on the day-restart bar was admitted"
    # Control: a label one bar later attaches to a real intra-day state.
    X2, y2, d2 = _build_xy(ends, closes, [(_ts(2026, 7, 27, 9, 32), "up")], 1e-6, 1e-4)
    assert len(X2) == 1 and np.isfinite(X2).all(), "a clean intra-day label was wrongly excluded"


def test_labels_respect_the_session_universe(tmp_path):
    from timeframe_config import SNAPSHOT_TABLE_1M

    from research.tcn_eval_v1.runner import _load_labeled_rows
    db = tmp_path / "snaps.db"
    con = sqlite3.connect(db)
    con.execute(f"CREATE TABLE {SNAPSHOT_TABLE_1M} (ticker TEXT, ts_utc REAL, outcome_5c TEXT)")
    con.executemany(
        f"INSERT INTO {SNAPSHOT_TABLE_1M} VALUES (?,?,?)",
        [
            ("SPY", _ts(2026, 7, 24, 15, 59), "up"),    # Friday RTH — kept
            ("SPY", _ts(2026, 7, 24, 17, 30), "down"),  # Friday extended — excluded under rth
            ("SPY", _ts(2026, 7, 25, 10, 0), "flat"),   # SATURDAY — excluded under rth
            ("SPY", _ts(2026, 7, 27, 9, 31), "up"),     # Monday RTH — kept
        ],
    )
    con.commit()
    con.close()
    rth = _load_labeled_rows(db, "SPY", "outcome_5c")
    assert len(rth) == 2, f"expected the 2 RTH labels, got {len(rth)}"
    assert all(y in ("up",) for _, y in rth), rth
    everything = _load_labeled_rows(db, "SPY", "outcome_5c", session="all")
    assert len(everything) == 4, "session='all' must be available, explicitly"
    with pytest.raises(ValueError):
        _load_labeled_rows(db, "SPY", "outcome_5c", session="weekend")
