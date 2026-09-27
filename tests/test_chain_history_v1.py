"""The chain history (DATA_FLOW decision 7): the capture clock and one capture round."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

import calibration.complete_chain_capture as cch
from json_blob_codec import decode_json_blob
from schwab_client import flatten_chain_contracts
from stream_spine import chain_contracts, chain_msg
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


_FX = Path(__file__).resolve().parent / "fixtures"
#: real MRVL full chain (every strike of every expiry, Schwab as sent, 2026-09-25); its payload
#: carries no underlyingPrice, so its spot is absent as sent
_MRVL = json.loads((_FX / "real_mrvl_full_chain_vs_strike_window.json").read_text(encoding="utf-8"))["full"]
#: real CRWD single-expiry chain with its underlying price (2026-09-02)
_CRWD = json.loads((_FX / "real_crwd_complete_chain_quarter.json").read_text(encoding="utf-8"))


@pytest.fixture
def board_db(tmp_path):
    db = tmp_path / "ed_console.db"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE logging_universe (ticker TEXT PRIMARY KEY, category TEXT)")
        c.executemany("INSERT INTO logging_universe VALUES (?, 'core')", [("MRVL",), ("CRWD",), ("XXT",)])
    return db


def test_a_round_writes_every_expiry_with_schwabs_own_price(board_db, pin_clock):
    # P2-1: the daemon fetches the chain; the round writes the newest pushed chain message
    pin_clock(2026, 9, 25, 12, 0)                     # the MRVL chain's capture day
    now = _ts("2026-09-25 12:00")
    mrvl = flatten_chain_contracts(_MRVL)
    latest = {"chain.MRVL": chain_msg(symbol="MRVL", contracts=mrvl, spot=None, status="ok", ts_recv=now - 5),
              "chain.CRWD": chain_msg(symbol="CRWD", contracts=_CRWD["chain"], spot=_CRWD["spot"],
                                      status="ok", ts_recv=now - 5),
              "chain.XXT": chain_msg(symbol="XXT", contracts=None, spot=None, status="error",
                                     reason="HTTP 400 Bad Request", ts_recv=now - 5)}
    result = cch.capture_round(latest, board_db, now)
    assert result == {"written": 2, "failed": ["XXT"]}
    with sqlite3.connect(board_db) as c:
        rows = c.execute("SELECT ticker, expiry, spot, n_contracts, chain_json "
                         "FROM complete_chain_captures ORDER BY ticker, expiry").fetchall()
    mrvl_expiries = sorted({str(ct["expirationDate"])[:10] for ct in mrvl})
    assert len(mrvl_expiries) > 1
    assert [(r[0], r[1], r[2]) for r in rows] == (
        [("CRWD", "2026-09-18", _CRWD["spot"])] + [("MRVL", e, None) for e in mrvl_expiries])
    assert sum(r[3] for r in rows if r[0] == "MRVL") == len(mrvl), "every contract of every expiry"
    assert isinstance(rows[0][4], bytes), "stored compressed"
    assert {c["putCall"] for c in decode_json_blob(rows[0][4])} == {"CALL", "PUT"}


def test_the_chain_fetch_takes_schwabs_price_as_sent(monkeypatch, pin_clock):
    """-999 is Schwab's "no number" (P2-1: the daemon fetches the chain; this check moved from
    the capture round to the one fetch)."""
    pin_clock(2026, 9, 25, 12, 0)                     # the MRVL chain's capture day

    class _Resp:
        status_code, reason = 200, ""

        def __init__(self, payload):
            self._p = payload

        def json(self):
            return self._p

    for sent, expected in ((-999, None), (263.51, 263.51)):
        # stand-in: the real MRVL payload with underlyingPrice set to `sent`
        payload = dict(_MRVL, underlyingPrice=sent)
        monkeypatch.setattr(cch, "safe_get_chain", lambda client, tk, _p=payload, **k: _Resp(_p))
        topic, msg = cch.fetch_chain(object(), "MRVL")
        assert topic == "chain.MRVL" and msg["status"] == "ok" and msg["spot"] == expected
        assert len(chain_contracts(msg)) == len(flatten_chain_contracts(_MRVL))


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


def test_the_console_refresh_window_follows_the_days_close_in_central_time():
    """7:45 AM CT to 30 minutes after the close; an early close ends early (checked 2026-09-27:
    the window ran to 3:30 PM CT on early-close days, and was shown in ET)."""
    import server
    assert server._refresh_window_ct("2026-09-28") == "7:45 AM-3:30 PM CT"
    assert server._refresh_window_ct("2026-11-27") == "7:45 AM-12:30 PM CT"
    assert server._refresh_window_et("2026-09-27") is None      # Sunday
    assert server._refresh_window_et("2026-11-26") is None      # Thanksgiving
