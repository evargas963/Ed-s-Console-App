"""Single ET authority: DST-aware America/New_York."""

from __future__ import annotations

from datetime import datetime

from time_et import ET, et_clock_from_ts_utc, now_et


def test_now_et_uses_america_new_york_zone():
    dt = now_et()
    assert dt.tzinfo is not None
    assert str(dt.tzinfo) in ("America/New_York", "America/New_York EST", "America/New_York EDT")
    assert dt.utcoffset() is not None


def test_et_clock_from_ts_utc_matches_now_et_zone():
    dt = now_et()
    h, m, wd = et_clock_from_ts_utc(dt.timestamp())
    assert h == dt.hour
    assert m == dt.minute
    assert wd == dt.weekday()


def test_dst_offset_differs_summer_vs_winter():
    winter = datetime(2026, 1, 15, 12, 0, tzinfo=ET)
    summer = datetime(2026, 7, 15, 12, 0, tzinfo=ET)
    assert winter.utcoffset() != summer.utcoffset()
    assert winter.utcoffset().total_seconds() == -5 * 3600
    assert summer.utcoffset().total_seconds() == -4 * 3600




def test_time_to_expiry_years_uses_timestamp_elapsed_not_civil_timedelta():
    from time_et import MIN_TIME_TO_EXPIRY_YEARS, YEAR_SECONDS, time_to_expiry_years

    # DST spring-forward 2026-03-08: civil wall-clock span is 1h longer than elapsed.
    fri = datetime(2026, 3, 6, 10, 30, tzinfo=ET)
    mon_close = datetime(2026, 3, 9, 16, 0, tzinfo=ET)
    tte = time_to_expiry_years("2026-03-09", now=fri)
    stamp_years = (mon_close.timestamp() - fri.timestamp()) / YEAR_SECONDS
    civil_years = (mon_close - fri).total_seconds() / YEAR_SECONDS
    assert tte is not None
    assert tte == max(stamp_years, MIN_TIME_TO_EXPIRY_YEARS)
    assert civil_years > stamp_years
    assert round((civil_years - stamp_years) * YEAR_SECONDS / 3600.0, 1) == 1.0


def test_a_contract_is_priced_to_its_own_settlement_whatever_the_ticker():
    """TICK-05 (2026-09-28 audit): T ran to 16:00 for every contract, so an AM-settled $SPX
    monthly (Schwab settlementType "A", lastTradingDay the Thursday before) kept gamma all
    expiration Friday after its value was set at the open. One rule, read from each contract:
    real $SPX (A) and SPXW (P) contracts of the same expiration, and a real TSLA (P) one."""
    import json
    from pathlib import Path

    from math_levels import contract_inputs
    fx = Path(__file__).parent / "fixtures"
    spx = json.loads((fx / "real_spx_chain_contracts_2026_09_28.json").read_text(encoding="utf-8"))["contracts"]
    am = [c for c in spx if c["settlementType"] == "A"]
    pm = [c for c in spx if c["settlementType"] == "P"]
    tsla = json.loads((fx / "real_tsla_complete_chain_strike_range_all.json").read_text(encoding="utf-8"))
    equity = [dict(c, openInterest=100, expirationDate="2026-10-16T20:00:00.000+00:00")   # stand-in: its OI and date
              for c in tsla["chain"] if c.get("volatility")][:4]
    assert am and pm and equity and all(c["settlementType"] == "P" for c in equity)

    thu_close = datetime(2026, 10, 15, 15, 30, tzinfo=ET)
    fri_open, fri_close = datetime(2026, 10, 16, 9, 30, tzinfo=ET), datetime(2026, 10, 16, 16, 0, tzinfo=ET)
    t_am = contract_inputs(am, now=thu_close)[0][0][3]
    t_pm = contract_inputs(pm, now=thu_close)[0][0][3]
    assert round(t_am * 365 * 24, 2) == round((fri_open - thu_close).total_seconds() / 3600, 2)
    assert round(t_pm * 365 * 24, 2) == round((fri_close - thu_close).total_seconds() / 3600, 2)

    fri_ten = datetime(2026, 10, 16, 10, 0, tzinfo=ET)
    assert contract_inputs(am, now=fri_ten) == ([], {"settled": len(am)})
    assert len(contract_inputs(pm, now=fri_ten)[0]) == len(pm)
    assert len(contract_inputs(equity, now=fri_ten)[0]) == len(equity)
