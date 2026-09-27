"""A test that loads a stored Schwab chain pins the clock (tests/conftest.py pin_clock) to before
the chain's expiries. MEASURED 2026-09-27: six tests had passed since mid-September by comparing
None with None -- their chains expired, the greeks read the real clock, and every compared value
went empty on both sides. This check fails any test that loads a stored chain without a pin."""
from __future__ import annotations

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
PINNED = re.compile(r"pin_clock|setattr\(\s*time_et\s*,\s*[\"']now_et")


def _chain_fixtures() -> list[str]:
    names = [p.name for p in (TESTS / "fixtures").glob("*.json")
             if "expirationDate" in p.read_text(encoding="utf-8")]
    assert names, "no stored chains found -- the check would pass on nothing"
    return names


def test_every_test_that_loads_a_stored_chain_pins_the_clock():
    chains = _chain_fixtures()
    loaders = 0
    offenders = []
    for p in sorted(TESTS.glob("test_*.py")):
        if p.name == Path(__file__).name:
            continue
        s = p.read_text(encoding="utf-8", errors="ignore")
        if any(c in s for c in chains):
            loaders += 1
            if not PINNED.search(s):
                offenders.append(p.name)
    assert loaders > 10, "the scan found too few chain tests -- it is not looking"
    assert not offenders, f"load a stored chain without pinning the clock: {offenders}"
