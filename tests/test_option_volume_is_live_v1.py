"""RC-68 END-TO-END PROOF: session option volume reaches the strikes panel from the LIVE chain.

The operator's question is "is options volume live yet?", and the honest answer must be a
measurement, not an assurance. MEASURED 2026-07-27 11:31 ET before the fix: the panel served a
09:47 morning capture, understating session volume by 281 percent (1,095,874 shown vs 4,176,672
live) with ~500K missing on strike 740 alone.

This drives the REAL chain end to end — compute_terrain -> TerrainSnapshot.per_strike -> the cache
payload shape the endpoint reads — and proves the volume that arrives on the chain is the volume
the panel would render, with no archive anywhere in the path. The input is a captured Schwab SPY
chain (tests/fixtures/), not a hand-built one: a fixture tuned by the same hand that writes the
assertion proves only that the hand is consistent.
"""
from __future__ import annotations

import pytest

import json
from pathlib import Path

from terrain_engine import compute_terrain

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = json.loads(
    (ROOT / "tests" / "fixtures" / "real_spy_0dte_chain.json").read_text(encoding="utf-8")
)
CHAIN: list[dict] = FIXTURE["chain"]
SPOT: float = float(FIXTURE["spot"])



@pytest.fixture(autouse=True)
def _at_capture(pin_clock):
    """Valued at the stored chain's capture (2026-09-22 12:46 ET), so its expiries passing never change
    what this test measures."""
    return pin_clock(2026, 9, 22, 12, 46)

def _expected_volume_by_strike(chain) -> dict[float, int | None]:
    """Ground truth read straight off the vendor payload, independent of the engine: call + put
    as sent (0 is 0), and None for a strike where a contract did not report a volume."""
    out: dict[float, int | None] = {}
    for c in chain:
        k, v = float(c["strikePrice"]), c.get("totalVolume")
        ok = isinstance(v, int) and not isinstance(v, bool) and v >= 0
        out[k] = None if not ok or out.get(k, 0) is None else out.get(k, 0) + v
    return out


def test_live_chain_volume_reaches_the_per_strike_rows():
    """The volume ON THE VENDOR CHAIN is the volume IN THE ROWS — call + put summed per strike."""
    snap = compute_terrain(FIXTURE["ticker"], CHAIN, SPOT)
    assert snap.per_strike, "terrain produced no per-strike rows; the panel would have no source"
    expected = _expected_volume_by_strike(CHAIN)
    got = {r[0]: r[2] for r in snap.per_strike["all"]}
    assert got == expected, f"volume altered in transit: {got} != {expected}"
    assert None not in expected.values() and sum(expected.values()) > 1_000_000, (
        "fixture no longer carries real session volume on every contract")


def test_a_strike_with_an_unreported_volume_has_no_volume_not_a_partial_sum():
    """A contract whose volume Schwab did not send leaves its strike's volume unknown: never the
    other leg's volume, never 0. Stand-in: totalVolume removed from one contract of the real chain."""
    chain = [dict(c) for c in CHAIN]
    gone = next(c for c in chain if c["totalVolume"] > 0)
    del gone["totalVolume"]
    got = {r[0]: r[2] for r in compute_terrain(FIXTURE["ticker"], chain, SPOT).per_strike["all"]}
    assert got[float(gone["strikePrice"])] is None
    assert got == _expected_volume_by_strike(chain)


def test_rows_are_the_shape_the_panel_renders():
    """RC-79: the defect was a SHAPE mismatch at the seam, not a missing source. The endpoint
    served today_source=terrain_live_cache with today_age_sec=7.4 — live and fresh — and ZERO
    rows, because it rebuilt synthetic contracts from these numbers and re-ran the exposure
    engine, which rejected them for having no open interest."""
    ps = compute_terrain(FIXTURE["ticker"], CHAIN, SPOT).per_strike
    # the three GEX scopes, and the Chart view's DEX and OI rows (operator 2026-09-29: those views
    # were blank)
    scopes = ("all", "near", "far", "dex", "oi")
    # beside the rows: each profile's largest strike, the GEX rows' side sums (2026-09-30), and
    # the count of contracts whose settlement cannot be determined (in no row), and why there is
    # no GEX row when there is none (2026-10-01: the panel served a wrong reason)
    assert set(ps) == {*scopes, "peak", "side_sums", "expiry_unknown", "absent_reason"}, (
        "the ALL / <=7DTE / MONTHLY+ chips each need their own rows; a missing scope is an "
        f"empty panel on that chip. got {sorted(ps)}"
    )
    for scope in scopes:
        for r in ps[scope]:
            assert len(r) == (2 if scope in ("dex", "oi") else 3), f"{scope}: row {r} has the wrong shape"
            assert all(isinstance(x, (int, float)) for x in r), f"{scope}: non-numeric row {r}"
    assert ps["all"], "the ALL scope is empty on a real 40-contract chain"
    assert any(r[1] != 0 for r in ps["all"]), "every gamma bar is zero — nothing would render"


def test_absence_renders_as_absence_not_as_stale_data():
    """With no chain there must be no fabricated per-strike data."""
    snap = compute_terrain(FIXTURE["ticker"], [], SPOT)
    assert not (snap.per_strike or {}).get("all")
    assert snap.error
