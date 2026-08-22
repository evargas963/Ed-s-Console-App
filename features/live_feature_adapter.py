"""
Map live Tier B / L1 JSON (`build_l1_context` + overlay + structural merge) to MVP canonical features.

Anchor and liquidity single sources (do not double-count duplicates):
- anchor: **flat** top-level `vwap_side`, `dist_to_vwap_pts` only (not `spot_anchors`).
- liquidity: **`liquidity_summary` dict only** (`range_imbalance_stall_score`, `range_imbalance_push_score`).

Source coercion is strict (`features.mvp_source_coercion`): missing vs invalid are distinct;
invalid present values raise `MvpFeatureSourceError`, never `None`.
"""

from __future__ import annotations

from typing import Any

from features.canonical_contract import get_mvp_feature_names
from features.mvp_source_coercion import (
    read_liquidity_summary_subdict,
    read_optional_float,
    read_optional_vwap_side,
    read_optional_zone,
)


def build_live_mvp_feature_row(l1_payload: dict[str, Any]) -> dict[str, Any]:
    """
    Build canonical MVP feature dict from a Tier B / L1 payload dict.

    Structural fields (`zone`, `nearest_*`, `net_gamma`) are read from **top-level** keys
    (present after `out.update(structural)` in `planes.context_light.build_l1_context`).

    Raises:
        MvpFeatureSourceError: present-but-invalid source values (never coerced to None).
    """
    liq = read_liquidity_summary_subdict(l1_payload)

    spread_pts = read_optional_float(l1_payload, "spread_pts", "price.spread_pts")
    # TRAIN/SERVE PARITY (ML-PIPE-V2 2026-07-11): the DB adapter withholds
    # crossed/stale negative spreads (canonical contract: spread_pts >= 0 when
    # present). The live path must apply the IDENTICAL missingness semantics —
    # otherwise the same market instant trains as None but serves negative.
    # Schwab CSV authority checked: yes
    # CSV row(s): quotes.<symbol>.bidPrice / quotes.<symbol>.askPrice (spread is
    #   the governed ask-bid derivation upstream; this block only aligns the
    #   invalid-value withhold semantics with the DB adapter).
    # Derived-field disposition: GATE_FAIL_CLOSED (crossed-quote artifact reads
    #   as missing on BOTH train and serve paths; never a fabricated value).
    # All consumers checked: yes - price.spread_pts consumers (xgb impute path,
    #   feature_quality lineage) already handle None identically to DB rows.
    # SCHWAB_CSV_CHECKED
    if spread_pts is not None and spread_pts < 0.0:
        spread_pts = None

    out = {
        "price.spot": read_optional_float(l1_payload, "spot", "price.spot"),
        "price.spread_pts": spread_pts,
        "structure.zone": read_optional_zone(l1_payload, "zone", "structure.zone"),
        "structure.nearest_above_dist": read_optional_float(
            l1_payload, "nearest_above_dist", "structure.nearest_above_dist"
        ),
        "structure.nearest_below_dist": read_optional_float(
            l1_payload, "nearest_below_dist", "structure.nearest_below_dist"
        ),
        "structure.net_gamma": read_optional_float(l1_payload, "net_gamma", "structure.net_gamma"),
        "anchor.vwap_side": read_optional_vwap_side(l1_payload, "vwap_side", "anchor.vwap_side"),
        "anchor.vwap_dist_pts": read_optional_float(
            l1_payload, "dist_to_vwap_pts", "anchor.vwap_dist_pts"
        ),
        "liquidity.range_imbalance_stall_score": read_optional_float(
            liq, "range_imbalance_stall_score", "liquidity.range_imbalance_stall_score"
        ),
        "liquidity.range_imbalance_push_score": read_optional_float(
            liq, "range_imbalance_push_score", "liquidity.range_imbalance_push_score"
        ),
    }

    order = get_mvp_feature_names()
    return {k: out[k] for k in order}
