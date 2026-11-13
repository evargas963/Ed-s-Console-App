"""A page prints an option level under the name the one list gives it.

`terrain_engine.OPTION_LEVELS` holds each level's key and its one name. Every page file is read
as text: a name a page types for a level is that level's name in the list, letter for letter.
"""

from __future__ import annotations

import re
from pathlib import Path

from terrain_engine import OPTION_LEVELS

STATIC = Path(__file__).resolve().parent.parent / "static"
NAMES = dict(OPTION_LEVELS)
LOOSE = {"Γ": "(?:Γ|γ|gamma)", "Δ": "(?:Δ|δ|delta)", " ": "[ -]?"}
#: Where a page types a name beside the key of the value it prints: (name, key) or (key, name).
NAME_THEN_KEY = (
    r"\['([^']+)'[^\],]*, num\(d\.(\w+)\)",
    r"row\('([^']+)', num\(t\.(\w+)",
)
KEY_THEN_NAME = (
    r"\b(\w+): '([^']+)'",
    r"\b(\w+): \['([^']+)', P\.",
    r"id: '(\w+)', price: [^,]+, label: '([^']+)'",
)


def _pages() -> dict[str, str]:
    files = [*STATIC.glob("*.html"), *STATIC.glob("js/*.js")]
    return {path.name: path.read_text(encoding="utf-8") for path in files}


def _typed(text: str) -> list[str]:
    """Every whole piece of text a page types: a quoted string, or an element's text."""
    return re.findall(r"'([^'\n]*)'", text) + re.findall(r">([^<>\n]+)<", text)


def test_a_level_name_a_page_types_is_the_lists_letter_for_letter():
    loose = {
        name: re.compile("".join(LOOSE.get(ch, re.escape(ch)) for ch in name), re.IGNORECASE)
        for name in NAMES.values()
    }
    seen, wrong = set(), []
    for page, text in _pages().items():
        for typed in _typed(text):
            for name, pattern in loose.items():
                if pattern.fullmatch(typed.strip()):
                    seen.add(name)
                    if typed.strip() != name:
                        wrong.append((page, typed, name))
    assert seen, "no level name found in any page"
    assert wrong == []


def test_a_name_typed_beside_a_levels_key_is_that_levels_name():
    pairs = []
    for page, text in _pages().items():
        for pattern in NAME_THEN_KEY:
            hits = re.findall(pattern, text)
            pairs += [(page, key, name) for name, key in hits]
        for pattern in KEY_THEN_NAME:
            pairs += [(page, key, name) for key, name in re.findall(pattern, text)]
    levels = [pair for pair in pairs if pair[1] in NAMES]
    assert {pair[0] for pair in levels} >= {
        "ed-gamma-chart.js",
        "ed-trade-desk.js",
        "ed-trade-desk-map.js",
    }
    assert [pair for pair in levels if pair[2] != NAMES[pair[1]]] == []


def test_the_key_levels_card_names_each_row_by_the_level_it_prints():
    pages = _pages()
    printed = dict(re.findall(r"txt\('(kl\w+)', px\(d\.(\w+)\)\)", pages["ed-gamma-panels.js"]))
    rows = dict(
        (cell, name)
        for name, cell in re.findall(
            r'<span class="k">([^<]+)</span><span class="v" id="(kl\w+)">', pages["index.html"]
        )
    )
    card = {printed[cell]: rows[cell] for cell in printed if printed[cell] in NAMES}
    assert len(card) == len([cell for cell in printed if printed[cell] in NAMES]) > 0
    assert card == {key: NAMES[key] for key in card}
