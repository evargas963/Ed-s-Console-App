"""The chain history (DATA_FLOW decision 7): every 30 minutes from 9:30 to the close (ET), and once
more 15 minutes after the close (the day's close capture), on market days, the capture daemon fetches the full chain (every expiry, every strike) of each
ticker on the board and writes it here, one row per expiry, compressed, with Schwab's own
underlying price. Schwab has no past option chains, so a chain not saved is gone. Nothing is
captured while the market is closed (weekend chains blank open interest). Research reads this
table; the console loads the newest capture per ticker at startup.
"""

from __future__ import annotations

import logging
import math
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from instrument_identity import ticker_storage_key
from json_blob_codec import decode_json_blob, encode_json_blob
from schwab_client import fetch_full_chain, flatten_chain_contracts, safe_get_chain
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


def next_capture_ts(now_ts: float) -> float:
    """The next capture time after `now_ts`: 9:30, 10:00, ... through the close (13:00 on an
    early close) ET, then the close capture 15 minutes after the close, on market days only
    (the one market calendar, time_et)."""
    now = datetime.fromtimestamp(now_ts, ET)
    for add in range(15):
        day = (now + timedelta(days=add)).date()
        if not is_trading_day_et(day.isoformat()):
            continue
        close = session_close_mins_for_et_date(day.isoformat())
        for m in [*range(RTH_START_MINS, close + 1, CAPTURE_EVERY_MIN),
                  close + CLOSE_CAPTURE_AFTER_MIN]:
            ts = datetime(day.year, day.month, day.day, m // 60, m % 60, tzinfo=ET).timestamp()
            if ts > now_ts:
                return ts
    raise RuntimeError(f"no market day within 15 days of {now:%Y-%m-%d} (calendar not covered)")


def board_tickers(db_path: Path | str) -> list[str]:
    """Every ticker on the board (the logging_universe table), read-only."""
    conn = sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True)
    try:
        return [r[0] for r in conn.execute("SELECT ticker FROM logging_universe ORDER BY ticker")]
    finally:
        conn.close()


def capture_round(client, db_path: Path | str) -> dict[str, Any]:
    """Fetch and write the full chain of every board ticker. A ticker Schwab does not answer is
    logged and skipped until the next capture; nothing is filled in."""
    written, failed = 0, []
    for tk in board_tickers(db_path):
        resp = fetch_full_chain(client, tk, lambda **d: safe_get_chain(
            client, tk, strike_range="ALL", **d))
        if resp.status_code != 200:
            failed.append(tk)
            log.warning("chain capture %s: %s", tk, resp.reason or f"HTTP {resp.status_code}")
            continue
        ts = time.time()
        payload = resp.json()
        spot = payload.get("underlyingPrice")          # Schwab's field, as sent
        if spot == -999:
            spot = None
        by_expiry: dict[str, list[dict]] = {}
        for ct in flatten_chain_contracts(payload):
            by_expiry.setdefault(str(ct.get("expirationDate") or "")[:10], []).append(ct)
        for expiry, contracts in by_expiry.items():
            persist_complete_chain_capture(
                db_path, ticker=tk, expiry=expiry, contracts=contracts, spot=spot,
                completeness_basis=CAPTURE_BASIS, ts_utc=ts)
        written += 1
    return {"written": written, "failed": failed}


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
