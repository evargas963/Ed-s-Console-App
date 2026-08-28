"""The watchdog's per-ticker clock ROTATES; the aggregate clock does not. One bound cannot serve both.

`tools/console_liveness_check.py` applied STALE_LIMIT_SECS=600 to two different clocks: the
aggregate newest-snapshot clock (held fresh by the dedicated ~60s SPY/QQQ/IWM loop) and each
ticker's `last_background_log_ts_utc`, which advances only when the SERIAL full-roster sweep comes
back around. Measured on production: the sweep takes ~1000s median / ~2000s max at N=58, so the
600s bound flagged 41 of 58 healthy rotating tickers as PARTIAL-DARK.

Every test drives the REAL `check()` against a real SQLite database. The required window is forced
so the tests do not depend on wall-clock time, and `_emit` is captured so the repo's run log is
never written by the suite.
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.console_liveness_check as clc  # noqa: E402

#: Production geometry, measured 2026-08-28: 58 enrolled, serial sweep, ~1000s per rotation.
ROSTER_N = 58
ROTATION_SECS = 1000.0


def _db(tmp_path, *, ages, mc_paths=10000, newest_snapshot_age=5.0, name="ed.db"):
    """A console DB with a given per-ticker age ladder.

    `ages` is the age in seconds of each ticker's last SUCCESSFUL background collection.
    The snapshot stream is written independently so aggregate and per-ticker clocks can diverge
    exactly as they do in production.
    """
    p = tmp_path / name
    con = sqlite3.connect(str(p))
    con.execute("CREATE TABLE snapshots (ts_utc REAL, ticker TEXT, mc_paths INTEGER)")
    con.execute("CREATE TABLE logging_universe (ticker TEXT, category TEXT, "
                "last_background_log_ts_utc REAL)")
    now = time.time()
    for i in range(6):
        con.execute("INSERT INTO snapshots VALUES (?,?,?)",
                    (now - newest_snapshot_age - i, "SPY", mc_paths))
    for i, a in enumerate(ages):
        con.execute("INSERT INTO logging_universe VALUES (?,?,?)",
                    (f"T{i:02d}", "core", None if a is None else now - a))
    con.commit()
    con.close()
    return str(p)


def _healthy_ladder(n=ROSTER_N, rotation=ROTATION_SECS, offset=0.0):
    """A serial round-robin leaves clocks on a UNIFORM ladder spanning one full cycle."""
    return [offset + rotation * i / n for i in range(n)]


def _run(db_path):
    emitted: list[tuple[str, str]] = []
    with patch.object(clc, "_required_window_now", return_value=(True, "forced inside window")), \
        patch.object(clc, "_emit", side_effect=lambda s, m: emitted.append((s, m))):
        rc = clc.check(db_path)
    return rc, emitted


def _joined(emitted):
    return " | ".join(f"{s}:{m}" for s, m in emitted)


# ── the derivation itself ─────────────────────────────────────────────────────────────────────
def test_allowance_is_derived_from_the_measured_ladder_not_a_constant():
    """The allowance tracks the collector's real rotation, so it scales with roster and fetch cost."""
    slow = sorted(_healthy_ladder(rotation=1000.0))
    fast = sorted(_healthy_ladder(rotation=200.0))
    a_slow, rot_slow = clc.rotation_allowance(slow)
    a_fast, rot_fast = clc.rotation_allowance(fast)

    # the measured rotation recovers the ladder span (p90 of a uniform ladder is ~0.9 of it)
    assert 0.8 * 1000.0 <= rot_slow <= 1000.0
    assert 0.8 * 200.0 <= rot_fast <= 200.0
    assert a_slow > a_fast, "a slower collector must earn a proportionally larger allowance"
    # never stricter than the aggregate bound
    assert clc.rotation_allowance([0.0])[0] >= clc.STALE_LIMIT_SECS


def test_a_uniform_offset_does_not_inflate_the_measured_rotation():
    """Outside the window every clock ages together; the LADDER SPAN is what matters, not the offset."""
    _, rot_now = clc.rotation_allowance(sorted(_healthy_ladder(offset=0.0)))
    _, rot_off = clc.rotation_allowance(sorted(_healthy_ladder(offset=9000.0)))
    assert abs(rot_now - rot_off) < 1.0, "rotation must be offset-invariant"


def test_one_dark_ticker_cannot_inflate_the_allowance_meant_to_catch_it():
    ages = sorted(_healthy_ladder() + [8_000_000.0])
    allowance, rotation = clc.rotation_allowance(ages)
    assert rotation < 2 * ROTATION_SECS, "p90 must exclude the outlier"
    assert allowance < 8_000_000.0, "the outlier must still be flaggable"


def test_small_roster_falls_back_because_p90_cannot_exclude_an_outlier():
    """DERIVED guard: p90 sits below the max only when n >= 11 (int(n*0.9) < n-1 <=> 0.1n > 1).
    Below that a single dark ticker would define the rotation meant to catch it."""
    for n in range(1, clc.MIN_LADDER_SAMPLE):
        idx = min(n - 1, int(n * 0.9))
        assert idx == n - 1, f"at n={n} the p90 index IS the maximum — estimator unusable"
        allowance, rotation = clc.rotation_allowance([5.0] + [1200.0] * (n - 1))
        assert rotation == 0.0
        assert allowance == float(clc.STALE_LIMIT_SECS), "must fall back to the aggregate bound"
    # at the derived threshold the estimator becomes usable
    assert min(clc.MIN_LADDER_SAMPLE - 1, int(clc.MIN_LADDER_SAMPLE * 0.9)) < clc.MIN_LADDER_SAMPLE - 1


def test_two_ticker_roster_with_a_20_minute_dark_ticker_still_alerts(tmp_path):
    """The exact case that exposed the p90 weakness: a tiny roster must not infer a 20-min rotation."""
    rc, emitted = _run(_db(tmp_path, ages=[5.0, 1200.0]))
    assert rc == 1, _joined(emitted)
    assert "PARTIAL-DARK" in _joined(emitted)


# ── PROOF 1: healthy full-roster rotation -> PASS, no false PARTIAL-DARK ───────────────────────
def test_healthy_rotation_passes_and_does_not_false_alarm(tmp_path):
    rc, emitted = _run(_db(tmp_path, ages=_healthy_ladder()))
    assert rc == 0, f"healthy rotation must not alert: {_joined(emitted)}"
    assert emitted[0][0] == "OK"
    assert "PARTIAL-DARK" not in _joined(emitted)


def test_the_old_fixed_bound_would_have_false_alarmed_on_that_same_roster(tmp_path):
    """Negative control on the DEFECT itself: the very ladder above trips a flat 600s rule."""
    ages = _healthy_ladder()
    would_flag = [a for a in ages if a > clc.STALE_LIMIT_SECS]
    assert len(would_flag) >= 20, "premise: a flat 600s bound flags much of a healthy roster"
    rc, _ = _run(_db(tmp_path, ages=ages))
    assert rc == 0, "the fix must clear exactly that false alarm"


# ── PROOF 2: a ticker genuinely beyond its revisit obligation -> PARTIAL-DARK ──────────────────
def test_genuinely_skipped_ticker_is_flagged(tmp_path):
    ages = _healthy_ladder() + [ROTATION_SECS * 6]          # missed many consecutive rotations
    rc, emitted = _run(_db(tmp_path, ages=ages))
    assert rc == 1
    assert "PARTIAL-DARK" in _joined(emitted)
    assert "T58" in _joined(emitted), "the skipped ticker must be named"


def test_a_ticker_that_never_collected_is_not_flagged(tmp_path):
    """NULL clock = freshly enrolled or a quarantined non-collector; not a regression."""
    rc, emitted = _run(_db(tmp_path, ages=_healthy_ladder() + [None]))
    assert rc == 0, _joined(emitted)


# ── PROOF 3: overall snapshot stream stopped -> ALERT (aggregate strength preserved) ───────────
def test_snapshot_stream_stopped_still_alerts(tmp_path):
    rc, emitted = _run(_db(tmp_path, ages=_healthy_ladder(), newest_snapshot_age=4000.0))
    assert rc == 1
    assert "STALLED" in _joined(emitted).upper()


def test_roster_loop_dark_alerts_even_when_the_aggregate_looks_fresh(tmp_path):
    """The blind spot: SPY's 60s loop holds the aggregate clock fresh while the sweep is dead.
    A uniform stall must NOT be silently absorbed by anchoring on the newest roster clock."""
    rc, emitted = _run(_db(tmp_path, ages=_healthy_ladder(offset=7200.0), newest_snapshot_age=5.0))
    assert rc == 1, "a uniformly stalled roster must alert"
    assert "ROSTER LOOP DARK" in _joined(emitted)


# ── PROOF 4 & 5: producer liveness unchanged ──────────────────────────────────────────────────
def test_healthy_base_neutral_mc_is_producer_live(tmp_path):
    rc, emitted = _run(_db(tmp_path, ages=_healthy_ladder(), mc_paths=10000))
    assert rc == 0, _joined(emitted)
    assert "DEAD PRODUCER" not in _joined(emitted)


def test_mc_paths_absent_across_the_window_is_dead_producer(tmp_path):
    rc, emitted = _run(_db(tmp_path, ages=_healthy_ladder(), mc_paths=None))
    assert rc == 1
    assert "DEAD PRODUCER" in _joined(emitted)


# ── PROOF 6: outside the required window -> clean no-op preserved ─────────────────────────────
def test_outside_required_window_is_a_clean_noop(tmp_path):
    db = _db(tmp_path, ages=_healthy_ladder(offset=9000.0), newest_snapshot_age=9000.0)
    emitted: list[tuple[str, str]] = []
    with patch.object(clc, "_required_window_now", return_value=(False, "after close")), \
        patch.object(clc, "_emit", side_effect=lambda s, m: emitted.append((s, m))):
        rc = clc.check(db)
    assert rc == 0
    assert emitted and emitted[0][0] == "OK"
    assert "outside required window" in emitted[0][1]
