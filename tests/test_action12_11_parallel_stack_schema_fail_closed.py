"""Action 12.11: parallel stack schema must not fabricate unavailable model triplets."""

from __future__ import annotations

from pathlib import Path











def test_parallel_stack_schema_no_third_defaults_in_source():
    text = (Path(__file__).resolve().parent.parent / "features" / "parallel_stack_schema.py").read_text(
        encoding="utf-8"
    )
    assert "0.33" not in text
    assert "0.333" not in text
    assert '"dominant": "flat"' not in text
    assert '"prob_up": 0.33' not in text
