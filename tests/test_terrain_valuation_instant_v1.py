"""compute_terrain(now=...) prices EVERY book at that one instant -- vanna included."""
from __future__ import annotations

import pytest

import json
from datetime import datetime, timedelta
from pathlib import Path

from terrain_engine import compute_terrain

_FX = Path(__file__).resolve().parent / "fixtures" / "real_tsla_complete_chain_strike_range_all.json"



@pytest.fixture(autouse=True)
def _at_capture(pin_clock):
    """Valued at the stored chain's capture (2026-08-30), so its expiries passing never change
    what this test measures."""
    return pin_clock(2026, 8, 30, 12, 0)

def _real_chain():
    chain = json.loads(_FX.read_text(encoding="utf-8"))["chain"]
    expiry = datetime.fromisoformat(chain[0]["expirationDate"].replace("Z", "+00:00"))
    strikes = sorted(float(c["strikePrice"]) for c in chain)
    return chain, expiry, strikes[len(strikes) // 2]


def test_the_valuation_instant_reaches_the_vanna_book():
    chain, expiry, spot = _real_chain()
    early = compute_terrain("TSLA", chain, spot, now=expiry - timedelta(days=6)).vanna_agg
    late = compute_terrain("TSLA", chain, spot, now=expiry - timedelta(days=1)).vanna_agg
    assert early is not None and late is not None
    assert early != late, "vanna must be priced at the given instant, not the wall clock"
    # a replayed chain is priced at ITS instant, not read as expired (zero vanna) by the wall clock
    assert early["net_vanna_shares_per_volpt"] != 0, early
