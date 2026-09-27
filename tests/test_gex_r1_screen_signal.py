"""Unit tests for GEX-R1-SCREEN 0DTE signal + morning full filter.

GEX correctness is proven on a REAL captured chain
(tests/fixtures/real_spy_0dte_chain.json), never a hand-built one.
"""

from __future__ import annotations

import pytest

import json
from pathlib import Path


_REAL_CHAIN = Path(__file__).parent / "fixtures" / "real_spy_0dte_chain.json"



@pytest.fixture(autouse=True)
def _at_capture(pin_clock):
    """Valued at the stored chain's capture (2026-09-22 12:46 ET), so its expiries passing never change
    what this test measures."""
    return pin_clock(2026, 9, 22, 12, 46)

def _load_real_chain() -> tuple[list, float]:
    data = json.loads(_REAL_CHAIN.read_text(encoding="utf-8"))
    return data["chain"], float(data["spot"])
