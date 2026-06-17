"""G3-R3: manifest lineage stamped before governed eval."""
from __future__ import annotations

from pathlib import Path

import pytest

from features.training_canonical_input import training_canonical_lineage_header
from ml_horizon import outcome_column
from training_cache import (
    compute_feature_cache_key,
    load_run_manifest,
    save_run_manifest,
    sync_candidate_manifest_lineage_before_governed_eval,
)


def _data_fp() -> dict:
    return {
        "row_count": 100,
        "min_ts_utc": "2026-01-01T14:30:00Z",
        "max_ts_utc": "2026-01-02T20:00:00Z",
        "table": "snapshots_1m_normalized",
        "timeframe": "1m",
        "ticker": "SPY",
    }


def test_sync_stamps_horizon_before_governed_eval(tmp_path: Path):
    par = tmp_path / "parallel" / "SPY"
    cas = tmp_path / "cascade" / "SPY"
    par.mkdir(parents=True)
    cas.mkdir(parents=True)

    stale = {
        **training_canonical_lineage_header(),
        "schema_version": "2",
        "ticker": "SPY",
        "architecture": "parallel",
        "ml_horizon_suffix": "1c",
        "scheduler_cache_key": "old",
        "feature_cache_key": "old_fk",
        "training_code_fingerprint": "old_code",
        "data_fingerprint": _data_fp(),
    }
    save_run_manifest(par, dict(stale, architecture="parallel"))
    save_run_manifest(cas, dict(stale, architecture="cascade"))

    data_fp = _data_fp()
    code_fp = "new_code"
    fk = compute_feature_cache_key("SPY", data_fp, code_fp, target_column=outcome_column("5c"))

    for arch, out in (("parallel", par), ("cascade", cas)):
        sync_candidate_manifest_lineage_before_governed_eval(
            out,
            ticker="SPY",
            architecture=arch,
            ml_horizon_suffix="5c",
            scheduler_cache_key=f"k_{arch}",
            feature_cache_key=fk,
            data_fp=data_fp,
            training_code_fingerprint=code_fp,
            evaluation={"eval_accuracy": 0.4, "n_rows": 100},
            trained_at="2026-05-22T12:00:00Z",
        )

    from arch_competition.lineage import validate_parallel_cascade_manifest_lineage

    lineage = validate_parallel_cascade_manifest_lineage(
        par,
        cas,
        ticker="SPY",
        expected_ml_horizon_suffix="5c",
    )
    assert lineage["ml_horizon_suffix"] == "5c"
    assert load_run_manifest(par)["ml_horizon_suffix"] == "5c"
    assert load_run_manifest(cas)["ml_horizon_suffix"] == "5c"


def test_governed_lineage_fails_without_sync(tmp_path: Path):
    par = tmp_path / "parallel" / "SPY"
    cas = tmp_path / "cascade" / "SPY"
    par.mkdir(parents=True)
    cas.mkdir(parents=True)
    data_fp = _data_fp()
    fk = compute_feature_cache_key("SPY", data_fp, "c", target_column=outcome_column("1c"))
    body = {
        **training_canonical_lineage_header(),
        "schema_version": "2",
        "ticker": "SPY",
        "scheduler_cache_key": "k",
        "feature_cache_key": fk,
        "training_code_fingerprint": "c",
        "data_fingerprint": data_fp,
        "ml_horizon_suffix": "1c",
    }
    save_run_manifest(par, {**body, "architecture": "parallel"})
    save_run_manifest(cas, {**body, "architecture": "cascade"})

    from arch_competition.lineage import EvaluationLineageError, validate_parallel_cascade_manifest_lineage

    with pytest.raises(EvaluationLineageError, match="expected '5c'"):
        validate_parallel_cascade_manifest_lineage(
            par,
            cas,
            ticker="SPY",
            expected_ml_horizon_suffix="5c",
        )
