"""The screen says the industry's names (operator 2026-11-22: "everything we do is standardized").

Each name the screen once drew and no longer does, with the name that replaced it, is refused in
every page file and in every table of words the server sends: a name made up here, one vendor's
product name, or a word that states the modelled sign as a fact. The sources of the names in use are
`docs/SOURCES.md`'s (imf-gfsr-2026-04, oic-gamma-flip-2026-06) and each row of
`docs/derived_register.md`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from calc.terrain_engine import OPTION_LEVELS
from calc.terrain_read import FLIP_RELATION_TEXT, REGIME_TEXT, build_terrain_read
from push.confluence import _OPTION_SHORT
from push.strikes import LEVEL_TEXT

pytestmark = pytest.mark.rail

STATIC = Path(__file__).resolve().parent.parent / "static"
#: the replaced name (as drawn, any case), and what the screen says in its place
REPLACED = {
    r"dealer (?:Γ|gamma|regime|net)": "net GEX, gamma regime",
    r"net dealer": "net GEX, net vanna exposure, net charm exposure",
    r"long gamma chop": "Positive gamma",
    r"short gamma trend": "Negative gamma",
    r"Γ flip": "Gamma flip",
    r"Abs Γ": "Largest total gamma strike",
    r"key Δ": "Largest total delta strike",
    r"Δ walls?\b": "Largest call or put delta strike",
    r"charm walls?\b": "Largest call or put charm strike",
    r"Γ peak": "Largest positive or negative net GEX strike",
    r"pin candidate": "Highest open interest strike near price",
    r"\b(?:CΔW|PΔW|CCh|PCh|Net PΓ|Net CΓ)\b": "the level's own words",
}


def _drawn(text: str) -> list[str]:
    """Return every piece of text a page can draw: a quoted string, or an element's text."""
    quoted = re.findall(r"""'([^'\n]*)'|"([^"\n]*)\"""", text)
    return [a or b for a, b in quoted] + re.findall(r">([^<>]+)<", text)


def _served() -> list[str]:
    """Return every word the server's own tables send for these values."""
    words = [label for _key, label in OPTION_LEVELS]
    words += [*_OPTION_SHORT, *_OPTION_SHORT.values(), *LEVEL_TEXT.values(), *REGIME_TEXT.values()]
    words += [w for w in FLIP_RELATION_TEXT.values() if w is not None]
    for gamma in (1.0, -1.0, None):
        words.append(build_terrain_read(spot=750.0, gamma_at_spot=gamma).headline)
    return words


@pytest.mark.parametrize("old", REPLACED)
def test_no_screen_says_a_name_that_was_replaced(old: str) -> None:
    pattern = re.compile(old, re.IGNORECASE)
    drawn = [
        (path.name, piece.strip())
        for path in [*STATIC.glob("*.html"), *STATIC.glob("js/*.js")]
        for piece in _drawn(path.read_text(encoding="utf-8"))
        if pattern.search(piece)
    ]
    served = [word for word in _served() if pattern.search(word)]
    assert drawn == [] and served == [], f"the name is now: {REPLACED[old]}"


def test_the_regime_is_the_industrys_pair() -> None:
    """Positive and negative gamma, with no word about what the price will do."""
    assert [
        REGIME_TEXT[build_terrain_read(spot=750.0, gamma_at_spot=g).regime] for g in (1, -1)
    ] == [
        "Positive gamma",
        "Negative gamma",
    ]
