"""CONFIDENCE-1b: top-card vs Decision Command confidence label disambiguation."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "static" / "index.html"


def test_top_card_horizon_conf_labels():
    html = INDEX.read_text(encoding="utf-8")
    labels = re.findall(
        r'<div class="tf-conf-lbl"[^>]*>([^<]+)</div>',
        html,
    )
    horizon = [t for t in labels if "HORIZON" in t.upper()]
    assert len(horizon) == 4, f"expected 4 HORIZON CONF labels, got {horizon!r}"
    assert all(t.strip() == "HORIZON CONF" for t in horizon)


def test_no_ambiguous_confidence_literal_in_tf_conf_lbl():
    html = INDEX.read_text(encoding="utf-8")
    assert '>CONFIDENCE<' not in html


def test_decision_command_uses_disambiguated_addkv_labels():
    html = INDEX.read_text(encoding="utf-8")
    assert "addKV(grid, 'Confidence'," not in html
    assert "addKV(grid, 'Fused Confidence'," in html
    assert "addKV(grid, 'Horizon Confidence'," in html
    assert "const confLabel = isFused ? 'Fused Confidence' : 'Horizon Confidence';" not in html


def test_track2_desk_confidence_headline_and_breakdown():
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="dr-desk-confidence"' in html
    assert "deskConf.textContent = 'UNAVAILABLE'" in html
    assert 'details class="hz-breakdown"' in html
    assert 'id="v2-confidence"' in html
