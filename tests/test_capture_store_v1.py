"""The chain captures the levels read are held in State, not read from the database live.

state.capture_store: a ticker's stored captures are loaded once, the first time it is asked for,
exactly as calibration.complete_chain_capture.last_capture_per_day reads them back; from then on
a chain the sweep marks as its window's capture is kept as it arrives (server._on_chain), with no
database read (rule 6). MRVL's real chain of 2026-10-07 (tests/real_chains.py), its front expiry,
stored as one day's capture and delivered as the next day's.
"""

from __future__ import annotations

import server
from calibration.complete_chain_capture import CAPTURE_BASIS, last_capture_per_day
from option_contract import read_chain
from state import capture_store
from tests.capture_store import store_capture
from tests.real_chains import MRVL

_FRONT = min(c["expirationDate"][:10] for c in MRVL.chain)
_CONTRACTS = [c for c in MRVL.chain if c["expirationDate"][:10] == _FRONT]
_DAY = 24 * 3600.0


def _stored(db, ts: float) -> None:
    out = store_capture(
        db,
        ticker="MRVL",
        expiry=_FRONT,
        contracts=_CONTRACTS,
        spot=MRVL.spot,
        chain_spot=MRVL.spot,
        chain_spot_ts=ts,
        completeness_basis=CAPTURE_BASIS,
        ts_utc=ts,
    )
    assert out.status == "written", out


def test_the_store_reads_back_the_database_once_then_keeps_a_new_capture_without_reading_it(
    tmp_path,
):
    db = tmp_path / "ed.db"
    first = MRVL.now.timestamp()
    _stored(db, first)
    held = capture_store.captures(db, "MRVL")
    assert held == last_capture_per_day(db, "MRVL", capture_store.CAPTURE_DAYS)
    assert [c.ts_utc for c in held] == [first]

    # the next day's chain, marked a capture by the sweep: kept as it arrives
    nxt = first + _DAY
    contracts = read_chain(_CONTRACTS)
    try:
        server._on_chain("MRVL", contracts, nxt, None, (MRVL.spot, nxt), True)
        server.chain_pricing.submit(lambda: None).result(timeout=120)
    finally:
        server.stop_terrain_loop()  # drops what waits; MRVL's levels are this test's
    held = capture_store.captures(db, "MRVL")
    assert [c.ts_utc for c in held] == [nxt, first]
    assert held[0].contracts == contracts and held[0].spot == MRVL.spot
    assert capture_store.newest_ts(db, "MRVL") == nxt
    # the database still holds only the first: the new one came from the chain, not a read
    assert [c.ts_utc for c in last_capture_per_day(db, "MRVL", 2)] == [first]


def test_a_chain_that_is_not_a_capture_is_not_kept(tmp_path):
    db = tmp_path / "ed.db"
    first = MRVL.now.timestamp()
    _stored(db, first)
    capture_store.captures(db, "MRVL")
    try:
        server._on_chain(
            "MRVL", read_chain(_CONTRACTS), first + 60, None, (MRVL.spot, first), False
        )
        server.chain_pricing.submit(lambda: None).result(timeout=120)
    finally:
        server.stop_terrain_loop()
    assert [c.ts_utc for c in capture_store.captures(db, "MRVL")] == [first]


def test_a_capture_of_a_day_already_held_replaces_it(tmp_path):
    """The newest capture of each date, as the database reads back the last one of the day."""
    db = tmp_path / "ed.db"
    first = MRVL.now.timestamp()
    _stored(db, first)
    capture_store.captures(db, "MRVL")
    later = first + 1800  # the same ET date, half an hour on
    try:
        server._on_chain("MRVL", read_chain(_CONTRACTS), later, None, (MRVL.spot, later), True)
        server.chain_pricing.submit(lambda: None).result(timeout=120)
    finally:
        server.stop_terrain_loop()
    assert [c.ts_utc for c in capture_store.captures(db, "MRVL")] == [later]
