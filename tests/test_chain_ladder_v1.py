"""The chain panel serves the ladder the Chain view draws (terrain_engine.chain_ladder).

Strikes high to low, one row per listed contract, in-the-money flags as Schwab sends them (its
money intrinsic value, positive in the money). Real CRWD chain; real SPY 2026-11-20 chain with its
/quotes answers; a real LEVELONE_OPTIONS record.
"""

import json
from pathlib import Path

from calc.math_exposure_core import overlay_streamed_contract_fields
from calc.terrain_engine import chain_ladder as _chain_ladder
from option_contract import NO_GREEKS, Streamed, chain_row, read_chain, streamed_top

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FX = json.loads((FIXTURES / "real_crwd_complete_chain_quarter.json").read_text(encoding="utf-8"))
SPY = json.loads(
    (FIXTURES / "real_spy_2026_11_20_chain_and_quotes.json").read_text(encoding="utf-8")
)
SPY_QUOTES = {s: e["quote"] for q in SPY["quotes"] for s, e in q["reply"].items()}
STREAM = json.loads(
    (FIXTURES / "real_options_stream_history_samples.json").read_text(encoding="utf-8")
)


def chain_ladder(raw, spot):
    """Return the ladder the chain panel serves for the raw contracts.

    Each read once, shown by chain_row.
    """
    contracts = read_chain(raw)
    shown = [chain_row(c) for c in contracts]
    return _chain_ladder(contracts, spot, shown)


def test_every_contract_on_one_row_strikes_high_to_low():
    rows, unplaced = chain_ladder(FX["chain"], FX["spot"])
    assert unplaced == 0
    ks = [r["strike"] for r in rows]
    assert ks == sorted(ks, reverse=True)
    placed = [r[s]["symbol"] for r in rows for s in ("call", "put") if r[s]]
    assert sorted(placed) == sorted(c["symbol"] for c in FX["chain"])
    assert len({r["strike"] for r in rows}) == FX["n_strikes"]


def test_in_the_money_is_schwabs_and_one_spot_row():
    """Each contract's flag is its /quotes moneyIntrinsicValue positive.

    Checked against the quote's own underlyingPrice (762.63) for every one of the 442 SPY
    contracts: a call below it and a put above it. Schwab's /chains inTheMoney was answered at
    another price (766.31) and differs on the strikes between the two, so the flag is the one
    answer's, never a mix.
    """
    raw = [dict(c, quote=SPY_QUOTES[c["symbol"]]) for c in SPY["chain"]]
    spot = SPY["spot"]
    rows, unplaced = chain_ladder(raw, spot)
    assert unplaced == 0
    flags = {
        r[s]["symbol"]: r[f"{s}_itm"] for r in rows for s in ("call", "put") if r[s] is not None
    }
    assert len(flags) == 442
    underlying = {c["symbol"]: SPY_QUOTES[c["symbol"]]["underlyingPrice"] for c in SPY["chain"]}
    assert set(underlying.values()) == {762.63}
    assert flags == {
        c["symbol"]: c["strikePrice"] < 762.63
        if c["putCall"] == "CALL"
        else c["strikePrice"] > 762.63
        for c in SPY["chain"]
    }
    assert flags == {
        c["symbol"]: SPY_QUOTES[c["symbol"]]["moneyIntrinsicValue"] > 0 for c in SPY["chain"]
    }
    (s,) = [r for r in rows if r["spot"]]
    assert s["strike"] == min({r["strike"] for r in rows}, key=lambda k: abs(k - spot))


def test_without_a_value_from_schwab_nothing_is_marked():
    """The CRWD chain was captured with no quote: no money intrinsic value, so no flag.

    Without a spot, no row is marked as spot.
    """
    rows, _ = chain_ladder(FX["chain"], None)
    assert all(r["call_itm"] is None and r["put_itm"] is None and not r["spot"] for r in rows)
    rows, _ = chain_ladder(FX["chain"], FX["spot"])
    assert all(r["call_itm"] is None and r["put_itm"] is None for r in rows)


def test_a_streamed_contract_takes_the_streams_money_intrinsic_value():
    """The pushed MONEY_INTRINSIC_VALUE is a streamed contract's flag (AGENTS.md rule 3).

    Real TSLA 367.5 call record: underlying 365.855, intrinsic -1.645, out of the money. Stand-in:
    it is laid over a SPY contract of the capture, whose own quote says in the money.
    """
    content = STREAM["contracts"][0]["events"][0]["content"]
    assert content["MONEY_INTRINSIC_VALUE"] == -1.645
    raw = dict(SPY["chain"][0], quote=SPY_QUOTES[SPY["chain"][0]["symbol"]])
    (contract,) = read_chain([raw])
    assert contract.money_intrinsic == 462.63
    sym = contract.symbol
    (streamed,) = overlay_streamed_contract_fields(
        [contract], {sym: Streamed(streamed_top(content), NO_GREEKS)}, {sym}, {}
    )
    assert streamed.money_intrinsic == -1.645
    rows, _ = _chain_ladder([streamed], SPY["spot"], [chain_row(streamed)])
    assert rows[0]["call_itm"] is False
    # the flag is the value's one use on the screen: the row carries no copy of the number
    assert "moneyIntrinsicValue" not in rows[0]["call"]


def test_a_second_contract_at_one_strike_and_side_gets_its_own_row():
    """Stand-in: the CRWD capture lists one contract per strike and side; one call is repeated."""
    chain = FX["chain"] + [dict(FX["chain"][0], symbol="CRWD-ADJ")]
    rows = [
        r
        for r in chain_ladder(chain, FX["spot"])[0]
        if r["strike"] == FX["chain"][0]["strikePrice"]
    ]
    assert [r["first"] for r in rows] == [True, False]


def test_a_number_schwab_did_not_send_is_absent_and_an_unknown_side_is_not_a_call():
    """Register P-23 / M-29: the ladder carried contracts raw, so a -999 printed as "-999.00".

    And any putCall other than PUT was placed as a call. Stand-in: one contract's delta set to
    Schwab's no-value -999, and one contract with an unknown side.
    """
    first = dict(FX["chain"][0], delta=-999.0)
    odd = dict(FX["chain"][1], putCall="X", symbol="CRWD-ODD")
    rows, unplaced = chain_ladder([first, odd] + FX["chain"][2:], FX["spot"])
    row, shown = next(
        (r, r[s])
        for r in rows
        for s in ("call", "put")
        if r[s] and r[s]["symbol"] == first["symbol"]
    )
    assert shown["delta"] is None and row["strike"] == first["strikePrice"]
    assert unplaced == 1 and all(
        r[s]["symbol"] != "CRWD-ODD" for r in rows for s in ("call", "put") if r[s]
    )
