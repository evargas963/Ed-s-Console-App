"""The Trade Desk's positioning migration is computed once, on the server (terrain_engine.
positioning_migration), from two real days of Schwab's PCG chain (tests/fixtures, captured
2026-09-24 and 2026-09-25). Expected values are worked out here from the rows themselves."""
import json
from datetime import datetime
from pathlib import Path

import pytest

import time_et
from terrain_engine import MIGRATION_DRIFT_STRIKES, compute_terrain, positioning_migration

_FX = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_pcg_two_day_chain.json")
                 .read_text(encoding="utf-8"))


@pytest.fixture
def two_days(pin_clock):
    rows = []
    for day in _FX["days"]:
        at = datetime.fromtimestamp(day["ts_utc"], time_et.ET)
        pin_clock(at.year, at.month, at.day, at.hour, at.minute)
        snap = compute_terrain("PCG", day["contracts"], day["spot"])
        rows.append((snap.per_strike, snap))
    return rows


def test_the_migration_matches_the_two_days_rows(two_days):
    (prior, _), (today, snap) = two_days
    m = positioning_migration(today["all"], prior["all"], snap.call_wall, snap.put_wall)
    prior_gex = {r[0]: r[1] for r in prior["all"]}
    changes = {r[0]: r[1] - prior_gex[r[0]] for r in today["all"]
               if r[1] is not None and prior_gex.get(r[0]) is not None}
    assert m["compared"] and len(changes) > 10
    assert {r[0]: r[3] for r in m["rows"] if r[3] is not None} == pytest.approx(changes)
    assert m["grew"] == [k for k, _ in sorted(changes.items(), key=lambda kv: -kv[1]) if changes[k] > 0][:2]
    # the weighted positive-gamma strike, each day, over strikes known on both days
    def wmean(day_gex):
        pos = [(k, day_gex[k]) for k in changes if day_gex[k] > 0]
        return sum(k * g for k, g in pos) / sum(g for _k, g in pos) if pos else None
    today_gex = {r[0]: r[1] for r in today["all"]}
    wt, wp = wmean(today_gex), wmean(prior_gex)
    assert m["weighted_strike_today"] == pytest.approx(wt) and m["weighted_strike_prior"] == pytest.approx(wp)
    d = wt - wp
    assert m["drift"] == ("UP" if d > MIGRATION_DRIFT_STRIKES else "DOWN" if -d > MIGRATION_DRIFT_STRIKES else "FLAT")


def test_busiest_strikes_and_volume_total_come_from_schwabs_volume(two_days):
    (_prior, _), (today, snap) = two_days
    m = positioning_migration(today["all"], [], snap.call_wall, snap.put_wall)
    vols = {r[0]: r[2] for r in today["all"] if r[2]}
    assert m["busiest"] == sorted(sorted(vols, key=lambda k: -vols[k])[:2])
    assert m["volume_total"] == sum(r[2] for r in today["all"] if r[2] is not None)
    assert not m["compared"] and m["drift"] is None      # no prior day: nothing to compare
