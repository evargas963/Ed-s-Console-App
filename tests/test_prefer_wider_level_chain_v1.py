"""RC-475: live level math may use a same-session wider archive when live is too narrow."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from calibration.option_chain_morning_full import (
    TABLE_SQL,
    load_morning_full_contracts,
)
from math_levels import (
    LEVEL_CHAIN_LIVE,
    LEVEL_CHAIN_MORNING_FULL,
    prefer_wider_level_chain,
    required_strike_count,
    unique_strike_count,
)


def _chain(strikes: list[float]) -> list[dict]:
    return [{"strikePrice": s, "openInterest": 10} for s in strikes]


def test_unique_strike_count_ignores_junk():
    assert unique_strike_count([]) == 0
    assert unique_strike_count(_chain([100.0, 101.0, 100.0])) == 2
    assert unique_strike_count([{"strikePrice": "x"}, {"strikePrice": 5.0}]) == 1


def test_prefer_archive_when_live_below_required_span():
    spot = 100.0
    live = _chain([99.0, 100.0, 101.0])  # 3 strikes
    archive = _chain([float(i) for i in range(90, 111)])  # 21 strikes
    need = required_strike_count(spot, 1.0)
    assert need is not None and unique_strike_count(live) < need
    out, src = prefer_wider_level_chain(live, archive, spot=spot, increment=1.0)
    assert src == LEVEL_CHAIN_MORNING_FULL
    assert unique_strike_count(out) == unique_strike_count(archive)


def test_keep_live_when_already_wide_enough():
    spot = 100.0
    live = _chain([float(i) for i in range(90, 111)])
    archive = _chain([float(i) for i in range(80, 121)])
    out, src = prefer_wider_level_chain(live, archive, spot=spot, increment=1.0)
    assert src == LEVEL_CHAIN_LIVE
    assert unique_strike_count(out) == unique_strike_count(live)


def test_keep_live_when_archive_is_not_wider():
    live = _chain([99.0, 100.0, 101.0])
    archive = _chain([100.0, 101.0])
    out, src = prefer_wider_level_chain(live, archive, spot=100.0, increment=1.0)
    assert src == LEVEL_CHAIN_LIVE
    assert out == live


def test_load_morning_full_contracts_roundtrip(tmp_path: Path):
    db = tmp_path / "mf.db"
    conn = sqlite3.connect(str(db))
    conn.execute(TABLE_SQL)
    chain = _chain([90.0, 100.0, 110.0])
    conn.execute(
        "INSERT INTO option_chain_morning_full "
        "(ticker, et_date, ts_utc, spot, n_contracts, n_expiries, max_dte, chain_json, source) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("SPY", "2026-08-24", 1.0, 100.0, 3, 1, 1.0, json.dumps(chain), "test"),
    )
    conn.commit()
    conn.close()
    loaded = load_morning_full_contracts(db, "spy", "2026-08-24")
    assert loaded is not None
    assert unique_strike_count(loaded) == 3
    assert load_morning_full_contracts(db, "SPY", "2026-08-25") is None
