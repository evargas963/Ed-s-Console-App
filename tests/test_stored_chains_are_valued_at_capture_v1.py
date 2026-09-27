"""A test that loads a stored Schwab chain pins the clock (tests/conftest.py pin_clock) to before
the chain's expiries. MEASURED 2026-09-27: six tests had passed since mid-September by comparing
None with None -- their chains expired, the greeks read the real clock, and every compared value
went empty on both sides. This check fails any test that loads a stored chain without a pin."""
from __future__ import annotations

import re
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PINNED = re.compile(r"pin_clock|setattr\(\s*time_et\s*,\s*[\"']now_et")


def _chain_fixtures() -> list[str]:
    names = [p.name for p in FIXTURES.glob("*.json")
             if "expirationDate" in p.read_text(encoding="utf-8")]
    assert names, "no stored chains found -- the check would pass on nothing"
    return names


def test_every_test_that_loads_a_stored_chain_pins_the_clock(repo_index):
    chains = _chain_fixtures()
    loaders, offenders = 0, []
    for rel, text, _tree in repo_index.items():
        path = rel.as_posix()
        if not (path.startswith("tests/test_") and path.endswith(".py")):
            continue
        if path.endswith(Path(__file__).name):
            continue
        if any(c in text for c in chains):
            loaders += 1
            if not PINNED.search(text):
                offenders.append(path)
    assert loaders > 10, "the scan found too few chain tests -- it is not looking"
    assert not offenders, f"load a stored chain without pinning the clock: {offenders}"
