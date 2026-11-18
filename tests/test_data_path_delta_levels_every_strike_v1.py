"""The delta levels through the terrain rank every strike by delta, whatever its gamma.

AMZN's 250 strike, two puts' gamma refused as impossible, and TSLA's $5 strike against its $400
strike, gamma reported 0 on the $5. Each expected strike is also worked out from the raw chain
outside the program (tests/real_chains.book_ranks).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from calc.terrain_engine import compute_terrain
from option_contract import read_chain
from tests.real_chains import book_ranks
from time_et import ET, sessions

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
    chain = read_chain(held["chain"])
    terrain = compute_terrain(
        held["ticker"], chain, float(held["spot"]), now=now, sessions=sessions()
    )
    worked_out = book_ranks(held["chain"], float(held["spot"]))
    assert terrain.key_delta_strike == worked_out["key_delta_strike"] == strike
    assert terrain.call_delta_wall == worked_out["call_delta_wall"] == strike


def test_the_call_wall_keeps_a_strike_whose_put_gamma_alone_is_refused():
    """AMZN's 250: its calls are all reported, two puts' gamma refused as impossible."""
    held = json.loads((_FX / "real_amzn_full_chain_2026_10_29.json").read_text(encoding="utf-8"))
    now = datetime.fromtimestamp(held["ts_utc"], ET)
    terrain = compute_terrain(
        "AMZN", read_chain(held["chain"]), float(held["spot"]), now=now, sessions=sessions()
    )
    worked_out = book_ranks(held["chain"], float(held["spot"]))["call_wall"]
    assert terrain.call_wall == worked_out == 250.0
