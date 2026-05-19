"""Layer 5: FIND-PSS1 — withhold dominant on exactly-uniform parallel stack triplet."""

from __future__ import annotations

from features.parallel_stack_schema import build_parallel_base_output


def test_uniform_triplet_withholds_dominant_when_confidence_zero():
    o = build_parallel_base_output(
        probs={"up": 1 / 3, "down": 1 / 3, "flat": 1 / 3},
        approved=False,
    )
    assert o["available"] is True
    assert o["confidence_score"] == 0.0
    assert o["dominant"] is None


def test_directional_triplet_still_sets_dominant():
    o = build_parallel_base_output(
        probs={"up": 0.5, "down": 0.3, "flat": 0.2},
        approved=True,
    )
    assert o["available"] is True
    assert o["dominant"] == "up"
    assert o["confidence_score"] == 0.1667
