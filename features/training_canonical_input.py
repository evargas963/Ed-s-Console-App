"""
Canonical training-input boundary: DB rows → MVP contract → merged legacy-shaped rows for encoders.

Single approved path for training-time MVP alignment with inference (see features.db_feature_adapter,
features.lstm_sequence_input.merge_db_row_with_canonical_mvp).

Does not widen the MVP feature set. Does not change live inference defaults.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from features.canonical_contract import (
    CANONICAL_FEATURE_CONTRACT_VERSION,
    CANONICAL_FEATURE_TIMEFRAME,
    validate_feature_contract_row,
)
from features.db_feature_adapter import build_db_mvp_feature_row
from features.lstm_sequence_input import merge_db_row_with_canonical_mvp
from features.mvp_source_coercion import MvpFeatureSourceError


class TrainingCanonicalInputError(ValueError):
    """Training row cannot be mapped to canonical MVP or failed strict validation."""


def training_canonical_lineage_header() -> dict[str, str]:
    """Metadata for manifests, cache identity, and scheduler lineage."""
    return {
        "canonical_feature_contract_version": CANONICAL_FEATURE_CONTRACT_VERSION,
        "canonical_timeframe": CANONICAL_FEATURE_TIMEFRAME,
    }


def assert_training_lineage_matches_canonical(lineage: dict[str, Any] | None) -> None:
    """Fail-closed: persisted lineage must match current canonical contract."""
    if not lineage:
        raise TrainingCanonicalInputError("missing lineage for canonical contract check")
    if lineage.get("canonical_feature_contract_version") != CANONICAL_FEATURE_CONTRACT_VERSION:
        raise TrainingCanonicalInputError(
            f"canonical_feature_contract_version mismatch: expected {CANONICAL_FEATURE_CONTRACT_VERSION!r}, "
            f"got {lineage.get('canonical_feature_contract_version')!r}"
        )
    if lineage.get("canonical_timeframe") not in (None, CANONICAL_FEATURE_TIMEFRAME):
        if lineage.get("canonical_timeframe") != CANONICAL_FEATURE_TIMEFRAME:
            raise TrainingCanonicalInputError(
                f"canonical_timeframe mismatch: expected {CANONICAL_FEATURE_TIMEFRAME!r}, "
                f"got {lineage.get('canonical_timeframe')!r}"
            )


def training_snapshot_for_sequence_encode(snapshot_row: dict[str, Any]) -> dict[str, Any]:
    """
    DB snapshot → canonical MVP → merge back to legacy column names for lstm_data.encode_snapshot_*.

    Sequence encoders read legacy keys (zone, vwap_side, …); MVP slots are sourced only from
    build_db_mvp_feature_row (same boundary as inference).
    """
    try:
        canon = build_db_mvp_feature_row(snapshot_row)
    except MvpFeatureSourceError as e:
        raise TrainingCanonicalInputError(f"MVP coercion failed before sequence encode: {e}") from e
    ok, errs = validate_feature_contract_row(canon)
    if not ok:
        raise TrainingCanonicalInputError(f"invalid canonical MVP row: {errs}")
    return merge_db_row_with_canonical_mvp(snapshot_row, canon)


def _row_dict_from_df(df: pd.DataFrame, idx: int) -> dict[str, Any]:
    """Convert DataFrame row to dict, mapping pandas NaN -> Python None.

    SQLite stores numeric NULL as actual NULL; pandas read_sql converts NULL
    in numeric columns to float NaN (numpy/pandas convention). The MVP
    coercion contract in features.mvp_source_coercion.read_optional_float
    distinguishes:
      * missing data (None) -> canonical None (OK, downstream handles)
      * non-finite numeric (NaN/Inf) -> MvpFeatureSourceError (broken
        upstream compute)

    Without this conversion, every snapshot row with a NULL numeric column
    fails the non-finite check at row 0. Incident 2026-05-25: the scheduler
    run failed 17 of 41 selected tickers (SPY, QQQ, IWM, AAPL, NVDA, META,
    MSFT, AMZN, GOOG, GOOGL, AVGO, MRVL, PLTR, SMCI, TSL, TSLA, PCG) with
    "row 0: MVP coercion failed: liquidity.absorption_score: non-finite
    value nan" because 33% of SPY snapshots have NULL absorption_score
    (and similar NULL distributions on other tickers / columns). Additional
    11 tickers blocked across various row positions on structure.nearest_*
    / anchor.vwap_dist_pts NaN -- same root cause.

    NaN coming from a DataFrame at this boundary is always pandas-loaded
    NULL: SQLite Python bindings cannot store NaN distinctly from NULL on
    a numeric column. Converting NaN -> None here restores the source
    semantics without weakening the contract for live inference (which
    receives dicts directly from runtime compute, not via DataFrame, so
    actual upstream NaN still raises as designed).
    """
    raw = df.iloc[idx].to_dict()
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if isinstance(v, float) and math.isnan(v):
            out[k] = None
        else:
            out[k] = v
    return out


def validate_tabular_training_dataframe_canonical(
    df: pd.DataFrame,
    *,
    max_rows: int = 500,
) -> None:
    """
    Sample rows from a tabular training frame and ensure each maps to a valid canonical MVP row.

    Raises TrainingCanonicalInputError on first failure (fail-closed).
    """
    n = len(df)
    if n == 0:
        return
    if n <= max_rows:
        indices = list(range(n))
    else:
        step = max(1, n // max_rows)
        indices = list(range(0, n, step))[:max_rows]
        if (n - 1) not in indices:
            indices.append(n - 1)
    for i in indices:
        row = _row_dict_from_df(df, i)
        try:
            canon = build_db_mvp_feature_row(row)
        except MvpFeatureSourceError as e:
            raise TrainingCanonicalInputError(f"row {i}: MVP coercion failed: {e}") from e
        ok, errs = validate_feature_contract_row(canon)
        if not ok:
            raise TrainingCanonicalInputError(f"row {i}: canonical validation failed: {errs}")


def assert_shared_feature_cache_keys_equal(a: str, b: str) -> None:
    """Fail-closed: parallel and cascade training must use the same shared feature cache key."""
    if a != b:
        raise TrainingCanonicalInputError(
            f"shared feature_cache_key mismatch: a={a[:16]}… b={b[:16]}…"
        )


# Back-compat name (same semantics: compare two `compute_feature_cache_key` outputs).
assert_parallel_cascade_feature_cache_key_match = assert_shared_feature_cache_keys_equal
