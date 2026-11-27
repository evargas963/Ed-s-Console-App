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

from calc.terrain_engine import compute_terrain
from option_contract import read_chain
from tests.real_chains import SPY_0DTE
from time_et import sessions

TICKER, CHAIN, SPOT, NOW = SPY_0DTE.ticker, SPY_0DTE.chain, SPY_0DTE.spot, SPY_0DTE.now


def _expected_volume_by_strike() -> dict[float, int]:
    """Ground truth read straight off the vendor payload, independent of the engine."""
    out: dict[float, int] = {}
    for c in CHAIN:
        k = float(c["strikePrice"])
        out[k] = out.get(k, 0) + int(c["totalVolume"])  # every contract here sent its volume
    return out


def test_live_chain_volume_reaches_the_per_strike_rows():
    """The volume ON THE VENDOR CHAIN is the volume IN THE ROWS — call + put summed per strike."""
    snap = compute_terrain(TICKER, read_chain(CHAIN), SPOT, now=NOW, sessions=sessions())
    assert snap.per_strike, "terrain produced no per-strike rows; the panel would have no source"
    expected = _expected_volume_by_strike()
    got = {r[0]: r[2] for r in snap.per_strike["gex"]}
    assert got == expected, f"volume altered in transit: {got} != {expected}"
    assert sum(expected.values()) > 1_000_000, "fixture no longer carries real session volume"


def test_rows_are_the_shape_the_panel_renders():
    """The per-strike rows are the producer's own, in the shape the panel renders.

    Never rebuilt from these numbers into contracts and run through the exposure engine again.
    """
    ps = compute_terrain(TICKER, read_chain(CHAIN), SPOT, now=NOW, sessions=sessions()).per_strike
    # the whole book's GEX, the Chart view's DEX and OI rows and the Vanna and Charm panels' rows,
    # its count of settled contracts, and each listed expiry's own, the rows a chosen expiry shows
    assert set(ps) == {"gex", "dex", "oi", "vanna", "charm", "settled", "by_expiry"}, (
        f"each book needs its rows; a missing one is an empty panel. got {sorted(ps)}"
    )
    books = {"all": ps, **ps["by_expiry"]}
    for book, view in books.items():
        assert view["settled"] == 0, f"{book}: a live chain has no settled contract"
        for scope in ("gex", "dex", "oi", "vanna", "charm"):
            for r in view[scope]:
                assert len(r) == (2 if scope in ("dex", "oi", "vanna", "charm") else 3), (
                    f"{book} {scope}: row {r} has the wrong shape"
                )
                assert all(isinstance(x, (int, float)) for x in r), (
                    f"{book} {scope}: non-numeric row {r}"
                )
    assert ps["gex"], "the whole book is empty on a real 40-contract chain"
    assert any(r[1] != 0 for r in ps["gex"]), "every gamma bar is zero — nothing would render"


def test_absence_renders_as_absence_not_as_stale_data():
    """With no chain there must be no fabricated per-strike data."""
    snap = compute_terrain(TICKER, [], SPOT, now=NOW, sessions=sessions())
    assert not snap.per_strike["gex"] and not snap.per_strike["by_expiry"]
    assert snap.error
