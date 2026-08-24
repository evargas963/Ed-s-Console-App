"""Action 12.9: static/index.html must not re-fabricate withheld producer fields.

2026-08-24 audit hardening: the original assertions were exact-substring bans
(e.g. ``"iv_direction || 'flat'" not in INDEX``), which a whitespace or quote-style
reformat could silently defeat while the fabrication itself survived. Every ban is
now a regex tolerant of whitespace and quote style, and a positive-control test
injects each banned pattern (in several spellings) into a copy of the source and
asserts the detector fires — so a dead detector cannot pass silently.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

_Q = r"['\"]"  # either quote style

# Banned fabrication patterns — each defeats a producer's deliberate withhold.
BANNED_PATTERNS: dict[str, re.Pattern[str]] = {
    # `iv_direction || 'flat'` in any spacing/quote style
    "iv_direction_flat_fallback": re.compile(
        rf"iv_direction\s*\|\|\s*{_Q}flat{_Q}"
    ),
    # fusion/prediction/dominant direction defaulted to 'flat'
    "fusion_dominant_direction_flat_fallback": re.compile(
        rf"fusion_dominant_direction\s*\|\|\s*{_Q}flat{_Q}"
    ),
    "prediction_dir_flat_fallback": re.compile(
        rf"prediction_dir\s*\|\|\s*{_Q}flat{_Q}"
    ),
    "dominant_dir_flat_fallback": re.compile(
        rf"dominant_dir\s*\|\|\s*{_Q}flat{_Q}"
    ),
    # stale DIAG fallback: `? Number(d.confluence_total) : 9`
    "confluence_total_ternary_nine": re.compile(
        r"\?\s*Number\s*\(\s*d\.confluence_total\s*\)\s*:\s*9\b"
    ),
    # any `: 9` default within reach of a confluence_total read
    "confluence_total_near_nine_default": re.compile(
        r"confluence_total[\s\S]{0,80}?:\s*9\s*;"
    ),
    # `charm_net || 0` (covers `parseFloat(d.charm_net || 0)` too)
    "charm_net_zero_fallback": re.compile(
        r"charm_net\s*\|\|\s*0\b"
    ),
}

# Positive-control injections: canonical spelling + a reformatted variant that the
# old exact-substring assertions could NOT catch. Every variant must trip its regex.
_CONTROL_SNIPPETS: dict[str, list[str]] = {
    "iv_direction_flat_fallback": [
        "d.iv_direction || 'flat'",
        'd.iv_direction  ||  "flat"',
        "d.iv_direction||'flat'",
    ],
    "fusion_dominant_direction_flat_fallback": [
        "d.fusion_dominant_direction || 'flat'",
        'd.fusion_dominant_direction||"flat"',
    ],
    "prediction_dir_flat_fallback": [
        "d.prediction_dir || 'flat'",
        "d.prediction_dir  ||'flat'",
    ],
    "dominant_dir_flat_fallback": [
        "d.dominant_dir || 'flat'",
        'd.dominant_dir|| "flat"',
    ],
    "confluence_total_ternary_nine": [
        "Number.isFinite(d.confluence_total) ? Number(d.confluence_total) : 9",
        "x ? Number( d.confluence_total ) : 9",
    ],
    "confluence_total_near_nine_default": [
        "const total = d.confluence_total != null ? d.confluence_total : 9;",
    ],
    "charm_net_zero_fallback": [
        "parseFloat(d.charm_net || 0)",
        "parseFloat(d.charm_net||0)",
        "const c = d.charm_net || 0;",
    ],
}


@pytest.mark.parametrize("name", sorted(BANNED_PATTERNS))
def test_index_free_of_banned_fabrication(name: str):
    m = BANNED_PATTERNS[name].search(INDEX)
    assert m is None, (
        f"static/index.html re-fabricates a withheld producer field ({name}): "
        f"{m.group(0)!r}"
    )


@pytest.mark.parametrize("name", sorted(BANNED_PATTERNS))
def test_detector_fires_on_injected_banned_pattern(name: str):
    """Positive control: inject the banned pattern into a copy of the source and
    prove the detector still fires — including reformatted spellings that the old
    exact-substring assertions were blind to."""
    snippets = _CONTROL_SNIPPETS[name]
    assert snippets, f"no positive-control snippets for {name}"
    for snippet in snippets:
        poisoned = INDEX + "\n<script>const poisoned = " + snippet + ";</script>\n"
        assert BANNED_PATTERNS[name].search(poisoned), (
            f"detector {name} is blind to injected variant: {snippet!r}"
        )


def test_index_has_iv_direction_key_helper():
    """The sanctioned helpers (fail-closed direction resolution) must stay present."""
    assert re.search(r"function\s+ivDirectionKey\s*\(\s*d\s*\)", INDEX)
    assert re.search(r"function\s+effectiveDirection\s*\(\s*x\s*\)", INDEX)
