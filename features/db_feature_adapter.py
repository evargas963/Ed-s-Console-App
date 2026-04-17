"""
Map a DB snapshot row (SnapshotRow-shaped or sqlite Row dict) to MVP canonical features.

Expected keys match `db.SnapshotRow` / `snapshots_1m_normalized` column names for MVP fields.
Uses the same strict coercion as the live adapter (`features.mvp_source_coercion`).
"""

from __future__ import annotations

from typing import Any

from features.canonical_contract import get_mvp_feature_names
from features.mvp_source_coercion import (
    read_optional_float,
    read_optional_vwap_side,
    read_optional_zone,
)


def build_db_mvp_feature_row(snapshot_row: dict[str, Any]) -> dict[str, Any]:
    """
    Build canonical MVP feature dict from a normalized snapshot / DB row dict.

    Raises:
        MvpFeatureSourceError: present-but-invalid column values.
    """
    out = {
        "price.spot": read_optional_float(snapshot_row, "spot", "price.spot"),
        "price.spread_pts": read_optional_float(snapshot_row, "spread", "price.spread_pts"),
        "structure.zone": read_optional_zone(snapshot_row, "zone", "structure.zone"),
        "structure.nearest_above_dist": read_optional_float(
            snapshot_row, "nearest_above_dist", "structure.nearest_above_dist"
        ),
        "structure.nearest_below_dist": read_optional_float(
            snapshot_row, "nearest_below_dist", "structure.nearest_below_dist"
        ),
        "structure.net_gamma": read_optional_float(snapshot_row, "net_gamma", "structure.net_gamma"),
        "anchor.vwap_side": read_optional_vwap_side(snapshot_row, "vwap_side", "anchor.vwap_side"),
        "anchor.vwap_dist_pts": read_optional_float(
            snapshot_row, "vwap_dist_pts", "anchor.vwap_dist_pts"
        ),
        "liquidity.absorption_score": read_optional_float(
            snapshot_row, "absorption_score", "liquidity.absorption_score"
        ),
        "liquidity.continuation_score": read_optional_float(
            snapshot_row, "continuation_score", "liquidity.continuation_score"
        ),
    }
    order = get_mvp_feature_names()
    return {k: out[k] for k in order}
