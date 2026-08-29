"""The watchdog's per-ticker clock ROTATES; the aggregate clock does not. One bound cannot serve both.

`tools/console_liveness_check.py` applied STALE_LIMIT_SECS=600 to two different clocks: the
aggregate newest-snapshot clock (held fresh by the dedicated ~60s SPY/QQQ/IWM loop) and each
ticker's `last_background_log_ts_utc`, which advances only when the SERIAL full-roster sweep comes
back around. Measured on production: the sweep takes ~1400s median at N=58, so the 600s bound
flagged 58 of 58 healthy rotating tickers as PARTIAL-DARK.

The revisit obligation is measured from OBSERVED same-ticker revisits, never inferred from the
cross-sectional age ladder — a ladder cannot separate "58 tickers rotating slowly" from "6 rotating
fast plus 52 stale", so every ladder statistic is defeatable by a diffuse stale tail.

Every test drives the REAL `check()` against a real SQLite database. The required window is forced
so tests do not depend on wall-clock time, and `_emit` is captured so the repo's run log is never
written by the suite.
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

#: Production geometry, measured 2026-08-28: 58 enrolled, serial sweep, ~1400s median revisit.
ROSTER_N = 58
ROTATION_SECS = 1400.0
HISTORY = 6          # prior collections per ticker, so a revisit interval is observable


def _db(tmp_path, *, ages, mc_paths=10000, newest_snapshot_age=5.0, name="ed.db",
        history_cycle=ROTATION_SECS, with_history=True):
    """A console DB whose per-ticker ages are `ages`.

    Each ticker also carries real background-logger HISTORY at `history_cycle`, so the collector's
    rotation is OBSERVABLE. A dark ticker simply stopped: its history ends at its last success.
    """
    p = tmp_path / name
    con = sqlite3.connect(str(p))
    con.execute("CREATE TABLE snapshots (ts_utc REAL, ticker TEXT, mc_paths INTEGER, "
                "logger_source TEXT)")
    con.execute("CREATE TABLE logging_universe (ticker TEXT, category TEXT, "
                "last_background_log_ts_utc REAL)")
    now = time.time()
    for i in range(6):                                  # aggregate stream, independent of roster
        con.execute("INSERT INTO snapshots VALUES (?,?,?,?)",
                    (now - newest_snapshot_age - i, "SPY", mc_paths, "base_money_path"))
    for i, a in enumerate(ages):
        tk = f"T{i:02d}"
        con.execute("INSERT INTO logging_universe VALUES (?,?,?)",
                    (tk, "core", None if a is None else now - a))
        if a is not None and with_history:
            # History is shifted by newest_snapshot_age too, so a scenario that stalls the
            # aggregate stream really does stall EVERY snapshot, not just the base-loop rows.
            for h in range(HISTORY):
                con.execute("INSERT INTO snapshots VALUES (?,?,?,?)",
                            (now - newest_snapshot_age - a - history_cycle * h, tk, mc_paths,
                             "background_logger"))
    con.commit()
    con.close()
    return str(p)


def _healthy_ladder(n=ROSTER_N, rotation=ROTATION_SECS, offset=0.0):
    """A serial round-robin leaves clocks on a UNIFORM ladder spanning one full cycle."""
    return [offset + rotation * i / n for i in range(n)]


def _clustered(n_healthy, d_dark, dark_age):
    """TIGHT outage: every failed ticker frozen at nearly the same age (sharp boundary)."""
    ages = [ROTATION_SECS * i / max(1, n_healthy - 1) for i in range(n_healthy)]
    return sorted(ages + [dark_age + 3.0 * j for j in range(d_dark)])


def _diffuse(n_healthy, d_dark, stale_lo, stale_hi):
    """DIFFUSE outage: failed clocks spread smoothly across multiple rotations — NO boundary gap.
    This is the realistic geometry: clocks start at different rotation positions and failures
    persist for different durations."""
    ages = [ROTATION_SECS * i / max(1, n_healthy - 1) for i in range(n_healthy)]
    if d_dark:
        step = (stale_hi - stale_lo) / max(1, d_dark - 1)
        ages += [stale_lo + step * j for j in range(d_dark)]
    return sorted(ages)


def _run(db_path):
    emitted: list[tuple[str, str]] = []
    with patch.object(clc, "_required_window_now", return_value=(True, "forced inside window")), \
        patch.object(clc, "_emit", side_effect=lambda s, m: emitted.append((s, m))):
        rc = clc.check(db_path)
    return rc, emitted


def _joined(emitted):
    return " | ".join(f"{s}:{m}" for s, m in emitted)


# ── the derivation itself ─────────────────────────────────────────────────────────────────────
def _rotation_of(tmp_path, ages, name, history_cycle=ROTATION_SECS):
    con = sqlite3.connect(_db(tmp_path, ages=ages, name=name, history_cycle=history_cycle))
    try:
        return clc.observed_rotation(con)
    finally:
        con.close()


def test_rotation_is_measured_from_observed_revisits_not_the_ladder(tmp_path):
    slow, _ = _rotation_of(tmp_path, _healthy_ladder(), "slow.db", history_cycle=1400.0)
    fast, _ = _rotation_of(tmp_path, _healthy_ladder(rotation=200.0), "fast.db", history_cycle=200.0)
    assert abs(slow - 1400.0) < 1.0
    assert abs(fast - 200.0) < 1.0


def test_rotation_is_offset_invariant(tmp_path):
    a, _ = _rotation_of(tmp_path, _healthy_ladder(offset=0.0), "o0.db")
    b, _ = _rotation_of(tmp_path, _healthy_ladder(offset=9000.0), "o9.db")
    assert abs(a - b) < 1.0


def test_unmeasurable_when_nothing_has_been_collected_twice(tmp_path):
    """FAIL CLOSED: no observed revisits => no obligation can be measured => never OK."""
    path = _db(tmp_path, ages=_healthy_ladder(), name="nohist.db", with_history=False)
    con = sqlite3.connect(path)
    try:
        rotation, n = clc.observed_rotation(con)
    finally:
        con.close()
    assert rotation is None and n == 0
    rc, emitted = _run(path)
    assert rc == 1 and "UNMEASURABLE" in _joined(emitted).upper()


# ── PROOF 1: healthy full-roster rotation -> PASS, no false PARTIAL-DARK ───────────────────────
def test_healthy_rotation_passes_and_does_not_false_alarm(tmp_path):
    rc, emitted = _run(_db(tmp_path, ages=_healthy_ladder()))
    assert rc == 0, f"healthy rotation must not alert: {_joined(emitted)}"
    assert emitted[0][0] == "OK"
    assert "PARTIAL-DARK" not in _joined(emitted)


def test_the_old_fixed_bound_would_have_false_alarmed_on_that_same_roster(tmp_path):
    """Negative control on the DEFECT itself: the very ladder above trips a flat 600s rule."""
    ages = _healthy_ladder()
    assert len([a for a in ages if a > clc.STALE_LIMIT_SECS]) >= 20
    assert _run(_db(tmp_path, ages=ages, name="old.db"))[0] == 0


# ── PROOF 2: a ticker genuinely beyond its revisit obligation -> PARTIAL-DARK ──────────────────
def test_genuinely_skipped_ticker_is_flagged(tmp_path):
    ages = _healthy_ladder() + [ROTATION_SECS * 6]
    rc, emitted = _run(_db(tmp_path, ages=ages, name="skip.db"))
    assert rc == 1
    assert "PARTIAL-DARK" in _joined(emitted)
    assert "T58" in _joined(emitted)


def test_a_ticker_that_never_collected_is_not_flagged(tmp_path):
    rc, emitted = _run(_db(tmp_path, ages=_healthy_ladder() + [None], name="null.db"))
    assert rc == 0, _joined(emitted)


# ── PROOF 3: aggregate strength preserved ─────────────────────────────────────────────────────
def test_snapshot_stream_stopped_still_alerts(tmp_path):
    rc, emitted = _run(_db(tmp_path, ages=_healthy_ladder(), newest_snapshot_age=4000.0,
                           name="stall.db"))
    assert rc == 1
    assert "STALLED" in _joined(emitted).upper()


def test_roster_loop_dark_alerts_even_when_the_aggregate_looks_fresh(tmp_path):
    rc, emitted = _run(_db(tmp_path, ages=_healthy_ladder(offset=7200.0), name="loopdark.db"))
    assert rc == 1
    assert "ROSTER LOOP DARK" in _joined(emitted)


# ── PROOF 4 & 5: producer liveness unchanged ──────────────────────────────────────────────────
def test_healthy_base_neutral_mc_is_producer_live(tmp_path):
    rc, emitted = _run(_db(tmp_path, ages=_healthy_ladder(), mc_paths=10000, name="mcok.db"))
    assert rc == 0, _joined(emitted)
    assert "DEAD PRODUCER" not in _joined(emitted)


def test_mc_paths_absent_across_the_window_is_dead_producer(tmp_path):
    rc, emitted = _run(_db(tmp_path, ages=_healthy_ladder(), mc_paths=None, name="mcdead.db"))
    assert rc == 1
    assert "DEAD PRODUCER" in _joined(emitted)


# ── PROOF 6: outside the required window -> clean no-op preserved ─────────────────────────────
def test_outside_required_window_is_a_clean_noop(tmp_path):
    db = _db(tmp_path, ages=_healthy_ladder(offset=9000.0), newest_snapshot_age=9000.0,
             name="outside.db")
    emitted: list[tuple[str, str]] = []
    with patch.object(clc, "_required_window_now", return_value=(False, "after close")), \
        patch.object(clc, "_emit", side_effect=lambda s, m: emitted.append((s, m))):
        rc = clc.check(db)
    assert rc == 0
    assert emitted and emitted[0][0] == "OK" and "outside required window" in emitted[0][1]


# ── PROOF 7: BOTH outage geometries must never produce an OK ──────────────────────────────────
def test_tight_clustered_darkness_never_reports_ok(tmp_path):
    """Geometry 1: every failed ticker frozen at nearly the same age (a sharp boundary)."""
    for dark_age in (8000.0, 30000.0):
        for d in (6, 12, 23, 29, 35, 40, 44, 46, 52, 55, 57):
            ages = _clustered(ROSTER_N - d, d, dark_age)
            rc, emitted = _run(_db(tmp_path, ages=ages, name=f"c{d}_{int(dark_age)}.db"))
            assert rc == 1, (f"tight {d}/{ROSTER_N} @{dark_age:.0f}s returned OK: "
                             f"{_joined(emitted)}")


def test_diffuse_multi_rotation_darkness_never_reports_ok(tmp_path):
    """Geometry 2: failed clocks spread SMOOTHLY across multiple rotations — no boundary gap, so
    nothing in the ladder's SHAPE reveals them. This defeated every ladder-based estimator."""
    for d in (44, 52, 55):                                   # ~76%, ~90%, ~95%
        for lo, hi in ((1500.0, 4000.0), (1600.0, 8000.0), (2000.0, 20000.0),
                       (2000.0, 60000.0), (3000.0, 100000.0)):
            ages = _diffuse(ROSTER_N - d, d, lo, hi)
            rc, emitted = _run(_db(tmp_path, ages=ages, name=f"f{d}_{int(lo)}_{int(hi)}.db"))
            assert rc == 1, (f"diffuse {d}/{ROSTER_N} {lo:.0f}-{hi:.0f}s returned OK: "
                             f"{_joined(emitted)}")


def test_a_diffuse_dark_population_cannot_define_its_own_rotation(tmp_path):
    """The root cause: the dark population must never become the population the rotation is
    inferred from. Observed revisits recover the TRUE cycle regardless of how the tail is spread."""
    for d in (44, 52, 55):
        for lo, hi in ((2000.0, 20000.0), (3000.0, 100000.0)):
            ages = _diffuse(ROSTER_N - d, d, lo, hi)
            rot, _n = _rotation_of(tmp_path, ages, f"r{d}_{int(lo)}_{int(hi)}.db")
            assert abs(rot - ROTATION_SECS) < 1.0, (
                f"rotation contaminated by the dark tail at {d}/{ROSTER_N} "
                f"{lo:.0f}-{hi:.0f}s: {rot:.0f}s")


def test_every_dark_fraction_alerts_with_no_ok_gap(tmp_path):
    """Sweep end to end in both geometries: the verdict may change KIND but never becomes OK."""
    for d in range(2, ROSTER_N - 1, 3):
        rc, _e = _run(_db(tmp_path, ages=_clustered(ROSTER_N - d, d, 8000.0), name=f"sc{d}.db"))
        assert rc == 1, f"tight {d}/{ROSTER_N} returned OK"
        rc, _e = _run(_db(tmp_path, ages=_diffuse(ROSTER_N - d, d, 2000.0, 20000.0),
                          name=f"sf{d}.db"))
        assert rc == 1, f"diffuse {d}/{ROSTER_N} returned OK"


def test_coverage_rule_catches_a_diffuse_outage_still_inside_per_ticker_tolerance(tmp_path):
    """Each dark ticker is individually within K rotations, so only the POPULATION signal can see
    it: a serial sweep puts almost everything within ONE rotation, so a majority beyond one
    rotation contradicts the rotation actually being achieved."""
    ages = _diffuse(ROSTER_N - 44, 44, 1500.0, 4000.0)
    allowance = clc.ROTATIONS_ALLOWED * ROTATION_SECS
    assert all(a < allowance for a in ages), "premise: every ticker is inside per-ticker tolerance"
    rc, emitted = _run(_db(tmp_path, ages=ages, name="cov.db"))
    assert rc == 1
    assert "NOT BEING SWEPT" in _joined(emitted).upper()


def test_healthy_jitter_does_not_trip_the_coverage_rule(tmp_path):
    """Measured jitter puts ~10% of tickers past one rotation (p90 = 1.66x). Only a MAJORITY may
    trip coverage, so normal jitter must pass."""
    ages = _healthy_ladder(n=ROSTER_N - 6) + [ROTATION_SECS * 1.7] * 6      # ~10% past one rotation
    rc, emitted = _run(_db(tmp_path, ages=sorted(ages), name="jit.db"))
    assert rc == 0, _joined(emitted)


# ── TOLERANCE: three rotations must cover MEASURED same-ticker revisit jitter ──────────────────
def test_three_rotations_covers_measured_revisit_jitter_but_not_a_real_hiccup():
    """Derived from 524 same-ticker background-logger revisit INTERVALS (outage hours excluded):
    p50 1391s, p90 2311s, p95 2656s, p99 2723s, max 6893s."""
    allowance = clc.ROTATIONS_ALLOWED * 1391.0
    for label, interval in (("p50", 1391.0), ("p90", 2311.0), ("p95", 2656.0), ("p99", 2723.0)):
        assert interval <= allowance, f"{label} revisit {interval}s false-alarms"
    assert 6893.0 > allowance, "a 1.9-hour RTH gap must still alert"
