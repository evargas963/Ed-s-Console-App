"""Issue 16 — scheduler/live coordination: fingerprint-gated snapshots_1m_normalized refresh."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from db import EdDB, get_snapshot_sql

from tests.conftest import in_window_ts
from horizon_outcomes import HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1
from timeframe_config import CANONICAL_TIMEFRAME as CF


@pytest.fixture
def tmp_db(tmp_path: Path) -> EdDB:
    return EdDB(tmp_path / "t16sync.db")


def test_ensure_skips_when_fingerprint_unchanged(monkeypatch, tmp_db: EdDB):
    from normalized_training_sync import (
        compute_snapshots_training_fingerprint,
        ensure_normalized_training_table,
        persist_training_fingerprint_after_materialize,
    )
    import normalized_training_sync as nts

    calls: list[int] = []

    def _track(*a, **k):
        calls.append(1)
        return {"errors": ["materialize should not run"], "normalized_rows": 0}

    monkeypatch.setattr(nts, "materialize_normalized_table", _track)

    with tmp_db._connect() as conn:
        fp0 = compute_snapshots_training_fingerprint(conn)
    persist_training_fingerprint_after_materialize(tmp_db.db_path)
    with tmp_db._connect() as conn:
        assert compute_snapshots_training_fingerprint(conn) == fp0

    r = ensure_normalized_training_table(tmp_db.db_path, force=False)
    assert r["skipped"] is True
    assert calls == []


def test_ensure_materializes_when_forced(monkeypatch, tmp_db: EdDB):
    from normalized_training_sync import ensure_normalized_training_table
    import normalized_training_sync as nts

    calls: list[int] = []

    def _fake(*a, **k):
        calls.append(1)
        return {"errors": [], "normalized_rows": 0, "raw_rows": 0, "by_ticker": {}}

    monkeypatch.setattr(nts, "materialize_normalized_table", _fake)
    r = ensure_normalized_training_table(tmp_db.db_path, force=True)
    assert r["ok"] is True
    assert r["materialized"] is True
    assert calls == [1]


def test_after_fill_outcomes_ensure_refreshes_normalized_and_skips_second(tmp_db: EdDB):
    """End-to-end: outcomes on snapshots → ensure updates normalized; second ensure is a no-op."""
    from normalized_training_sync import ensure_normalized_training_table
    from snapshot_normalizer import materialize_normalized_table

    # RC-306: t0 was 1_020_000.0 — epoch 1970-01-12, refused by RC-214's collect-window law,
    # so the 100 bars below never reached price_bars_1m and fill_outcomes had nothing to
    # label. The fixture now starts inside the window on a real trading day.
    t0 = in_window_ts(9, 20, span_minutes=100)
    t_snap = t0 + 90.0
    with tmp_db._connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                candle_open, candle_high, candle_low, candle_close, candle_volume,
                horizon_outcome_schema_version, outcome_filled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "SPY",
                CF,
                t_snap,
                "test",
                10,
                30,
                "rth",
                9999.0,
                100.0,
                101.0,
                99.0,
                100.0,
                1.0,
                HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                0,
            ),
        )
        conn.commit()
    bars = []
    for i in range(100):
        bs = t0 + i * 60.0
        bars.append(
            {
                "datetime": bs,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0 + 0.1 * i,
                "volume": 1.0,
            }
        )
    tmp_db.upsert_1m_bars("SPY", bars)
    tmp_db.fill_outcomes("SPY", CF, t_snap + 5000.0)

    with tmp_db._connect() as conn:
        s = conn.execute(
            get_snapshot_sql("tests/test_issue16_normalized_training_sync.py:100")
        ).fetchone()
    assert s["outcome_15c"] is not None
    assert s["outcome_60c"] is not None

    r1 = ensure_normalized_training_table(tmp_db.db_path, force=False)
    assert r1["ok"] is True
    assert r1["materialized"] is True
    assert not (r1.get("materialize") or {}).get("errors")

    with tmp_db._connect() as conn:
        n = conn.execute(
            "SELECT outcome_15c, outcome_60c FROM snapshots_1m_normalized WHERE ticker='SPY'"
        ).fetchone()
    assert n["outcome_15c"] == s["outcome_15c"]
    assert n["outcome_60c"] == s["outcome_60c"]

    r2 = ensure_normalized_training_table(tmp_db.db_path, force=False)
    assert r2["skipped"] is True

    # Regression: direct materialize still works and CLI persist keeps ensure happy
    mat = materialize_normalized_table(Path(tmp_db.db_path), clear_first=True)
    assert not mat.get("errors")
    from normalized_training_sync import persist_training_fingerprint_after_materialize

    persist_training_fingerprint_after_materialize(tmp_db.db_path)
    r3 = ensure_normalized_training_table(tmp_db.db_path, force=False)
    assert r3["skipped"] is True


def test_ensure_materialize_truncates_wal(monkeypatch, tmp_db: EdDB):
    """DB-WRITE-PATH-FIXES (b), 2026-05-31: a successful (forced) materialize truncates the WAL
    afterward (no checkpoint existed anywhere before → unbounded WAL growth). A skipped run
    (fingerprint unchanged) must NOT checkpoint."""
    import normalized_training_sync as nts

    calls: list[int] = []
    real = nts._wal_checkpoint_truncate

    def _spy(conn):
        calls.append(1)
        return real(conn)

    monkeypatch.setattr(nts, "_wal_checkpoint_truncate", _spy)

    r = nts.ensure_normalized_training_table(tmp_db.db_path, force=True)
    assert r["materialized"] is True
    assert r.get("wal_checkpoint_truncated") is True
    assert calls == [1], "forced materialize must checkpoint exactly once"

    calls.clear()
    r2 = nts.ensure_normalized_training_table(tmp_db.db_path, force=False)
    assert r2["skipped"] is True
    assert calls == [], "fingerprint-unchanged skip must not checkpoint"


def test_verify_normalized_freshness(tmp_db: EdDB):
    from normalized_training_sync import persist_training_fingerprint_after_materialize, verify_normalized_freshness

    with tmp_db._connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                horizon_outcome_schema_version, outcome_filled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            ("QQQ", CF, 1_100_000.0, "test", 10, 30, "rth", 100.0, HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1),
        )
        conn.commit()

    persist_training_fingerprint_after_materialize(tmp_db.db_path)
    v = verify_normalized_freshness(tmp_db.db_path)
    assert v["fresh"] is True

    with sqlite3.connect(str(tmp_db.db_path)) as conn:
        conn.execute("UPDATE snapshots SET spot = spot + 1 WHERE ticker='QQQ' AND timeframe = ?", (CF,))
        conn.commit()
    v2 = verify_normalized_freshness(tmp_db.db_path)
    assert v2["fresh"] is False


def test_fingerprint_moves_when_label_config_version_changes(monkeypatch, tmp_db: EdDB):
    """A label-semantics bump (LABEL_CONFIG_VERSION) must move the fingerprint even though the
    row-level aggregates are unchanged — otherwise a force_refresh that only rewrites outcome_Nc
    directions (same pts / same non-null counts) would leave the normalized table stale and the
    scheduler's force=False sync would skip re-materialization. This locks the Phase 1 re-baseline
    flow: bumping the version is sufficient to invalidate the normalized training table."""
    import normalized_training_sync as nts
    import training_provenance as tp

    with tmp_db._connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                horizon_outcome_schema_version, outcome_filled, outcome_5c, outcome_5c_pts
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'flat', 0.10)
            """,
            ("SPY", CF, 1_300_000.0, "test", 10, 30, "rth", 100.0, HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1),
        )
        conn.commit()

    with tmp_db._connect() as conn:
        fp_v1 = nts.compute_snapshots_training_fingerprint(conn)

        # Simulate a force_refresh that only flips the direction label: pts and non-null counts
        # unchanged, so the row-aggregate portion of the fingerprint is identical.
        conn.execute("UPDATE snapshots SET outcome_5c = 'up' WHERE ticker='SPY' AND timeframe = ?", (CF,))
        conn.commit()
        fp_same_aggs = nts.compute_snapshots_training_fingerprint(conn)
        assert fp_same_aggs == fp_v1, "direction-only rewrite is invisible to row aggregates (premise)"

        # Now bump the label config version: the fingerprint MUST move so the table re-materializes.
        monkeypatch.setattr(tp, "LABEL_CONFIG_VERSION", tp.LABEL_CONFIG_VERSION + "_probe")
        fp_v2 = nts.compute_snapshots_training_fingerprint(conn)
    assert fp_v2 != fp_v1
    assert fp_v2.endswith("_probe")
