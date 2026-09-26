"""Evaluation runner + promotion engine (offline; no production default change)."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest



def _dfp():
    return {
        "min_ts_utc": "2020-01-01",
        "max_ts_utc": "2020-06-01",
        "row_count": 1000,
        "table": "snap",
        "timeframe": "1m",
        "ticker": "SPY",
    }


def _base_lineage():
    return {
        "feature_cache_key": "shared_cache_key",
        "data_fingerprint": _dfp(),
        "ml_horizon_suffix": "1c",
        "training_code_fingerprint": "train-fp-test",
        "canonical_feature_contract_version": "v-test",
        "canonical_timeframe": "1m",
    }


def _metrics(
    name: str,
    *,
    n: int,
    ll: float | None,
    bal: float,
    brier: float | None,
    stab: float | None,
    mid_bucket_bal: float = 0.5,
    calibration_ece: float | None = 0.08,
):
    return {
        "architecture": name,
        "n_rows_scored": n,
        "accuracy": 0.5,
        "balanced_accuracy": bal,
        "log_loss": ll,
        "brier_score": brier,
        "stability_log_loss_std_halves": stab,
        "calibration_ece": calibration_ece,
        "calibration_mce": 0.05,
        "brier_decomposition": {"brier_score": brier},
        "regime_slices": {
            "low": {"n": 0, "balanced_accuracy": None, "skipped_low_support": True},
            "mid": {
                "n": 50,
                "balanced_accuracy": mid_bucket_bal,
                "skipped_low_support": False,
            },
            "high": {"n": 0, "balanced_accuracy": None, "skipped_low_support": True},
        },
        "confidence_reliability": {},
        "realized_contract_metrics": {},
    }


def _empirical_shell():
    return {
        "calibration_summary": {"schema_version": "1", "by_architecture": {}},
        "confidence_reliability_summary": {
            "schema_version": "1",
            "by_architecture": {
                "parallel": {"confidence_hit_correlation": 0.1},
                "cascade": {"confidence_hit_correlation": 0.1},
            },
        },
        "rolling_stability_summary": {
            "schema_version": "1",
            "by_architecture": {
                "parallel": {"calibration_degradation_flag": False},
                "cascade": {"calibration_degradation_flag": False},
            },
        },
        "empirical_validation": {"schema_version": "1"},
    }


def _manifest(mp, mc, lineage=None):
    lg = lineage or _base_lineage()
    return {
        "schema_version": "1",
        "ticker": "SPY",
        "ml_horizon_slug": "1c",
        "lineage": lg,
        "metrics": {"parallel": mp, "cascade": mc},
        **_empirical_shell(),
    }
























def _promotable_manifest():
    return _manifest(
        _metrics("parallel", n=100, ll=0.8, bal=0.5, brier=0.2, stab=0.01),
        _metrics("cascade", n=100, ll=0.7, bal=0.55, brier=0.21, stab=0.02),
    )










def _write_lineage_manifest_pair(
    tmp_path: Path,
    *,
    parallel: dict | None = None,
    cascade: dict | None = None,
) -> tuple[Path, Path]:
    fp = _dfp()
    common = {
        "schema_version": "2",
        "ticker": "SPY",
        "ml_horizon_suffix": "1c",
        "data_fingerprint": fp,
        "training_code_fingerprint": "trainfp",
        "feature_cache_key": "shared",
    }
    pdir = tmp_path / "p"
    cdir = tmp_path / "c"
    pdir.mkdir()
    cdir.mkdir()
    p_body = {**common, **(parallel or {})}
    c_body = {**common, **(cascade or {})}
    (pdir / "scheduler_run_manifest.json").write_text(json.dumps(p_body), encoding="utf-8")
    (cdir / "scheduler_run_manifest.json").write_text(json.dumps(c_body), encoding="utf-8")
    return pdir, cdir




















def test_row_count_mismatch_aligns_to_common_rows_not_fails():
    """Aligned-row-set design (AGENTS world-class gate) replaced the old fail-on-raw-
    count-mismatch: arches scoring different raw row sets are intersected on ts_utc and
    raw counts recorded, not rejected. Stale fail-expectation removed."""
    from arch_competition.eval_runner import _align_eval_detail_pair

    def _det(ts_list):
        return {
            "rows_used": [{"ts_utc": float(t)} for t in ts_list],
            "prob_rows": [[0.5, 0.3, 0.2] for _ in ts_list],
            "y_true": [0 for _ in ts_list],
        }

    pdet = _det([1, 2, 3, 4, 5])  # parallel scored 5 rows
    cdet = _det([2, 3, 4])        # cascade scored 3 (subset, e.g. LSTM/TR skipped 1 & 5)
    pd2, cd2, n_common, pn_raw, cn_raw = _align_eval_detail_pair(pdet, cdet)
    assert pn_raw == 5 and cn_raw == 3          # raw counts preserved for the manifest
    assert n_common == 3                         # intersected, not rejected
    assert [r["ts_utc"] for r in pd2["rows_used"]] == [2.0, 3.0, 4.0]
    assert len(pd2["prob_rows"]) == len(cd2["prob_rows"]) == 3
































def test_arch_competition_modules_do_not_call_run_unified_stack_ml_once():
    root = Path(__file__).resolve().parents[1] / "arch_competition"
    for name in ("eval_runner.py", "promotion_engine.py", "__init__.py", "lineage.py", "metrics.py", "exceptions.py"):
        src = (root / name).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "run_unified_stack_ml_once":
                    pytest.fail(f"{name} must not call run_unified_stack_ml_once")
                if isinstance(node.func, ast.Attribute) and node.func.attr == "run_unified_stack_ml_once":
                    pytest.fail(f"{name} must not call run_unified_stack_ml_once")




