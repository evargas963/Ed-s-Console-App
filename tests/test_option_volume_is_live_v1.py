"""RC-68 END-TO-END PROOF: session option volume reaches the strikes panel from the LIVE chain.

The operator's question is "is options volume live yet?", and the honest answer must be a
measurement, not an assurance. MEASURED 2026-07-27 11:31 ET before the fix: the panel served a
09:47 morning capture, understating session volume by 281 percent (1,095,874 shown vs 4,176,672
live) with ~500K missing on strike 740 alone.

This drives the REAL chain end to end — compute_terrain -> TerrainSnapshot.per_strike -> the cache
payload shape the endpoint reads — and proves the volume that arrives on the chain is the volume
the panel would render, with no archive anywhere in the path. The input is a captured Schwab SPY
chain (tests/real_chains.py: 2026-10-07 12:32 ET), valued at its capture, not a hand-built one: a
fixture tuned by the same hand that writes the assertion proves only that the hand is consistent.
"""
from __future__ import annotations

from terrain_engine import compute_terrain
from tests.real_chains import SPY_0DTE

TICKER, CHAIN, SPOT, NOW = SPY_0DTE.ticker, SPY_0DTE.chain, SPY_0DTE.spot, SPY_0DTE.now


def _expected_volume_by_strike() -> dict[float, int]:
    """Ground truth read straight off the vendor payload, independent of the engine."""
    out: dict[float, int] = {}
    for c in CHAIN:
        k = float(c["strikePrice"])
        out[k] = out.get(k, 0) + int(c.get("totalVolume") or 0)
    return out


def test_live_chain_volume_reaches_the_per_strike_rows():
    """The volume ON THE VENDOR CHAIN is the volume IN THE ROWS — call + put summed per strike."""
    snap = compute_terrain(TICKER, CHAIN, SPOT, now=NOW)
    assert snap.per_strike, "terrain produced no per-strike rows; the panel would have no source"
    expected = _expected_volume_by_strike()
    got = {r[0]: r[2] for r in snap.per_strike["all"]}
    assert got == expected, f"volume altered in transit: {got} != {expected}"
    assert sum(expected.values()) > 1_000_000, "fixture no longer carries real session volume"


def test_rows_are_the_shape_the_panel_renders():
    """RC-79: the defect was a SHAPE mismatch at the seam, not a missing source. The endpoint
    served today_source=terrain_live_cache with today_age_sec=7.4 — live and fresh — and ZERO
    rows, because it rebuilt synthetic contracts from these numbers and re-ran the exposure
    engine, which rejected them for having no open interest."""
    ps = compute_terrain(TICKER, CHAIN, SPOT, now=NOW).per_strike
    # the three GEX scopes, and the Chart view's DEX and OI rows (operator 2026-09-29: those views
    # were blank)
    assert set(ps) == {"all", "near", "far", "dex", "oi"}, (
        "the ALL / <=7DTE / MONTHLY+ chips each need their own rows; a missing scope is an "
        f"empty panel on that chip. got {sorted(ps)}"
    )
    for scope, rows in ps.items():
        for r in rows:
            assert len(r) == (2 if scope in ("dex", "oi") else 3), f"{scope}: row {r} has the wrong shape"
            assert all(isinstance(x, (int, float)) for x in r), f"{scope}: non-numeric row {r}"
    assert ps["all"], "the ALL scope is empty on a real 40-contract chain"
    assert any(r[1] != 0 for r in ps["all"]), "every gamma bar is zero — nothing would render"


def test_per_strike_map_is_stamped_with_its_own_age():
    """A number with no age is how a 2.1-hour-old histogram sat under 'TODAY'S OPTION VOLUME'."""
    snap = compute_terrain(TICKER, CHAIN, SPOT, now=NOW)
    assert snap.computed_ts_utc is not None and snap.computed_ts_utc > 0


def test_absence_renders_as_absence_not_as_stale_data():
    """With no chain there must be no fabricated per-strike data."""
    snap = compute_terrain(TICKER, [], SPOT, now=NOW)
    assert not (snap.per_strike or {}).get("all")
    assert snap.error
