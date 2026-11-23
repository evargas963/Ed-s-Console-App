"""The screen says the industry's names (operator 2026-11-22: "everything we do is standardized").

Each name the screen once drew and no longer does, with the name that replaced it, is refused in
every page file and in every panel as the server serves it on captured Schwab data (the browser
tests' panels, each kept equal to the program's answer by its own test): a name made up here, one
vendor's product name or trademark, a word that is another thing's name, or a word that states the
modelled sign as a fact. The sources of the names in use are `docs/SOURCES.md`'s (imf-gfsr-2026-04,
oic-gamma-flip-2026-06, cartea-2018, osler-2000, finra-extended-hours, Schwab's own guides) and each
row of `docs/derived_register.md`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.rail

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
#: panels as the server answered them on Schwab's captured data
SERVED = (
    "tests/e2e/fixtures/panels_spy_two_day.json",
    "tests/e2e/fixtures/panels_amzn_two_day.json",
    "tests/e2e/fixtures/vanna_charm_panels_crwd.json",
    "tests/e2e/fixtures/liquidity_readout_live.json",
    "tests/fixtures/real_mrvl_confluence_payloads_2026_10_07.json",
)
#: the replaced name (as drawn, any case), and what the screen says in its place
REPLACED = {
    r"dealer (?:Γ|gamma|regime|net)": "net GEX, gamma regime",
    r"net dealer": "net GEX, net vanna exposure, net charm exposure",
    r"gamma chop|gamma trend": "Positive gamma, Negative gamma",
    r"Γ flip": "Gamma flip",
    r"Abs Γ": "Largest total gamma strike",
    r"key Δ": "Largest total delta strike",
    r"Δ walls?\b": "Largest call or put delta strike",
    r"charm walls?\b": "Largest call or put charm strike",
    r"Γ peak": "Largest positive or negative net GEX strike",
    r"pin candidate": "Highest open interest strike near price",
    r"\b(?:CΔW|PΔW|CCh|PCh|Net PΓ|Net CΓ)\b": "the level's own words",
    r"market map": "Price Chart (MARKETMAP is a registered mark)",
    r"bookmap panel": "Order Book Heatmap (BOOKMAP is a registered mark)",
    r"options book": "Options Level II",
    r"book (?:/|·) dom|book/dom": "Level II",
    r"dot map": "Bubbles",
    r"multi-map": "Small Multiples",
    r"attention queue": "Alerts",
    r"cross-domain": "Readings",
    r"data trust|system / trust": "Data status, System",
    r"liquidity map|liquidity levels": "Support and Resistance Zones, Reference Levels",
    r"options flow": "Options Time & Sales, Contract Order Flow",
    r"contract structures": "Contract Specifications",
    r"\b(?:bid|offer) heavy\b": "BUY-HEAVY, SELL-HEAVY",
    r"at the touch": "TOP OF BOOK",
    r"gold composite|^composite:|· composite,": "Aggregate",
    r">microprice": "weighted mid",
    r"cum Δ|cvd / cum_delta": "Cumulative volume delta (est.)",
    r"tape pressure": "Trade imbalance (est.)",
    r"top-book pressure": "Queue imbalance",
    r"overnight (?:high|low)|\bON[HL]\b": "Extended-hours high, low",
    r"\bp(?:POC|VAH|VAL)\b": "Prior POC, VAH, VAL",
    r"pivot / value": "Price inside zone",
    r"confluence-scored|, confluence |\(confluence ": "levels in zone",
    r"\btouches\b|\bhow often each level held\b": "hits, bounce frequency",
    r"\bIV%": "IV (%)",
}


def _drawn(text: str) -> list[str]:
    """Return every piece of text a page can draw: a quoted string, or an element's text."""
    quoted = re.findall(r"""'([^'\n]*)'|"([^"\n]*)\"""", text)
    return [a or b for a, b in quoted] + re.findall(r">([^<>]+)<", text)


def _words(value: Any) -> list[str]:
    """Return every string in a served panel."""
    if isinstance(value, dict):
        return [w for v in value.values() for w in _words(v)]
    if isinstance(value, list):
        return [w for v in value for w in _words(v)]
    return [value] if isinstance(value, str) else []


def _panels(name: str) -> Any:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("old", REPLACED)
def test_no_screen_says_a_name_that_was_replaced(old: str) -> None:
    pattern = re.compile(old, re.IGNORECASE)
    drawn = [
        (path.name, piece.strip())
        for path in [*STATIC.glob("*.html"), *STATIC.glob("js/*.js")]
        for piece in _drawn(path.read_text(encoding="utf-8"))
        if pattern.search(piece)
    ]
    served = [(name, w) for name in SERVED for w in _words(_panels(name)) if pattern.search(w)]
    assert drawn == [] and served == [], f"the name is now: {REPLACED[old]}"


@pytest.mark.parametrize(
    ("name", "words"),
    [(SERVED[0], "Negative gamma"), (SERVED[1], "Positive gamma")],
)
def test_the_regime_is_the_industrys_pair(name: str, words: str) -> None:
    """SPY's net GEX at the price is negative that day and AMZN's positive."""
    assert _panels(name)["terrain"]["regime_text"] == words


@pytest.mark.parametrize("name", SERVED[:2])
def test_a_zones_levels_are_drawn_by_name_never_by_code(name: str) -> None:
    """The zones list drew raw codes (OVERNIGHT_HIGH, ABS_GAMMA)."""
    levels = [s for z in _panels(name)["liquidity"]["zones"] for s in z["source_levels"]]
    assert levels and not [s["label"] for s in levels if "_" in s["label"]]
