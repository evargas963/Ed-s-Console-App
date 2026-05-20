"""Batch-2: signals engine error contract and decision bundle skip."""

from __future__ import annotations

from live_decision_bundle import stamp_decision_bundle


def test_stamp_decision_bundle_skips_generation_on_signals_engine_failed():
    md = {"signals_engine_failed": True, "state_error": "signals_engine_error"}
    out = stamp_decision_bundle(md)
    assert out["decision_tick_kind"] == "signals_engine_error"
    assert out.get("decision_generation_skipped") is True
    assert "decision_generation_id" not in out


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
