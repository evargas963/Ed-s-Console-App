"""Action 12.11: parallel stack schema must not fabricate unavailable model triplets."""

from __future__ import annotations

from pathlib import Path

from features.parallel_stack_schema import build_parallel_base_output, empty_parallel_output


def test_empty_parallel_output_no_fabricated_triplet():
    o = empty_parallel_output(reason="unavailable")
    assert o["available"] is False
    assert o["prob_up"] is None
    assert o["prob_down"] is None
    assert o["prob_flat"] is None
    assert o["dominant"] is None
    assert o["confidence_score"] is None
    assert o["error"] == "unavailable"


def test_build_parallel_base_output_none_probs():
    o = build_parallel_base_output(probs=None, approved=False)
    assert o["available"] is False
    assert o["prob_up"] is None


def test_build_parallel_base_output_incomplete_triplet():
    o = build_parallel_base_output(probs={"up": 0.5, "down": 0.3}, approved=True)
    assert o["available"] is False
    assert o.get("error") == "incomplete_triplet"


def test_build_parallel_base_output_complete_triplet():
    o = build_parallel_base_output(probs={"up": 0.5, "down": 0.3, "flat": 0.2}, approved=True)
    assert o["available"] is True
    assert o["prob_up"] == 0.5
    assert o["dominant"] == "up"


def test_parallel_stack_schema_no_third_defaults_in_source():
    text = (Path(__file__).resolve().parent.parent / "features" / "parallel_stack_schema.py").read_text(
        encoding="utf-8"
    )
    assert "0.33" not in text
    assert "0.333" not in text
    assert '"dominant": "flat"' not in text
    assert '"prob_up": 0.33' not in text
