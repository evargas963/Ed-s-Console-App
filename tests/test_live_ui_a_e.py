"""LIVE-UI-A/E — transport badge + decision bundle age surfacing."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_transport_liveness_badge_survives_in_ed_core():
    """The header badge names LAST_PRICE observation state (SPOT LIVE / SPOT STALE /
    UNAVAILABLE), not whole-screen streaming health. Repointed to static/js/ed-core.js.

    The Tier-C decision-bundle-age half (data-bundle-freshness, _updateDecisionBundleAgeUI,
    _updateTierCLaneStaleMarkers, data-ed-tier-c/data-lane-stale) has no equivalent — the new
    console's simpler poll model has no Tier-C decision-bundle concept at all (grepped
    static/js/*.js, zero matches for any of these names) — and is not reproduced here."""
    core = (ROOT / "static" / "js" / "ed-core.js").read_text(encoding="utf-8")
    assert "function setFeed(cls, label, age) {" in core
    assert "getElementById('hFeedDot')" in core
    assert "getElementById('hFeed')" in core
    assert "getElementById('hAge')" in core
    assert "feedLabel:" in core
    assert "'SPOT LIVE'" in core
    assert "'SPOT STALE'" in core
    assert "'UNAVAILABLE'" in core
    assert "streaming_healthy" not in core.split("function paintQuote")[1].split("function liveTick")[0]
