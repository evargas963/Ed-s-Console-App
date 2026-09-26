"""
Structured stack degradation / health signals (machine-visible).

Attached to ml_bundle, PredictiveCard, and replay outputs so optional failures and
fallback paths cannot present as fully healthy without an audit trail.
"""

from __future__ import annotations

from typing import Any, Literal

Severity = Literal["info", "warning", "error"]


def record_stack_degradation(
    events: list[dict[str, Any]],
    *,
    component: str,
    severity: Severity,
    reason: str,
    exc_type: str | None = None,
    fallback_used: bool = False,
    authority_intact: bool = True,
    detail: str | None = None,
    dedupe_key: str | None = None,
) -> None:
    """Append one degradation record. Optional dedupe_key skips duplicate components for the same tick."""
    if dedupe_key is not None:
        if any(e.get("dedupe_key") == dedupe_key for e in events):
            return
    rec: dict[str, Any] = {
        "component": component,
        "severity": severity,
        "reason": reason,
        "exc_type": exc_type,
        "fallback_used": fallback_used,
        "authority_intact": authority_intact,
        "detail": detail,
    }
    if dedupe_key is not None:
        rec["dedupe_key"] = dedupe_key
    events.append(rec)


def merge_stack_integrity_events(
    *event_lists: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for el in event_lists:
        if el:
            out.extend(el)
    return out


def finalize_stack_integrity_v1(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize events for JSON / API consumers; strip internal dedupe keys."""
    public_events: list[dict[str, Any]] = []
    for e in events:
        pe = {k: v for k, v in e.items() if k != "dedupe_key"}
        public_events.append(pe)

    degraded = any(pe.get("severity") in ("warning", "error") for pe in public_events)
    mh_ok = not any(
        pe.get("component") == "mh_ml_product_overlay" and pe.get("authority_intact") is False
        for pe in public_events
    )
    fusion_overlay_ok = not any(
        pe.get("component") == "fusion_model_overlay" and pe.get("authority_intact") is False
        for pe in public_events
    )
    base_models_ok = not any(
        pe.get("component") == "run_unified_stack_ml_once" and pe.get("authority_intact") is False
        for pe in public_events
    )

    return {
        "version": 1,
        "events": public_events,
        "degraded": degraded,
        "mh_ml_overlay_authority_intact": mh_ok,
        "fusion_overlay_richness_intact": fusion_overlay_ok,
        "base_models_bundle_intact": base_models_ok,
    }
