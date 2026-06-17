"""
LSTM sequence encoding contract (1m MVP, downstream enforcement).

Sequence bars are encoded with `encode_lstm_structure_sequence_bar` /
`encode_lstm_micro_sequence_bar` (which call `lstm_data.encode_snapshot_*` internally), expecting
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
- **Feature ordering:** `lstm_data.ENCODED_FEATURES_5M` / `ENCODED_FEATURES_1M` (stable; do not reorder
  without retrain).
- **Missing canonical values:** nullable cross-asset / vol numerics emit value + ``__present`` mask
  channels (see ``lstm_data.NULLABLE_NUMERIC_COLS_*``); other columns use ``_safe_float`` only where
  0.0 is not a semantic signal.
- **Fail closed:** invalid envelope, invalid canonical row, insufficient history, or MVP source
  ambiguity → `LstmSequenceInputError`.

Transformer encoder window (same canonical MVP rules as the LSTM **5m structure stream**):
- **Envelope (when live):** `snapshot_type`, `feature_contract_version == "v1_1m_mvp"`,
  `canonical_timeframe == "1m"` via `validate_inference_snapshot_for_fusion_stack`.
- **Sequence:** `seq_len` consecutive 1m DB snapshots (model checkpoint `seq_len`, default 20);
  each bar merged the same way as LSTM `window` — MVP from `build_db_mvp_feature_row` except the
  last bar, which uses `inference_snapshot_v1["features"]` when provided.
- **Encoding:** `encode_lstm_structure_sequence_bar(merged_row, ref_spot)` per bar.
- **Missing canonical values:** as LSTM structure stream.
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
    ENCODED_FEATURES_1M,
    ENCODED_FEATURES_5M,
    FEATURES_1M,
    FEATURES_5M,
    LSTM_ENCODER_SCHEMA_VERSION,
    STREAM_1M_LOOKBACK,
    STREAM_5M_LOOKBACK,
    VWAP_SIDE_MAP,
    ZONE_MAP,
    encoded_width_5m,
    encoded_width_1m,
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
    zone_keys = ("zone", "cat_zone")
    vwap_keys = ("vwap_side", "cat_vwap_side")
    for zkey in zone_keys:
        if zkey in feature_names:
            zi = feature_names.index(zkey)
            z = canonical_features.get("structure.zone")
            if z is None:
                features[zi] = ZONE_MISSING_ENCODED
            else:
                features[zi] = float(ZONE_MAP.get(str(z).lower(), 2))
            break
    for vkey in vwap_keys:
        if vkey in feature_names:
            vi = feature_names.index(vkey)
            vs = canonical_features.get("anchor.vwap_side")
            if vs is None:
                features[vi] = VWAP_SIDE_UNKNOWN_ENCODED
            else:
                features[vi] = float(VWAP_SIDE_MAP.get(str(vs).lower(), VWAP_SIDE_UNKNOWN_ENCODED))
            break


def _canonical_features_for_merged_row(merged_row: Mapping[str, Any]) -> dict[str, Any]:
    from features.db_feature_adapter import build_db_mvp_feature_row

    try:
        cf = build_db_mvp_feature_row(dict(merged_row))
    except MvpFeatureSourceError as e:
        raise LstmSequenceInputError(str(e)) from e
    ok, errs = validate_feature_contract_row(cf)
    if not ok:
        raise LstmSequenceInputError(f"invalid canonical feature row: {errs}")
    return cf


def encode_lstm_structure_sequence_bar(
    merged_row: Mapping[str, Any],
    ref_spot: float,
    *,
    canonical_features: dict[str, Any] | None = None,
) -> list[float]:
    """
    Production structure-stream encoder (training + inference).

    Nullable cross-asset/vol numerics emit value + ``__present`` mask channels via
    ``encode_snapshot_5m``; categoricals use canonical sentinels.
    """
    cf = canonical_features if canonical_features is not None else _canonical_features_for_merged_row(
        merged_row
    )
    base = list(encode_snapshot_5m(dict(merged_row), ref_spot))
    _patch_lstm_categoricals(base, ENCODED_FEATURES_5M, cf)
    return base


def encode_lstm_micro_sequence_bar(
    merged_row: Mapping[str, Any],
    ref_spot: float,
    *,
    canonical_features: dict[str, Any] | None = None,
) -> list[float]:
    """Production micro-stream encoder (training + inference)."""
    cf = canonical_features if canonical_features is not None else _canonical_features_for_merged_row(
        merged_row
    )
    base = list(encode_snapshot_1m(dict(merged_row), ref_spot))
    _patch_lstm_categoricals(base, ENCODED_FEATURES_1M, cf)
    return base


def encode_lstm_structure_sequence_bar_for_checkpoint(
    merged_row: Mapping[str, Any],
    ref_spot: float,
    checkpoint: Mapping[str, Any],
    *,
    canonical_features: dict[str, Any] | None = None,
) -> list[float]:
    """Structure-stream encode using checkpoint schema (v2 legacy or current v3)."""
    from lstm_data import (
        LEGACY_ENCODER_SCHEMA_VERSION,
        LEGACY_V2_ENCODED_FEATURES_5M,
        checkpoint_encoder_schema_version,
        encode_snapshot_5m_for_checkpoint,
    )

    cf = canonical_features if canonical_features is not None else _canonical_features_for_merged_row(
        merged_row
    )
    base = list(encode_snapshot_5m_for_checkpoint(dict(merged_row), ref_spot, checkpoint))
    names = (
        LEGACY_V2_ENCODED_FEATURES_5M
        if checkpoint_encoder_schema_version(checkpoint) == LEGACY_ENCODER_SCHEMA_VERSION
        else ENCODED_FEATURES_5M
    )
    _patch_lstm_categoricals(base, names, cf)
    return base


def encode_lstm_micro_sequence_bar_for_checkpoint(
    merged_row: Mapping[str, Any],
    ref_spot: float,
    checkpoint: Mapping[str, Any],
    *,
    canonical_features: dict[str, Any] | None = None,
) -> list[float]:
    """Micro-stream encode using checkpoint schema (v2 legacy or current v3)."""
    from lstm_data import (
        LEGACY_ENCODER_SCHEMA_VERSION,
        LEGACY_V2_ENCODED_FEATURES_1M,
        checkpoint_encoder_schema_version,
        encode_snapshot_1m_for_checkpoint,
    )

    cf = canonical_features if canonical_features is not None else _canonical_features_for_merged_row(
        merged_row
    )
    base = list(encode_snapshot_1m_for_checkpoint(dict(merged_row), ref_spot, checkpoint))
    names = (
        LEGACY_V2_ENCODED_FEATURES_1M
        if checkpoint_encoder_schema_version(checkpoint) == LEGACY_ENCODER_SCHEMA_VERSION
        else ENCODED_FEATURES_1M
    )
    _patch_lstm_categoricals(base, names, cf)
    return base


def encode_lstm_structure_bar_with_masks(
    merged_row: Mapping[str, Any],
    canonical_features: dict[str, Any],
    ref_spot: float,
) -> dict[str, Any]:
    """Test/diagnostic wrapper around ``encode_lstm_structure_sequence_bar``."""
    return {
        "features": encode_lstm_structure_sequence_bar(
            merged_row, ref_spot, canonical_features=canonical_features
        ),
        "canonical_missing_masks": _canonical_missing_masks(canonical_features),
    }


def encode_lstm_micro_bar_with_masks(
    merged_row: Mapping[str, Any],
    canonical_features: dict[str, Any],
    ref_spot: float,
) -> dict[str, Any]:
    """Test/diagnostic wrapper around ``encode_lstm_micro_sequence_bar``."""
    return {
        "features": encode_lstm_micro_sequence_bar(
            merged_row, ref_spot, canonical_features=canonical_features
        ),
        "canonical_missing_masks": _canonical_missing_masks(canonical_features),
    }


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
