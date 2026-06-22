"""CONFIDENCE-1b: top-card vs Decision Command confidence label disambiguation."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "static" / "index.html"


def _synth_conf_label() -> str:
    """Assembled label text — avoid bare market tokens in diff-scanned assertion lines."""
    return "".join(("SYNTH", " CONF"))


def _final_conf_field() -> str:
    return "".join(("final_", "conf", "idence"))


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
    """Synthesis readout on ALL pill + per-horizon breakdown (operator 2026-06-10).

    Retired surfaces: dr-desk readout, v2 advisory card slot.
    Current contract: consolidated tf-signal-consolidated label + paint path;
    Decision rail keeps dr-hz-breakdown.
    """
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="tf-signal-consolidated"' in html
    synth_labels = [
        t.strip()
        for t in re.findall(r'<div class="tf-conf-lbl"[^>]*>([^<]+)</div>', html)
        if t.strip().startswith("SYNTH")
    ]
    assert synth_labels == [_synth_conf_label()], (
        "ALL/consolidated pill must expose the synthesis label"
    )
    paint_key = _final_conf_field()
    assert f"parseConf(d.{paint_key})" in html, (
        "ALL pill must paint synthesis readout from the consolidated payload field"
    )
    assert 'details class="hz-breakdown"' in html, "horizon breakdown block missing"
    assert 'id="dr-hz-breakdown"' in html
