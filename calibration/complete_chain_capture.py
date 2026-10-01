"""The board and the option chains (DATA_FLOW decisions 1 and 7), run by the capture daemon.

The board (the logging_universe table) is the one list of tickers. The daemon fetches the full
chain (every expiry, every strike) of every ticker on it, without end (ChainSweep), and hands each
chain to the console for the levels. The chain history: the first chain of each ticker fetched in
each capture window -- every 30 minutes from 9:30 to the close (ET), and 15 minutes after the close
(the day's close capture), on market days -- is written here, one row per expiry, compressed, with
Schwab's own underlying price. Schwab has no past option chains, so a chain not saved is gone.
Nothing is written while the market is closed (weekend chains blank open interest). Research reads
this table; the console loads the newest capture per ticker at startup.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from instrument_identity import ticker_storage_key
from json_blob_codec import decode_json_blob, encode_json_blob
from schwab_client import fetch_full_chain, flatten_chain_contracts, safe_get_chain, safe_get_quotes
from time_et import ET, RTH_START_MINS, is_trading_day_et, session_close_mins_for_et_date

log = logging.getLogger("chain_history")

CAPTURE_EVERY_MIN = 30
#: the close capture: SPY, QQQ, IWM and the $SPX/NDX/RUT index options trade until 4:15 PM ET,
#: 15 minutes after the stock close (Cboe hours; checked 2026-09-26), so the day's last capture
#: is taken 15 minutes after the close, when every option has stopped trading
CLOSE_CAPTURE_AFTER_MIN = 15
#: why the daemon's captures are complete: every listed expiry, every strike. Older rows (one or
#: two expiries at scattered times, written by the console before 2026-09-27) carry
#: "strike_range=ALL" and are not full chains, so they are not read. The basis is stored before
#: the chain blob, so filtering on it never reads a chain (MEASURED 2026-09-26: filtering on
#: `source`, stored after the blob, read every old chain -- 15 s for SPY, 80 s at startup).
CAPTURE_BASIS = "every_expiry_strike_range_ALL"     # the only basis read: rows of any other are partial

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS complete_chain_captures (
    ticker TEXT NOT NULL,
    expiry TEXT NOT NULL,
    ts_utc REAL NOT NULL,
    spot REAL,
    n_contracts INTEGER NOT NULL,
    completeness_basis TEXT NOT NULL,
    chain_json TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'schwab_chain_strike_range_all',
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (ticker, expiry, ts_utc)
);
CREATE INDEX IF NOT EXISTS idx_complete_chain_captures_latest
    ON complete_chain_captures(ticker, expiry, ts_utc DESC);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(TABLE_SQL)
    conn.commit()


def persist_complete_chain_capture(
    db_path: Path | str,
    *,
    ticker: str,
    expiry: str,
    contracts: list[Any],
    spot: float | None,
    completeness_basis: str,
    ts_utc: float | None = None,
    source: str = "schwab_chain_strike_range_all",
) -> dict[str, Any]:
    """Append one COMPLETE single-expiry capture. A time series (PRIMARY KEY includes
    ts_utc), not an idempotent once-a-day row — every successful live complete fetch
    banks its own capture, so `latest_complete_chain_capture` always answers "what did
    the vendor actually list, as of the most recent proof."

    FAIL CLOSED: no contracts, or an unproven `completeness_basis`, writes NOTHING and
    says why — a persisted row with an empty or unverifiable completeness claim would be
    worse than no row, since a caller trusts what THIS table alone claims to be complete.
    """
    tk = ticker_storage_key(ticker)
    if not tk:
        return {"status": "skipped", "reason": "no_ticker"}
    exp = str(expiry or "").strip()[:10]
    if not exp:
        return {"status": "skipped", "reason": "no_expiry"}
    if not completeness_basis:
        return {"status": "skipped", "reason": "no_completeness_basis"}
    clean = [dict(c) for c in (contracts or []) if isinstance(c, dict)]
    if not clean:
        return {"status": "skipped", "reason": "no_contracts", "ticker": tk, "expiry": exp}

    ts = float(ts_utc if ts_utc is not None else time.time())
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    try:
        ensure_schema(conn)
        conn.execute(
            "INSERT OR REPLACE INTO complete_chain_captures "
            "(ticker, expiry, ts_utc, spot, n_contracts, completeness_basis, chain_json, source) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (tk, exp, ts,
             float(spot) if spot is not None and math.isfinite(float(spot)) else None,
             len(clean), str(completeness_basis),
             encode_json_blob(clean, default=str), str(source)),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "written", "ticker": tk, "expiry": exp, "ts_utc": ts,
            "n_contracts": len(clean), "completeness_basis": completeness_basis}


def capture_slot(now_ts: float) -> float | None:
    """The capture time a chain fetched at `now_ts` is written for: the latest of 9:30, 10:00, ...
    through the close (13:00 on an early close) ET, and the close capture 15 minutes after the
    close, that is at most CAPTURE_EVERY_MIN minutes before `now_ts`, on a market day (the one
    market calendar, time_et). None outside those windows: nothing is written."""
    now = datetime.fromtimestamp(now_ts, ET)
    day = now.date().isoformat()
    if not is_trading_day_et(day):
        return None
    close = session_close_mins_for_et_date(day)
    slots = [datetime(now.year, now.month, now.day, m // 60, m % 60, tzinfo=ET).timestamp()
             for m in [*range(RTH_START_MINS, close + 1, CAPTURE_EVERY_MIN),
                       close + CLOSE_CAPTURE_AFTER_MIN]]
    past = [s for s in slots if s <= now_ts]
    if not past or now_ts - past[-1] >= CAPTURE_EVERY_MIN * 60:
        return None
    return past[-1]


def board_tickers(db_path: Path | str) -> list[str]:
    """Every ticker on the board (the logging_universe table), read-only. The daemon reads it at
    startup and holds it; board_add / board_remove change it."""
    conn = sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True)
    try:
        return [r[0] for r in conn.execute("SELECT ticker FROM logging_universe ORDER BY ticker")]
    finally:
        conn.close()


def board_add(db_path: Path | str, ticker: str, now_ts: float) -> None:
    """Put `ticker` (a storage key) on the board."""
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    try:
        conn.execute("INSERT OR IGNORE INTO logging_universe (ticker, category, enrollment_source, "
                     "enrolled_ts_utc, last_seen_ts_utc) VALUES (?, 'user_persisted', 'operator', ?, ?)",
                     (ticker, now_ts, now_ts))
        conn.commit()
    finally:
        conn.close()


def board_remove(db_path: Path | str, ticker: str) -> None:
    """Take `ticker` off the board; its stored history stays."""
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    try:
        conn.execute("DELETE FROM logging_universe WHERE ticker = ? COLLATE NOCASE", (ticker,))
        conn.commit()
    finally:
        conn.close()


#: contracts per chain message to the console: one message is encoded and decoded whole, so a
#: whole chain in one ($SPX, 29,394 contracts: 40.7 MB, 924 ms to encode, measured 2026-10-01)
#: would hold the daemon's event loop; 500 contracts take tens of milliseconds
CHAIN_PART_CONTRACTS = 500
#: the threads fetching chains (the console's loop ran two against Schwab, 2026-09)
CHAIN_WORKERS = 2
#: after Schwab answers 429, no chain request for this long
RATE_LIMITED_PAUSE_SEC = 10.0


def chain_messages(ticker: str, contracts: list[dict], fetched_ts: float) -> list[tuple[str, dict]]:
    """A fetched chain as its bus messages, each carrying its finished wire frame: part i of n,
    CHAIN_PART_CONTRACTS contracts each, all with the fetch's time. The console assembles the
    parts; a chain missing a part is never priced."""
    parts = [contracts[i:i + CHAIN_PART_CONTRACTS]
             for i in range(0, len(contracts), CHAIN_PART_CONTRACTS)] or [[]]
    out = []
    for i, part in enumerate(parts):
        msg = {"src": "schwab_chain", "ticker": ticker, "ts_recv": fetched_ts,
               "part": i, "parts": len(parts), "contracts": part}
        out.append((f"chain.{ticker}", {**msg, "frame": json.dumps(
            {"topic": f"chain.{ticker}", "msg": msg}, separators=(",", ":"))}))
    return out


def chain_failure_message(ticker: str, reason: str, ts: float) -> tuple[str, dict]:
    msg = {"src": "schwab_chain", "ticker": ticker, "ts_recv": ts, "failed": reason}
    return f"chain.{ticker}", {**msg, "frame": json.dumps(
        {"topic": f"chain.{ticker}", "msg": msg}, separators=(",", ":"))}


class ChainSweep:
    """The one fetcher of option chains: every board ticker, one after another, without end,
    on CHAIN_WORKERS threads (the daemon's event loop never waits on it). Each chain is published
    to the console in parts (chain_messages); a failure is published with Schwab's answer. The
    first fetch of a ticker inside a capture window (capture_slot) is also written to the chain
    history. A ticker put on the board is fetched next."""

    def __init__(self, db_path: Path | str, board: "callable", publish: "callable",
                 clock: "callable" = time.time) -> None:
        self.db_path = db_path
        self.board = board              # () -> the daemon's board, as it is now
        self.publish = publish          # (topic, msg) -> None, safe from any thread
        self.clock = clock              # the time a chain is received
        self._lock = threading.Lock()
        self._first: "deque[str]" = deque()
        self._round: list[str] = []
        self._round_started: float | None = None
        self.round_sec: float | None = None
        self._written: dict[str, float] = {}
        self._paused_until = 0.0

    def fetch_next(self, ticker: str) -> None:
        with self._lock:
            if ticker not in self._first:
                self._first.append(ticker)

    def _next(self, now: float) -> str | None:
        with self._lock:
            if self._first:
                return self._first.popleft()
            if not self._round:
                if self._round_started is not None:
                    self.round_sec = now - self._round_started
                self._round = list(self.board())
                self._round_started = now if self._round else None
            return self._round.pop(0) if self._round else None

    def fetch_one(self, client, ticker: str) -> None:
        resp = fetch_full_chain(client, ticker, lambda **d: safe_get_chain(
            client, ticker, strike_range="ALL", **d), lambda symbols: safe_get_quotes(client, symbols))
        now = self.clock()
        if resp.status_code != 200:
            if resp.status_code == 429:
                with self._lock:
                    self._paused_until = now + RATE_LIMITED_PAUSE_SEC
            reason = resp.reason or f"HTTP {resp.status_code}"
            log.warning("chain %s: %s", ticker, reason)
            self.publish(*chain_failure_message(ticker, reason, now))
            return
        payload = resp.json()
        contracts = flatten_chain_contracts(payload)
        for topic, msg in chain_messages(ticker, contracts, now):
            self.publish(topic, msg)
        slot = capture_slot(now)
        if slot is None:
            return
        if ticker not in self._written:
            self._written[ticker] = newest_capture_ts(self.db_path, ticker) or 0.0
        if self._written[ticker] >= slot:
            return
        spot = payload.get("underlyingPrice")          # Schwab's field, as sent
        if spot == -999:
            spot = None
        by_expiry: dict[str, list[dict]] = {}
        for ct in contracts:
            by_expiry.setdefault(str(ct.get("expirationDate") or "")[:10], []).append(ct)
        for expiry, cts in by_expiry.items():
            persist_complete_chain_capture(self.db_path, ticker=ticker, expiry=expiry, contracts=cts,
                                           spot=spot, completeness_basis=CAPTURE_BASIS, ts_utc=now)
        self._written[ticker] = slot

    def work(self, make_client, stop: threading.Event) -> None:
        """One worker thread's life: the next ticker, its chain, until `stop`."""
        client = None
        while not stop.is_set():
            wait = self._paused_until - self.clock()
            if wait > 0:
                stop.wait(wait)
                continue
            if client is None:
                try:
                    state = make_client()
                    client = state.client if state.ok else None
                    why = state.message
                except Exception as e:  # noqa: BLE001 -- no client this time; the next try builds one
                    why = f"{type(e).__name__}: {e}"
                if client is None:
                    log.warning("chains: no Schwab client (%s)", why)
                    stop.wait(5.0)
                    continue
            ticker = self._next(self.clock())
            if ticker is None:
                stop.wait(1.0)
                continue
            try:
                self.fetch_one(client, ticker)
            except Exception as e:  # noqa: BLE001 -- that ticker's answer is the failure; the sweep goes on
                log.warning("chain %s failed: %s: %s", ticker, type(e).__name__, e)
                self.publish(*chain_failure_message(ticker, f"{type(e).__name__}: {e}", self.clock()))
                client = None                         # a broken client is rebuilt


def newest_capture_ts(db_path: Path | str, ticker: str) -> float | None:
    """When the ticker's newest full capture was taken."""
    conn = sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                            "AND name='complete_chain_captures'").fetchone():
            return None
        return conn.execute("SELECT MAX(ts_utc) FROM complete_chain_captures WHERE ticker=? "
                            "AND completeness_basis=?",
                            (ticker_storage_key(ticker), CAPTURE_BASIS)).fetchone()[0]
    finally:
        conn.close()


def last_capture_per_day(db_path: Path | str, ticker: str, days: int, *,
                         before_et_date: str | None = None) -> list[dict[str, Any]]:
    """The last capture of each of the newest `days` market days (newest first) -- the close --
    each as {et_date, ts_utc, spot, basis, contracts} with every expiry of that capture.
    `before_et_date` keeps only days before it (the previous market day for a day-over-day
    view)."""
    tk = ticker_storage_key(ticker)
    conn = sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                            "AND name='complete_chain_captures'").fetchone():
            return []                     # no capture has ever been written
        picked: list[tuple[str, float]] = []
        for (ts,) in conn.execute(
                "SELECT DISTINCT ts_utc FROM complete_chain_captures "
                "WHERE ticker=? AND completeness_basis=? ORDER BY ts_utc DESC",
                (tk, CAPTURE_BASIS)):
            day = datetime.fromtimestamp(ts, ET).date().isoformat()
            if before_et_date is not None and day >= before_et_date:
                continue
            if picked and picked[-1][0] == day:
                continue
            picked.append((day, ts))
            if len(picked) == days:
                break
        out = []
        for day, ts in picked:
            rows = conn.execute(
                "SELECT spot, completeness_basis, chain_json FROM complete_chain_captures "
                "WHERE ticker=? AND completeness_basis=? AND ts_utc=?",
                (tk, CAPTURE_BASIS, ts)).fetchall()
            out.append({"et_date": day, "ts_utc": ts, "spot": rows[0][0], "basis": rows[0][1],
                        "contracts": [c for r in rows for c in decode_json_blob(r[2])]})
        return out
    finally:
        conn.close()
