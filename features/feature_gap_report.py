"""
Static comparison of MVP feature support on live vs DB paths (documentation / audits).
"""

from __future__ import annotations

from typing import Any


def compare_live_and_db_feature_support() -> dict[str, Any]:
    """
    Per MVP feature: whether live/DB support it and which source fields adapters use.

    Derived from adapter design — not runtime introspection.
    Categoricals: live and DB paths both use strict `read_optional_zone` / `read_optional_vwap_side`
    in `mvp_source_coercion` (strip + lowercase + vocabulary check).
    """
    return {
        "contract_version": "v1_1m_range_imbalance",
        "categorical_normalization": "strip + lowercase; must match ALLOWED_ZONE_VALUES / ALLOWED_VWAP_SIDE_VALUES",
        "features": [
            {
                "canonical_name": "price.spot",
                "live_supported": True,
                "db_supported": True,
                "chosen_live_source": "l1_payload['spot']",
                "chosen_db_source": "snapshot_row['spot']",
            },
            {
                "canonical_name": "price.spread_pts",
                "live_supported": True,
                "db_supported": True,
                "chosen_live_source": "l1_payload['spread']",
                "chosen_db_source": "snapshot_row['spread']",
            },
            {
                "canonical_name": "structure.zone",
                "live_supported": True,
                "db_supported": True,
                "chosen_live_source": "l1_payload['zone'] (top-level structural)",
                "chosen_db_source": "snapshot_row['zone']",
            },
            {
                "canonical_name": "structure.nearest_above_dist",
                "live_supported": True,
                "db_supported": True,
                "chosen_live_source": "l1_payload['nearest_above_dist']",
                "chosen_db_source": "snapshot_row['nearest_above_dist']",
            },
            {
                "canonical_name": "structure.nearest_below_dist",
                "live_supported": True,
                "db_supported": True,
                "chosen_live_source": "l1_payload['nearest_below_dist']",
                "chosen_db_source": "snapshot_row['nearest_below_dist']",
            },
            {
                "canonical_name": "structure.net_gamma",
                "live_supported": True,
                "db_supported": True,
                "chosen_live_source": "l1_payload['net_gamma']",
                "chosen_db_source": "snapshot_row['net_gamma']",
            },
            {
                "canonical_name": "anchor.vwap_side",
                "live_supported": True,
                "db_supported": True,
                "chosen_live_source": "l1_payload['vwap_side'] (flat; spot_anchors ignored)",
                "chosen_db_source": "snapshot_row['vwap_side']",
            },
            {
                "canonical_name": "anchor.vwap_dist_pts",
                "live_supported": True,
                "db_supported": True,
                "chosen_live_source": "l1_payload['dist_to_vwap_pts'] (flat; spot_anchors ignored)",
                "chosen_db_source": "snapshot_row['vwap_dist_pts']",
            },
            {
                "canonical_name": "liquidity.range_imbalance_stall_score",
                "live_supported": True,
                "db_supported": True,
                "chosen_live_source": "l1_payload['liquidity_summary']['range_imbalance_stall_score']",
                "chosen_db_source": "snapshot_row['range_imbalance_stall_score']",
            },
            {
                "canonical_name": "liquidity.range_imbalance_push_score",
                "live_supported": True,
                "db_supported": True,
                "chosen_live_source": "l1_payload['liquidity_summary']['range_imbalance_push_score']",
                "chosen_db_source": "snapshot_row['range_imbalance_push_score']",
            },
        ],
    }
