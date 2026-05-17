from __future__ import annotations

from pathlib import Path


def _html() -> str:
    p = Path(__file__).resolve().parent.parent / "static" / "index.html"
    return p.read_text(encoding="utf-8", errors="replace")


def test_the_call_card_title_present():
    h = _html()
    assert "THE CALL" in h


def test_mhap_card_present_with_required_columns():
    h = _html()
    assert "Horizon alignment" in h
    assert "renderMultiHorizon" in h
    for el_id in ("dr-align-1m", "dr-align-5m", "dr-align-15m", "dr-align-60m"):
        assert el_id in h


def test_mhap_fixed_row_order_in_renderer():
    h = _html()
    assert "const fixed = ['1c','5c','15c','60c']" in h


def test_entry_state_labels_render_contract():
    h = _html()
    for s in ("mh-call-entry", "entry_display_text", "renderMultiHorizon"):
        assert s in h
