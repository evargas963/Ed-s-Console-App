"""
Narrow live pipeline diagnostics for SPY vs QQQ comparison.

Enable before starting the server:
  set ED_LIVE_DIAG=1

Log output (grep ``LIVE_DIAG``):
  - ``compute_signals_complete``: model stack, fusion, canonical, predictive_card
    (samples_used, match_tier, horizon_prob_bars counts, product triplets any_none),
    call pre/post multi-horizon, full multi_horizon bundle + mhap_rows.
  - ``api_state``: cache_hit true/false when expiry is set (stale payload risk).
  - ``_fetch_state_start``: confirms full fetch began for ticker.

HTTP comparison (server already running):
  python tools/live_diag_compare.py SPY QQQ
  Optional: ED_DIAG_BASE, ED_DIAG_EXPIRY, ED_DIAG_TOKEN
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional

_LOG = logging.getLogger("live_pipeline_diag")

_PRODUCT_HZ = ("1c", "5c", "15c", "60c")


def _live_diag_on() -> bool:
    v = (os.environ.get("ED_LIVE_DIAG") or "").strip().lower()
    return v in ("1", "true", "yes")


def _avail(obj: Any) -> bool:
    return obj is not None and bool(getattr(obj, "available", False))


def _fus_pack(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {"present": False, "available": False}
    return {
        "present": True,
        "available": bool(getattr(obj, "available", False)),
        "dominant_class": str(getattr(obj, "dominant_class", None) or getattr(obj, "dominant_direction", "") or ""),
        "confidence_label": str(getattr(obj, "confidence_label", None) or getattr(obj, "confidence", "") or ""),
    }


def _serialize_predictive(pred: Any) -> dict[str, Any]:
    if pred is None:
        return {"present": False}
    hpb = getattr(pred, "horizon_prob_bars", None) or {}
    bars_out: dict[str, Any] = {}
    for key, row in hpb.items():
        if not isinstance(row, dict):
            continue
        bars_out[key] = {
            "up": row.get("up"),
            "down": row.get("down"),
            "flat": row.get("flat"),
            "source": row.get("source"),
            "labeled_count": row.get("labeled_count"),
            "min_samples_required": row.get("min_samples_required"),
        }
    tri: dict[str, Any] = {}
    for hz in _PRODUCT_HZ:
        u = getattr(pred, f"up_prob_{hz}", None)
        d = getattr(pred, f"down_prob_{hz}", None)
        f = getattr(pred, f"flat_prob_{hz}", None)
        tri[hz] = {
            "up": u,
            "down": d,
            "flat": f,
            "any_none": u is None or d is None or f is None,
        }
    mo = getattr(pred, "model_outputs", None)
    return {
        "present": True,
        "samples_used": getattr(pred, "samples_used", None),
        "match_tier": getattr(pred, "match_tier", None),
        "tier_label": getattr(pred, "tier_label", None),
        "empirical_confidence": getattr(pred, "empirical_confidence", None),
        "model_version": getattr(pred, "model_version", None),
        "horizon_prob_bars": bars_out,
        "product_horizon_triplets": tri,
        "model_outputs": mo,
    }


def _serialize_mh_bundle(mh_bundle: Any) -> dict[str, Any]:
    if mh_bundle is None:
        return {"present": False}
    out: dict[str, Any] = {"present": True, "horizons": {}, "final": {}}
    for hz in _PRODUCT_HZ:
        f = getattr(mh_bundle, f"canonical_{hz}", None)
        if f is None:
            out["horizons"][hz] = None
            continue
        out["horizons"][hz] = {
            "direction": getattr(f, "direction", None),
            "confidence": round(float(getattr(f, "confidence", 0.0) or 0.0), 4),
            "tradeable": bool(getattr(f, "tradeable", False)),
            "unavailable": bool(getattr(f, "unavailable", False)),
            "missing": bool(getattr(f, "missing", False)),
            "entry_ref": getattr(f, "entry_ref", None),
        }
    fd = getattr(mh_bundle, "final_decision", None)
    if fd is not None:
        ar = getattr(fd, "alignment_report", None)
        out["final"] = {
            "primary_horizon": getattr(fd, "primary_horizon", None),
            "trade_mode": getattr(fd, "trade_mode", None),
            "alignment_state": getattr(fd, "alignment_state", None),
            "contradiction_state": getattr(fd, "contradiction_state", None),
            "final_bias": getattr(fd, "final_bias", None),
            "final_tradeable": bool(getattr(fd, "final_tradeable", False)),
            "wait_reason": getattr(fd, "wait_reason", None),
            "entry_state": getattr(fd, "entry_state", None),
            "conflict_level": getattr(ar, "conflict_level", None) if ar else None,
        }
        rows = []
        for a in list(getattr(fd, "supporting_assessments", []) or []):
            rows.append(
                {
                    "horizon": getattr(a, "horizon", None),
                    "role": getattr(a, "role", None),
                    "call": getattr(a, "call", None),
                    "confidence": getattr(a, "confidence", None),
                    "entry_ref": getattr(a, "entry_ref", None),
                    "effect": getattr(a, "effect", None),
                    "row_state": getattr(a, "row_state", None),
                }
            )
        out["mhap_rows"] = rows
    sel = getattr(mh_bundle, "selected_primary_horizon", None)
    out["selected_primary_horizon"] = sel
    return out


def emit_compute_signals_diag(
    *,
    ticker: str,
    xgb_out: Any,
    lstm_out: Any,
    transformer_out: Any,
    mc_out: Any,
    fusion: Any,
    canonical: Any,
    pred: Any,
    call_pre_mh: dict[str, Any],
    call_post_mh: dict[str, Any],
    mh_bundle: Any,
    ml_bundle: Optional[dict[str, Any]] = None,
) -> None:
    if not _live_diag_on():
        return
    mo = (ml_bundle or {}).get("model_outputs") if isinstance(ml_bundle, dict) else None
    try:
        from ml_predict import stack_probs_bundle_key

        spk = stack_probs_bundle_key()
    except Exception:
        spk = "stack_probs_1c"
    stack_probs = (ml_bundle or {}).get(spk) if isinstance(ml_bundle, dict) else None
    payload: dict[str, Any] = {
        "ts": time.time(),
        "stage": "compute_signals_complete",
        "ticker": (ticker or "").upper(),
        "model_stack": {
            "xgb": _fus_pack(xgb_out),
            "lstm": _fus_pack(lstm_out),
            "transformer": _fus_pack(transformer_out),
            "monte_carlo": {
                "present": mc_out is not None,
                "available": bool(getattr(mc_out, "available", False)) if mc_out is not None else False,
            },
            "model_outputs_fresh": mo,
            "stack_probs_triplet": stack_probs,
        },
        "fusion": {
            "present": fusion is not None,
            "available": _avail(fusion),
            "dominant_direction": str(getattr(fusion, "dominant_direction", "") or "") if fusion else "",
            "fusion_confidence": str(getattr(fusion, "fusion_confidence", "") or "") if fusion else "",
        },
        "canonical": {
            "present": canonical is not None,
            "direction": str(getattr(canonical, "direction", "") or "") if canonical else "",
            "confidence": str(getattr(canonical, "confidence", "") or "") if canonical else "",
            "provenance": str(getattr(canonical, "provenance", "") or "") if canonical else "",
        },
        "predictive_card": _serialize_predictive(pred),
        "call": {"pre_multi_horizon": call_pre_mh, "post_multi_horizon": call_post_mh},
        "multi_horizon": _serialize_mh_bundle(mh_bundle),
    }
    _LOG.warning("LIVE_DIAG %s", json.dumps(payload, default=str))


def emit_api_state_cache(*, ticker: str, expiry: Optional[str], cache_hit: bool, ttl: Optional[float] = None) -> None:
    if not _live_diag_on():
        return
    _LOG.warning(
        "LIVE_DIAG %s",
        json.dumps(
            {
                "ts": time.time(),
                "stage": "api_state",
                "ticker": (ticker or "").upper(),
                "expiry": expiry,
                "cache_hit": cache_hit,
                "cache_ttl_sec": ttl,
            },
            default=str,
        ),
    )


def emit_fetch_state_start(*, ticker: str, log_only: bool) -> None:
    if not _live_diag_on():
        return
    _LOG.warning(
        "LIVE_DIAG %s",
        json.dumps(
            {"ts": time.time(), "stage": "_fetch_state_start", "ticker": (ticker or "").upper(), "log_only": log_only},
            default=str,
        ),
    )
