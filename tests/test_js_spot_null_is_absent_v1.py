"""A missing spot is ABSENT on every screen, never 0.00.

Audit P0 (2026-09-23): `Number(null)` is 0, which passes `isFinite`, so four screens (chain,
levels, liquidity map, trade desk) drew "spot 0.00" -- and the chain marked the lowest strike
as spot -- whenever the server withheld spot. Every `Number(<...>.spot)` in static/js must sit
on a line that first treats null as absent. Repo-wide scan, fails closed on an empty scan.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_CALL = re.compile(r"Number\(\s*(?:\w+\.)*spot\s*\)")


def test_every_spot_number_conversion_guards_null():
    files = sorted((ROOT / "static" / "js").glob("*.js"))
    assert files, "no JS found -- the scan must not pass vacuously"
    bad = []
    scanned = 0
    for f in files:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("//", 1)[0]
            if not _CALL.search(code):
                continue
            scanned += 1
            if "== null" not in code and "!= null" not in code:
                bad.append(f"{f.name}:{i}: {line.strip()}")
    assert scanned >= 5, f"expected the known spot conversions, found {scanned}"
    assert not bad, "Number(spot) without a null guard draws 0.00:\n" + "\n".join(bad)
