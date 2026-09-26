"""
Pinned LSTM/Transformer encoder schema v2 (pre–Stage-2-tabular, mask-channel layout).

Used only by offline ablation bundle inference — never by live production loaders.
Recovered from lstm_data.py @ f0496f2 (encoder_width_5m_pre_mask=31 on pool bundles).
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

import numpy as np

ENCODER_SCHEMA_VERSION_V2 = 2

FEATURES_5M_V2: tuple[str, ...] = (
    "spot",
    "candle_body_pts",
    "candle_range_pts",
    "vwap_dist_pts",
    "dist_call_gamma_wall",
    "dist_put_gamma_wall",
    "dist_gamma_inflection",
    "dist_delta_inflection",
    "dist_call_oi_wall",
    "dist_put_oi_wall",
    "net_gamma",
    "net_delta",
    "charm_net",
    "spy_chg_pct",
    "qqq_chg_pct",
    "iwm_chg_pct",
    "spy_weighted_push",
    "qqq_weighted_push",
    "iwm_weighted_push",
    "vix_level",
    "iv_level",
    "zone",
    "vwap_side",
)

FEATURES_1M_V2: tuple[str, ...] = (
    "spot",
    "candle_body_pts",
    "candle_range_pts",
    "vwap_dist_pts",
    "net_gamma",
    "net_delta",
    "spy_chg_pct",
    "qqq_chg_pct",
    "vix_level",
    "iv_level",
    "zone",
    "vwap_side",
)

NULLABLE_NUMERIC_COLS_5M_V2 = frozenset(
    {
        "spy_chg_pct",
        "qqq_chg_pct",
        "iwm_chg_pct",
        "spy_weighted_push",
        "qqq_weighted_push",
        "iwm_weighted_push",
        "vix_level",
        "iv_level",
    }
)
NULLABLE_NUMERIC_COLS_1M_V2 = frozenset(
    {"spy_chg_pct", "qqq_chg_pct", "vix_level", "iv_level"}
)
LOG_TRANSFORM_COLS_V2 = frozenset({"net_gamma", "net_delta", "charm_net"})
CATEGORICAL_COLS_V2 = frozenset({"zone", "vwap_side"})

ZONE_MAP_V2 = {
    "pin_bull": 0,
    "pin_bear": 1,
    "pin_neutral": 2,
    "pin_chaos": 3,
    "breakout": 4,
    "breakdown": 5,
}
VWAP_SIDE_MAP_V2 = {"above": 1.0, "below": -1.0}
ZONE_MISSING_ENCODED_V2 = -1.0
VWAP_SIDE_UNKNOWN_ENCODED_V2 = 2.0


def _build_encoded_feature_names_v2(
    base: tuple[str, ...], nullable: frozenset[str]
) -> tuple[str, ...]:
    names: list[str] = []
    for col in base:
        names.append(col)
        if col in nullable:
            names.append(f"{col}__present")
    return tuple(names)


ENCODED_FEATURES_5M_V2 = _build_encoded_feature_names_v2(
    FEATURES_5M_V2, NULLABLE_NUMERIC_COLS_5M_V2
)
ENCODED_FEATURES_1M_V2 = _build_encoded_feature_names_v2(
    FEATURES_1M_V2, NULLABLE_NUMERIC_COLS_1M_V2
)

assert len(ENCODED_FEATURES_5M_V2) == 31
assert len(ENCODED_FEATURES_1M_V2) == 16


def v2_encoder_lineage_valid(checkpoint: Mapping[str, Any]) -> tuple[bool, str]:
    enc_ver = int(checkpoint.get("encoder_schema_version") or 0)
    if enc_ver != ENCODER_SCHEMA_VERSION_V2:
        return False, f"encoder_schema_version={enc_ver}!=2"
    pre5 = checkpoint.get("encoder_width_5m_pre_mask")
    if pre5 is not None and int(pre5) != len(ENCODED_FEATURES_5M_V2):
        return False, f"encoder_width_5m_pre_mask={pre5}!={len(ENCODED_FEATURES_5M_V2)}"
    mask5 = checkpoint.get("mask_5m") or checkpoint.get("feature_mask")
    if not isinstance(mask5, list) or len(mask5) != len(ENCODED_FEATURES_5M_V2):
        return False, "mask_5m/feature_mask length mismatch vs v2 encoded width"
    return True, ""


def resolve_encoder_lineage(
    checkpoint: Mapping[str, Any] | None,
    meta: Mapping[str, Any] | None,
) -> tuple[int, tuple[str, ...], tuple[str, ...], str | None]:
    """
    Return (schema_version, encoded_names_5m, encoded_names_1m, error).
    v3: names from checkpoint; v2: pinned registry.
    """
    from lstm_data import LSTM_ENCODER_SCHEMA_VERSION, encoded_width_5m, encoded_width_1m

    ck = checkpoint if isinstance(checkpoint, dict) else {}
    enc_ver = int(ck.get("encoder_schema_version") or (meta or {}).get("encoder_schema_version") or 0)
    if enc_ver >= LSTM_ENCODER_SCHEMA_VERSION:
        names5 = ck.get("encoder_feature_names_5m") or (meta or {}).get("encoder_feature_names_5m")
        names1 = ck.get("encoder_feature_names_1m") or (meta or {}).get("encoder_feature_names_1m")
        if not isinstance(names5, list) or not names5:
            return enc_ver, (), (), "encoder_feature_names_5m_missing"
        if not isinstance(names1, list) or not names1:
            return enc_ver, (), (), "encoder_feature_names_1m_missing"
        pre5 = ck.get("encoder_width_5m_pre_mask")
        if pre5 is not None and int(pre5) != encoded_width_5m():
            return enc_ver, (), (), f"encoder_width_5m_pre_mask={pre5}!={encoded_width_5m()}"
        pre1 = ck.get("encoder_width_1m_pre_mask")
        if pre1 is not None and int(pre1) != encoded_width_1m():
            return enc_ver, (), (), f"encoder_width_1m_pre_mask={pre1}!={encoded_width_1m()}"
        return enc_ver, tuple(str(x) for x in names5), tuple(str(x) for x in names1), None
    if enc_ver == ENCODER_SCHEMA_VERSION_V2:
        ok, reason = v2_encoder_lineage_valid(ck)
        if not ok:
            return enc_ver, (), (), reason
        return enc_ver, ENCODED_FEATURES_5M_V2, ENCODED_FEATURES_1M_V2, None
    return enc_ver, (), (), f"encoder_schema_version={enc_ver}_unsupported"


def _safe_float(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _raw_finite_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(f):
        return None
    return f


def _encode_zone_v2(snap: dict) -> float:
    zr = snap.get("zone")
    if zr is None:
        return ZONE_MISSING_ENCODED_V2
    return float(ZONE_MAP_V2.get(str(zr).lower(), 2))


def _encode_vwap_side_v2(snap: dict) -> float:
    vs = snap.get("vwap_side")
    if vs is None:
        return VWAP_SIDE_UNKNOWN_ENCODED_V2
    return float(VWAP_SIDE_MAP_V2.get(str(vs).lower(), VWAP_SIDE_UNKNOWN_ENCODED_V2))


def _encode_nullable_chg_or_push(raw: Any) -> tuple[float, float]:
    f = _raw_finite_float(raw)
    if f is None:
        return 0.0, 0.0
    return max(-5.0, min(5.0, f)), 1.0


def _encode_nullable_level(raw: Any) -> tuple[float, float]:
    f = _raw_finite_float(raw)
    if f is None:
        return 0.0, 0.0
    return f, 1.0


def _append_nullable_v2(features: list[float], snap: dict, col: str) -> None:
    if col.endswith("_chg_pct") or col.endswith("_push"):
        val, mask = _encode_nullable_chg_or_push(snap.get(col))
    else:
        val, mask = _encode_nullable_level(snap.get(col))
    features.extend([val, mask])


def _signed_log(v: float) -> float:
    if v == 0.0:
        return 0.0
    return float(np.sign(v) * np.log1p(abs(v)))


def encode_snapshot_5m_v2(snap: dict, ref_spot: float) -> list[float]:
    features: list[float] = []
    spot = _safe_float(snap.get("spot"))
    for col in FEATURES_5M_V2:
        if col in CATEGORICAL_COLS_V2:
            if col == "zone":
                features.append(_encode_zone_v2(snap))
            else:
                features.append(_encode_vwap_side_v2(snap))
        elif col == "spot":
            features.append((spot - ref_spot) / ref_spot if ref_spot > 0 else 0.0)
        elif col in ("candle_body_pts", "candle_range_pts", "vwap_dist_pts") or col.startswith(
            "dist_"
        ):
            val = _safe_float(snap.get(col))
            features.append(val / ref_spot if ref_spot > 0 else 0.0)
        elif col in LOG_TRANSFORM_COLS_V2:
            features.append(_signed_log(_safe_float(snap.get(col))))
        elif col in NULLABLE_NUMERIC_COLS_5M_V2:
            _append_nullable_v2(features, snap, col)
        else:
            features.append(_safe_float(snap.get(col)))
    return features


def encode_snapshot_1m_v2(snap: dict, ref_spot: float) -> list[float]:
    features: list[float] = []
    spot = _safe_float(snap.get("spot"))
    for col in FEATURES_1M_V2:
        if col in CATEGORICAL_COLS_V2:
            if col == "zone":
                features.append(_encode_zone_v2(snap))
            else:
                features.append(_encode_vwap_side_v2(snap))
        elif col == "spot":
            features.append((spot - ref_spot) / ref_spot if ref_spot > 0 else 0.0)
        elif col in ("candle_body_pts", "candle_range_pts", "vwap_dist_pts"):
            val = _safe_float(snap.get(col))
            features.append(val / ref_spot if ref_spot > 0 else 0.0)
        elif col in LOG_TRANSFORM_COLS_V2:
            features.append(_signed_log(_safe_float(snap.get(col))))
        elif col in NULLABLE_NUMERIC_COLS_1M_V2:
            _append_nullable_v2(features, snap, col)
        else:
            features.append(_safe_float(snap.get(col)))
    return features


def apply_checkpoint_variance_mask(vec: list[float], mask: list[bool] | None) -> list[float]:
    if not mask:
        return list(vec)
    m = [bool(x) for x in mask]
    if len(m) != len(vec):
        raise ValueError(f"mask length {len(m)} != vector length {len(vec)}")
    return [float(vec[i]) for i, keep in enumerate(m) if keep]
