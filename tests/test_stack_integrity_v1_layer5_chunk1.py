"""Layer 5 stack_integrity_v1 chunk-1: gap-fill contract locks (parallel-runtime audit trail)."""

from __future__ import annotations

from features.stack_integrity_v1 import (
    finalize_stack_integrity_v1,
    merge_stack_integrity_events,
    record_stack_degradation,
)


def test_record_stack_degradation_dedupe_skips_second_event():
    ev: list = []
    record_stack_degradation(
        ev,
        component="run_base_models_once",
        severity="warning",
        reason="first",
        dedupe_key="tick-1",
    )
    record_stack_degradation(
        ev,
        component="run_base_models_once",
        severity="error",
        reason="second",
        dedupe_key="tick-1",
    )
    assert len(ev) == 1
    assert ev[0]["reason"] == "first"


def test_merge_stack_integrity_events_concatenates_non_empty():
    a = [{"component": "a"}]
    b = [{"component": "b"}]
    merged = merge_stack_integrity_events(a, None, b)
    assert len(merged) == 2
    assert merged[0]["component"] == "a"
    assert merged[1]["component"] == "b"


def test_finalize_not_degraded_when_no_warning_or_error():
    fin = finalize_stack_integrity_v1(
        [{"component": "x", "severity": "info", "reason": "ok"}]
    )
    assert fin["degraded"] is False
    assert fin["version"] == 1


def test_finalize_mh_overlay_authority_false_when_flagged():
    fin = finalize_stack_integrity_v1(
        [
            {
                "component": "mh_ml_product_overlay",
                "severity": "error",
                "reason": "overlay failed",
                "authority_intact": False,
            }
        ]
    )
    assert fin["degraded"] is True
    assert fin["mh_ml_overlay_authority_intact"] is False


def test_finalize_fusion_overlay_authority_false_when_flagged():
    fin = finalize_stack_integrity_v1(
        [
            {
                "component": "fusion_model_overlay",
                "severity": "warning",
                "reason": "overlay down",
                "authority_intact": False,
            }
        ]
    )
    assert fin["fusion_overlay_richness_intact"] is False


def test_finalize_base_models_bundle_false_when_flagged():
    fin = finalize_stack_integrity_v1(
        [
            {
                "component": "run_base_models_once",
                "severity": "error",
                "reason": "bundle failed",
                "authority_intact": False,
            }
        ]
    )
    assert fin["base_models_bundle_intact"] is False


def test_finalize_empty_events_not_degraded():
    fin = finalize_stack_integrity_v1([])
    assert fin["events"] == []
    assert fin["degraded"] is False
    assert fin["mh_ml_overlay_authority_intact"] is True
