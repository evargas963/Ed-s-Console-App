"""
L1 runtime discipline — materiality gating, cache policy, fingerprinting.

Single authoritative compute: server._project_l1. This module holds thresholds and
pure helpers; no I/O.
"""

from __future__ import annotations

from typing import Any, Optional

# --- Cache lifecycle (mandatory: bounded retention + TTL) ---
L1_CACHE_ENTRY_TTL_SEC: float = 600.0
"""Drop snapshots older than this on maintenance (eviction)."""

L1_MAX_CACHE_SCOPES: int = 128
"""Hard cap on distinct (ticker, expiry) L1 rows."""

L1_HTTP_SERVE_MAX_AGE_SEC: float = 90.0
"""If snapshot older than this, GET triggers rebuild (stale for near-real-time)."""

L1_ORDER_FLOW_STALE_SEC: float = 15.0
"""If order_flow_as_of_ts is older than this vs now, mark order_flow_stale (cache-hit safe)."""

# --- Quote-hook OF engine (debounced path only; _project_l1 unchanged) ---
L1_OF_MIN_COMPUTE_INTERVAL_SEC: float = 0.2
"""Minimum wall time between OrderFlowEngine.compute on quote hook when input probe is unchanged."""

L1_OF_PROBE_FORCE_REFRESH_SEC: float = 3.0
"""Periodic full OF compute on quote hook when probe matches (bounded drift safety)."""

# --- Materiality (quote path — skip useless full L1 rebuilds) ---
L1_SPOT_REL_EPS: float = 2e-4
"""Default relative spot threshold; prefer planes.l1_thresholds.resolve_spot_rel_eps at call sites."""

L1_SPREAD_FRAC_ABS_EPS: float = 5e-5
"""Default spread delta; prefer planes.l1_thresholds.resolve_spread_frac_abs_eps at call sites."""

def _sf(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v:
        return None
    return v


def compute_l2_version(ent: Optional[dict[str, Any]]) -> int:
    if not ent:
        return 0
    try:
        return int(ent.get("analytics_version") or 0)
    except (TypeError, ValueError):
        return 0


def build_input_fingerprint(
    row: Optional[dict[str, Any]],
    ent: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """
    Cheap fingerprint of L0+L2 inputs that drive L1. Used to skip full rebuild when
    debounced quote fires but nothing material changed for this scope.
    """
    spot = _sf(row.get("spot")) if row else None
    spf = _sf(row.get("spread")) if row else None
    fg = row.get("fast_generation_id") if row else None
    try:
        fg_n = float(fg) if fg is not None else None
    except (TypeError, ValueError):
        fg_n = None
    return {
        "spot": round(spot, 6) if spot is not None and spot > 0 else None,
        "spread_frac": round(spf, 8) if spf is not None else None,
        "l2_version": compute_l2_version(ent),
        "fast_gen": fg_n,
    }


def input_fingerprint_materially_changed(
    prev_fp: Optional[dict[str, Any]],
    row: Optional[dict[str, Any]],
    ent: Optional[dict[str, Any]],
    *,
    ticker: str = "",
    session_label: Optional[str] = None,
    adaptive_context: Optional[Any] = None,
    adaptive_diagnostics_out: Optional[dict[str, Any]] = None,
) -> bool:
    """True if a full L1 recompute is justified (L0+L2 inputs moved vs last stored fingerprint)."""
    from planes.l1_thresholds import resolve_l1_materiality_engine

    tkr = (ticker or "").upper().strip() or "SPY"
    _ = session_label
    if adaptive_context is not None:
        res = resolve_l1_materiality_engine(tkr, context=adaptive_context)
        spot_eps = res.spot_rel_eps
        spr_eps = res.spread_frac_abs_eps
        if adaptive_diagnostics_out is not None:
            adaptive_diagnostics_out.clear()
            adaptive_diagnostics_out.update(res.as_dict())
    else:
        spot_eps = L1_SPOT_REL_EPS
        spr_eps = L1_SPREAD_FRAC_ABS_EPS
        if adaptive_diagnostics_out is not None:
            adaptive_diagnostics_out.clear()
            adaptive_diagnostics_out.update(
                {
                    "spot_rel_eps": spot_eps,
                    "spread_frac_abs_eps": spr_eps,
                    "mode": "static_defaults",
                    "rules_applied": ["no_adaptive_context_runtime_constants"],
                }
            )
    cur = build_input_fingerprint(row, ent)
    if prev_fp is None:
        return True
    pv = prev_fp.get("l2_version")
    cv = cur["l2_version"]
    if pv != cv:
        return True
    pfg = prev_fp.get("fast_gen")
    cfg = cur["fast_gen"]
    if pfg != cfg:
        return True
    ps = _sf(prev_fp.get("spot"))
    cs = _sf(cur.get("spot"))
    if (ps is None) != (cs is None):
        return True
    if ps is not None and cs is not None:
        if ps <= 0 or cs <= 0:
            return ps != cs
        if abs(cs - ps) / max(ps, 1e-9) >= spot_eps:
            return True
    psp = _sf(prev_fp.get("spread_frac"))
    csp = _sf(cur.get("spread_frac"))
    if (psp is None) != (csp is None):
        return True
    if psp is not None and csp is not None and abs(csp - psp) >= spr_eps:
        return True
    return False


def snapshot_expired_for_http_serve(cached: dict[str, Any], now_ts: float) -> bool:
    """True if cached L1 is too old to serve without rebuild."""
    built = _sf(cached.get("as_of_ts")) or _sf(cached.get("_server_build_ts"))
    if built is None or built <= 0:
        return True
    return (now_ts - float(built)) >= L1_HTTP_SERVE_MAX_AGE_SEC


def entry_past_ttl(cached: dict[str, Any], now_ts: float) -> bool:
    """True if entry should be evicted (TTL), not just rebuilt."""
    built = _sf(cached.get("as_of_ts")) or _sf(cached.get("_server_build_ts"))
    if built is None or built <= 0:
        return True
    return (now_ts - float(built)) >= L1_CACHE_ENTRY_TTL_SEC
