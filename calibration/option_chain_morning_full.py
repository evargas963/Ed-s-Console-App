"""Once-per-day morning full-chain persist for GEX-R1 forward collection.

Stores all fetched contracts with T <= ~0.10y (not selected_exp only).
Does not widen every snapshot's option_chain_json.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from time_et import ET

log = logging.getLogger(__name__)

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS option_chain_morning_full (
    ticker TEXT NOT NULL,
    et_date TEXT NOT NULL,
    ts_utc REAL NOT NULL,
    spot REAL,
    n_contracts INTEGER,
    n_expiries INTEGER,
    max_dte REAL,
    chain_json TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'schwab_chain',
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (ticker, et_date)
);
"""

# ~0.10y ≈ 36.5 calendar days
MAX_DTE_DAYS = 37.0
#: RC-159: widened 570 -> 555 on operator mandate. The archive used to open at 09:30 ET, so the
#: earliest a wide chain could be banked was the cash open — and MEASURED 2026-07-30, SPY's
#: actually landed at 09:53. Premarket from 08:15 CT (09:15 ET) is explicitly in scope for chain
#: accrual, so the first-write window now opens with it. The END bound is unchanged: this row is
#: still ONE per (ticker, et_date); continuous accrual is `option_chain_accrual` below.
MORNING_START_MINS = 555  # 09:15 ET == 08:15 CT (was 570 / 09:30 ET)
MORNING_END_MINS = 600    # 10:00 ET — capture window for first write
# Dedicated morning wide fetch (UI live path stays at CHAIN_STRIKE_COUNT=20).
# Cap 100: Schwab 502'd strikeCount=200 on SPY/QQQ at the 2026-07-20 open.
GEX_FULL_CHAIN_STRIKE_COUNT = 100
SOURCE_WIDE = "schwab_chain_wide_gex"
#: FULL-UNIVERSE capture rides the terrain loop AFTER the money-path window closes
#: (operator 2026-07-20: "q4.2 lets do it"). Sentinels keep their in-window capture via
#: the logger path; every other ticker is picked up between 10:00 and this bound —
#: deliberately outside 09:30-10:00 so ~48 wide fetches never contend with the open.
#: The backtest observes at ~10:00 ET, so a 10:0x capture is the same terrain epoch.
UNIVERSAL_CAPTURE_END_MINS = 690  # 11:30 ET


def universal_capture_window(mins: int) -> bool:
    """True when the terrain loop may spend budget on universe wide captures."""
    return MORNING_END_MINS < mins <= UNIVERSAL_CAPTURE_END_MINS


# ─────────────────────────────────────────────────────────────────────────────
# ACCRUAL (RC-159) — the wide chain persisted as a TIME SERIES, not one row a day
# ─────────────────────────────────────────────────────────────────────────────
#: OPERATOR MANDATE 2026-07-30: gamma and per-strike option volume must accrue from BEFORE the
#: cash open through late session, every regular trading day. The operator's wall clock is
#: America/Chicago; the exchange calendar is America/New_York, and `time_et.ET` remains the ONE
#: session authority — these bounds are ET minutes, and the CT equivalence is a fact about the
#: US market's fixed one-hour offset between the two zones, not a second clock.
#:
#:     08:15 America/Chicago  ==  09:15 America/New_York  ==  minute 555
#:     15:15 America/Chicago  ==  16:15 America/New_York  ==  minute 975
#:
#: MEASURED 2026-07-30 (the gap this closes): SPY's ONLY wide chain landed at 09:53:02 ET
#: (08:53 CT) — 38 minutes after the mandated start — because `option_chain_morning_full` is
#: keyed PRIMARY KEY (ticker, et_date), i.e. one row per day by construction. Everything else in
#: the DB before that was the NARROW chain: 178 contracts / 89 strikes, against 3,060 in the wide
#: capture. Narrow is enough to price a spread and far too thin to paint a gamma ladder.
ACCRUAL_START_MINS = 555   # 09:15 ET == 08:15 CT
ACCRUAL_END_MINS = 975     # 16:15 ET == 15:15 CT
ACCRUAL_SOURCE = "terrain_wide_chain_accrual"

ACCRUAL_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS option_chain_accrual (
    ticker TEXT NOT NULL,
    ts_utc REAL NOT NULL,
    et_date TEXT NOT NULL,
    et_minute INTEGER NOT NULL,
    spot REAL,
    n_strikes INTEGER NOT NULL,
    session_volume REAL,
    abs_gex_total REAL,
    per_strike_json TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (ticker, ts_utc)
);
CREATE INDEX IF NOT EXISTS idx_chain_accrual_ticker_date
    ON option_chain_accrual(ticker, et_date, et_minute);
"""


def latest_accrual_rows(
    db_path: Path | str, ticker: str, et_date: str | None = None
) -> dict[str, Any] | None:
    """Newest banked wide-chain observation for (ticker, et_date), or None.

    RC-162 — the bank's FIRST production reader. RC-159 built the writer and RC-161 made the
    producer universal, but nothing read it, so a Chart with a cold or stale live cache painted
    nothing while the session's own gamma and volume sat in the DB. Banking is not rendering.

    Returns `{rows, ts_utc, et_minute, spot, n_strikes, session_volume, source}` where `rows` is
    the `[[strike, net_gex_1pct$, session_volume], ...]` shape the Chart already paints — the
    same metric family, from the same wide book, so the fallback cannot silently change what the
    numbers MEAN.

    Fail-closed everywhere: a missing file, a missing table, an unparseable payload or an empty
    row set all return None. Absence must reach the surface as absence; this reader never
    substitutes a different day, a different scope, or a narrower book.
    """
    path = Path(db_path)
    if not path.is_file():
        return None
    day = str(et_date) if et_date else et_date_and_mins()[0]
    try:
        conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='option_chain_accrual'"
        ).fetchone():
            return None
        row = conn.execute(
            "SELECT ts_utc, et_minute, spot, n_strikes, session_volume, per_strike_json, source "
            "FROM option_chain_accrual WHERE ticker=? AND et_date=? "
            "ORDER BY ts_utc DESC LIMIT 1",
            (str(ticker).upper().strip(), day),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if not row:
        return None
    try:
        rows = json.loads(row[5])
    except (TypeError, ValueError):
        return None
    if not isinstance(rows, list) or not rows:
        return None
    return {"rows": rows, "ts_utc": float(row[0]), "et_minute": int(row[1]),
            "spot": row[2], "n_strikes": int(row[3]), "session_volume": row[4],
            "source": str(row[6]), "et_date": day}


def accrual_window(mins: int) -> bool:
    """True inside the mandated accrual span [09:15, 16:15] ET (= 08:15-15:15 CT).

    Inclusive at BOTH ends: the operator named the boundaries as times data must exist, so a
    snapshot landing exactly at 09:15:00 or 16:15:00 belongs in the record.
    """
    return ACCRUAL_START_MINS <= int(mins) <= ACCRUAL_END_MINS


def ensure_accrual_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(ACCRUAL_TABLE_SQL)
    conn.commit()


def persist_chain_accrual(
    db_path: Path | str,
    *,
    ticker: str,
    per_strike_rows: list[Any],
    spot: float | None,
    ts_utc: float | None = None,
    source: str = ACCRUAL_SOURCE,
) -> dict[str, Any]:
    """Append one wide-chain observation: `[[strike, net_gex_1pct$, session_volume], ...]`.

    We store the PER-STRIKE AGGREGATE rather than every contract. It is exactly what the gamma
    ladder and the volume histogram consume, and it is what the terrain loop already computed
    from the wide chain it already fetched — so accrual costs ZERO additional vendor calls
    (RC-68 kept this map in memory and threw it away at the end of each cycle). Persisting whole
    chains at this cadence would add hundreds of megabytes a day for data no surface reads.

    FAIL CLOSED: no rows, or rows that carry no finite strike, writes NOTHING and says why. A
    fabricated or empty-but-present observation is worse than a gap, because a gap is visible.
    """
    et_date, mins = et_date_and_mins(ts_utc)
    tk = str(ticker).upper().strip()
    if not tk:
        return {"status": "skipped", "reason": "no_ticker"}
    if not accrual_window(mins):
        return {"status": "skipped", "reason": "outside_accrual_window",
                "et_date": et_date, "mins": mins}

    clean: list[list[float]] = []
    vol_total = 0.0
    gex_total = 0.0
    for row in per_strike_rows or []:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        try:
            k, g, v = float(row[0]), float(row[1]), float(row[2])
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(k) and math.isfinite(g) and math.isfinite(v)):
            continue
        clean.append([k, g, v])
        vol_total += v
        gex_total += abs(g)
    if not clean:
        return {"status": "skipped", "reason": "no_finite_per_strike_rows", "ticker": tk}

    ts = float(ts_utc if ts_utc is not None else time.time())
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    try:
        ensure_accrual_schema(conn)
        conn.execute(
            "INSERT OR REPLACE INTO option_chain_accrual "
            "(ticker, ts_utc, et_date, et_minute, spot, n_strikes, session_volume, "
            " abs_gex_total, per_strike_json, source) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (tk, ts, et_date, int(mins),
             float(spot) if spot is not None and math.isfinite(float(spot)) else None,
             len(clean), vol_total, gex_total,
             json.dumps(clean, separators=(",", ":")), str(source)),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "written", "ticker": tk, "et_date": et_date, "mins": mins,
            "n_strikes": len(clean), "session_volume": vol_total, "ts_utc": ts}


def ensure_morning_full_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(TABLE_SQL)
    conn.commit()


def et_date_and_mins(ts_utc: float | None = None) -> tuple[str, int]:
    """Public ET calendar date + minute-of-day for morning-window gates."""
    dt = datetime.fromtimestamp(
        float(ts_utc if ts_utc is not None else time.time()),
        tz=timezone.utc,
    ).astimezone(ET)
    return dt.strftime("%Y-%m-%d"), int(dt.hour * 60 + dt.minute)


def _et_date_and_mins(ts_utc: float | None = None) -> tuple[str, int]:
    return et_date_and_mins(ts_utc)


def has_morning_full_capture(
    db_path: Path | str, ticker: str, et_date: str
) -> bool:
    """True when ``option_chain_morning_full`` already has (ticker, et_date)."""
    path = Path(db_path)
    if not path.is_file():
        return False
    try:
        conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='option_chain_morning_full'"
        ).fetchone()
        if not row:
            return False
        hit = conn.execute(
            "SELECT 1 FROM option_chain_morning_full WHERE ticker=? AND et_date=?",
            (str(ticker).upper(), str(et_date)),
        ).fetchone()
        return hit is not None
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def _dte_days(ct: dict[str, Any]) -> float | None:
    if ct.get("daysToExpiration") is not None:
        try:
            return float(ct["daysToExpiration"])
        except (TypeError, ValueError):
            pass
    exp = ct.get("expirationDate")
    if not exp:
        return None
    try:
        # 2026-07-17T20:00:00.000+00:00
        day = str(exp)[:10]
        exp_dt = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return max((exp_dt - now).total_seconds() / 86400.0, 0.0)
    except (TypeError, ValueError):
        return None


def filter_near_term_contracts(contracts: list[Any], *, max_dte_days: float = MAX_DTE_DAYS) -> list[dict]:
    out: list[dict] = []
    for ct in contracts or []:
        if not isinstance(ct, dict):
            continue
        dte = _dte_days(ct)
        if dte is None or dte > max_dte_days:
            continue
        row = dict(ct)
        row.pop("raw", None)
        out.append(row)
    return out


def maybe_persist_morning_full_chain(
    db_path: Path | str,
    *,
    ticker: str,
    contracts: list[Any],
    spot: float | None,
    ts_utc: float | None = None,
    source: str = SOURCE_WIDE,
) -> dict[str, Any]:
    """Idempotent: one row per (ticker, et_date) in the capture span 09:30-11:30 ET.

    Accept bound is the FULL span (Bugbot 2026-07-20 HIGH: it rejected everything after
    MORNING_END_MINS while the universal path calls only after it — every universal
    capture was a silent no-op). Sentinel in-window path is a subset, unchanged.
    """
    et_date, mins = et_date_and_mins(ts_utc)
    ticker_u = str(ticker).upper()
    if mins < MORNING_START_MINS or mins > UNIVERSAL_CAPTURE_END_MINS:
        return {"status": "skipped", "reason": "outside_capture_span", "et_date": et_date, "mins": mins}
    if has_morning_full_capture(db_path, ticker_u, et_date):
        return {"status": "idempotent_skip", "ticker": ticker_u, "et_date": et_date}
    near = filter_near_term_contracts(contracts)
    if len(near) < 10:
        return {"status": "skipped", "reason": "too_few_near_term_contracts", "n": len(near)}

    conn = sqlite3.connect(str(db_path), timeout=60.0)
    try:
        ensure_morning_full_schema(conn)
        # Race-safe second check under write connection
        exists = conn.execute(
            "SELECT 1 FROM option_chain_morning_full WHERE ticker=? AND et_date=?",
            (ticker_u, et_date),
        ).fetchone()
        if exists:
            return {"status": "idempotent_skip", "ticker": ticker_u, "et_date": et_date}

        exps = {
            str(c.get("expirationDate") or "")[:10]
            for c in near
            if c.get("expirationDate")
        }
        dtes = [d for d in (_dte_days(c) for c in near) if d is not None]
        ts = float(ts_utc if ts_utc is not None else time.time())
        conn.execute(
            """
            INSERT INTO option_chain_morning_full(
              ticker, et_date, ts_utc, spot, n_contracts, n_expiries, max_dte, chain_json, source
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                ticker_u,
                et_date,
                ts,
                float(spot) if spot is not None and math.isfinite(float(spot)) else None,
                len(near),
                len(exps),
                max(dtes) if dtes else None,
                json.dumps(near, default=str),
                str(source),
            ),
        )
        conn.commit()
        log.info(
            "option_chain_morning_full wrote ticker=%s et_date=%s n=%s expiries=%s source=%s",
            ticker_u,
            et_date,
            len(near),
            len(exps),
            source,
        )
        return {
            "status": "ok",
            "ticker": ticker_u,
            "et_date": et_date,
            "n_contracts": len(near),
            "n_expiries": len(exps),
            "source": str(source),
        }
    finally:
        conn.close()
