"""PR4 auto-promote execution skip paths (governed record, env off)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from arch_competition.promotion_execution import execute_promotion_if_eligible


def _write_minimal_governed(model_dir: Path, *, would_promote: bool) -> None:
    hz = "1c"
    tku = "SPY"
    base = model_dir / "arch_competition" / hz / tku
    base.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1",
        "ticker": tku,
        "ml_horizon_slug": hz,
        "created_at_utc": "2026-01-01T00:00:00+00:00",
        "lineage": {
            "feature_cache_key": "fk",
            "data_fingerprint": "df",
            "ml_horizon_suffix": hz,
            "training_code_fingerprint": "cf",
        },
        "metrics": {"parallel": {"n_rows_scored": 100}, "cascade": {"n_rows_scored": 100}},
    }
    record = {
        "schema_version": "1",
        "promotion_decision": "promote_cascade" if would_promote else "keep_incumbent",
        "would_promote_challenger": would_promote,
        "blocked_promotion_flags": [],
        "evaluation_manifest_reference": {
            "lineage_feature_cache_key": "fk",
            "ml_horizon_slug": hz,
        },
    }
    (base / "evaluation_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (base / "promotion_decision.json").write_text(json.dumps(record), encoding="utf-8")


def test_auto_promote_skipped_when_env_off(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ED_SCHEDULER_AUTO_PROMOTE", raising=False)
    _write_minimal_governed(tmp_path, would_promote=True)
    result = execute_promotion_if_eligible(
        tmp_path,
        "SPY",
        "1c",
        scheduler_run_id="test-run",
    )
    assert result["executed"] is False
    assert result["skipped_reason"] == "auto_promote_disabled"
