"""Batch-2: signals engine error contract and decision bundle skip."""

from __future__ import annotations

from live_decision_bundle import stamp_decision_bundle


def test_stamp_decision_bundle_skips_generation_on_signals_engine_failed():
    md = {"signals_engine_failed": True, "state_error": "signals_engine_error"}
    out = stamp_decision_bundle(md)
    assert out["decision_tick_kind"] == "signals_engine_error"
    assert out.get("decision_generation_skipped") is True
    assert "decision_generation_id" in out
    assert out["decision_generation_id"] is None
    assert out.get("decision_timestamp_utc") is None


def test_stamp_decision_bundle_increments_on_success():
    md = {"signals_engine_failed": False}
    out = stamp_decision_bundle(dict(md))
    assert out.get("decision_generation_skipped") is False
    assert out.get("decision_tick_kind") == "live"
    assert isinstance(out.get("decision_generation_id"), int)


def test_index_html_shared_render_guards():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "function _renderCoherenceGuards(" in html
    assert "function _updateErrorBarFromPayload(" in html
    assert "renderTierCPendingShell" in html and "checkDecisionGen: false" in html


def test_tier_a_does_not_advance_analytical_last_render_timestamp():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "function _commitTierAFastTimestamp(" in html
    assert "function _commitAnalyticalRenderTimestampAndGen(" in html
    assert "_commitQuoteLaneTimestamps(d)" in html
    assert "timestampLane: 'quote'" in html
    tier_a = html.split("function renderTierALive")[1].split("function render(")[0]
    assert "lastRenderTimestamp" not in tier_a
    assert "_commitAnalyticalRenderTimestampAndGen" not in tier_a


def test_error_bar_fires_on_either_state_error_field():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "d.state_error || d.state_error_detail" in html
