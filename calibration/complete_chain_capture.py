"""Canonical persistence for the COMPLETE vendor options-chain capture, one expiry at a
time — distinct from option_chain_morning_full.py (near-term MULTI-expiry, gated to a
once-daily morning window, tuned width) and from the bounded ANALYTICAL chain snapshots
in `snapshots.option_chain_json` (gamma/terrain width, one row per refresh). Neither of
those tables is a record of what contracts actually existed for a ticker+expiry — this one
is, and only this one carries `completeness_basis`, the machine-readable record of WHY a
given capture is believed complete (not merely wide).

Written from the SAME live single-expiry fetch that serves GET /api/chain
(server.get_chain) — no separate scheduled job, no second producer duplicating the fetch.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Any

from instrument_identity import ticker_storage_key

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
             json.dumps(clean, default=str), str(source)),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "written", "ticker": tk, "expiry": exp, "ts_utc": ts,
            "n_contracts": len(clean), "completeness_basis": completeness_basis}


def has_complete_chain_capture_today(
    db_path: Path | str, ticker: str, expiry: str, et_date: str
) -> bool:
    """True when a COMPLETE capture for (ticker, expiry) already exists for the given
    ET calendar date. DB-backed (not an in-process memo) so the once-daily systematic
    iteration survives a restart without re-fetching an expiry it already proved
    complete today, and correctly re-attempts on a fresh day."""
    path = Path(db_path)
    if not path.is_file():
        return False
    tk = ticker_storage_key(ticker)
    exp = str(expiry or "").strip()[:10]
    day = str(et_date or "").strip()[:10]
    if not tk or not exp or not day:
        return False
    try:
        conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='complete_chain_captures'"
        ).fetchone():
            return False
        row = conn.execute(
            "SELECT ts_utc FROM complete_chain_captures WHERE ticker=? AND expiry=? "
            "ORDER BY ts_utc DESC LIMIT 1",
            (tk, exp),
        ).fetchone()
    except sqlite3.Error:
        return False
    finally:
        conn.close()
    if not row:
        return False
    from calibration.option_chain_morning_full import et_date_and_mins
    captured_day, _mins = et_date_and_mins(float(row[0]))
    return captured_day == day


def eligible_near_term_expiries(
    expiry_dates: "set[str] | list[str]", *, max_dte_days: float, now_et_date: str
) -> list[str]:
    """The declared systematic-collection expiry scope: listed expiries from today
    through `max_dte_days` out — the SAME near-term horizon
    `option_chain_morning_full.MAX_DTE_DAYS` already uses for its own systematic
    capture, so the two mechanisms share one definition of "near-term," not two.
    Far-dated expiries (LEAPS, distant monthlies) are deliberately OUT of this
    systematic scope; they remain reachable only via an operator's manual /api/chain
    request, unchanged from before this function existed."""
    from datetime import date as _date
    today = _date.fromisoformat(str(now_et_date)[:10])
    out = []
    for e in expiry_dates or []:
        exp = str(e or "").strip()[:10]
        if not exp:
            continue
        try:
            d = _date.fromisoformat(exp)
        except ValueError:
            continue
        dte = (d - today).days
        if 0 <= dte <= max_dte_days:
            out.append(exp)
    return sorted(set(out))


def next_capture_batch(
    eligible: list[str], *, already_captured: "set[str]", given_up: "set[str]" = frozenset(),
    batch_size: int,
) -> list[str]:
    """The systematic capture's own per-cycle work-selection policy: filter the
    declared eligible set down to what genuinely still needs capturing THIS cycle
    (not already proven complete today, not given up on today), THEN take the next
    `batch_size` of that remaining work.

    ROUND-4 DEFECT this exists to prevent regressing (operator-caught, 2026-08-31): an
    earlier draft sliced `eligible[:batch_size]` FIRST and filtered afterward. Once the
    first `batch_size` expiries were captured, every later cycle re-selected that SAME
    first-`batch_size` slice — all already done, so the loop body no-opped on every one
    — and any eligible expiry past the cap was NEVER attempted, on any cycle, any day:
    a bounded per-cycle vendor budget had silently become a PERMANENT completeness
    ceiling. Filtering before slicing is the entire fix — once today's captured
    expiries drop out of the candidate set, the next cycle's slice naturally advances
    past them to the expiries still waiting."""
    still_needed = [e for e in eligible if e not in already_captured and e not in given_up]
    return still_needed[:batch_size]


def latest_complete_chain_capture(
    db_path: Path | str, ticker: str, expiry: str
) -> dict[str, Any] | None:
    """Newest banked COMPLETE capture for (ticker, expiry), or None.

    Fail-closed: a missing file, a missing table, an unparseable payload, or an empty
    contract list all return None — absence must reach the caller as absence, never
    substitute a different expiry or a narrower book silently.
    """
    path = Path(db_path)
    if not path.is_file():
        return None
    tk = ticker_storage_key(ticker)
    exp = str(expiry or "").strip()[:10]
    if not tk or not exp:
        return None
    try:
        conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='complete_chain_captures'"
        ).fetchone():
            return None
        row = conn.execute(
            "SELECT ts_utc, spot, n_contracts, completeness_basis, chain_json, source "
            "FROM complete_chain_captures WHERE ticker=? AND expiry=? "
            "ORDER BY ts_utc DESC LIMIT 1",
            (tk, exp),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if not row:
        return None
    try:
        contracts = json.loads(row[4])
    except (TypeError, ValueError):
        return None
    if not isinstance(contracts, list) or not contracts:
        return None
    return {"ticker": tk, "expiry": exp, "ts_utc": float(row[0]), "spot": row[1],
            "n_contracts": int(row[2]), "completeness_basis": row[3],
            "contracts": contracts, "source": str(row[5])}


def nearest_complete_chain_capture(
    db_path: Path | str, ticker: str, *, on_or_after_expiry: str
) -> dict[str, Any] | None:
    """Newest banked COMPLETE capture for ticker at the nearest expiry on/after a date.

    Fail-closed: missing file/table/payload -> None. Does not invent a chain or
    substitute a narrower book. Expiry is the vendor date already stored on the row.
    """
    path = Path(db_path)
    if not path.is_file():
        return None
    tk = ticker_storage_key(ticker)
    cutoff = str(on_or_after_expiry or "").strip()[:10]
    if not tk or not cutoff:
        return None
    try:
        conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='complete_chain_captures'"
        ).fetchone():
            return None
        row = conn.execute(
            "SELECT expiry, ts_utc, spot, n_contracts, completeness_basis, chain_json, source "
            "FROM complete_chain_captures WHERE ticker=? AND expiry>=? "
            "ORDER BY expiry ASC, ts_utc DESC LIMIT 1",
            (tk, cutoff),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if not row:
        return None
    try:
        contracts = json.loads(row[5])
    except (TypeError, ValueError):
        return None
    if not isinstance(contracts, list) or not contracts:
        return None
    return {"ticker": tk, "expiry": str(row[0]), "ts_utc": float(row[1]), "spot": row[2],
            "n_contracts": int(row[3]), "completeness_basis": row[4],
            "contracts": contracts, "source": str(row[6])}
