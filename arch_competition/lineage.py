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
        t_a = str(a.get("ticker") or "").strip()
        t_b = str(b.get("ticker") or "").strip()
        if not t_a or not t_b:
            return False
        return (
            a.get("min_ts_utc") == b.get("min_ts_utc")
            and a.get("max_ts_utc") == b.get("max_ts_utc")
            and a.get("row_count") == b.get("row_count")
            and a.get("table") == b.get("table")
            and a.get("timeframe") == b.get("timeframe")
            and t_a.upper() == t_b.upper()
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
    if not ticker or not str(ticker).strip():
        raise EvaluationLineageError("ticker argument required (non-empty)")

    mp = load_run_manifest(parallel_dir)
    mc = load_run_manifest(cascade_dir)
    if not mp:
        raise EvaluationLineageError(f"parallel manifest missing under {parallel_dir}")
    if not mc:
        raise EvaluationLineageError(f"cascade manifest missing under {cascade_dir}")

    mp_ticker = mp.get("ticker")
    mc_ticker = mc.get("ticker")
    if mp_ticker is None or not str(mp_ticker).strip():
        raise EvaluationLineageError("parallel manifest missing ticker")
    if mc_ticker is None or not str(mc_ticker).strip():
        raise EvaluationLineageError("cascade manifest missing ticker")
    tku = str(ticker).strip().upper()
    if str(mp_ticker).strip().upper() != tku or str(mc_ticker).strip().upper() != tku:
        raise EvaluationLineageError("manifest ticker does not match evaluation ticker")

    fcp = mp.get("feature_cache_key")
    fcc = mc.get("feature_cache_key")
    if fcp is None or not str(fcp).strip():
        raise EvaluationLineageError("parallel manifest missing feature_cache_key")
    if fcc is None or not str(fcc).strip():
        raise EvaluationLineageError("cascade manifest missing feature_cache_key")
    if fcp != fcc:
        raise EvaluationLineageError(
            f"feature_cache_key mismatch: parallel={fcp!r} cascade={fcc!r}"
        )

    dfp = mp.get("data_fingerprint")
    dfc = mc.get("data_fingerprint")
    if not _normalize_fp(dfp, dfc):
        raise EvaluationLineageError(
            f"data_fingerprint mismatch between parallel and cascade manifests: {dfp!r} vs {dfc!r}"
        )

    hz_p_raw = mp.get("ml_horizon_suffix")
    hz_c_raw = mc.get("ml_horizon_suffix")
    if hz_p_raw is None or not str(hz_p_raw).strip():
        raise EvaluationLineageError("parallel manifest missing ml_horizon_suffix")
    if hz_c_raw is None or not str(hz_c_raw).strip():
        raise EvaluationLineageError("cascade manifest missing ml_horizon_suffix")
    hz_p = str(hz_p_raw).strip().lower()
    hz_c = str(hz_c_raw).strip().lower()
    if hz_p != hz_c:
        raise EvaluationLineageError(f"ml_horizon_suffix mismatch: {hz_p!r} vs {hz_c!r}")

    if expected_ml_horizon_suffix is not None:
        if not str(expected_ml_horizon_suffix).strip():
            raise EvaluationLineageError(
                "expected_ml_horizon_suffix must be omitted or non-empty; empty string is not allowed"
            )
        ex = str(expected_ml_horizon_suffix).strip().lower()
        if hz_p != ex:
            raise EvaluationLineageError(f"manifest horizon {hz_p!r} != expected {ex!r}")

    tfp = mp.get("training_code_fingerprint")
    tfc = mc.get("training_code_fingerprint")
    if tfp is None or not str(tfp).strip():
        raise EvaluationLineageError("parallel manifest missing training_code_fingerprint")
    if tfc is None or not str(tfc).strip():
        raise EvaluationLineageError("cascade manifest missing training_code_fingerprint")
    if tfp != tfc:
        raise EvaluationLineageError("training_code_fingerprint mismatch between parallel and cascade manifests")

    sv_p = mp.get("schema_version")
    sv_c = mc.get("schema_version")
    if sv_p is None or not str(sv_p).strip():
        raise EvaluationLineageError("parallel manifest missing schema_version")
    if sv_c is None or not str(sv_c).strip():
        raise EvaluationLineageError("cascade manifest missing schema_version")

    return {
        "feature_cache_key": fcp,
        "data_fingerprint": dfp,
        "ml_horizon_suffix": hz_p,
        "training_code_fingerprint": tfp,
        "canonical_feature_contract_version": CANONICAL_FEATURE_CONTRACT_VERSION,
        "canonical_timeframe": CANONICAL_FEATURE_TIMEFRAME,
        "parallel_schema_version": sv_p,
        "cascade_schema_version": sv_c,
    }
