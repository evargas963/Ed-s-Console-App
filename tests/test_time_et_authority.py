"""Single ET authority: DST-aware America/New_York, and T to each contract's own settlement.

The settlement as Schwab's /markets sends it (tests/conftest.py holds the answers captured
2026-10-07).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

from math_levels import contract_inputs
from option_contract import read_chain
from time_et import (
    ET,
    MIN_TIME_TO_EXPIRY_YEARS,
    YEAR_SECONDS,
    elapsed,
    now_et,
    set_within,
    time_to_expiry_years,
)


def test_a_wait_for_an_event_answers_whether_it_was_set_and_leaves_no_task_behind():
    """time_et.set_within: False once the time passes with the event unset, True once it is set.

    True as soon as it is set (not at the end of the time), and no waiting task is left running
    after either.
    """

    async def go():
        event = asyncio.Event()
        started = elapsed()
        unset = await set_within(event, 0.05)
        waited = elapsed() - started
        asyncio.get_running_loop().call_later(0.01, event.set)
        started = elapsed()
        is_set = await set_within(event, 5.0)
        await asyncio.sleep(0)  # a cancelled waiter ends on the loop's next turn
        left = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        return unset, waited, is_set, elapsed() - started, left

    unset, waited, is_set, took, left = asyncio.run(go())
    assert (unset, is_set, left) == (False, True, [])
    assert waited >= 0.05 and took < 1.0


def test_now_et_uses_america_new_york_zone():
    dt = now_et()
    assert dt.tzinfo is not None
    assert str(dt.tzinfo) in ("America/New_York", "America/New_York EST", "America/New_York EDT")
    assert dt.utcoffset() is not None


def test_dst_offset_differs_summer_vs_winter():
    winter = datetime(2026, 1, 15, 12, 0, tzinfo=ET)
    summer = datetime(2026, 7, 15, 12, 0, tzinfo=ET)
    assert winter.utcoffset() != summer.utcoffset()
    assert winter.utcoffset().total_seconds() == -5 * 3600
    assert summer.utcoffset().total_seconds() == -4 * 3600


def test_time_to_expiry_years_uses_timestamp_elapsed_not_civil_timedelta():
    # DST ends 2026-11-01: the elapsed span from Friday to Monday's close is 1 h longer than the
    # civil wall-clock one. Monday's close is the 16:00 ET Schwab's /markets sent for EQO.
    fri = datetime(2026, 10, 30, 10, 30, tzinfo=ET)
    mon_close = datetime(2026, 11, 2, 16, 0, tzinfo=ET)
    tte = time_to_expiry_years("2026-11-02", now=fri)
    stamp_years = (mon_close.timestamp() - fri.timestamp()) / YEAR_SECONDS
    civil_years = (mon_close - fri).total_seconds() / YEAR_SECONDS
    assert tte is not None
    assert tte == max(stamp_years, MIN_TIME_TO_EXPIRY_YEARS)
    assert stamp_years > civil_years
    assert round((stamp_years - civil_years) * YEAR_SECONDS / 3600.0, 1) == 1.0


def test_a_contract_is_priced_to_its_own_settlement_whatever_the_ticker():
    """TICK-05 (2026-09-28 audit): T ran to 16:00 for every contract.

    So an AM-settled $SPX monthly (Schwab settlementType "A", lastTradingDay the Thursday
    before) kept gamma all expiration Friday after its value was set at the open. One rule, read
    from each contract: real $SPX (A) and SPXW (P) contracts of the same expiration, and a real
    TSLA (P) one.
    """
    fx = Path(__file__).parent / "fixtures"
    spx = json.loads((fx / "real_spx_chain_contracts_2026_09_28.json").read_text(encoding="utf-8"))[
        "contracts"
    ]
    am = [c for c in spx if c["settlementType"] == "A"]
    pm = [c for c in spx if c["settlementType"] == "P"]
    tsla = json.loads(
        (fx / "real_tsla_complete_chain_strike_range_all.json").read_text(encoding="utf-8")
    )
    equity = [
        dict(
            c, openInterest=100, expirationDate="2026-10-16T20:00:00.000+00:00"
        )  # stand-in: its OI and date
        for c in tsla["chain"]
        if c.get("volatility")
    ][:4]
    assert am and pm and equity and all(c["settlementType"] == "P" for c in equity)
    am, pm, equity = read_chain(am), read_chain(pm), read_chain(equity)

    thu_close = datetime(2026, 10, 15, 15, 30, tzinfo=ET)
    fri_open, fri_close = (
        datetime(2026, 10, 16, 9, 30, tzinfo=ET),
        datetime(2026, 10, 16, 16, 0, tzinfo=ET),
    )
    t_am = contract_inputs(am, now=thu_close)[0][0][3]
    t_pm = contract_inputs(pm, now=thu_close)[0][0][3]
    assert round(t_am * 365 * 24, 2) == round((fri_open - thu_close).total_seconds() / 3600, 2)
    assert round(t_pm * 365 * 24, 2) == round((fri_close - thu_close).total_seconds() / 3600, 2)

    fri_ten = datetime(2026, 10, 16, 10, 0, tzinfo=ET)
    assert contract_inputs(am, now=fri_ten) == ([], {"settled": len(am)})
    assert len(contract_inputs(pm, now=fri_ten)[0]) == len(pm)
    assert len(contract_inputs(equity, now=fri_ten)[0]) == len(equity)
