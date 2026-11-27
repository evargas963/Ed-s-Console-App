"""The largest total gamma strike's move, announced on the Gamma page (operator 2026-11-22).

The operator asked for a toast and a chime "whenever Largest total gamma strike changes for either
the regular of 0dte column on the Option > Gamma page". The strike is the levels' own
(`absolute_gamma_strike`, the whole book's and the same-day book's); its move is worked out once,
as the levels are published (calc.terrain_engine.total_gamma_record, server._publish_levels), and
served with the terrain panel (push.terrain.total_gamma_text).

Real data: SPY's last complete capture of 2026-11-11 (the close) and its complete capture of
2026-11-12 10:30:41 ET, each stored by the daemon's writer and published by the one producer in
turn, as the program publishes a day and then the next; Schwab's /markets answers for the two days.
Expected strikes are worked out here from the raw chains (_largest): the whole book's stands at
760 and the same-day book's moves from 760 to 756.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

import server
import time_et
from calc.terrain_engine import (
    TotalGammaChange,
    TotalGammaMove,
    TotalGammaRecord,
    total_gamma_record,
)
from db import last_capture_per_day
from push.terrain import terrain, total_gamma_text
from state import level_store
from tests.capture_store import store_capture

pytestmark = pytest.mark.rail

_FX = Path(__file__).resolve().parent / "fixtures"
TWO_DAYS = json.loads(
    gzip.decompress((_FX / "real_spy_two_day_captures_2026_11_12.json.gz").read_bytes())
)
TK = TWO_DAYS["ticker"]
MARKETS = [
    json.loads((_FX / f"real_schwab_markets_{day}.json").read_text(encoding="utf-8"))["body"]
    for day in ("2026_11_11", "2026_11_12")
]


def _largest(contracts: list[dict]) -> float:
    """Return the strike of the largest call GEX + put GEX, sizes, with Schwab's gamma as sent.

    GEX per 1% = gamma x open interest x multiplier x spot^2 x 1%; the spot is common to every
    strike, so the largest is that of gamma x open interest x multiplier. The gamma is the one the
    capture holds for the contract: the /quotes answer's (its `quote`) where it holds one, else
    its own as the sweep wrote it (a streamed contract's, the stream's); open interest the
    chain's. A gamma Schwab sent as no number (absent or -999), or a contract with no open
    interest, is left out.
    """
    by_strike: dict[float, float] = {}
    for c in contracts:
        gamma = (c["quote"] if "quote" in c else c).get("gamma")
        oi = c.get("openInterest")
        if isinstance(gamma, (int, float)) and gamma != -999 and oi is not None:
            k = c["strikePrice"]
            by_strike[k] = by_strike.get(k, 0) + abs(gamma) * oi * c["multiplier"]
    return max(by_strike, key=by_strike.__getitem__)


def _worked_out(capture: dict) -> tuple[float, float]:
    """Return the capture's largest total gamma strike: the whole book's, the same-day one's."""
    day = capture["et"][:10]
    every = [c for row in capture["rows"] for c in row["contracts"]]
    same_day = [c for row in capture["rows"] if row["expiry"] == day for c in row["contracts"]]
    return _largest(every), _largest(same_day)


@pytest.fixture
def published(tmp_path):
    """Each day's levels as the one producer published them, the earlier day first."""
    db = tmp_path / "ed_console.db"
    for capture in TWO_DAYS["captures"]:
        for row in capture["rows"]:
            store_capture(
                db,
                ticker=TK,
                expiry=row["expiry"],
                contracts=row["contracts"],
                spot=row["spot"],
                completeness_basis=capture["completeness_basis"],
                ts_utc=capture["ts_utc"],
                chain_spot=capture["chain_spot"],
                chain_spot_ts=capture["chain_spot_ts"],
            )
    newer, older = last_capture_per_day(db, TK, 2)
    held = time_et.HELD.sessions
    time_et.HELD.sessions = {}  # the two days' own answers, whatever else a test run holds
    try:
        for answer in MARKETS:
            time_et.record_markets(answer)
        levels = []
        for captures in ([older], [newer, older]):
            now = datetime.fromtimestamp(captures[0].ts_utc, time_et.ET)
            server._publish_levels(TK, captures=captures, now=now)
            levels.append((level_store.published_levels(TK), terrain(TK, now.timestamp())))
        yield levels
    finally:
        time_et.HELD.sessions = held
        with level_store._lock:
            level_store._levels.pop(TK, None)
        server._gamma_surface_seq.pop(TK, None)


def test_the_first_levels_announce_nothing_and_the_next_days_announce_the_move(published):
    """The 0DTE column moved 760 → 756 and the regular one stood: one move, at the levels' time."""
    (first, first_panel), (second, second_panel) = published
    was, now = (_worked_out(capture) for capture in TWO_DAYS["captures"])
    assert (was, now) == ((760.0, 760.0), (760.0, 756.0))
    assert first.total_gamma == TotalGammaRecord(was, None)
    assert first_panel["total_gamma_change"] is None
    assert second.total_gamma == TotalGammaRecord(
        now, TotalGammaMove((TotalGammaChange("0DTE", 760.0, 756.0),), second.levels_ts_utc)
    )
    assert second_panel["total_gamma_change"] == {
        "id": f"{second.levels_ts_utc!r} Gamma Total · 0DTE 760.00 → 756.00",
        "text": "Gamma Total · 0DTE 760.00 → 756.00",
        "time_ct": time_et.ct_label(second.levels_ts_utc),
    }


def test_the_same_levels_again_move_nothing_and_the_last_move_stands(published):
    """A reprice that keeps both strikes announces nothing new: the move served is the last one."""
    _first, (second, _panel) = published
    record, snap, at = second.total_gamma, second.snap, second.levels_ts_utc + 1.0
    assert total_gamma_record(record, snap, at) == record
    # the first strikes known move nothing, with no levels published before or none known in them
    for first in (None, TotalGammaRecord()):
        assert total_gamma_record(first, snap, at) == TotalGammaRecord(record.known)
    # INDUCED: neither column known (as with no price): the strikes last known stand, no move
    unknown = replace(
        snap, absolute_gamma_strike=None, same_day={**snap.same_day, "absolute_gamma_strike": None}
    )
    assert total_gamma_record(record, unknown, at) == record
    # INDUCED: the regular column one strike higher, the 0DTE column still not known
    higher = replace(unknown, absolute_gamma_strike=761.0)
    assert total_gamma_record(record, higher, at) == TotalGammaRecord(
        (761.0, 756.0), TotalGammaMove((TotalGammaChange("Regular", 760.0, 761.0),), at)
    )
    assert total_gamma_text(None) is None
