"""The Trade Desk's positioning migration is computed once, on the server.

The producer is terrain_engine.positioning_migration, from two real days of Schwab's PCG chain
(tests/fixtures, captured 2026-09-24 and 2026-09-25), each valued at its capture. Expected values
are worked out here from the rows themselves (question 3: a calculation Schwab does not send,
against its definition).
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

import server
import time_et
from calibration.complete_chain_capture import CAPTURE_BASIS, last_capture_per_day
from option_contract import read_chain
from terrain_engine import MIGRATION_DRIFT_STRIKES, compute_terrain, positioning_migration
from tests.capture_store import store_capture

#: the strikes panel's window as the page asks it: Auto, following the price
_AUTO = {"scope": "auto", "centre": None, "shift": 0}
_FX = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "real_pcg_two_day_chain.json").read_text(
        encoding="utf-8"
    )
)


@pytest.fixture
def two_days():
    rows = []
    for day in _FX["days"]:
        snap = compute_terrain(
            "PCG",
            read_chain(day["contracts"]),
            day["spot"],
            now=datetime.fromtimestamp(day["ts_utc"], time_et.ET),
        )
        rows.append((snap.per_strike, snap))
    return rows


def test_the_migration_matches_the_two_days_rows(two_days):
    (prior, _), (today, snap) = two_days
    m = positioning_migration(today["all"], prior["all"], snap.call_wall, snap.put_wall)
    prior_gex = {r[0]: r[1] for r in prior["all"]}
    changes = {
        r[0]: r[1] - prior_gex[r[0]]
        for r in today["all"]
        if r[1] is not None and prior_gex.get(r[0]) is not None
    }
    assert m["compared"] and len(changes) > 10
    assert {r[0]: r[3] for r in m["rows"] if r[3] is not None} == pytest.approx(changes)
    assert (
        m["grew"]
        == [k for k, _ in sorted(changes.items(), key=lambda kv: -kv[1]) if changes[k] > 0][:2]
    )

    # the weighted positive-gamma strike, each day, over strikes known on both days
    def wmean(day_gex):
        pos = [(k, day_gex[k]) for k in changes if day_gex[k] > 0]
        return sum(k * g for k, g in pos) / sum(g for _k, g in pos) if pos else None

    today_gex = {r[0]: r[1] for r in today["all"]}
    wt, wp = wmean(today_gex), wmean(prior_gex)
    assert wt is not None and wp is not None
    d = wt - wp
    assert m["drift"] == (
        "UP" if d > MIGRATION_DRIFT_STRIKES else "DOWN" if -d > MIGRATION_DRIFT_STRIKES else "FLAT"
    )


def test_busiest_strikes_and_volume_total_come_from_schwabs_volume(two_days):
    (_prior, _), (today, snap) = two_days
    m = positioning_migration(today["all"], [], snap.call_wall, snap.put_wall)
    vols = {r[0]: r[2] for r in today["all"] if r[2]}
    assert m["busiest"] == sorted(sorted(vols, key=lambda k: -vols[k])[:2])
    assert m["volume_total"] == sum(r[2] for r in today["all"] if r[2] is not None)
    assert not m["compared"] and m["drift"] is None  # no prior day: nothing to compare


def _prior_gex(body: dict) -> dict:
    """Return the prior day's net GEX the migration compared, by strike."""
    return {r[0]: r[2] for r in body["migration"]["all"]["rows"] if r[2] is not None}


def _gex(per_strike: dict) -> dict:
    """Return a day's own net GEX by strike, from its per-strike rows."""
    return {r[0]: r[1] for r in per_strike["all"] if r[1] is not None}


def test_on_a_closed_market_the_prior_day_is_the_day_before_the_chains_own(two_days):
    """On a weekend the terrain holds the newest capture (Friday).

    The prior day was picked by the wall clock's date, so it was that same Friday capture: every
    change 0, served as `compared` (2026-09-27). It is the capture before the day of the chain the
    rows came from; and a new market day's first chain makes Friday's capture the prior day. Real
    PCG chains, stored as the daemon writes them in the console's database. STAND-IN (named):
    Monday's chain and its spot, Friday's capture's.
    """
    db = server.get_db().db_path
    for day in _FX["days"]:
        by_exp: dict = {}
        for c in day["contracts"]:
            by_exp.setdefault(str(c.get("expirationDate") or "")[:10], []).append(c)
        for exp, cs in by_exp.items():
            store_capture(
                db,
                ticker="PCG",
                expiry=exp,
                contracts=cs,
                spot=day["spot"],
                chain_spot=day["spot"],
                completeness_basis=CAPTURE_BASIS,
                ts_utc=day["ts_utc"],
            )
    stored = last_capture_per_day(db, "PCG", 2)  # the startup load's one read
    newest = stored[0]
    try:
        # startup on a closed market (Sunday 2026-09-27): the levels producer prices the newest
        # capture (Friday) and, with it, the prior day's rows the route serves
        assert (
            server._publish_levels(
                "PCG", captures=stored, now=datetime(2026, 9, 27, 12, 0, tzinfo=time_et.ET)
            )
            is not None
        )
        body = server.strikes("PCG", time_et.now(), _AUTO)
        # a new market day's first chain (Monday 2026-09-28 10:00 ET), before that day's first
        # capture: the prior day is recomputed against the new day
        monday = datetime(2026, 9, 28, 10, 0, tzinfo=time_et.ET)
        server._publish_levels(
            "PCG",
            newest["contracts"],
            monday.timestamp(),
            chain_spot=(newest["spot"], monday.timestamp()),
            now=monday,
        )
        monday_prior = server.published_levels("PCG").prior_strikes
        monday_migration = server.strikes("PCG", monday.timestamp(), _AUTO)["migration"]["all"]
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop("PCG", None)
    (thursday, _), (friday, _) = two_days  # the captures of 2026-09-24 and 2026-09-25
    assert _prior_gex(body) == pytest.approx(_gex(thursday))
    m = body["migration"]["all"]
    assert (
        m["compared"] and sum(1 for r in m["rows"] if r[3]) > 10
    )  # real changes, not self vs self
    # the migration panel's one scale: the largest |GEX| today or the prior day among the strikes
    # drawn (every today bar too, whether or not the prior day lists its strike)
    drawn = {r[0] for r in body["today"]["all"]}
    both = [abs(v) for r in m["rows"] if r[0] in drawn for v in (r[1], r[2]) if v is not None]
    both += [abs(r[1]) for r in body["today"]["all"] if r[1] is not None]
    assert body["views"]["all"]["max_abs_with_prior"] == max(both)
    assert _gex(monday_prior) == pytest.approx(_gex(friday))
    # Monday's own rows are priced (the chain came with its spot) and compared with Friday's
    assert monday_migration["compared"] and len(monday_migration["rows"]) > 10
