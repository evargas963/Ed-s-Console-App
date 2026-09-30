"""The Trade Desk's positioning migration is computed once, on the server (terrain_engine.
positioning_migration), from two real days of Schwab's PCG chain (tests/fixtures, captured
2026-09-24 and 2026-09-25). Expected values are worked out here from the rows themselves."""
import json
import time
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


def test_on_a_closed_market_the_prior_day_is_the_day_before_the_chains_own(tmp_path, monkeypatch, pin_clock):
    """On a weekend the terrain holds the newest capture (Friday). The prior day was picked by the
    wall clock's date, so it was that same Friday capture: every change 0, served as `compared`
    (2026-09-27). It is the capture before the day of the chain the rows came from. Real PCG
    chains, stored as the daemon writes them; the clock is Sunday."""
    import server
    from calibration.complete_chain_capture import CAPTURE_BASIS, persist_complete_chain_capture
    db = tmp_path / "ed.db"
    for day in _FX["days"]:
        by_exp: dict = {}
        for c in day["contracts"]:
            by_exp.setdefault(str(c.get("expirationDate") or "")[:10], []).append(c)
        for exp, cs in by_exp.items():
            persist_complete_chain_capture(db, ticker="PCG", expiry=exp, contracts=cs, spot=day["spot"],
                                           completeness_basis=CAPTURE_BASIS, ts_utc=day["ts_utc"])
    pin_clock(2026, 9, 27, 12, 0)                                        # Sunday
    from db import EdDB
    edb = EdDB(db)
    monkeypatch.setattr(server, "get_db", lambda: edb)
    monkeypatch.setattr(server, "_terrain_cache", {})
    # startup on a closed market: the levels producer prices the newest capture (Friday) and,
    # with it, the prior day's rows the route serves
    from calibration.complete_chain_capture import last_capture_per_day
    stored = last_capture_per_day(str(db), "PCG", 2)            # the startup load's one read
    newest = stored[0]
    assert server._publish_levels("PCG", captures=stored, now=time.time()) is not None
    body = json.loads(server.get_terrain_strikes(ticker="PCG").body)
    assert body["prior_source"] == "chain_capture:2026-09-24"
    m = body["migration"]["all"]
    assert m["compared"] and sum(1 for r in m["rows"] if r[3]) > 10       # real changes, not self vs self
    # the stored chains are read by the producer once per new capture, never by a page request
    reads = []
    monkeypatch.setattr(server, "last_capture_per_day", lambda *a, **k: reads.append(a) or [])
    for _ in range(3):
        assert json.loads(server.get_terrain_strikes(ticker="PCG").body)["prior_source"] == "chain_capture:2026-09-24"
        server.get_forces(ticker="PCG")
    server._publish_levels("PCG", captures=stored, now=time.time())                       # same capture: nothing new
    assert reads == []
    # a new capture is computed once, by the next publish
    key_before = server.terrain_cache_get("PCG")["_captures_key"]
    later = newest["ts_utc"] + 1800
    for exp, cs in {str(c.get("expirationDate") or "")[:10]: [] for c in newest["contracts"]}.items():
        persist_complete_chain_capture(db, ticker="PCG", expiry=exp,
                                       contracts=[c for c in newest["contracts"]
                                                  if str(c.get("expirationDate") or "")[:10] == exp],
                                       spot=newest["spot"], completeness_basis=CAPTURE_BASIS, ts_utc=later)
    monkeypatch.setattr(server, "last_capture_per_day",
                        lambda *a, **k: reads.append(a) or last_capture_per_day(*a, **k))
    stored = last_capture_per_day(str(db), "PCG", 2)            # the caller's one read ...
    newer = stored[0]
    server._publish_levels("PCG", captures=stored, now=time.time())
    assert server.terrain_cache_get("PCG")["_captures_key"] != key_before
    assert reads == []                            # ... serves the levels, forces and prior day
    server._publish_levels("PCG", captures=stored, now=time.time())
    assert reads == []
    # a new market day's first chain, before that day's first capture: the prior day is recomputed
    # against the new day (Friday's capture becomes the prior day), once
    monkeypatch.setattr(server, "resolve_spot", lambda tk: (newer["spot"], "streaming_plane", later))
    monkeypatch.setattr(server, "_record_level_crosses", lambda *a, **k: None)
    monday = datetime(2026, 9, 28, 10, 0, tzinfo=time_et.ET).timestamp()
    pin_clock(2026, 9, 28, 10, 0)
    server._publish_levels("PCG", newer["contracts"], monday, now=monday)
    assert len(reads) == 1                        # the two newest days, read once for both
    assert json.loads(server.get_terrain_strikes(ticker="PCG").body)["prior_source"] == "chain_capture:2026-09-25"
    server._publish_levels("PCG", newer["contracts"], monday + 5, now=monday + 5)
    assert len(reads) == 1
