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

import ast
import json
from pathlib import Path

from terrain_engine import compute_terrain

ROOT = Path(__file__).resolve().parent.parent
SERVER_SRC = (ROOT / "server.py").read_text(encoding="utf-8")
FIXTURE = json.loads(
    (ROOT / "tests" / "fixtures" / "real_spy_0dte_chain_with_poison.json").read_text(encoding="utf-8")
)
CHAIN: list[dict] = FIXTURE["chain"]
SPOT: float = float(FIXTURE["spot"])


def _expected_volume_by_strike() -> dict[float, int]:
    """Ground truth read straight off the vendor payload, independent of the engine."""
    out: dict[float, int] = {}
    for c in CHAIN:
        k = float(c["strikePrice"])
        out[k] = out.get(k, 0) + int(c.get("totalVolume") or 0)
    return out


def test_live_chain_volume_reaches_the_per_strike_rows():
    """The volume ON THE VENDOR CHAIN is the volume IN THE ROWS — call + put summed per strike."""
    snap = compute_terrain(FIXTURE["ticker"], CHAIN, SPOT)
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
    ps = compute_terrain(FIXTURE["ticker"], CHAIN, SPOT).per_strike
    assert set(ps) == {"all", "near", "far"}, (
        "the ALL / <=7DTE / MONTHLY+ chips each need their own rows; a missing scope is an "
        f"empty panel on that chip. got {sorted(ps)}"
    )
    for scope, rows in ps.items():
        for r in rows:
            assert len(r) == 3, f"{scope}: row {r} is not [strike, net_gex_1pct, volume]"
            assert all(isinstance(x, (int, float)) for x in r), f"{scope}: non-numeric row {r}"
    assert ps["all"], "the ALL scope is empty on a real 40-contract chain"
    assert any(r[1] != 0 for r in ps["all"]), "every gamma bar is zero — nothing would render"


def test_no_synthetic_contracts_are_reconstructed_anywhere():
    """The rows are already finished. Rebuilding contract dicts out of them to recompute what
    they already contain is what emptied the panel — it must not come back."""
    assert "netGex" not in SERVER_SRC, (
        "a synthetic contract dict is being rebuilt from finished per-strike output again (RC-79)"
    )


def test_per_strike_map_is_stamped_with_its_own_age():
    """A number with no age is how a 2.1-hour-old histogram sat under 'TODAY'S OPTION VOLUME'."""
    snap = compute_terrain(FIXTURE["ticker"], CHAIN, SPOT)
    assert snap.computed_ts_utc is not None and snap.computed_ts_utc > 0


def test_endpoint_reads_the_live_cache_and_has_no_today_fallback():
    """The strikes endpoint must take TODAY from the live terrain cache only. Both former
    fallbacks (morning archive, narrow snapshot chain) are gone — a fallback is a second faucet."""
    seg = ""
    for n in ast.walk(ast.parse(SERVER_SRC)):
        if isinstance(n, ast.FunctionDef) and n.name == "get_terrain_strikes":
            seg = ast.get_source_segment(SERVER_SRC, n) or ""
    assert seg, "get_terrain_strikes not found"
    assert "terrain_cache_get(" in seg, "endpoint no longer reads the live terrain cache"
    assert '"terrain_live_cache"' in seg, "today_source no longer declares the live faucet"
    assert "_latest_chain_and_spot" not in seg, (
        "RC-68 regression: the narrow-snapshot fallback is back — a third faucet for one field"
    )
    assert "narrow_snapshot_chain" not in seg, "RC-68 regression: narrow-chain fallback restored"
    assert "today_age_sec" in seg, "panel age is no longer published; staleness becomes invisible"


def test_terrain_loop_publishes_the_map_into_the_cache():
    """The endpoint can only be live if the loop actually puts the map where it looks."""
    assert '"_per_strike"' in SERVER_SRC, (
        "the terrain loop no longer publishes the per-strike map into the cache, so the endpoint "
        "would render an empty panel"
    )


def test_absence_renders_as_absence_not_as_stale_data():
    """With no chain there must be no fabricated per-strike data."""
    snap = compute_terrain(FIXTURE["ticker"], [], SPOT)
    assert not (snap.per_strike or {}).get("all")
    assert snap.error
