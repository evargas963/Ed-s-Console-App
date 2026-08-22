"""RC-462: a narrow-chain flip must not display as a precise institutional number."""
from __future__ import annotations

from math_levels import (
    GAMMA_FLIP_NARROW,
    GAMMA_FLIP_TRUSTED,
    GAMMA_FLIP_UNAVAILABLE,
    displayable_gamma_flip,
    displayable_trusted_level,
)


def test_only_trusted_flip_is_displayable():
    assert displayable_gamma_flip(745.61, GAMMA_FLIP_TRUSTED) == 745.61
    assert displayable_gamma_flip(770.35, GAMMA_FLIP_NARROW) is None
    assert displayable_gamma_flip(770.35, GAMMA_FLIP_UNAVAILABLE) is None
    assert displayable_gamma_flip(None, GAMMA_FLIP_TRUSTED) is None


def test_trusted_level_withholds_narrow_and_unavailable():
    assert displayable_trusted_level(745.0, GAMMA_FLIP_TRUSTED) == 745.0
    assert displayable_trusted_level(740.0, GAMMA_FLIP_NARROW) is None
    assert displayable_trusted_level(740.0, GAMMA_FLIP_UNAVAILABLE) is None
    assert displayable_trusted_level(None, GAMMA_FLIP_TRUSTED) is None


def test_index_and_chart_gate_chain_levels_on_confidence():
    from pathlib import Path
    idx = Path("static/index.html").read_text(encoding="utf-8")
    chart = Path("static/chart.html").read_text(encoding="utf-8")
    assert "function edTrustedChainLevel" in idx
    assert "function edKlLevelValue" in idx
    assert "edTrustedChainLevel(d, 'kl_gamma_pin')" in idx
    assert "function edTrustedTerrainLevel" in chart
    assert "edTrustedTerrainLevel(T, 'call_wall')" in chart
    assert "edTrustedTerrainLevel(T, key)" in chart


def test_index_html_desk_flip_consults_confidence():
    from pathlib import Path
    src = Path("static/index.html").read_text(encoding="utf-8")
    assert "kl_gamma_flip_confidence" in src
    assert src.count("if (c !== 'TRUSTED') return '—'") >= 2
    assert "function edTrustedGammaFlip" in src
    assert src.count("edTrustedGammaFlip(") >= 8
