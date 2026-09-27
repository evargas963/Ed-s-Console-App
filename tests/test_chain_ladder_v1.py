"""/api/chain serves the ladder the Chain view draws (terrain_engine.chain_ladder): strikes high to
low, one row per listed contract, in-the-money flags against the live spot. Real CRWD chain."""
import json
from pathlib import Path

import pytest

from terrain_engine import chain_ladder

FX = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_crwd_complete_chain_quarter.json")
                .read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _at_capture(pin_clock):
    return pin_clock(2026, 9, 2, 12, 0)


def test_every_contract_on_one_row_strikes_high_to_low():
    rows = chain_ladder(FX["chain"], FX["spot"])
    ks = [r["strike"] for r in rows]
    assert ks == sorted(ks, reverse=True)
    placed = [r[s]["symbol"] for r in rows for s in ("call", "put") if r[s]]
    assert sorted(placed) == sorted(c["symbol"] for c in FX["chain"])
    assert len({r["strike"] for r in rows}) == FX["n_strikes"]


def test_in_the_money_against_the_spot_and_one_spot_row():
    spot = FX["spot"]   # 205.4
    rows = chain_ladder(FX["chain"], spot)
    for r in rows:
        assert r["call_itm"] is (r["strike"] < spot) and r["put_itm"] is (r["strike"] > spot)
    (s,) = [r for r in rows if r["spot"]]
    assert s["strike"] == min({r["strike"] for r in rows}, key=lambda k: abs(k - spot))


def test_without_a_spot_nothing_is_marked():
    rows = chain_ladder(FX["chain"], None)
    assert all(r["call_itm"] is None and r["put_itm"] is None and not r["spot"] for r in rows)


def test_a_second_contract_at_one_strike_and_side_gets_its_own_row():
    """Stand-in: the CRWD capture lists one contract per strike and side; one call is repeated."""
    chain = FX["chain"] + [dict(FX["chain"][0], symbol="CRWD-ADJ")]
    rows = [r for r in chain_ladder(chain, FX["spot"]) if r["strike"] == FX["chain"][0]["strikePrice"]]
    assert [r["first"] for r in rows] == [True, False]
