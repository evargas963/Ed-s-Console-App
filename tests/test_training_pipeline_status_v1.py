"""POD pipeline status aggregate (P0-3)."""
from __future__ import annotations

from pathlib import Path




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
