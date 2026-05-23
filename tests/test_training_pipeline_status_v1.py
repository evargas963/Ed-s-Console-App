"""POD pipeline status aggregate (P0-3)."""
from __future__ import annotations

from pathlib import Path


def test_enrollment_category_counts(tmp_path: Path):
    from db import EdDB
    from training_pipeline_status import enrollment_category_counts

    db_path = tmp_path / "t.db"
    edb = EdDB(str(db_path))
    edb.logging_universe_sync_core(["SPY", "QQQ"], "2026-05-22T12:00:00Z")
    edb.logging_universe_upsert_pinned("IWM", enrollment_source="test", now_ts=1716380000.0)

    counts = enrollment_category_counts(db_path)
    assert counts.get("core", 0) >= 2
    assert counts.get("pinned", 0) >= 1
    assert counts["total"] >= 3


def test_record_run_start_writes_json(tmp_path: Path):
    from training_pipeline_status import record_run_start, STATUS_SCHEMA_VERSION

    status_path = tmp_path / "training_pipeline_status.json"
    payload = record_run_start(
        path=status_path,
        ml_horizon="1c",
        target_column="outcome_1c",
        tickers=["SPY"],
        db_path=tmp_path / "empty.db",
    )
    assert payload["schema_version"] == STATUS_SCHEMA_VERSION
    assert status_path.is_file()
    assert payload["tickers_selected_count"] == 1
