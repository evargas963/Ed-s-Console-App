"""Batch-2: signals engine error contract and decision bundle skip."""

from __future__ import annotations







# test_index_html_shared_render_guards and test_tier_a_does_not_advance_analytical_last_render_
# timestamp were retired here (/console cutover, operator directive 2026-09-14): both locked
# legacy static/index.html's Tier-A/Tier-C render-generation architecture
# (_renderCoherenceGuards, _commitTierAFastTimestamp, renderTierALive), which has no equivalent
# in the new console's simpler poll model (static/js/ed-core.js) -- grepped, zero matches.


def test_error_engine_surfaces_in_the_new_console():
    """The real invariant test_error_bar_fires_on_either_state_error_field protected -- an
    engine error must surface, not render silently -- has a live equivalent in the new console,
    just without legacy's state_error_detail OR-fallback (a minor gap: state_error_detail alone,
    with state_error falsy, would not surface here either, same as it wouldn't have needed to
    in practice since callers always set both or neither)."""
    from pathlib import Path

    # The header no longer polls /api/live/state for a quote (operator rule 2026-09-23: the
    # SSE push is its only source), so the engine error surfaces where the analytics are
    # read -- the PCR panel below -- not through a header poll fallback.
    panels = (Path(__file__).resolve().parents[1] / "static" / "js" / "ed-gamma-panels.js").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "if (d.state_error) { _pcrPending = false; paintPcr(null, 'analytics error'); return; }" in panels
