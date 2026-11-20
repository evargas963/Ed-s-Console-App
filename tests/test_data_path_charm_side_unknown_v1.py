"""A side's charm with a contract not known is unknown, never the sum of the rest.

NFLX's captured calls of 2027-12-17 and 2028-01-21 at $3: Schwab sent their volatility as -999,
open interest known.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from calc.math_levels import compute_charm_by_strike
from calc.terrain_engine import compute_terrain
from option_contract import read_chain
from tests.real_chains import NFLX
from time_et import ET, INDEX_OPTIONS, sessions


def test_a_contract_schwab_sent_no_volatility_leaves_its_side_and_net_unknown():
    snap = compute_terrain(
        NFLX.ticker, read_chain(NFLX.chain), NFLX.spot, now=NFLX.now, sessions=sessions()
    )
    bucket = snap.charm_by_strike[3.0]
    assert bucket["call_charm"] is None
    assert bucket["net_charm"] is None
    assert isinstance(bucket["put_charm"], float)


def test_an_expired_contract_with_no_volatility_has_no_charm_left():
    after_all = datetime(2028, 2, 1, 12, 0, tzinfo=ET)
    assert (
        compute_charm_by_strike(
            read_chain(NFLX.chain), NFLX.spot, now=after_all, sessions=sessions()
        )
        == {}
    )


def test_a_live_contract_with_no_time_to_expiry_leaves_its_side_unknown():
    """$SPX's AM-settled 2027-12-17 contracts on 2027-01-04 are not known, never left out.

    2027-01-04 is a date within the year of it that the held /markets answers do not reach: not
    known to have settled, so not known, never left out.
    """
    fx = json.loads(
        (
            Path(__file__).parent / "fixtures" / "real_spx_chain_2026_10_07_2027_12_17.json"
        ).read_text(encoding="utf-8")
    )
    now = datetime(2027, 1, 4, 12, 0, tzinfo=ET)
    book = compute_charm_by_strike(
        read_chain(fx["chain"]), fx["spot"], now=now, sessions=sessions(), product=INDEX_OPTIONS
    )
    assert book and all(b["net_charm"] is None for b in book.values())


def test_a_contract_past_its_date_with_no_session_held_has_settled():
    """$SPX's AM-settled 2027-12-17 contracts on 2028-02-01.

    No /markets answer is held, and the date has passed.
    """
    fx = json.loads(
        (
            Path(__file__).parent / "fixtures" / "real_spx_chain_2026_10_07_2027_12_17.json"
        ).read_text(encoding="utf-8")
    )
    now = datetime(2028, 2, 1, 12, 0, tzinfo=ET)
    chain = read_chain(fx["chain"])
    assert (
        compute_charm_by_strike(
            chain, fx["spot"], now=now, sessions=sessions(), product=INDEX_OPTIONS
        )
        == {}
    )


def test_a_reported_multiplier_of_0_is_0_and_a_missing_one_is_not_known():
    """Induced test condition: NFLX's $5 call, which has a charm, with its multiplier changed."""
    call = next(
        c
        for c in NFLX.chain
        if c["strikePrice"] == 5.0
        and c["putCall"] == "CALL"
        and c["expirationDate"].startswith("2027-12-17")
    )
    book = [c for c in NFLX.chain if c["strikePrice"] == 5.0 and c is not call]
    zero_chain = read_chain([*book, dict(call, multiplier=0)])
    gone_chain = read_chain([*book, dict(call, multiplier=None)])
    zero = compute_charm_by_strike(zero_chain, NFLX.spot, now=NFLX.now, sessions=sessions())
    gone = compute_charm_by_strike(gone_chain, NFLX.spot, now=NFLX.now, sessions=sessions())
    assert zero[5.0]["call_charm"] is not None
    assert gone[5.0]["call_charm"] is None


def test_a_contract_with_no_readable_date_leaves_its_side_unknown_in_the_terrain():
    """Induced test condition: NFLX's $5 call put back with its expirationDate removed."""
    call = next(
        c
        for c in NFLX.chain
        if c["strikePrice"] == 5.0 and c["putCall"] == "CALL" and c["openInterest"] > 0
    )
    chain = [*NFLX.chain, {k: v for k, v in call.items() if k != "expirationDate"}]
    snap = compute_terrain(
        NFLX.ticker, read_chain(chain), NFLX.spot, now=NFLX.now, sessions=sessions()
    )
    assert snap.charm_by_strike[5.0]["call_charm"] is None
