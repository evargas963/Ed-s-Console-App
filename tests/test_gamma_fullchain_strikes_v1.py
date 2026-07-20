"""FIND-GAMMA-FULLCHAIN-STRIKES-V1 — wide morning capture helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from calibration.option_chain_morning_full import (
    GEX_FULL_CHAIN_STRIKE_COUNT,
    SOURCE_WIDE,
    et_date_and_mins,
    filter_near_term_contracts,
    has_morning_full_capture,
    maybe_persist_morning_full_chain,
)
from time_et import ET


def test_gex_full_chain_strike_count_is_wide_not_ui_20() -> None:
    assert GEX_FULL_CHAIN_STRIKE_COUNT == 100
    import server as srv

    assert srv.CHAIN_STRIKE_COUNT == 20
    assert srv.GEX_FULL_CHAIN_STRIKE_COUNT == 100


def test_has_morning_full_capture_false_then_true(tmp_path: Path) -> None:
    # institutional-synthetic-ok: near-term-filter/capture test needs controlled DTEs
    # (incl. 120 to prove the <=37 boundary) and exact strike counts to prove no thinning;
    # this exercises the DTE filter + persistence, not gamma/GEX correctness.
    db = tmp_path / "gex.db"
    # Morning ET window: build a UTC ts that is 09:40 America/Chicago
    local = datetime(2026, 7, 20, 9, 40, tzinfo=ET)
    ts = local.astimezone(timezone.utc).timestamp()
    et_date, mins = et_date_and_mins(ts)
    assert 570 <= mins <= 600
    assert has_morning_full_capture(db, "SPY", et_date) is False

    contracts = []
    for exp_off, dte in ((0, 0), (7, 7), (21, 21)):
        day = f"2026-07-{20 + exp_off:02d}" if exp_off < 11 else "2026-08-10"
        for i in range(40):
            strike = 700.0 + i
            contracts.append(
                {
                    "putCall": "CALL" if i % 2 == 0 else "PUT",
                    "strikePrice": strike,
                    "expirationDate": f"{day}T20:00:00.000+00:00",
                    "daysToExpiration": dte,
                    "gamma": 0.01,
                    "openInterest": 10,
                    "delta": 0.5 if i % 2 == 0 else -0.5,
                    "multiplier": 100,
                }
            )
    # ensure near-term filter keeps far calendar within 37d
    contracts.append(
        {
            "putCall": "PUT",
            "strikePrice": 600.0,
            "expirationDate": "2026-08-15T20:00:00.000+00:00",
            "daysToExpiration": 26,
            "gamma": 0.02,
            "openInterest": 50,
            "delta": -0.2,
            "multiplier": 100,
        }
    )
    contracts.append(
        {
            "putCall": "PUT",
            "strikePrice": 500.0,
            "expirationDate": "2026-12-01T20:00:00.000+00:00",
            "daysToExpiration": 120,
            "gamma": 0.01,
            "openInterest": 99,
            "delta": -0.1,
            "multiplier": 100,
        }
    )

    near = filter_near_term_contracts(contracts)
    assert all(c["daysToExpiration"] <= 37 for c in near)
    assert not any(c.get("daysToExpiration") == 120 for c in near)
    # all strikes on kept expiries retained (not strike-thinned by filter)
    strikes_dte0 = {c["strikePrice"] for c in near if c["daysToExpiration"] == 0}
    assert len(strikes_dte0) == 40

    res = maybe_persist_morning_full_chain(
        db,
        ticker="SPY",
        contracts=contracts,
        spot=720.0,
        ts_utc=ts,
        source=SOURCE_WIDE,
    )
    assert res["status"] == "ok"
    assert has_morning_full_capture(db, "SPY", et_date) is True
    # second call skips without needing another fetch
    res2 = maybe_persist_morning_full_chain(
        db,
        ticker="SPY",
        contracts=contracts,
        spot=720.0,
        ts_utc=ts,
        source=SOURCE_WIDE,
    )
    assert res2["status"] == "idempotent_skip"
