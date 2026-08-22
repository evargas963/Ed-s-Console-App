"""RC-462: a narrow-chain flip must not display as a precise institutional number."""
from __future__ import annotations

from math_levels import (
    GAMMA_FLIP_NARROW,
    GAMMA_FLIP_TRUSTED,
    GAMMA_FLIP_UNAVAILABLE,
    displayable_gamma_flip,
)


def test_only_trusted_flip_is_displayable():
    assert displayable_gamma_flip(745.61, GAMMA_FLIP_TRUSTED) == 745.61
    assert displayable_gamma_flip(770.35, GAMMA_FLIP_NARROW) is None
    assert displayable_gamma_flip(770.35, GAMMA_FLIP_UNAVAILABLE) is None
    assert displayable_gamma_flip(None, GAMMA_FLIP_TRUSTED) is None


def test_index_html_desk_flip_consults_confidence():
    from pathlib import Path
    src = Path("static/index.html").read_text(encoding="utf-8")
    assert "kl_gamma_flip_confidence" in src
    assert src.count("if (c !== 'TRUSTED') return '—'") >= 2
    assert "function edTrustedGammaFlip" in src
    assert src.count("edTrustedGammaFlip(") >= 8
