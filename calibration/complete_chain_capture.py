"""The chain history (DATA_FLOW decisions 1 and 7): the Recorder's capture table.

Each capture the chain sweep (feed/chain_sweep.py) takes -- the first chain of each ticker begun
in each capture window, every 30 minutes from its option market's open and at its close -- is
written by the Recorder (stream_spine.CaptureWriter.store_capture, store_capture_message) in one
transaction, one row per expiry, compressed, with Schwab's own underlying price, before the
console hears of the chain (operator 2026-11-01: "Yes, store first"). Schwab
has no past option chains, so a chain not saved is gone. Research reads this table; the console
loads the newest capture per ticker at startup.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from instrument_identity import ticker_storage_key
from json_blob_codec import decode_json_blob, encode_json_blob, encode_text_blob
from option_contract import read_chain
from time_et import ET

#: why the daemon's captures are complete: every listed expiry, every strike. The daemon writes
#: only this basis, and rows of any other are not read. The basis is stored before the chain
#: blob, so filtering on it never reads a chain (measured: filtering on `source`, stored after
#: the blob, read every chain -- 15 s for SPY, 80 s at startup).
CAPTURE_BASIS = (
    "every_expiry_strike_range_ALL"  # the only basis read: rows of any other are partial
)

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS complete_chain_captures (
    ticker TEXT NOT NULL,
    expiry TEXT NOT NULL,
    ts_utc REAL NOT NULL,
    spot REAL,
    completeness_basis TEXT NOT NULL,
    chain_json TEXT NOT NULL,
    chain_spot REAL,
    chain_spot_ts REAL,
    chains_answer BLOB,
    PRIMARY KEY (ticker, expiry, ts_utc)
);
CREATE INDEX IF NOT EXISTS idx_complete_chain_captures_latest
    ON complete_chain_captures(ticker, expiry, ts_utc DESC);
"""
# `spot` is each expiry's own underlyingPrice as Schwab sent it; `chain_spot` / `chain_spot_ts`
# the chain's one spot (Schwab's LAST_PRICE when the chain was complete) and its trade time.
# `chain_json` is the chain as the levels took it (each contract's Greeks and quote from the
# stream or /quotes, the one producer of each); `chains_answer` is Schwab's /chains answer for the
# expiry, the body exactly as received (json_blob_codec.encode_text_blob), absent in captures
# written before the column was added.


INSERT_SQL = (
    "INSERT INTO complete_chain_captures "
    "(ticker, expiry, ts_utc, spot, completeness_basis, chain_json, chain_spot, "
    "chain_spot_ts, chains_answer) VALUES (?,?,?,?,?,?,?,?,?)"
)


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(TABLE_SQL)


@contextmanager
def capture_transaction(db_path: Path | str) -> Generator[sqlite3.Connection]:
    """One transaction on the capture table.

    What is written in it commits together or not at all, so a reader finds a capture whole or
    finds none.
    """
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    try:
        ensure_schema(conn)
        with conn:
            yield conn
    finally:
        conn.close()


def persist_complete_chain_capture(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    expiry: str,
    contracts: list[dict[str, Any]],
    spot: float | None,
    completeness_basis: str,
    ts_utc: float,
    chain_spot: float | None = None,
    chain_spot_ts: float | None = None,
    chains_answer: str | None = None,
) -> dict[str, Any]:
    """Append one COMPLETE single-expiry capture.

    `spot` is that expiry's underlyingPrice as Schwab sent it; `chain_spot` / `chain_spot_ts`
    the chain's one spot and its trade time (None when the daemon held no price). A time series
    (PRIMARY KEY includes ts_utc): each capture time is its own set of rows, one per expiry. A
    stored capture is never replaced: a second write of the same (ticker, expiry, ts_utc) raises
    sqlite3.IntegrityError and the stored row stands. `conn` is the capture_transaction the row
    joins.

    FAIL CLOSED: no contracts, or an unproven `completeness_basis`, writes NOTHING and
    says why — a persisted row with an empty or unverifiable completeness claim would be
    worse than no row, since a caller trusts what THIS table alone claims to be complete.
    """
    tk = ticker_storage_key(ticker)
    if not tk:
        return {"status": "skipped", "reason": "no_ticker"}
    exp = expiry.strip()[:10]
    if not exp:
        return {"status": "skipped", "reason": "no_expiry"}
    if not completeness_basis:
        return {"status": "skipped", "reason": "no_completeness_basis"}
    if not contracts:
        return {"status": "skipped", "reason": "no_contracts", "ticker": tk, "expiry": exp}
    conn.execute(
        INSERT_SQL,
        (
            tk,
            exp,
            float(ts_utc),
            spot,
            str(completeness_basis),
            encode_json_blob([dict(c) for c in contracts], default=str),
            chain_spot,
            chain_spot_ts,
            None if chains_answer is None else encode_text_blob(chains_answer),
        ),
    )
    return {
        "status": "written",
        "ticker": tk,
        "expiry": exp,
        "ts_utc": float(ts_utc),
        "n_contracts": len(contracts),
        "completeness_basis": completeness_basis,
    }


def store_capture_message(conn: sqlite3.Connection, msg: dict[str, Any]) -> int:
    """Write a capture message (capture_message) in `conn`'s transaction: one row per expiry.

    How many rows were written; an expiry with no contracts is not a row. Every row is written
    or none: a row the database refuses rolls back the capture's rows and raises.
    """
    conn.execute("SAVEPOINT capture")
    try:
        written = [
            persist_complete_chain_capture(
                conn,
                ticker=msg["ticker"],
                expiry=e["expiry"],
                contracts=e["contracts"],
                spot=e["spot"],
                completeness_basis=CAPTURE_BASIS,
                ts_utc=msg["ts_utc"],
                chain_spot=msg["chain_spot"],
                chain_spot_ts=msg["chain_spot_ts"],
                chains_answer=e["chains_answer"],
            )["status"]
            == "written"
            for e in msg["expiries"]
        ]
    except BaseException:
        conn.execute("ROLLBACK TO capture")
        raise
    finally:
        conn.execute("RELEASE capture")
    return sum(written)


def capture_message(
    ticker: str,
    ts_utc: float,
    chain_spot: tuple[float | None, float | None],
    expiries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return a capture as the Recorder takes it (topic `capture.<TICKER>`).

    `expiries`: each {expiry, spot, contracts, chains_answer}, the expiry's underlyingPrice and
    contracts and its /chains answer as received (None: not recorded); `chain_spot`: the chain's
    one spot and its trade time.
    """
    return {
        "ticker": ticker_storage_key(ticker),
        "ts_utc": ts_utc,
        "chain_spot": chain_spot[0],
        "chain_spot_ts": chain_spot[1],
        "expiries": expiries,
    }


def newest_capture_ts(db_path: Path | str, ticker: str) -> float | None:
    """When the ticker's newest full capture was taken.

    None when there is none.
    """
    if not Path(db_path).is_file():
        return None
    conn = sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True)
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='complete_chain_captures'"
        ).fetchone():
            return None
        return conn.execute(
            "SELECT MAX(ts_utc) FROM complete_chain_captures WHERE ticker=? "
            "AND completeness_basis=?",
            (ticker_storage_key(ticker), CAPTURE_BASIS),
        ).fetchone()[0]
    finally:
        conn.close()


def last_capture_per_day(
    db_path: Path | str,
    ticker: str,
    days: int,
    *,
    before_et_date: str | None = None,
) -> list[dict[str, Any]]:
    """Return the last capture of each of the newest `days` market days (newest first).

    That is the close, each as {et_date, ts_utc, spot, spot_ts, basis, contracts} with every
    expiry of that capture, its contracts read once (option_contract.read_chain). `spot` is the
    chain's one spot with its trade time `spot_ts`: Schwab's LAST_PRICE when the chain was
    complete. A capture stored without one has no spot (None, None): the underlyingPrice of its
    /chains answers is recorded beside it and read by nothing.
    `before_et_date` keeps only days before it (the previous market day for a day-over-day
    view).
    """
    tk = ticker_storage_key(ticker)
    conn = sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True)
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='complete_chain_captures'"
        ).fetchone():
            return []  # no capture has ever been written
        picked: list[tuple[str, float]] = []
        for (ts,) in conn.execute(
            "SELECT DISTINCT ts_utc FROM complete_chain_captures "
            "WHERE ticker=? AND completeness_basis=? ORDER BY ts_utc DESC",
            (tk, CAPTURE_BASIS),
        ):
            day = datetime.fromtimestamp(ts, ET).date().isoformat()
            if before_et_date is not None and day >= before_et_date:
                continue
            if picked and picked[-1][0] == day:
                continue
            picked.append((day, ts))
            if len(picked) == days:
                break
        out: list[dict[str, Any]] = []
        for day, ts in picked:
            rows = conn.execute(
                "SELECT chain_spot, chain_spot_ts, completeness_basis, chain_json "
                "FROM complete_chain_captures "
                "WHERE ticker=? AND completeness_basis=? AND ts_utc=? ORDER BY expiry",
                (tk, CAPTURE_BASIS, ts),
            ).fetchall()
            spot, spot_ts = rows[0][0], rows[0][1]
            out.append(
                {
                    "et_date": day,
                    "ts_utc": ts,
                    "spot": spot,
                    # a trade time without its price is no spot
                    "spot_ts": None if spot is None else spot_ts,
                    "basis": rows[0][2],
                    "contracts": read_chain(c for r in rows for c in decode_json_blob(r[3])),
                }
            )
        return out
    finally:
        conn.close()
