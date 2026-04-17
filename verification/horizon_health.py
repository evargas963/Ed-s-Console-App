"""Phase 3 — horizon health report for any ticker / similar list / live snapshot dict."""
from __future__ import annotations

from typing import Any, Optional

from math_exposure import MIN_SAMPLES_STATISTICAL
from prediction_engine import _count_labeled, _literal_empirical_horizon

from verification.similar_set_trace import PRODUCT_EMPIRICAL


def empirical_horizon_rows(similar: list, outcome_col: str) -> int:
    return _count_labeled(similar, outcome_col)


def horizon_health_report(
    similar: list,
    *,
    min_required: int = MIN_SAMPLES_STATISTICAL,
    fusion_probs_by_hz: Optional[dict[str, tuple[Optional[float], Optional[float], Optional[float]]]] = None,
) -> dict[str, Any]:
    """
    Reusable per-horizon status for 1c/5c/15c/60c.
    fusion_probs_by_hz: optional { '1c': (u,d,f), ... } if caller has fusion layer;
                        default empirical-only assessment.
    """
    fusion_probs_by_hz = fusion_probs_by_hz or {}
    rows: dict[str, Any] = {}
    for hz_key, col, bars in PRODUCT_EMPIRICAL:
        probs, src_key, note, n = _literal_empirical_horizon(similar, col, bars)
        triplet = (
            (float(probs["up"]), float(probs["down"]), float(probs["flat"])) if probs else (None, None, None)
        )
        if hz_key in fusion_probs_by_hz:
            triplet = fusion_probs_by_hz[hz_key]
            src = "fusion"
            prob_ok = all(x is not None for x in triplet)
            n_eff = n
        else:
            src = "empirical" if probs is not None else "empirical_withheld"
            prob_ok = probs is not None
            n_eff = n

        if not similar:
            status = "MISSING"
            reason = "empty similar set"
        elif hz_key in fusion_probs_by_hz:
            status = "OK" if prob_ok else "UNAVAILABLE"
            reason = "fusion triplet" if prob_ok else "fusion incomplete"
        elif n < min_required:
            status = "WITHHELD"
            reason = f"labeled_count={n} < min_required={min_required} ({src_key})"
        else:
            status = "OK"
            reason = f"empirical histogram ok ({src_key})"

        tradeable = status == "OK" and prob_ok

        rows[hz_key] = {
            "status": status,
            "labeled_count": n_eff,
            "min_required": min_required,
            "probability_triplet_present": prob_ok,
            "triplet_up_dn_flat": triplet,
            "tradeable": tradeable,
            "reason": reason,
            "source": src,
        }
    return {"horizons": rows, "min_required_default": min_required, "similar_size": len(similar)}


def horizon_health_from_state_horizon_bars(ms_dict: dict) -> dict[str, Any]:
    """Derive empirical health from /api/state-style horizon_prob_bars (1m/5m/15m/60m keys)."""
    hpb = ms_dict.get("horizon_prob_bars") or {}
    key_map = {"1m": "1c", "5m": "5c", "15m": "15c", "60m": "60c"}
    out: dict[str, Any] = {}
    for k_ui, hz in key_map.items():
        row = hpb.get(k_ui) if isinstance(hpb, dict) else None
        if not isinstance(row, dict):
            out[hz] = {
                "status": "UNAVAILABLE",
                "labeled_count": None,
                "min_required": MIN_SAMPLES_STATISTICAL,
                "probability_triplet_present": False,
                "tradeable": False,
                "reason": f"no horizon_prob_bars[{k_ui!r}]",
                "source": "other",
            }
            continue
        u, d, f = row.get("up"), row.get("down"), row.get("flat")
        tri_ok = u is not None and d is not None and f is not None
        lc = row.get("labeled_count")
        mn = row.get("min_samples_required", MIN_SAMPLES_STATISTICAL)
        src = row.get("source") or ""
        if tri_ok:
            st = "OK"
            reason = "triplet present in payload"
        elif lc is not None and mn is not None and int(lc) < int(mn):
            st = "WITHHELD"
            reason = f"labeled_count={lc} < min_samples_required={mn}"
        else:
            st = "FAILED" if src.startswith("insufficient") else "UNAVAILABLE"
            reason = src or "missing triplet"
        out[hz] = {
            "status": st,
            "labeled_count": lc,
            "min_required": mn,
            "probability_triplet_present": tri_ok,
            "tradeable": tri_ok,
            "reason": reason,
            "source": "empirical" if "empirical" in str(src) else ("fusion" if "fusion" in str(src) else "other"),
        }
    return {"horizons": out, "from": "market_state.horizon_prob_bars"}
