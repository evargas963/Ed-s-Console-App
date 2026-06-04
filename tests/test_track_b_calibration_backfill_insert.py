"""Track B (v2.1) — historical calibration backfill INSERT path.

New `backfill_calibration_decisions_insert_from_snapshots` writes a
calibration_decision_log row for every snapshot that has fusion populated
AND outcome_5c populated but no existing calibration row. Distinct from
the existing UPDATE path (`backfill_v2_advisory_decisions`).

Acceptance per v2.1 plan:
  - Fixture DB with N snapshots -> expect M inserts (M = qualifying rows)
  - Second run = 0 inserts (idempotent via NOT EXISTS + UNIQUE)
  - Returns {inserted, skipped, skipped_reason_counts}
  - decision_source='reconstructed_from_snapshot' on all inserted rows
    (training-skew gate per [REAL-GATE: training-skew] OPEN_ITEMS tag)

Per AGENTS No-new-files: new test file is allowed (new topic; existing
tests/test_calibration_*.py own UPDATE-path behavior, fail-closed, and
production logging — none own INSERT-from-snapshot reconstruction).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


from calibration.schema import ensure_calibration_schema
from calibration.v2_advisory_backfill import (
    RECONSTRUCTED_DECISION_SOURCE,
    backfill_calibration_decisions_insert_from_snapshots,
)


# Minimal snapshots schema sufficient for the backfill SELECT — only the
# columns the function reads. Real db.py has 200+ columns; we lock the
# narrow contract Track B depends on so a future snapshots-schema refactor
# that drops a Track B input column fails this test in the same commit.
_SNAPSHOTS_DDL = """
CREATE TABLE snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    ts_utc REAL NOT NULL,
    spot REAL,
    session_bucket TEXT,
    expiry TEXT,
    zone TEXT,
    vwap_side TEXT,
    nearest_above_dist REAL,
    nearest_below_dist REAL,
    regime_primary TEXT,
    regime_confidence TEXT,
    vol_regime TEXT,
    vix_bucket TEXT,
    fusion_dominant_prob REAL,
    fusion_dominant_direction TEXT,
    fusion_available INTEGER,
    fusion_prob_up REAL,
    fusion_prob_down REAL,
    fusion_prob_flat REAL,
    outcome_1c TEXT,
    outcome_5c TEXT,
    outcome_15c TEXT,
    outcome_60c TEXT,
    outcome_1c_pts REAL,
    outcome_5c_pts REAL,
    outcome_15c_pts REAL,
    outcome_60c_pts REAL
);
"""


def _seed_db(tmp_path: Path, snapshots: list[dict]) -> Path:
    db_path = tmp_path / "track_b.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_SNAPSHOTS_DDL)
        ensure_calibration_schema(conn)
        for s in snapshots:
            cols = ", ".join(s.keys())
            ph = ", ".join("?" for _ in s)
            conn.execute(
                f"INSERT INTO snapshots ({cols}) VALUES ({ph})",
                list(s.values()),
            )
        conn.commit()
    finally:
        conn.close()
    return db_path


def _qualifying(ticker: str, ts: float, *, outcome: str = "up") -> dict:
    """A snapshot row that qualifies for backfill (fusion + outcome populated)."""
    return {
        "ticker": ticker,
        "timeframe": "1m",
        "ts_utc": ts,
        "spot": 500.0,
        "session_bucket": "morning",
        "zone": "pin_neutral",
        "vwap_side": "above",
        "nearest_above_dist": 1.2,
        "nearest_below_dist": -0.8,
        "regime_primary": "trend_up",
        "regime_confidence": "medium",
        "vol_regime": "normal",
        "vix_bucket": "vix_low",
        "fusion_dominant_prob": 0.62,
        "fusion_dominant_direction": "up",
        "fusion_available": 1,
        "fusion_prob_up": 0.62,
        "fusion_prob_down": 0.21,
        "fusion_prob_flat": 0.17,
        "outcome_1c": outcome,
        "outcome_5c": outcome,
        "outcome_15c": outcome,
        "outcome_60c": outcome,
        "outcome_5c_pts": 1.4,
    }


def test_backfill_inserts_one_row_per_qualifying_snapshot(tmp_path: Path) -> None:
    base = 1_800_000_000.0
    snaps = [_qualifying("SPY", base + i * 60.0) for i in range(5)]
    db_path = _seed_db(tmp_path, snaps)

    stats = backfill_calibration_decisions_insert_from_snapshots(db_path)
    assert stats["inserted"] == 5
    assert stats["skipped"] == 0
    assert stats["skipped_reason_counts"] == {}

    conn = sqlite3.connect(str(db_path))
    try:
        total = conn.execute("SELECT COUNT(*) FROM calibration_decision_log").fetchone()[0]
    finally:
        conn.close()
    assert total == 5


def test_backfill_skips_snapshots_missing_fusion(tmp_path: Path) -> None:
    base = 1_800_000_000.0
    qual = _qualifying("SPY", base)
    no_fusion = _qualifying("SPY", base + 60.0)
    no_fusion["fusion_dominant_prob"] = None
    no_outcome = _qualifying("SPY", base + 120.0)
    no_outcome["outcome_5c"] = None
    db_path = _seed_db(tmp_path, [qual, no_fusion, no_outcome])

    stats = backfill_calibration_decisions_insert_from_snapshots(db_path)
    # SELECT filter excludes the 2 missing-data rows; they don't reach the
    # loop so they're invisible in the stats (not "skipped" — never visited).
    assert stats["inserted"] == 1
    assert stats["skipped"] == 0


def test_backfill_second_run_inserts_zero(tmp_path: Path) -> None:
    """Idempotency: re-running against unchanged data yields 0 inserts."""
    base = 1_800_000_000.0
    snaps = [_qualifying("SPY", base + i * 60.0) for i in range(3)]
    db_path = _seed_db(tmp_path, snaps)

    first = backfill_calibration_decisions_insert_from_snapshots(db_path)
    second = backfill_calibration_decisions_insert_from_snapshots(db_path)

    assert first["inserted"] == 3
    assert second["inserted"] == 0
    assert second["skipped"] == 0
    assert second["skipped_reason_counts"] == {}


def test_backfill_does_not_overwrite_existing_calibration_rows(tmp_path: Path) -> None:
    """If a calibration row already exists for (ticker, ts_utc), the snapshot
    is excluded by the NOT EXISTS clause and the existing row is untouched."""
    base = 1_800_000_000.0
    qual = _qualifying("SPY", base)
    db_path = _seed_db(tmp_path, [qual])

    # Pre-seed a calibration row marked as live writer (no decision_source).
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO calibration_decision_log "
            "(ticker, canonical_timeframe, decision_ts_utc, calibration_trust) "
            "VALUES (?, '1m', ?, 'trusted')",
            ("SPY", base),
        )
        conn.commit()
    finally:
        conn.close()

    stats = backfill_calibration_decisions_insert_from_snapshots(db_path)
    assert stats["inserted"] == 0

    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT calibration_trust, decision_source FROM calibration_decision_log "
            "WHERE ticker='SPY' AND decision_ts_utc=?",
            (base,),
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "trusted"  # original calibration_trust preserved
    assert row[1] is None       # original (live writer) decision_source preserved


def test_backfill_marks_decision_source_as_reconstructed(tmp_path: Path) -> None:
    """Every inserted row carries decision_source='reconstructed_from_snapshot'
    so training-skew analyses can filter."""
    base = 1_800_000_000.0
    snaps = [_qualifying("SPY", base + i * 60.0) for i in range(3)]
    db_path = _seed_db(tmp_path, snaps)

    backfill_calibration_decisions_insert_from_snapshots(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT decision_source FROM calibration_decision_log "
            "WHERE ticker='SPY' ORDER BY decision_ts_utc"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 3
    assert all(r[0] == RECONSTRUCTED_DECISION_SOURCE for r in rows)
    assert RECONSTRUCTED_DECISION_SOURCE == "reconstructed_from_snapshot"


def test_backfill_copies_analysis_columns_from_snapshot(tmp_path: Path) -> None:
    """Analysis-critical columns (zone, vwap_side, nearest_above_dist, outcomes)
    must travel from snapshot -> calibration row so calibration analyzers see
    the same values they'd have seen if the live writer had logged the row."""
    base = 1_800_000_000.0
    qual = _qualifying("SPY", base)
    qual["zone"] = "breakout"
    qual["vwap_side"] = "above"
    qual["nearest_above_dist"] = 2.5
    qual["outcome_5c"] = "down"
    qual["outcome_5c_pts"] = -1.7
    db_path = _seed_db(tmp_path, [qual])

    backfill_calibration_decisions_insert_from_snapshots(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT zone, vwap_side, nearest_above_dist, outcome_5c, outcome_5c_pts "
            "FROM calibration_decision_log WHERE ticker='SPY'"
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "breakout"
    assert row[1] == "above"
    assert row[2] == 2.5
    assert row[3] == "down"
    assert row[4] == -1.7


def test_backfill_respects_limit(tmp_path: Path) -> None:
    base = 1_800_000_000.0
    snaps = [_qualifying("SPY", base + i * 60.0) for i in range(10)]
    db_path = _seed_db(tmp_path, snaps)

    stats = backfill_calibration_decisions_insert_from_snapshots(db_path, limit=4)
    assert stats["inserted"] == 4

    conn = sqlite3.connect(str(db_path))
    try:
        total = conn.execute("SELECT COUNT(*) FROM calibration_decision_log").fetchone()[0]
    finally:
        conn.close()
    assert total == 4


def test_backfill_returns_structured_skip_when_schema_missing(tmp_path: Path) -> None:
    """If snapshots table doesn't exist, return a schema_unavailable skip reason
    rather than crashing — Track B is operator-triggered, not auto-run."""
    db_path = tmp_path / "no_snapshots.db"
    conn = sqlite3.connect(str(db_path))
    try:
        ensure_calibration_schema(conn)
    finally:
        conn.close()

    stats = backfill_calibration_decisions_insert_from_snapshots(db_path)
    assert stats["inserted"] == 0
    assert any("schema_unavailable" in k for k in stats["skipped_reason_counts"].keys())


# ───────────────────── FEATURE_STUDY_PREDICATE_SQL row-level lock ─────────────────────


def test_feature_study_predicate_includes_live_and_reconstructed_excludes_premilestone(
    tmp_path: Path,
) -> None:
    """Lock which rows each predicate matches.

    Three row shapes exist in production calibration_decision_log:
      (a) trusted + decision_source NULL    -> live writer (post-quarantine)
      (b) legacy  + decision_source 'reconstructed_from_snapshot' -> Track B
      (c) legacy  + decision_source NULL    -> 42 pre-milestone unreviewed rows

    TRUSTED_PREDICATE_SQL must match only (a).
    FEATURE_STUDY_PREDICATE_SQL must match (a) + (b) but NOT (c).
    The pre-milestone rows stay excluded from both because they predate the
    current schema lock; explicit operator review is required to admit them.
    """
    from calibration.trust import (
        FEATURE_STUDY_PREDICATE_SQL,
        TRUSTED_PREDICATE_SQL,
    )

    db_path = tmp_path / "predicate_lock.db"
    conn = sqlite3.connect(str(db_path))
    try:
        ensure_calibration_schema(conn)
        # Live writer shape (trusted, NULL).
        conn.execute(
            "INSERT INTO calibration_decision_log "
            "(ticker, canonical_timeframe, decision_ts_utc, calibration_trust, decision_source) "
            "VALUES ('SPY', '1m', 1000.0, 'trusted', NULL)"
        )
        # Track B shape (legacy, reconstructed_from_snapshot).
        conn.execute(
            "INSERT INTO calibration_decision_log "
            "(ticker, canonical_timeframe, decision_ts_utc, calibration_trust, decision_source) "
            "VALUES ('SPY', '1m', 2000.0, 'legacy', 'reconstructed_from_snapshot')"
        )
        # Pre-milestone shape (legacy, NULL) — the 42-row class.
        conn.execute(
            "INSERT INTO calibration_decision_log "
            "(ticker, canonical_timeframe, decision_ts_utc, calibration_trust, decision_source) "
            "VALUES ('SPY', '1m', 3000.0, 'legacy', NULL)"
        )
        conn.commit()

        trusted_rows = {
            r[0] for r in conn.execute(
                f"SELECT decision_ts_utc FROM calibration_decision_log WHERE {TRUSTED_PREDICATE_SQL}"
            ).fetchall()
        }
        feature_rows = {
            r[0] for r in conn.execute(
                f"SELECT decision_ts_utc FROM calibration_decision_log WHERE {FEATURE_STUDY_PREDICATE_SQL}"
            ).fetchall()
        }
    finally:
        conn.close()

    assert trusted_rows == {1000.0}, (
        f"TRUSTED_PREDICATE_SQL must match only the live-writer row; got {trusted_rows}"
    )
    assert feature_rows == {1000.0, 2000.0}, (
        f"FEATURE_STUDY_PREDICATE_SQL must match live + Track B but exclude pre-milestone; "
        f"got {feature_rows}"
    )


def test_feature_study_and_helper_composes_with_caller_predicate() -> None:
    """`feature_study_and(sql_fragment)` returns a parenthesized AND-composition
    that callers can drop into existing WHERE clauses. Lock the exact shape so
    future refactors of the helper don't silently change predicate semantics."""
    from calibration.trust import FEATURE_STUDY_PREDICATE_SQL, feature_study_and

    composed = feature_study_and("ticker = ? AND decision_ts_utc >= ?")
    assert composed == (
        f"(ticker = ? AND decision_ts_utc >= ?) AND {FEATURE_STUDY_PREDICATE_SQL}"
    )


def test_trusted_predicate_unchanged_post_feature_study_addition() -> None:
    """Defensive lock: TRUSTED_PREDICATE_SQL string must stay exactly as the
    existing analyze_phase3 / edge_discovery / signal_engineering pipelines
    expect it. A typo in feature-predicate work cannot ripple."""
    from calibration.trust import TRUSTED_PREDICATE_SQL

    assert TRUSTED_PREDICATE_SQL == "calibration_trust = 'trusted'"
