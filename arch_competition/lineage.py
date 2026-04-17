"""Validate shared artifact lineage between parallel and cascade candidate directories."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from training_cache import load_run_manifest

from arch_competition.exceptions import EvaluationLineageError
from features.canonical_contract import CANONICAL_FEATURE_CONTRACT_VERSION, CANONICAL_FEATURE_TIMEFRAME


def _normalize_fp(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return False
    if isinstance(a, dict) and isinstance(b, dict):
        return (
            a.get("min_ts_utc") == b.get("min_ts_utc")
            and a.get("max_ts_utc") == b.get("max_ts_utc")
            and a.get("row_count") == b.get("row_count")
            and a.get("table") == b.get("table")
            and a.get("timeframe") == b.get("timeframe")
            and a.get("ticker", "").upper() == b.get("ticker", "").upper()
        )
    return a == b


def validate_parallel_cascade_manifest_lineage(
    parallel_dir: Path,
    cascade_dir: Path,
    *,
    ticker: str,
    expected_ml_horizon_suffix: str | None = None,
) -> dict[str, Any]:
    """
    Require both scheduler_run_manifest.json files and matching shared-cache identity.

    Raises:
        EvaluationLineageError: missing manifest, mismatched keys, or data fingerprint drift.
    """
    mp = load_run_manifest(parallel_dir)
    mc = load_run_manifest(cascade_dir)
    if not mp:
        raise EvaluationLineageError(f"parallel manifest missing under {parallel_dir}")
    if not mc:
        raise EvaluationLineageError(f"cascade manifest missing under {cascade_dir}")

    if mp.get("ticker", "").upper() != ticker.upper() or mc.get("ticker", "").upper() != ticker.upper():
        raise EvaluationLineageError("manifest ticker does not match evaluation ticker")

    if mp.get("feature_cache_key") != mc.get("feature_cache_key"):
        raise EvaluationLineageError(
            f"feature_cache_key mismatch: parallel={mp.get('feature_cache_key')!r} "
            f"cascade={mc.get('feature_cache_key')!r}"
        )

    dfp = mp.get("data_fingerprint")
    dfc = mc.get("data_fingerprint")
    if not _normalize_fp(dfp, dfc):
        raise EvaluationLineageError(
            f"data_fingerprint mismatch between parallel and cascade manifests: {dfp!r} vs {dfc!r}"
        )

    hz_p = str(mp.get("ml_horizon_suffix") or "").strip().lower()
    hz_c = str(mc.get("ml_horizon_suffix") or "").strip().lower()
    if hz_p != hz_c:
        raise EvaluationLineageError(f"ml_horizon_suffix mismatch: {hz_p!r} vs {hz_c!r}")

    if expected_ml_horizon_suffix is not None:
        ex = expected_ml_horizon_suffix.strip().lower()
        if hz_p != ex:
            raise EvaluationLineageError(f"manifest horizon {hz_p!r} != expected {ex!r}")

    if mp.get("training_code_fingerprint") != mc.get("training_code_fingerprint"):
        raise EvaluationLineageError("training_code_fingerprint mismatch between parallel and cascade manifests")

    return {
        "feature_cache_key": mp.get("feature_cache_key"),
        "data_fingerprint": dfp,
        "ml_horizon_suffix": hz_p,
        "training_code_fingerprint": mp.get("training_code_fingerprint"),
        "canonical_feature_contract_version": CANONICAL_FEATURE_CONTRACT_VERSION,
        "canonical_timeframe": CANONICAL_FEATURE_TIMEFRAME,
        "parallel_schema_version": mp.get("schema_version"),
        "cascade_schema_version": mc.get("schema_version"),
    }
