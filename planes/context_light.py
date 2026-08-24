"""
L1 — Near-real-time context plane (formal domain).

Merge rule (locked): L1 = current L0 + last acknowledged L2 snapshot only.
L1 never implies L2 is fresh; every payload names the L2 analytics_version merged.

Forbidden here: chain fetch, DB, ML, build_market_state, compute_exposures_by_strike.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from instrument_identity import ticker_storage_key

log = logging.getLogger("ed.planes.l1")

# Single engine for L1 path — avoids per-request allocation (OrderFlowEngine is stateless per compute inputs).
_of_engine_singleton: Any = None


def _get_order_flow_engine() -> Any:
    global _of_engine_singleton
    if _of_engine_singleton is None:
        from order_flow_engine import OrderFlowEngine

        _of_engine_singleton = OrderFlowEngine()
    return _of_engine_singleton

PLANE_L1 = "L1_context"
L1_SCHEMA_VERSION = 1
MERGE_RULE_L1 = "L0_plus_acknowledged_L2_snapshot"

# Max age (seconds) for the acknowledged L2 ms_dict before structural_context_stale
# flips True. Operator-tunable policy threshold (not market data); named so the value
# is grep-discoverable and consumer-facing diagnostics can reference the same constant.
STRUCTURAL_CONTEXT_STALE_SEC: float = 120.0

# Structural fields copied only from acknowledged L2 ms_dict (never recomputed here).
_STRUCTURAL_KEYS = (
    "zone",
    "zone_label",
    "zone_badge_css",
    "bias_signal",
    "bias_color_css",
    "pin_strength",
    "pin_color_css",
    "nd_disp",
    "nd_color_css",
    "net_gamma",
    "nearest_above_name",
    "nearest_above_val",
    "nearest_above_dist",
    "nearest_below_name",
    "nearest_below_val",
    "nearest_below_dist",
    "charm_net",
    "charm_direction_display",
    "charm_drift_toward",
    # RC-292: renamed from kl_gamma_pin (the raw value carries its metric's name); the
    # qualified pin claim travels beside it, blockers included, so the plane sees WHY a
    # pin claim is absent rather than a bare null.
    "kl_absolute_gamma_strike",
    "kl_pin_candidate",
    "kl_pin_candidate_blockers",
    "kl_hvl",
    "kl_max_pain",
    "kl_net_gex",
    "kl_net_gex_disp",
    "kl_net_gex_regime",
)

_ORDER_FLOW_KEYS = (
    "order_flow_regime",
    "order_flow_readiness",
    "order_flow_verdict",
    "order_flow_verdict_color",
    "order_flow_arrow",
    "order_flow_agreement",
    "book_imbalance_5",
    "cum_delta_proxy",
    "tape_pressure_30s",
    "order_flow_score",
)


@dataclass(frozen=True)
class L1BuildContext:
    """Inputs for a single L1 projection. No I/O."""

    ticker: str
    request_expiry: Optional[str]
    l0_row: Optional[dict[str, Any]]
    l2_cache_entry: Optional[dict[str, Any]]
    now_ts: float
    l2_analytics_refresh_in_progress: bool
    l1_generation: int


def _safe_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def order_flow_compact_signature(ofc: dict[str, Any]) -> tuple[Any, ...]:
    """Stable tuple for materiality: same keys as compact OF output, floats rounded."""
    out: list[Any] = []
    for k in _ORDER_FLOW_KEYS:
        v = ofc.get(k)
        if isinstance(v, float):
            out.append((k, round(v, 6)))
        elif isinstance(v, (int, str)) or v is None:
            out.append((k, v))
        else:
            out.append((k, repr(v)))
    return tuple(out)


def build_order_flow_input_probe(ticker: str, l0_row: Optional[dict[str, Any]]) -> tuple[Any, ...]:
    """
    Lightweight fingerprint for quote-hook OF gating: plane quote + streaming buffer probe.
    Does not run OrderFlowEngine.
    """
    from order_flow_live_state import get_l1_stream_input_probe

    tkr = ticker_storage_key(ticker)  # RC-345/F25: canonical L1 context key
    sp = _safe_float(l0_row.get("spot")) if l0_row else None
    bd = _safe_float(l0_row.get("bid")) if l0_row else None
    ak = _safe_float(l0_row.get("ask")) if l0_row else None
    fg = l0_row.get("fast_generation_id") if l0_row else None
    try:
        fg_n = float(fg) if fg is not None else None
    except (TypeError, ValueError):
        fg_n = None
    q = (
        round(sp, 6) if sp is not None and sp > 0 else None,
        round(bd, 6) if bd is not None else None,
        round(ak, 6) if ak is not None else None,
        fg_n,
    )
    return ("l1_of_in", tkr, q, get_l1_stream_input_probe(tkr))


def compute_order_flow_compact(
    ticker: str,
    l0_row: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """
    L1 order-flow slice: in-process stream + plane quote only.
    Does not use chain maps (callExpDateMap empty in Tier C OF path — engine still runs).
    """
    out: dict[str, Any] = {}
    try:
        from order_flow_live_state import get_content_for_symbol

        _of_data: dict[str, Any] = {"content": get_content_for_symbol(ticker)}
        if l0_row and l0_row.get("spot") is not None:
            _of_data["quote"] = {
                "bidPrice": l0_row.get("bid"),
                "askPrice": l0_row.get("ask"),
                "lastPrice": l0_row.get("spot"),
            }
        eng = _get_order_flow_engine()
        full = eng.compute(_of_data)
        for k in _ORDER_FLOW_KEYS:
            if k in full:
                out[k] = full[k]
    except Exception as ex:
        log.debug("L1 order_flow compact: %s", ex)
    return out


def derive_readiness_summary(
    order_flow_compact: dict[str, Any],
    structural_context_stale: bool,
    l2_snapshot_present: bool,
) -> dict[str, Any]:
    return {
        "order_flow_readiness": order_flow_compact.get("order_flow_readiness"),
        "structural_anchor_stale": structural_context_stale,
        "has_acknowledged_l2_snapshot": l2_snapshot_present,
    }


def build_l1_context(
    ctx: L1BuildContext,
    *,
    derive_vwap_side_fn: Callable[[Optional[float], Optional[float]], Optional[str]],
) -> dict[str, Any]:
    """
    Build the versioned L1 JSON object. Pure — no OrderFlowEngine compute here.

    RC-404 (Cursor F10): the order_flow block CARRIES the single canonical L2 computation from
    `ctx.l2_cache_entry`; it is not recomputed on thin L1 inputs. See the order_flow_block build.

    derive_vwap_side_fn: injected (e.g. math_snapshot_derive.derive_vwap_side) to avoid
    importing heavy graph here at module load.
    """
    t0 = time.perf_counter()
    tkr = ticker_storage_key(ctx.ticker)  # RC-345/F25: canonical L1 context key
    md: dict[str, Any] = {}
    ent = ctx.l2_cache_entry

    l2_ver_used: int = 0
    src_ts = 0.0
    if ent:
        l2_ver_used = int(ent.get("analytics_version", 0))
        src_ts = float(ent.get("generated_at") or ent.get("ts") or 0.0)
        md = ent.get("ms_dict") or {}

    spot_f = _safe_float(ctx.l0_row.get("spot")) if ctx.l0_row else None
    l0_usable = (
        ctx.l0_row is not None
        and spot_f is not None
        and spot_f > 0
    )

    structural_age: Optional[float] = None
    if src_ts > 0:
        structural_age = max(0.0, ctx.now_ts - src_ts)
    structural_context_stale = (
        structural_age is None or structural_age > STRUCTURAL_CONTEXT_STALE_SEC
    )
    l2_snapshot_present = bool(ent and md)

    vwap_val = md.get("vwap")
    vwap_f = _safe_float(vwap_val)
    vwap_side = derive_vwap_side_fn(spot_f, vwap_f)
    dist_vwap: Optional[float] = None
    if spot_f is not None and vwap_f is not None:
        dist_vwap = round(spot_f - vwap_f, 4)

    # RC-404 (Cursor F10) — ONE FAUCET = ONE COMPUTATION. The L1 order_flow block is a CARRIER of
    # the single canonical L2 OrderFlowEngine computation, read from the acknowledged L2 cache (`md`)
    # exactly as the structural block below is. It is no longer a second, chain-less engine
    # invocation on thin L1 inputs — that produced a divergent order_flow_score / book_imbalance_5
    # under the same field names on /api/analytics/light vs /api/state at the same tick. Absent L2
    # row → absent order_flow (fail-closed), never a thin recompute.
    order_flow_block: dict[str, Any] = {}
    for k in _ORDER_FLOW_KEYS:
        if k in md and md[k] is not None:
            order_flow_block[k] = md[k]

    structural: dict[str, Any] = {}
    for k in _STRUCTURAL_KEYS:
        if k in md and md[k] is not None:
            structural[k] = md[k]

    lb = md.get("liquidity_behavior")
    liquidity_summary: Optional[dict[str, Any]] = None
    if isinstance(lb, dict):
        liquidity_summary = {
            "behavior_label": lb.get("behavior_label"),
            "absorption_score": lb.get("absorption_score"),
            "continuation_score": lb.get("continuation_score"),
        }

    readiness = derive_readiness_summary(order_flow_block, structural_context_stale, l2_snapshot_present)

    # Stale when L0 spot is missing or not usable — do not treat a non-empty row with bad spot as fresh.
    l1_stale = not l0_usable

    l2_structural_scope_exact = bool(ent and ent.get("ms_dict"))

    if ctx.request_expiry:
        selected_exp_out: Optional[str] = ctx.request_expiry
    else:
        selected_exp_out = md.get("selected_exp")

    wall_ms = (time.perf_counter() - t0) * 1000.0
    iso_now = datetime.fromtimestamp(ctx.now_ts, tz=timezone.utc).isoformat()
    iso_l2 = (
        datetime.fromtimestamp(src_ts, tz=timezone.utc).isoformat() if src_ts > 0 else None
    )

    out: dict[str, Any] = {
        "plane": PLANE_L1,
        "schema_version": L1_SCHEMA_VERSION,
        "merge_rule": MERGE_RULE_L1,
        "l1_generation": ctx.l1_generation,
        "as_of_ts": ctx.now_ts,
        "as_of_iso": iso_now,
        "l1_pipeline_ms": round(wall_ms, 3),
        "l1_stale": l1_stale,
        "l2_analytics_refresh_in_progress": bool(ctx.l2_analytics_refresh_in_progress),
        "l2_snapshot_version_used": l2_ver_used,
        "l2_snapshot_ts_used_iso": iso_l2,
        "l2_merge_acknowledged": l2_snapshot_present,
        "l2_structural_scope_exact": l2_structural_scope_exact,
        "structural_context_stale": structural_context_stale,
        "structural_context_age_sec": round(structural_age, 3) if structural_age is not None else None,
        "spot": spot_f,
        "spot_anchors": {
            "vwap": vwap_f,
            "vwap_side": vwap_side,
            "dist_to_vwap_pts": dist_vwap,
        },
        "order_flow": order_flow_block,
        "order_flow_as_of_ts": ctx.now_ts,
        "liquidity_summary": liquidity_summary,
        "liquidity_behavior_summary": liquidity_summary,
        "readiness_summary": readiness,
        "tier_b_structural": structural,
        # Back-compat for existing UI / Tier B label
        "_tier": "B_light",
        "_endpoint": "/api/analytics/light",
        "ticker": tkr,
        "selected_exp": selected_exp_out,
        "_server_build_ts": ctx.now_ts,
        "_pipeline_ms": round(wall_ms, 3),
        "b_light_generated_at": iso_now,
        "b_light_age_sec": 0.0,
        "b_structural_source_ts": iso_l2,
        "b_structural_age_sec": round(structural_age, 3) if structural_age is not None else None,
        "b_structural_stale": structural_context_stale,
        "b_order_flow_live": True,
        "vwap": vwap_f,
        "vwap_side": vwap_side,
        "dist_to_vwap_pts": dist_vwap,
    }
    out.update(structural)
    return out
