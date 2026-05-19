"""
LSTM sequence encoding contract (1m MVP, downstream enforcement).

Sequence bars are encoded with `lstm_data.encode_snapshot_5m` / `encode_snapshot_1m`, which expect
legacy DB-shaped column names. **MVP columns** (spot, zone, VWAP, distances, net_gamma, liquidity)
must come **only** from validated canonical feature rows — never directly from raw L1, SignalInput,
or unvalidated legacy snapshot fields for those keys.

Non-MVP columns in `FEATURES_5M` / `FEATURES_1M` (walls, cross-asset, VIX, candle_body_pts, …)
remain sourced from the DB row until a future contract expansion; MVP slots are overwritten from
canonical after stripping legacy MVP keys from the row copy.

Contract (inference):
- **Envelope:** same InferenceSnapshotV1 rules as fusion (`validate_inference_snapshot_for_fusion_stack`)
  when a live snapshot is supplied.
- **Timeframe:** `canonical_timeframe` must be `1m` (`CANONICAL_FEATURE_TIMEFRAME`).
- **Version:** `feature_contract_version` must match `CANONICAL_FEATURE_CONTRACT_VERSION`.
- **Sequence length:** `STREAM_5M_LOOKBACK` consecutive 1m bars for structure stream;
  `STREAM_1M_LOOKBACK` for micro stream (see `lstm_data`).
- **Feature ordering:** unchanged from training — `lstm_data.FEATURES_5M` / `FEATURES_1M` column order
  inside `encode_snapshot_*` (stable; do not reorder without retrain).
- **Missing canonical values:** `None` in a canonical row is allowed (contract validation); encoders
  treat missing numerics as 0.0 via `_safe_float`.
- **Fail closed:** invalid envelope, invalid canonical row, insufficient history, or MVP source
  ambiguity → `LstmSequenceInputError`.

Transformer encoder window (same canonical MVP rules as the LSTM **5m structure stream**):
- **Envelope (when live):** `snapshot_type`, `feature_contract_version == "v1_1m_mvp"`,
  `canonical_timeframe == "1m"` via `validate_inference_snapshot_for_fusion_stack`.
- **Sequence:** `seq_len` consecutive 1m DB snapshots (model checkpoint `seq_len`, default 20);
  each bar merged the same way as LSTM `window` — MVP from `build_db_mvp_feature_row` except the
  last bar, which uses `inference_snapshot_v1["features"]` when provided.
- **Encoding:** `lstm_data.encode_snapshot_5m(merged_row, ref_spot)` per bar; feature order is
  `lstm_data.FEATURES_5M` (stable; do not reorder without retrain).
- **Missing canonical values:** as LSTM — `None` allowed where contract permits; encoders use
  `_safe_float` / defaults.
- **Fail closed:** same validation as above → `TransformerSequenceInputError` (wraps merge
  failures from the shared merge path).
"""

from __future__ import annotations

from typing import Any, Mapping

from features.canonical_contract import validate_feature_contract_row
from features.mvp_source_coercion import MvpFeatureSourceError
from features.fusion_model_input import FusionModelInputError, validate_inference_snapshot_for_fusion_stack
from features.xgb_model_input import CANONICAL_TO_XGB_TABULAR, MVP_LEGACY_KEYS

# Re-export for callers documenting sequence length (single source in lstm_data).
from lstm_data import (  # noqa: F401
    FEATURES_1M,
    FEATURES_5M,
    STREAM_1M_LOOKBACK,
    STREAM_5M_LOOKBACK,
    VWAP_SIDE_MAP,
    ZONE_MAP,
    encode_snapshot_1m,
    encode_snapshot_5m,
)

# Encoded sentinel when canonical zone is missing (distinct from pin_neutral=2).
ZONE_MISSING_ENCODED = -1.0
# Encoded sentinel when canonical vwap_side is missing (distinct from above=1, below=-1).
VWAP_SIDE_UNKNOWN_ENCODED = 2.0

# Canonical MVP numerics mirrored in LSTM feature lists → missingness mask channel (1=present).
_CANONICAL_NUMERIC_MASK_ORDER: tuple[str, ...] = (
    "structure.net_gamma",
    "anchor.vwap_dist_pts",
)


class LstmSequenceInputError(ValueError):
    """LSTM sequence preparation failed: invalid canonical data, contract, or history."""


class TransformerSequenceInputError(LstmSequenceInputError):
    """Transformer encoder-window preparation failed (canonical MVP / contract / history)."""


def _canonical_missing_masks(canonical_features: dict[str, Any]) -> list[float]:
    return [1.0 if canonical_features.get(k) is not None else 0.0 for k in _CANONICAL_NUMERIC_MASK_ORDER]


def _patch_lstm_categoricals(
    features: list[float],
    feature_names: list[str],
    canonical_features: dict[str, Any],
) -> None:
    if "zone" in feature_names:
        zi = feature_names.index("zone")
        z = canonical_features.get("structure.zone")
        if z is None:
            features[zi] = ZONE_MISSING_ENCODED
        else:
            features[zi] = float(ZONE_MAP.get(str(z).lower(), 2))
    if "vwap_side" in feature_names:
        vi = feature_names.index("vwap_side")
        vs = canonical_features.get("anchor.vwap_side")
        if vs is None:
            features[vi] = VWAP_SIDE_UNKNOWN_ENCODED
        else:
            features[vi] = float(VWAP_SIDE_MAP.get(str(vs).lower(), VWAP_SIDE_UNKNOWN_ENCODED))


def encode_lstm_structure_bar_with_masks(
    merged_row: Mapping[str, Any],
    canonical_features: dict[str, Any],
    ref_spot: float,
) -> dict[str, Any]:
    """
    Structure-stream encode with canonical missingness masks and categorical sentinels.

    Missing canonical numerics are accompanied by mask=0 (value may be 0.0 from encoder).
    """
    base = list(encode_snapshot_5m(dict(merged_row), ref_spot))
    _patch_lstm_categoricals(base, FEATURES_5M, canonical_features)
    masks = _canonical_missing_masks(canonical_features)
    return {"features": base + masks, "canonical_missing_masks": masks}


def encode_lstm_micro_bar_with_masks(
    merged_row: Mapping[str, Any],
    canonical_features: dict[str, Any],
    ref_spot: float,
) -> dict[str, Any]:
    """Micro-stream encode with the same missingness / sentinel contract as structure."""
    base = list(encode_snapshot_1m(dict(merged_row), ref_spot))
    _patch_lstm_categoricals(base, FEATURES_1M, canonical_features)
    masks = _canonical_missing_masks(canonical_features)
    return {"features": base + masks, "canonical_missing_masks": masks}


def merge_db_row_with_canonical_mvp(
    db_row: Mapping[str, Any],
    canonical_features: dict[str, Any],
) -> dict[str, Any]:
    """
    Strip MVP keys from a copy of `db_row`, then set MVP columns strictly from `canonical_features`
    (canonical_name -> value).
    """
    out = {k: v for k, v in dict(db_row).items() if k not in MVP_LEGACY_KEYS}
    for canon, leg in CANONICAL_TO_XGB_TABULAR.items():
        out[leg] = canonical_features.get(canon)
    return out


def _ts_close(a: Any, b: Any, *, eps: float = 1e-3) -> bool:
    """
    True when both UTC timestamps are within ``eps`` seconds (default **1e-3**, ~1 ms).

    Used by ``build_lstm_merged_windows`` to align ``day_snaps`` rows with the live
    window's last bar. Callers must pass comparable ``ts_utc`` values (same epoch
    units); the epsilon tolerates float serialization jitter only, not missing bars.
    """
    try:
        if a is None or b is None:
            return False
        return abs(float(a) - float(b)) < eps
    except (TypeError, ValueError):
        return False


def build_lstm_merged_windows(
    window: list[Mapping[str, Any]],
    day_snaps: list[Mapping[str, Any]],
    *,
    inference_snapshot_v1: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    """
    Build merged snapshot dicts for LSTM encode + confluence. Per bar, MVP comes from
    `build_db_mvp_feature_row` except the **last bar of `window`**, which uses
    `inference_snapshot_v1["features"]` when provided (live current bar).

    Day-bar alignment: when ``inference_snapshot_v1`` is set, rows in ``day_snaps`` whose
    ``ts_utc`` is within **1 ms** of the window's last bar (see ``_ts_close``, default
    ``eps=1e-3``) also receive live canonical features.

    Raises:
        LstmSequenceInputError: invalid canonical rows or adapter failure.
    """
    from features.db_feature_adapter import build_db_mvp_feature_row

    if inference_snapshot_v1 is not None:
        try:
            validate_inference_snapshot_for_fusion_stack(inference_snapshot_v1)
        except FusionModelInputError as e:
            raise LstmSequenceInputError(str(e)) from e

    last_ts = window[-1].get("ts_utc") if window else None

    merged_window: list[dict] = []
    for i, s in enumerate(window):
        d = dict(s)
        try:
            cf = build_db_mvp_feature_row(d)
        except MvpFeatureSourceError as e:
            raise LstmSequenceInputError(str(e)) from e
        if inference_snapshot_v1 is not None and i == len(window) - 1:
            cf = inference_snapshot_v1["features"]
        ok, errs = validate_feature_contract_row(cf)
        if not ok:
            raise LstmSequenceInputError(f"invalid canonical feature row: {errs}")
        merged = merge_db_row_with_canonical_mvp(d, cf)
        merged_window.append(merged)

    merged_days: list[dict] = []
    for sn in day_snaps:
        d = dict(sn)
        try:
            cf = build_db_mvp_feature_row(d)
        except MvpFeatureSourceError as e:
            raise LstmSequenceInputError(str(e)) from e
        if inference_snapshot_v1 is not None and last_ts is not None and _ts_close(
            sn.get("ts_utc"), last_ts
        ):
            cf = inference_snapshot_v1["features"]
        ok, errs = validate_feature_contract_row(cf)
        if not ok:
            raise LstmSequenceInputError(f"invalid canonical feature row: {errs}")
        merged = merge_db_row_with_canonical_mvp(d, cf)
        merged_days.append(merged)

    return merged_window, merged_days


def build_transformer_merged_window(
    window: list[Mapping[str, Any]],
    *,
    inference_snapshot_v1: dict | None = None,
) -> list[dict]:
    """
    Build merged DB-shaped rows for `encode_snapshot_5m` (Transformer sequence).

    Uses the same per-bar MVP merge as `build_lstm_merged_windows` for the structure stream.
    `day_snaps` is set to `list(window)` so live-bar override by `ts_utc` matches the last bar
    of the encoder window only.

    Raises:
        TransformerSequenceInputError: invalid envelope, invalid canonical row, or adapter error.
    """
    try:
        merged_window, _ = build_lstm_merged_windows(
            window, list(window), inference_snapshot_v1=inference_snapshot_v1
        )
    except LstmSequenceInputError as e:
        raise TransformerSequenceInputError(str(e)) from e
    return merged_window
