"""LIVE-UI-A/E — transport badge + decision bundle age surfacing."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_transport_liveness_badge_survives_in_ed_core():
    """The transport-liveness half of this test (a LIVE/STALE badge + age, driven off the
    streaming-health flag) has a real equivalent. Repointed to static/js/ed-core.js (/console
    cutover, operator directive 2026-09-14): setFeed()/paintQuote() paint #hFeedDot/#hFeed/
    #hAge off the same streaming_healthy flag legacy's badge used, just LIVE/DEGRADED rather
    than legacy's SSE LIVE/SSE STALE spelling.

    The Tier-C decision-bundle-age half (data-bundle-freshness, _updateDecisionBundleAgeUI,
    _updateTierCLaneStaleMarkers, data-ed-tier-c/data-lane-stale) has no equivalent — the new
    console's simpler poll model has no Tier-C decision-bundle concept at all (grepped
    static/js/*.js, zero matches for any of these names) — and is not reproduced here."""
    core = (ROOT / "static" / "js" / "ed-core.js").read_text(encoding="utf-8")
    assert "function setFeed(cls, label, age) {" in core
    assert "getElementById('hFeedDot')" in core
    assert "getElementById('hFeed')" in core
    assert "getElementById('hAge')" in core
    assert "feedLabel: healthy ? 'LIVE' : 'DEGRADED'" in core
