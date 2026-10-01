"""The daemon's chain sweep (DATA_FLOW decisions 1 and 7): the one fetcher of every board ticker's
chain, what it hands the console, and the chain history it writes.

Real data (tests/fixtures/real_spy_2026_11_20_chain_and_quotes.json): SPY's 2026-11-20 contracts
from the capture daemon's full-chain capture of 2026-09-30 15:31:57 ET, and Schwab's quotes for
every one of them. Schwab's network is the only stand-in (`_Schwab`): it answers the chain with the
captured contracts and each quotes request with the recorded quotes."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import pytest

import calibration.complete_chain_capture as cch
from app.options.order_flow import streaming as ofs
from json_blob_codec import decode_json_blob
from time_et import ET

_FX = json.loads((Path(__file__).resolve().parent / "fixtures"
                  / "real_spy_2026_11_20_chain_and_quotes.json").read_text(encoding="utf-8"))
_QUOTED = {s: e["quote"] for q in _FX["quotes"] for s, e in q["reply"].items()}


def _ts(s: str) -> float:
    return datetime.fromisoformat(s).replace(tzinfo=ET).timestamp()


def _et(ts: float) -> str:
    return datetime.fromtimestamp(ts, ET).strftime("%Y-%m-%d %H:%M")


@pytest.mark.parametrize("now, slot", [
    ("2026-09-28 08:00", None),                 # Monday before the open: nothing written
    ("2026-09-28 09:30", "2026-09-28 09:30"),
    ("2026-09-28 09:59", "2026-09-28 09:30"),
    ("2026-09-28 15:45", "2026-09-28 15:30"),
    ("2026-09-28 16:05", "2026-09-28 16:00"),
    ("2026-09-28 16:20", "2026-09-28 16:15"),   # the close capture: options trade to 16:15
    ("2026-09-28 16:46", None),                 # nothing after the close capture's window
    ("2026-09-26 12:00", None),                 # Saturday
    ("2026-11-26 12:00", None),                 # Thanksgiving
    ("2026-11-27 13:10", "2026-11-27 13:00"),   # early close
    ("2026-11-27 13:20", "2026-11-27 13:15"),   # early close: the close capture at 13:15
    ("2026-11-02 09:31", "2026-11-02 09:30"),   # after the DST change, still 9:30 ET
])
def test_the_capture_window_a_fetch_is_written_for(now, slot):
    got = cch.capture_slot(_ts(now))
    assert (_et(got) if got is not None else None) == slot


def test_fifteen_capture_windows_on_a_full_day():
    slots = {cch.capture_slot(_ts(f"2026-09-28 {h:02d}:{m:02d}"))
             for h in range(0, 24) for m in range(0, 60)} - {None}
    assert sorted(_et(s)[11:] for s in slots) == [
        f"{h:02d}:{m:02d}" for h in range(9, 17) for m in (0, 30)
        if (9, 30) <= (h, m) <= (16, 0)] + ["16:15"]


class _Resp:
    def __init__(self, code, payload=None):
        self.status_code = code
        self._p = payload if payload is not None else {}

    def json(self):
        return self._p


class _Schwab:
    """Schwab's network (the stand-in): the captured SPY chain for SPY, `refused` codes per
    ticker, and the recorded quotes; every request is counted."""

    def __init__(self, refused: "dict | None" = None, quotes_refused: "int | None" = None):
        self.refused = refused or {}
        self.quotes_refused = quotes_refused
        self.chains: "list[str]" = []
        self.quotes = 0

    def chain(self, client, ticker, **kw):
        self.chains.append(ticker)
        if ticker in self.refused:
            return _Resp(self.refused[ticker])
        payload = {"symbol": ticker, "underlyingPrice": _FX["spot"], "callExpDateMap": {}, "putExpDateMap": {}}
        for ct in json.loads(json.dumps(_FX["chain"])):
            side = "callExpDateMap" if ct["putCall"] == "CALL" else "putExpDateMap"
            payload[side].setdefault(f"{ct['expirationDate'][:10]}:{ct['daysToExpiration']}", {}) \
                .setdefault(str(ct["strikePrice"]), []).append(ct)
        return _Resp(200, payload)

    def quote(self, client, symbols):
        self.quotes += 1
        if self.quotes_refused is not None:
            return _Resp(self.quotes_refused)
        return _Resp(200, {s: {"symbol": s, "quote": dict(_QUOTED[s])} for s in symbols if s in _QUOTED})


@pytest.fixture
def schwab(monkeypatch):
    net = _Schwab()
    monkeypatch.setattr(cch, "safe_get_chain", net.chain)
    monkeypatch.setattr(cch, "safe_get_quotes", net.quote)
    return net


def _sweep(tmp_path, board, at):
    sqlite3.connect(tmp_path / "ed_console.db").close()          # the daemon's database exists
    published: list = []
    clock = {"now": _ts(at)}
    sweep = cch.ChainSweep(tmp_path / "ed_console.db", lambda: list(board),
                           lambda topic, msg: published.append((topic, msg)), clock=lambda: clock["now"])
    return sweep, published, clock


def _assembled(published):
    ofs._chain_parts.clear()
    out = [ofs.assemble_chain_part(json.loads(msg["frame"])["msg"]) for _t, msg in published]
    return [o for o in out if o is not None]


def test_each_fetch_reaches_the_console_whole_in_parts_with_schwabs_exact_greeks(tmp_path, schwab, monkeypatch):
    monkeypatch.setattr(cch, "CHAIN_PART_CONTRACTS", 100)
    sweep, published, _clock = _sweep(tmp_path, ["SPY"], "2026-09-30 15:31:57")
    sweep.fetch_one(object(), "SPY")
    assert [m["part"] for _t, m in published] == [0, 1, 2, 3, 4]           # 442 contracts
    (tk, contracts, ts, reason), = _assembled(published)
    assert (tk, ts, reason) == ("SPY", _ts("2026-09-30 15:31:57"), None)
    assert sorted(c["symbol"] for c in contracts) == sorted(c["symbol"] for c in _FX["chain"])
    assert all(c["gamma"] == _QUOTED[c["symbol"]]["gamma"] for c in contracts)


def test_a_chain_missing_a_part_is_never_priced_and_says_why(tmp_path, schwab, monkeypatch):
    monkeypatch.setattr(cch, "CHAIN_PART_CONTRACTS", 100)
    sweep, published, clock = _sweep(tmp_path, ["SPY"], "2026-09-30 15:31:57")
    sweep.fetch_one(object(), "SPY")
    del published[2]                                     # one part lost on the way
    clock["now"] += 240
    sweep.fetch_one(object(), "SPY")                     # the next chain begins
    first, second = _assembled(published)
    assert first[1] is None and "arrived with 4 of its 5 parts" in first[3]
    assert second[1] is not None and second[3] is None


def test_a_refused_chain_reaches_the_console_as_schwabs_answer(tmp_path, schwab):
    schwab.refused = {"SPY": 400}
    sweep, published, _clock = _sweep(tmp_path, ["SPY"], "2026-09-30 15:31:57")
    sweep.fetch_one(object(), "SPY")
    (tk, contracts, _ts_, reason), = _assembled(published)
    assert tk == "SPY" and contracts is None and "HTTP 400" in reason


def test_a_429_pauses_every_chain_request(tmp_path, schwab):
    schwab.quotes_refused = 429
    sweep, _published, _clock = _sweep(tmp_path, ["SPY"], "2026-09-30 15:31:57")
    sweep.fetch_one(object(), "SPY")
    assert sweep._paused_until == _ts("2026-09-30 15:31:57") + cch.RATE_LIMITED_PAUSE_SEC


def test_the_history_is_written_once_per_capture_window_and_never_outside_one(tmp_path, schwab):
    db = tmp_path / "ed_console.db"
    sweep, _published, clock = _sweep(tmp_path, ["SPY"], "2026-09-30 15:31:57")
    for at in ("2026-09-30 15:31:57", "2026-09-30 15:35:00",      # the 15:30 window, twice
               "2026-09-30 16:01:00",                             # the 16:00 window
               "2026-09-30 17:00:00"):                            # after the close capture's window
        clock["now"] = _ts(at)
        sweep.fetch_one(object(), "SPY")
    with sqlite3.connect(db) as c:
        rows = c.execute("SELECT ts_utc, expiry, spot, n_contracts, chain_json FROM complete_chain_captures "
                         "ORDER BY ts_utc").fetchall()
    assert [(_et(r[0]), r[1], r[2], r[3]) for r in rows] == [
        ("2026-09-30 15:31", "2026-11-20", 766.31, 442), ("2026-09-30 16:01", "2026-11-20", 766.31, 442)]
    assert isinstance(rows[0][4], bytes), "stored compressed"
    stored = {c["symbol"]: c for c in decode_json_blob(rows[0][4])}
    assert all(stored[s]["gamma"] == q["gamma"] for s, q in _QUOTED.items()), "the quote's gamma is stored"


def test_the_sweep_fetches_every_board_ticker_in_turn_and_a_new_one_first(tmp_path, schwab):
    board = ["AAA", "BBB", "CCC"]
    sweep, _published, clock = _sweep(tmp_path, board, "2026-09-30 15:31:57")
    order = [sweep._next(clock["now"]) for _ in range(3)]
    sweep.fetch_next("NEW")
    order += [sweep._next(clock["now"] + 200)]
    order += [sweep._next(clock["now"] + 200)]
    assert order == ["AAA", "BBB", "CCC", "NEW", "AAA"]
    assert sweep.round_sec == 200                       # the round it delivered


@pytest.mark.parametrize("at", ["2026-10-01 08:08", "2026-10-01 09:45", "2026-10-01 21:00",
                                "2026-10-03 12:00"], ids=["pre-market", "the-open", "after-hours", "saturday"])
def test_every_board_ticker_is_fetched_at_any_hour(tmp_path, schwab, at):
    """2026-10-01 07:08 CT (08:08 ET): a restarted console fetched no chain pre-market -- its loop
    sat behind an archival window. The daemon's sweep fetches every board ticker's chain whatever
    the hour; only the history write keeps to the capture windows."""
    import threading

    board = ["SPY", "QQQ", "IWM", "$SPX", "MU"]
    sweep, published, _clock = _sweep(tmp_path, board, at)
    halt = threading.Event()
    state = type("State", (), {"ok": True, "client": object(), "message": ""})()
    worker = threading.Thread(target=sweep.work, args=(lambda: state, halt), daemon=True)
    worker.start()
    deadline = time.monotonic() + 10
    while set(board) - set(schwab.chains) and time.monotonic() < deadline:
        halt.wait(0.02)
    halt.set()
    worker.join(5)
    assert set(schwab.chains[:len(board)]) == set(board), "one round fetches the whole board"
    assert {m["ticker"] for _t, m in published} >= set(board)


def test_the_daemon_task_stops_when_told():
    from app.market_data.schwab.streaming import capture

    class _Daemon:
        board, board_db, chains = [], None, None
        bus = None

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(capture.run_chains(_Daemon(), lambda: None, stop))
        await asyncio.sleep(0)
        stop.set()
        await asyncio.wait_for(task, timeout=5)
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


def test_a_partial_morning_capture_is_never_the_prior_day(tmp_path):
    """2026-09-28: the only 09-25 captures were the partial morning chains (expiries to 37 days),
    so the forces diffed Monday's full chain against them and every later expiry read as new open
    interest (SPY: +1.4M below and above spot in one day). Only full captures are read: with no
    full prior day the forces are absent with their reason."""
    import server
    db = tmp_path / "ed_console.db"
    # institutional-synthetic-ok: the reader returns stored contracts verbatim; none is priced.
    ct = {"symbol": "ZZ 2030-01-04", "expirationDate": "2030-01-04T20:00:00.000+00:00"}
    cch.persist_complete_chain_capture(db, ticker="ZZ", expiry="2030-01-04", contracts=[ct],
                                       spot=5.0, completeness_basis="expiries_to_37_days_morning",
                                       ts_utc=_ts("2026-09-25 10:00"))
    cch.persist_complete_chain_capture(db, ticker="ZZ", expiry="2030-01-04", contracts=[ct],
                                       spot=5.0, completeness_basis=cch.CAPTURE_BASIS,
                                       ts_utc=_ts("2026-09-28 16:15"))
    caps = cch.last_capture_per_day(db, "ZZ", 2)
    assert [(c["et_date"], c["basis"]) for c in caps] == [("2026-09-28", cch.CAPTURE_BASIS)]
    forces = server._forces_from_captures("ZZ", caps)
    assert forces["available"] is False and "fewer than 2 market days" in forces["reason"]
