"""The delta levels through the terrain rank every strike by delta, whatever its gamma: AMZN's 250
strike, one contract's gamma refused as impossible, and TSLA's $5 strike, gamma reported 0."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from terrain_engine import compute_terrain
from time_et import ET

_FX = Path(__file__).resolve().parent / "fixtures"


@pytest.mark.parametrize(
    ("name", "strike"),
    [
        ("real_amzn_full_chain_2026_10_29.json", 250.0),
        ("real_tsla_strikes_5_and_400_2026_09_28.json", 5.0),
    ],
)
def test_the_key_delta_strike_and_call_delta_wall_rank_every_strike(name, strike):
    held = json.loads((_FX / name).read_text(encoding="utf-8"))
    now = datetime.fromtimestamp(held["ts_utc"], ET)
    terrain = compute_terrain(held["ticker"], held["chain"], float(held["spot"]), now=now)
    assert terrain.key_delta_strike == strike
    assert terrain.call_delta_wall == strike


def test_the_call_wall_keeps_a_strike_whose_put_gamma_alone_is_refused():
    """AMZN's 250: its calls are all reported, two puts' gamma refused as impossible."""
    held = json.loads((_FX / "real_amzn_full_chain_2026_10_29.json").read_text(encoding="utf-8"))
    now = datetime.fromtimestamp(held["ts_utc"], ET)
    terrain = compute_terrain("AMZN", held["chain"], float(held["spot"]), now=now)
    assert terrain.call_wall == 250.0
