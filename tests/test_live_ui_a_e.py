"""LIVE-UI-A/E — transport badge + decision bundle age surfacing."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_index_html_live_ui_transport_and_bundle_age():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8", errors="replace")
    assert 'id="ed-transport-badge"' in html
    assert 'id="data-bundle-freshness"' in html
    assert "function _updateEdTransportBadge(" in html
    assert "function _updateDecisionBundleAgeUI(" in html
    assert "function _updateTierCLaneStaleMarkers(" in html
    assert "function _updateLiveUiAe(" in html
    assert "label = 'SSE STALE'" in html
    assert "label = 'SSE LIVE'" in html
    assert "Built <1s ago" in html or "Built ' + ageSec" in html
    assert 'data-ed-tier-c="1"' in html
    assert "data-lane-stale" in html
    assert "sseStale" in html
