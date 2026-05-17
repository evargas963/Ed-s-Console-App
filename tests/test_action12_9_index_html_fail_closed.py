"""Action 12.9: static/index.html must not re-fabricate withheld producer fields."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")


def test_index_no_iv_direction_flat_fallback():
    assert "iv_direction || 'flat'" not in INDEX
    assert 'iv_direction || "flat"' not in INDEX


def test_index_no_fusion_direction_flat_fallback():
    assert "fusion_dominant_direction || 'flat'" not in INDEX
    assert "prediction_dir || 'flat'" not in INDEX
    assert "dominant_dir || 'flat'" not in INDEX


def test_index_no_confluence_total_nine_fallback():
    assert ": 9;" not in INDEX or "confluence_total" not in INDEX.split(": 9;")[0][-80:]
    # Explicit stale DIAG fallback removed
    assert "? Number(d.confluence_total) : 9" not in INDEX


def test_index_no_charm_net_zero_parse_fallback():
    assert "charm_net || 0" not in INDEX
    assert "parseFloat(d.charm_net || 0)" not in INDEX


def test_index_has_iv_direction_key_helper():
    assert "function ivDirectionKey(d)" in INDEX
    assert "function effectiveDirection(x)" in INDEX
