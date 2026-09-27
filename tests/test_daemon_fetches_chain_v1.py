"""P2-1: the daemon holds the one chain fetch (DATA_FLOW 4.1). Its `chain.<ticker>` message
carries every contract as Schwab sent it, compressed for the push socket; the history capture
writes the newest fetched chain instead of fetching again; the refresh runs in its one window.
Real CRWD chain (tests/fixtures)."""
import json
import sqlite3

import pytest
from datetime import datetime
from pathlib import Path

from app.market_data.schwab.streaming.live_push import is_forwarded
from calibration.complete_chain_capture import CAPTURE_MAX_CHAIN_AGE_SEC, capture_round, last_capture_per_day
from stream_spine import chain_contracts, chain_msg
from time_et import ET, chain_refresh_open

FX = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_crwd_complete_chain_quarter.json")
                .read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _at_capture(pin_clock):
    """Valued at the CRWD chain's capture (2026-09-02)."""
    return pin_clock(2026, 9, 2, 12, 0)


def test_the_chain_message_carries_every_contract_as_sent_and_compressed():
    msg = chain_msg(symbol="CRWD", contracts=FX["chain"], spot=FX["spot"], status="ok", ts_recv=1_790_000_000.0)
    assert chain_contracts(msg) == FX["chain"]
    raw = len(json.dumps(FX["chain"]))
    assert len(msg["z"]) < raw / 4, (len(msg["z"]), raw)        # the push socket sends a short string
    assert is_forwarded("chain.CRWD", msg)


def test_a_refused_chain_is_a_message_with_its_reason_and_no_contracts():
    msg = chain_msg(symbol="XXT", contracts=None, spot=None, status="error", reason="HTTP 400 Bad Request")
    assert msg["z"] is None and chain_contracts(msg) == [] and msg["reason"].startswith("HTTP 4")


def _board(tmp_path, tickers):
    db = tmp_path / "ed.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE logging_universe (ticker TEXT)")
    con.executemany("INSERT INTO logging_universe VALUES (?)", [(t,) for t in tickers])
    con.commit(); con.close()
    return db


def test_the_capture_writes_the_newest_fetched_chain(tmp_path):
    db = _board(tmp_path, ["CRWD", "SPY"])
    now = 1_790_000_000.0
    latest = {"chain.CRWD": chain_msg(symbol="CRWD", contracts=FX["chain"], spot=FX["spot"], status="ok",
                                      ts_recv=now - 10)}
    out = capture_round(latest, db, now)
    assert out == {"written": 1, "failed": ["SPY"]}               # SPY: no chain fetched
    (day,) = last_capture_per_day(db, "CRWD", 1)
    assert day["spot"] == FX["spot"] and len(day["contracts"]) == len(FX["chain"])


def test_a_chain_older_than_the_limit_is_not_written_as_this_capture(tmp_path):
    db = _board(tmp_path, ["CRWD"])
    now = 1_790_000_000.0
    stale = {"chain.CRWD": chain_msg(symbol="CRWD", contracts=FX["chain"], spot=FX["spot"], status="ok",
                                     ts_recv=now - CAPTURE_MAX_CHAIN_AGE_SEC - 1)}
    assert capture_round(stale, db, now) == {"written": 0, "failed": ["CRWD"]}


def test_the_refresh_window_is_the_market_day_from_845_to_30_minutes_after_the_close():
    assert chain_refresh_open(datetime(2026, 9, 28, 8, 45, tzinfo=ET))        # Monday
    assert chain_refresh_open(datetime(2026, 9, 28, 16, 30, tzinfo=ET))
    assert not chain_refresh_open(datetime(2026, 9, 28, 8, 44, tzinfo=ET))
    assert not chain_refresh_open(datetime(2026, 9, 28, 16, 31, tzinfo=ET))
    assert not chain_refresh_open(datetime(2026, 9, 27, 12, 0, tzinfo=ET))     # Sunday
