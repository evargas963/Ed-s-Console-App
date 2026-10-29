"""One meaning per name (2026-09-27): DEX is dealer-signed (+call/-put) in every bucket; vanna is per 1 volatility point in every bucket and in the aggregate; a contract with
no readable expiry is in no expiry's book; yesterday's chain is priced at its own capture time.

Real data (tests/real_chains.py): SPY's same-day chain of 2026-10-07 12:32 ET and CRWD's 2026-10-16
chain of 2026-10-07 10:38 ET, each valued at its capture."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

import time_et
from math_exposure_core import compute_exposures_by_strike, compute_net_vanna
from terrain_engine import compute_terrain
from tests.real_chains import CRWD, SPY_0DTE


def _book():
    per, _ = compute_exposures_by_strike(SPY_0DTE.chain, spot=SPY_0DTE.spot, now=SPY_0DTE.now)
    return per


def test_dex_is_dealer_signed_in_every_bucket():
    per = _book()
    for b in per.values():
        assert b["net_dex_dollars"] == pytest.approx(b["call_dex_dollars"] - b["put_dex_dollars"])


def test_vanna_is_per_vol_point_in_every_bucket_and_in_the_aggregate():
    per = _book()
    shares = sum(b["call_vanna"] - b["put_vanna"] for b in per.values())
    agg = compute_net_vanna(per, SPY_0DTE.spot)
    assert agg["net_vanna_shares_per_volpt"] == pytest.approx(shares, abs=0.01)


def test_a_contract_with_no_expiry_is_not_counted_as_same_day():
    """On a chain with no same-day expiry (CRWD, 9 days out), a contract that does not state its
    expiry must not create a same-day share (it was pooled into the 0DTE book)."""
    chain, spot = CRWD.chain, CRWD.spot
    base = compute_terrain("CRWD", chain, spot, now=CRWD.now).zero_dte_gamma_share_pct
    top = max(chain, key=lambda c: c.get("gamma") or 0.0)          # a contract that carries gamma
    orphan = {k: v for k, v in top.items() if k not in ("expirationDate", "daysToExpiration")}
    orphan["openInterest"] = 100_000
    assert base == 0.0
    assert compute_terrain("CRWD", chain + [orphan], spot, now=CRWD.now).zero_dte_gamma_share_pct == base


def test_forces_prices_yesterdays_chain_at_its_capture_time(tmp_path):
    """The stored captures are priced at their own capture times, whatever the clock reads now
    (after the chain's expiry). Stand-in: SPY's real chain stored as two days' captures."""
    import server
    from calibration.complete_chain_capture import (CAPTURE_BASIS, last_capture_per_day,
                                                    persist_complete_chain_capture)
    db = tmp_path / "ed_console.db"
    for day, hour in ((7, 12), (6, 15)):
        ts = datetime(2026, 10, day, hour, 0, tzinfo=time_et.ET).timestamp()
        by_exp: dict = {}
        for ct in SPY_0DTE.chain:
            by_exp.setdefault(ct["expirationDate"][:10], []).append(ct)
        for exp, cts in by_exp.items():
            persist_complete_chain_capture(db, ticker="SPY", expiry=exp, contracts=cts,
                                           spot=SPY_0DTE.spot, completeness_basis=CAPTURE_BASIS,
                                           ts_utc=ts)
    body = server._forces_from_captures("SPY", last_capture_per_day(db, "SPY", 2))   # the producer's forces
    assert body["available"] is True
    assert body["charm_below"] is not None and body.get("charm_error") is None, body


def test_the_put_call_volume_ratio_is_todays_trading_and_says_so_when_volume_is_missing():
    """Both ratios are served (operator 2026-09-27): OI (positions held) and volume (today's
    trading, Cboe's convention). A strike with no call listed has no call volume, not a zero."""
    from math_exposure_core import put_call_volume_ratio
    book = {100.0: {"call_volume": 400.0, "put_volume": 300.0, "volume_unreported": 0},
            105.0: {"call_volume": 100.0, "put_volume": 200.0, "volume_unreported": 0}}
    assert put_call_volume_ratio(book) == pytest.approx(500.0 / 500.0)
    book[105.0]["volume_unreported"] = 1
    assert put_call_volume_ratio(book) is None, "a contract with no volume is not zero volume"
    book[105.0]["volume_unreported"] = 0
    book[110.0] = {"call_volume": None, "put_volume": 50.0, "volume_unreported": 0}
    assert put_call_volume_ratio(book) == pytest.approx(550.0 / 500.0)


def test_a_book_that_priced_no_vanna_serves_absent_not_zero():
    """Audit M-17: vanna fields start at 0.0 in every bucket, and the total read those zeros as
    data. Real chain priced the day after its own expiry (Schwab still lists an expired Friday on
    the weekend): no contract has a vanna, so there is no net vanna."""
    from math_exposure_core import bucket_metric
    next_day = SPY_0DTE.now + timedelta(days=1)
    per, _ = compute_exposures_by_strike(SPY_0DTE.chain, spot=SPY_0DTE.spot, now=next_day)
    assert [bucket_metric(b, "net_vanna") for b in per.values()] == [None] * len(per)
    assert compute_net_vanna(per, SPY_0DTE.spot) is None
