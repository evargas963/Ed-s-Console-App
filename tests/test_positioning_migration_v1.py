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
from calc.terrain_engine import compute_terrain, level_moves, positioning_migration
from calibration.complete_chain_capture import CAPTURE_BASIS
from db import last_capture_per_day
from numeric_contract import dollars_text
from option_contract import read_chain
from push import strikes as push_strikes
from state import level_store
from tests.capture_store import store_capture

#: the strikes panel's window as the page asks it: Auto, following the price
_AUTO = {"scope": "auto", "centre": None, "shift": 0, "expiry": None}
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
            sessions=time_et.sessions(),
        )
        rows.append((snap.per_strike, snap))
    return rows


def test_the_migration_matches_the_two_days_rows(two_days):
    (prior, prior_snap), (today, snap) = two_days
    m = positioning_migration(today["gex"], prior["gex"], snap.call_wall, snap.put_wall)
    prior_gex = {r.strike: r.value for r in prior["gex"]}
    changes = {
        r.strike: r.value - prior_gex[r.strike]
        for r in today["gex"]
        if r.value is not None and prior_gex.get(r.strike) is not None
    }
    assert m["compared"] and len(changes) > 10
    assert {r.strike: r.change for r in m["rows"] if r.change is not None} == pytest.approx(changes)
    assert (
        m["grew"]
        == [k for k, _ in sorted(changes.items(), key=lambda kv: -kv[1]) if changes[k] > 0][:2]
    )

    # the walls and the flip, each day's own, and the move between them: no drift word
    assert "drift" not in m
    moves = {v.level: (v.prior, v.today, v.change) for v in level_moves(snap, prior_snap)}
    assert snap.call_wall is not None and prior_snap.call_wall is not None
    assert moves == {
        name: (
            getattr(prior_snap, name),
            getattr(snap, name),
            None
            if getattr(prior_snap, name) is None or getattr(snap, name) is None
            else getattr(snap, name) - getattr(prior_snap, name),
        )
        for name in ("call_wall", "put_wall", "gamma_flip")
    }


def test_busiest_strikes_and_volume_total_come_from_schwabs_volume(two_days):
    (_prior, _), (today, snap) = two_days
    m = positioning_migration(today["gex"], [], snap.call_wall, snap.put_wall)
    vols = {r.strike: r.volume for r in today["gex"] if r.volume}
    assert m["busiest"] == sorted(sorted(vols, key=lambda k: -vols[k])[:2])
    assert m["volume_total"] == sum(r.volume for r in today["gex"] if r.volume is not None)
    # no prior day: nothing is compared, and no level's move is known
    assert not m["compared"] and [v.change for v in level_moves(snap, None)] == [None] * 3


def test_where_the_busiest_strikes_sit_is_said_only_when_it_is_known(two_days):
    """The busiest strikes against the walls, on PCG's real rows; the walls are INDUCED around them.

    Above the call wall, below the put wall, inside both, and the two busiest strikes on both
    sides of a wall: across it. When a wall the place depends on is not known: not known (None),
    never "inside" by default.
    """
    (_prior, _), (today, _snap) = two_days
    rows = today["gex"]
    low, high = positioning_migration(rows, [], None, None)["busiest"]
    assert low < high, "the two busiest strikes differ: the straddle case would be vacuous"
    mid = (low + high) / 2

    def where(call: float | None, put: float | None) -> str | None:
        return positioning_migration(rows, [], call, put)["busiest_vs_walls"]

    assert where(low - 1, None) == "ABOVE_CALL_WALL"
    assert where(None, high + 1) == "BELOW_PUT_WALL"
    assert where(high, low) == "INSIDE_WALLS"
    assert where(high, None) is None, "the put wall not known"
    assert where(None, None) is None
    assert where(mid, low - 1) == "ACROSS_CALL_WALL", "one below the call wall, one above"
    assert where(high + 1, high) == "ACROSS_PUT_WALL", "one on the put wall, one below it"
    assert where(None, mid) == "ACROSS_PUT_WALL", "the call wall not needed to say so"
    assert where(mid + 0.01, mid - 0.01) == "ACROSS_WALLS", "one below both walls, one above"


def test_where_the_busiest_strikes_sit_is_served_in_the_screens_words(two_days):
    """The same INDUCED walls around PCG's real rows: each place is served as the screen says it.

    The page draws the served sentence, `busiest_where_said`, and picks no words itself: above the
    largest call gamma strike, below the largest put gamma strike, between the two, across one or
    both, and no sentence (None) where the place is not known, which the page leaves out.
    """
    (_prior, _), (today, _snap) = two_days
    rows = today["gex"]
    low, high = positioning_migration(rows, [], None, None)["busiest"]
    mid = (low + high) / 2

    def said(call: float | None, put: float | None) -> str | None:
        migration = positioning_migration(rows, [], call, put)
        return push_strikes._shown_migration(migration, None, "LIVE")["busiest_where_said"]

    assert said(low - 1, None) == "That is ABOVE Gamma Call."
    assert said(None, high + 1) == "That is BELOW Gamma Put."
    assert said(high, low) == "That is between Gamma Put and Gamma Call."
    assert said(high, None) is None
    assert said(mid, low - 1) == "That is across Gamma Call."
    assert said(high + 1, high) == "That is across Gamma Put."
    assert said(mid + 0.01, mid - 0.01) == "That is across Gamma Put and Gamma Call."


def _prior_gex(body: dict) -> dict:
    """Return the prior day's net GEX the migration compared, by strike."""
    rows = body["migration"]["rows"]
    return {r["strike"]: r["prior"] for r in rows if r["prior"] is not None}


def _gex(per_strike: dict) -> dict:
    """Return a day's own net GEX by strike, from its per-strike rows."""
    return {r.strike: r.value for r in per_strike["gex"] if r.value is not None}


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
            by_exp.setdefault(c["expirationDate"][:10], []).append(c)
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
        sunday = datetime(2026, 9, 27, 12, 0, tzinfo=time_et.ET)
        assert server._publish_levels("PCG", captures=stored, now=sunday) is not None
        body = push_strikes.strikes("PCG", sunday.timestamp(), _AUTO)
        # a new market day's first chain (Monday 2026-09-28 10:00 ET), before that day's first
        # capture: the prior day is recomputed against the new day
        monday = datetime(2026, 9, 28, 10, 0, tzinfo=time_et.ET)
        server._publish_levels(
            "PCG",
            newest.contracts,
            monday.timestamp(),
            chain_spot=(newest.spot, monday.timestamp()),
            now=monday,
        )
        monday_prior = level_store.published_levels("PCG").prior_day.per_strike
        monday_migration = push_strikes.strikes("PCG", monday.timestamp(), _AUTO)["migration"]
    finally:
        with level_store._lock:
            level_store._levels.pop("PCG", None)
    (thursday, _), (friday, _) = two_days  # the captures of 2026-09-24 and 2026-09-25
    assert _prior_gex(body) == pytest.approx(_gex(thursday))
    m = body["migration"]
    assert (
        m["compared"] and sum(1 for r in m["rows"] if r["change"]) > 10
    )  # real changes, not self vs self
    # each change as the screen shows it, its direction and size in dollars
    for r in m["rows"]:
        c = r["change"]
        want = None if c is None else ("▲" if c >= 0 else "▼") + dollars_text(abs(c))
        assert r["change_text"] == want
    # the migration panel's one scale: the largest |GEX| today or the prior day among the strikes
    # drawn (every today bar too, whether or not the prior day lists its strike)
    today_rows = body["today"]
    drawn = {r["strike"] for r in today_rows}
    both = [
        abs(v)
        for r in m["rows"]
        if r["strike"] in drawn
        for v in (r["value"], r["prior"])
        if v is not None
    ]
    both += [abs(r["value"]) for r in today_rows if r["value"] is not None]
    assert body["view"]["max_abs_with_prior"] == max(both)
    assert _gex(monday_prior) == pytest.approx(_gex(friday))
    # Monday's own rows are priced (the chain came with its spot) and compared with Friday's
    assert monday_migration["compared"] and len(monday_migration["rows"]) > 10
