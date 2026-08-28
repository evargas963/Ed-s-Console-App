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
    a_slow, rot_slow, _ = clc.rotation_allowance(slow)
    a_fast, rot_fast, _ = clc.rotation_allowance(fast)

    # the measured rotation recovers the ladder span (p90 of a uniform ladder is ~0.9 of it)
    assert 0.8 * 1000.0 <= rot_slow <= 1000.0
    assert 0.8 * 200.0 <= rot_fast <= 200.0
    assert a_slow > a_fast, "a slower collector must earn a proportionally larger allowance"
    # never stricter than the aggregate bound
    assert clc.rotation_allowance([0.0])[0] >= clc.STALE_LIMIT_SECS


def test_a_uniform_offset_does_not_inflate_the_measured_rotation():
    """Outside the window every clock ages together; the LADDER SPAN is what matters, not the offset."""
    _, rot_now, _ = clc.rotation_allowance(sorted(_healthy_ladder(offset=0.0)))
    _, rot_off, _ = clc.rotation_allowance(sorted(_healthy_ladder(offset=9000.0)))
    assert abs(rot_now - rot_off) < 1.0, "rotation must be offset-invariant"


def test_one_dark_ticker_cannot_inflate_the_allowance_meant_to_catch_it():
    ages = sorted(_healthy_ladder() + [8_000_000.0])
    allowance, rotation, _ = clc.rotation_allowance(ages)
    assert rotation < 2 * ROTATION_SECS, "p90 must exclude the outlier"
    assert allowance < 8_000_000.0, "the outlier must still be flaggable"


def test_small_roster_collapses_to_the_floor_without_a_special_case():
    """On a handful of tickers the q=0.25 index sits at the newest clock, so the measured rotation
    is 0 and the flat aggregate floor applies — no sample-size branch needed."""
    for ages in ([5.0, 1200.0], [5.0, 1200.0, 1200.0]):
        allowance, rotation, _ = clc.rotation_allowance(sorted(ages))
        assert rotation == 0.0
        assert allowance == ages[0] + float(clc.STALE_LIMIT_SECS)
        assert any(a > allowance for a in ages), "a dark ticker must still be flaggable"


# ── CONTAMINATION: a clustered outage must not enlarge the allowance enough to hide itself ─────
def _clustered(n_healthy, d_dark, dark_age, span=ROTATION_SECS):
    ages = [span * i / max(1, n_healthy - 1) for i in range(n_healthy)]
    ages += [dark_age + 3.0 * j for j in range(d_dark)]   # went dark together => tight cluster
    return sorted(ages)


def test_clustered_outage_cannot_hide_itself_across_the_contamination_range():
    """The attack that broke the previous p90 reading at 6/58 (10%). Sweep the dark fraction well
    past the 10% boundary, at two dark ages, and require the measured rotation to stay UNcontaminated
    (i.e. the estimator recovers the healthy cycle, it does not merely happen to still flag)."""
    for dark_age in (8000.0, 30000.0):
        for d in (1, 3, 6, 9, 12, 17, 23, 29, 35, 40):
            ages = _clustered(ROSTER_N - d, d, dark_age)
            allowance, rotation, _ = clc.rotation_allowance(ages)
            assert allowance < dark_age, (
                f"{d}/{ROSTER_N} dark ({100*d/ROSTER_N:.0f}%) at {dark_age:.0f}s hid itself: "
                f"rotation={rotation:.0f} allowance={allowance:.0f}")
            assert rotation < 2 * ROTATION_SECS, (
                f"rotation contaminated at d={d}, dark_age={dark_age:.0f}: {rotation:.0f}")


def test_trim_uses_membership_not_the_verdict_multiplier():
    """A ticker more than ONE rotation behind is not part of the rotation being measured. Trimming
    at the generous verdict multiplier instead left a 50%-dark group at 8000s hidden behind its own
    inflated allowance."""
    ages = _clustered(ROSTER_N - 29, 29, 8000.0)          # exactly 50% dark
    allowance, rotation, _ = clc.rotation_allowance(ages)
    assert rotation < 2 * ROTATION_SECS, f"seed stayed contaminated: {rotation:.0f}"
    assert allowance < 8000.0


def test_the_previous_p90_reading_would_have_hidden_a_ten_percent_outage():
    """Negative control on the DEFECT: pin why p90 had to be replaced, not merely retuned."""
    ages = _clustered(ROSTER_N - 6, 6, 8000.0)
    p90 = ages[min(len(ages) - 1, int(len(ages) * 0.9))]
    old_rotation = p90 - ages[0]
    old_allowance = ages[0] + max(float(clc.STALE_LIMIT_SECS),
                                  clc.ROTATIONS_ALLOWED * old_rotation)
    assert old_allowance >= 8000.0, "premise: p90 absorbed the cluster at 6/58"
    # the shipped estimator does not
    assert clc.rotation_allowance(ages)[0] < 8000.0


def test_clustered_outage_alerts_end_to_end(tmp_path):
    rc, emitted = _run(_db(tmp_path, ages=_clustered(ROSTER_N - 9, 9, 8000.0)))
    assert rc == 1
    assert "PARTIAL-DARK" in _joined(emitted)


# ── FAIL-CLOSED: past the breakdown point the roster must ALERT, never pass ───────────────────
def test_unmeasurable_ladder_never_reports_ok(tmp_path):
    """Beyond the estimator's breakdown point the quantile read point sits INSIDE the dark group
    and the rotation it returns is that group's own age. That must ALERT, not silently pass, and
    must not fabricate a rotation or fall back to the flat per-ticker bound."""
    for dark_age in (8000.0, 30000.0):
        for d in (44, 46, 47, 52, 55, 57):                    # 76% .. 98% of the roster dark
            ages = _clustered(ROSTER_N - d, d, dark_age)
            allowance, rotation, measurable = clc.rotation_allowance(ages)
            assert measurable is False, f"d={d} @{dark_age:.0f}s claimed measurable"
            assert allowance is None and rotation is None, "must not fabricate an estimate"

            rc, emitted = _run(_db(tmp_path, ages=ages, name=f"u{d}_{int(dark_age)}.db"))
            assert rc == 1, f"d={d} @{dark_age:.0f}s FAILED OPEN: {_joined(emitted)}"
            assert "UNMEASURABLE" in _joined(emitted).upper()
            assert emitted[0][0] == "ALERT"


def test_the_whole_dark_fraction_range_alerts_with_no_ok_gap(tmp_path):
    """Sweep every dark fraction end to end: the verdict may change KIND (partial-dark ->
    unmeasurable) but must never become OK while a large group is dark."""
    for d in range(1, ROSTER_N - 1):
        ages = _clustered(ROSTER_N - d, d, 8000.0)
        rc, emitted = _run(_db(tmp_path, ages=ages, name=f"s{d}.db"))
        assert rc == 1, f"{d}/{ROSTER_N} dark returned OK: {_joined(emitted)}"


def test_healthy_roster_is_measurable_and_natural_step_unevenness_does_not_trip_it():
    """MEASURED on the live roster: ladder steps median 17.0s, max 67.9s => natural unevenness is
    4.0x, far below the 10x cluster-boundary ratio. A healthy ladder must stay measurable."""
    allowance, rotation, measurable = clc.rotation_allowance(sorted(_healthy_ladder()))
    assert measurable is True and allowance is not None
    # a 4x-uneven ladder (the measured live worst case) must still be measurable
    uneven = sorted([ROTATION_SECS * i / ROSTER_N for i in range(ROSTER_N - 1)] + [ROTATION_SECS])
    assert clc.rotation_allowance(uneven)[2] is True


# ── TOLERANCE: two rotations must cover MEASURED same-ticker revisit jitter ────────────────────
def test_two_rotations_covers_measured_revisit_jitter_but_not_a_real_hiccup():
    """Derived from 524 same-ticker background-logger revisit INTERVALS (outage hours excluded):
    p50 1391s, p90 2311s, p95 2656s, p99 2723s, max 6893s. The tolerance must absorb jitter up to
    p99 and still flag the 1.9-hour outlier."""
    allowance, rotation, _ = clc.rotation_allowance(sorted(_healthy_ladder(rotation=1391.0)))
    for label, interval in (("p50", 1391.0), ("p90", 2311.0), ("p95", 2656.0), ("p99", 2723.0)):
        assert interval <= allowance, f"{label} revisit {interval}s false-alarms (allow {allowance:.0f})"
    assert 6893.0 > allowance, "a 1.9-hour RTH gap must still alert"


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
