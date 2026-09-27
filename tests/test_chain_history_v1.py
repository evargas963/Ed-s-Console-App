"""The chain history (DATA_FLOW decision 7): the capture clock and one capture round."""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime

import pytest

import calibration.complete_chain_capture as cch
from json_blob_codec import decode_json_blob
from time_et import ET


def _ts(s: str) -> float:
    return datetime.fromisoformat(s).replace(tzinfo=ET).timestamp()


def _et(ts: float) -> str:
    return datetime.fromtimestamp(ts, ET).strftime("%Y-%m-%d %H:%M")


@pytest.mark.parametrize("now, expected", [
    ("2026-09-28 08:00", "2026-09-28 09:30"),   # Monday before the open
    ("2026-09-28 09:30", "2026-09-28 10:00"),   # strictly after now
    ("2026-09-28 15:45", "2026-09-28 16:00"),
    ("2026-09-28 16:00", "2026-09-28 16:15"),   # the close capture: options trade to 16:15
    ("2026-09-28 16:15", "2026-09-29 09:30"),   # nothing after it
    ("2026-09-26 12:00", "2026-09-28 09:30"),   # Saturday: next market day
    ("2026-11-25 16:30", "2026-11-27 09:30"),   # Thanksgiving is skipped
    ("2026-11-27 12:45", "2026-11-27 13:00"),
    ("2026-11-27 13:00", "2026-11-27 13:15"),   # early close: the close capture at 13:15
    ("2026-11-27 13:15", "2026-11-30 09:30"),
    ("2026-11-02 09:00", "2026-11-02 09:30"),   # after the DST change, still 9:30 ET
])
def test_capture_clock(now, expected):
    assert _et(cch.next_capture_ts(_ts(now))) == expected


def test_fifteen_captures_on_a_full_day():
    ts, day = _ts("2026-09-28 00:00"), []
    while True:
        ts = cch.next_capture_ts(ts)
        if _et(ts)[:10] != "2026-09-28":
            break
        day.append(_et(ts)[11:])
    assert day == [f"{h:02d}:{m:02d}" for h in range(9, 17) for m in (0, 30)
                   if (9, 30) <= (h, m) <= (16, 0)] + ["16:15"]
    assert len(day) == 15


class _Resp:
    def __init__(self, code, payload=None):
        self.status_code = code
        self._p = payload or {}

    def json(self):
        return self._p


def _chain(price, expiries):
    # institutional-synthetic-ok: transport test -- the capture groups contracts by
    # expirationDate and stores them verbatim; no contract field is priced here.
    ct = lambda e, side: {"symbol": f"ZZ {e}{side}", "putCall": side, "strikePrice": 100.0,
                          "expirationDate": f"{e}T20:00:00.000+00:00", "openInterest": 7}
    return {"underlyingPrice": price,
            "callExpDateMap": {f"{e}:1": {"100.0": [ct(e, "CALL")]} for e in expiries},
            "putExpDateMap": {f"{e}:1": {"100.0": [ct(e, "PUT")]} for e in expiries}}


@pytest.fixture
def board_db(tmp_path):
    db = tmp_path / "ed_console.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE logging_universe (ticker TEXT PRIMARY KEY, category TEXT)")
        c.executemany("INSERT INTO logging_universe VALUES (?, 'core')", [("AAA",), ("BBB",), ("CCC",)])
    return db


def test_a_round_writes_every_expiry_with_schwabs_own_price(board_db, monkeypatch):
    answers = {"AAA": _Resp(200, _chain(101.5, ["2030-01-04", "2030-01-11"])),
               "BBB": _Resp(200, _chain(-999, ["2030-01-04"])),
               "CCC": _Resp(400)}
    monkeypatch.setattr(cch, "safe_get_chain", lambda client, tk, **k: answers[tk])
    result = cch.capture_round(object(), board_db)
    assert result == {"written": 2, "failed": ["CCC"]}
    with sqlite3.connect(board_db) as c:
        rows = c.execute("SELECT ticker, expiry, spot, n_contracts, chain_json "
                         "FROM complete_chain_captures ORDER BY ticker, expiry").fetchall()
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [
        ("AAA", "2030-01-04", 101.5, 2), ("AAA", "2030-01-11", 101.5, 2),
        ("BBB", "2030-01-04", None, 2)]          # -999 is Schwab's "no number"
    assert isinstance(rows[0][4], bytes), "stored compressed"
    assert {c["putCall"] for c in decode_json_blob(rows[0][4])} == {"CALL", "PUT"}


def test_the_daemon_task_stops_when_told(monkeypatch):
    from app.market_data.schwab.streaming import capture

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(capture.capture_chains(lambda: None, stop))
        await asyncio.sleep(0)
        stop.set()
        await asyncio.wait_for(task, timeout=2)
        return task
    task = asyncio.run(go())
    assert task.done() and task.exception() is None


def test_the_reader_gives_the_last_full_capture_of_each_day(tmp_path):
    db = tmp_path / "ed_console.db"
    # institutional-synthetic-ok: the reader returns stored contracts verbatim; none is priced.
    ct = lambda e: {"symbol": f"ZZ {e}", "expirationDate": f"{e}T20:00:00.000+00:00"}
    def put(when, spot, expiries, basis=cch.CAPTURE_BASIS):
        for e in expiries:
            cch.persist_complete_chain_capture(
                db, ticker="ZZ", expiry=e, contracts=[ct(e)], spot=spot,
                completeness_basis=basis, ts_utc=_ts(when))
    put("2026-09-24 15:30", 10.0, ["2030-01-04"])
    put("2026-09-24 16:00", 11.0, ["2030-01-04", "2030-01-11"])       # Thursday's last
    put("2026-09-25 16:00", 12.0, ["2030-01-04", "2030-01-11"])       # Friday's last
    put("2026-09-25 16:05", 99.0, ["2030-01-04"], basis="strike_range=ALL")  # old row
    caps = cch.last_capture_per_day(db, "ZZ", 2)
    assert [(c["et_date"], c["spot"], len(c["contracts"])) for c in caps] == [
        ("2026-09-25", 12.0, 2), ("2026-09-24", 11.0, 2)]
    prior = cch.last_capture_per_day(db, "ZZ", 1, before_et_date="2026-09-25")
    assert [(c["et_date"], c["spot"]) for c in prior] == [("2026-09-24", 11.0)]


def test_the_friday_morning_copy_is_read_and_labelled(tmp_path):
    db = tmp_path / "ed_console.db"
    # institutional-synthetic-ok: the reader returns stored contracts verbatim; none is priced.
    ct = {"symbol": "ZZ 2030-01-04", "expirationDate": "2030-01-04T20:00:00.000+00:00"}
    cch.persist_complete_chain_capture(db, ticker="ZZ", expiry="2030-01-04", contracts=[ct],
                                       spot=5.0, completeness_basis=cch.MORNING_BASIS,
                                       ts_utc=_ts("2026-09-25 10:00"))
    caps = cch.last_capture_per_day(db, "ZZ", 1)
    assert [(c["et_date"], c["basis"]) for c in caps] == [("2026-09-25", cch.MORNING_BASIS)]
