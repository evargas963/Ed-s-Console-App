"""One meaning per name (2026-09-27).

DEX is the signed sum of Schwab's deltas in every bucket; vanna is per 1 volatility point in every
bucket and in their sum; a contract with no readable expiry is in no expiry's book;
yesterday's chain is priced at its own capture time.

Real data (tests/real_chains.py): SPY's same-day chain of 2026-10-07 12:32 ET and CRWD's 2026-10-16
chain of 2026-10-07 10:38 ET, each valued at its capture.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

import server
import time_et
from calc.math_exposure_core import (
    bucket_metric,
    compute_exposures_by_strike,
    put_call_volume_ratio,
)
from calc.terrain_engine import compute_terrain
from calibration.complete_chain_capture import CAPTURE_BASIS
from db import last_capture_per_day
from option_contract import read_chain
from state import level_store
from tests.capture_store import store_capture
from tests.real_chains import CRWD, SPY_0DTE, SPY_FULL


def _book():
    per, _ = compute_exposures_by_strike(
        read_chain(SPY_0DTE.chain),
        spot=SPY_0DTE.spot,
        now=SPY_0DTE.now,
        sessions=time_et.sessions(),
    )
    return per


def test_dex_is_the_signed_sum_of_schwabs_deltas_in_every_bucket():
    """Net DEX is call + put with each delta as Schwab sent it (a put's is negative).

    The industry's net delta exposure (docs/SOURCES.md flashalpha-dex-api); it assumes nothing about
    who holds a contract. Worked out from SPY's whole chain of 2026-11-09 as Schwab sent it,
    outside the program: delta x open interest x multiplier x price per contract, summed by
    strike. Before, a put's negative delta was subtracted: the two sides added as sizes, so no
    strike was ever negative (+305.1 million delta-shares on this chain, where the signed sum is
    -37.6 million and 181 strikes are negative).
    """
    spot = SPY_FULL.spot
    want: dict[float, float] = {}
    for c in SPY_FULL.chain:
        delta, oi, mult = c["delta"], c["openInterest"], c["multiplier"]
        if delta in (None, -999.0) or oi is None or not mult:
            continue
        want[c["strikePrice"]] = want.get(c["strikePrice"], 0.0) + delta * oi * mult * spot
    per, _ = compute_exposures_by_strike(
        read_chain(SPY_FULL.chain), spot=spot, now=SPY_FULL.now, sessions=time_et.sessions()
    )
    got = {k: b["net_dex_dollars"] for k, b in per.items() if b["net_dex_dollars"] is not None}
    assert set(got) == set(want)
    for k, value in got.items():
        assert value == pytest.approx(want[k], rel=1e-9, abs=1e-6), k
        assert value == pytest.approx(per[k]["call_dex_dollars"] + per[k]["put_dex_dollars"])
    total = sum(got.values())
    assert total == pytest.approx(sum(want.values()), rel=1e-9)
    assert total < 0  # the book is net short delta on this chain: the old sum could never be
    assert sum(1 for v in got.values() if v < 0) == 181


def test_vanna_is_per_vol_point_in_every_bucket_and_in_the_aggregate():
    per = _book()
    shares = sum(b["call_vanna"] - b["put_vanna"] for b in per.values())
    nets = sum(b["net_vanna"] for b in per.values())
    assert nets == shares  # each bucket's net is its call less its put, summed in the same order


def test_a_contract_with_no_expiry_is_not_counted_as_same_day():
    """On a chain with no same-day expiry, a contract with no stated expiry is not same-day.

    On CRWD, 9 days out, a contract that does not state its expiry is in no expiry's book: the
    terrain has no same-day book (no expiry of 0 days) with it or without it.
    """
    chain, spot = CRWD.chain, CRWD.spot
    held = time_et.sessions()
    base = compute_terrain("CRWD", read_chain(chain), spot, now=CRWD.now, sessions=held).books
    # the contract with the most gamma among those Schwab sent a gamma for
    top = max((c for c in chain if c.get("gamma") is not None), key=lambda c: c["gamma"])
    orphan = {k: v for k, v in top.items() if k not in ("expirationDate", "daysToExpiration")}
    orphan["openInterest"] = 100_000
    assert not [d for (_e, d) in base if d is not None and d <= 0]
    with_orphan = read_chain(chain + [orphan])
    books = compute_terrain("CRWD", with_orphan, spot, now=CRWD.now, sessions=held).books
    assert not [d for (_e, d) in books if d is not None and d <= 0]


def test_stored_captures_are_priced_at_their_own_capture_times(tmp_path):
    """The stored captures are priced at their own capture times, whatever the clock reads now.

    Now is after the chain's expiry. Stand-in: SPY's real chain stored as two days' captures: the
    newer is today's levels, the older the prior day's.
    """
    db = tmp_path / "ed_console.db"
    for day, hour in ((7, 12), (6, 15)):
        ts = datetime(2026, 10, day, hour, 0, tzinfo=time_et.ET).timestamp()
        by_exp: dict = {}
        for ct in SPY_0DTE.chain:
            by_exp.setdefault(ct["expirationDate"][:10], []).append(ct)
        for exp, cts in by_exp.items():
            store_capture(
                db,
                ticker="SPY",
                expiry=exp,
                contracts=cts,
                spot=SPY_0DTE.spot,
                chain_spot=SPY_0DTE.spot,
                completeness_basis=CAPTURE_BASIS,
                ts_utc=ts,
            )
    later = datetime(2026, 10, 20, 20, 0, tzinfo=time_et.ET)  # after the chain's expiry
    try:
        server._publish_levels("SPY", captures=last_capture_per_day(db, "SPY", 2), now=later)
        levels = level_store.published_levels("SPY")
        assert levels is not None
    finally:
        with level_store._lock:
            level_store._levels.pop("SPY", None)
    # priced at its capture time, the newer capture's contracts have time left: a charm map
    charm = [b["net_charm"] for b in levels.snap.charm_by_strike.values()]
    assert charm and any(v is not None for v in charm)
    assert levels.prior_day is not None and levels.prior_day.charm_by_strike


def test_the_put_call_volume_ratio_is_todays_trading_and_says_so_when_volume_is_missing():
    """Both ratios are served (operator 2026-09-27).

    OI (positions held) and volume (today's trading, Cboe's convention). A strike with no call
    listed adds 0 calls: the sum of none.
    """
    book = {
        100.0: {"call_volume": 400.0, "put_volume": 300.0, "volume_unreported": 0},
        105.0: {"call_volume": 100.0, "put_volume": 200.0, "volume_unreported": 0},
    }
    assert put_call_volume_ratio(book.values()) == pytest.approx(500.0 / 500.0)
    book[105.0]["volume_unreported"] = 1
    assert put_call_volume_ratio(book.values()) is None, (
        "a contract with no volume is not zero volume"
    )
    book[105.0]["volume_unreported"] = 0
    book[110.0] = {"call_volume": 0.0, "put_volume": 50.0, "volume_unreported": 0}
    assert put_call_volume_ratio(book.values()) == pytest.approx(550.0 / 500.0)


def test_a_book_that_priced_no_vanna_serves_absent_not_zero():
    """Audit M-17: vanna fields start at 0.0 in every bucket.

    The total read those zeros as data. Real chain priced the day after its own expiry (Schwab
    still lists an expired Friday on the weekend): no contract has a vanna, so there is no net
    vanna.
    """
    next_day = SPY_0DTE.now + timedelta(days=1)
    per, _ = compute_exposures_by_strike(
        read_chain(SPY_0DTE.chain), spot=SPY_0DTE.spot, now=next_day, sessions=time_et.sessions()
    )
    assert [bucket_metric(b, "net_vanna") for b in per.values()] == [None] * len(per)
    assert [bucket_metric(b, f"{s}_vanna") for b in per.values() for s in ("call", "put")] == [
        None
    ] * (2 * len(per)), "no leg has a vanna: none is 0"
