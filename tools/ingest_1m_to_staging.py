#!/usr/bin/env python3
"""
Fetch Schwab 1m candles for one symbol and INSERT into price_bars_1m_staging only.

Does NOT call EdDB.upsert_1m_bars, does NOT write price_bars_1m, does NOT recompute outcomes.

Usage:
  python tools/ingest_1m_to_staging.py --db data/ed_console.db --days 2 --symbol SPY
  python tools/ingest_1m_to_staging.py --batch-id my_run_001 --days 7
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from instrument_identity import ticker_storage_key
from market_data_adapter import schwab_candles_to_bars

STAGING_SOURCE = "schwab_1m_staging_v1"
CHUNK_DAYS = 7
SLEEP_BETWEEN_CHUNKS_SEC = 1.5


def staging_ddl_statements() -> list[str]:
    p = ROOT / "tools" / "price_bars_1m_staging.ddl.sql"
    raw = p.read_text(encoding="utf-8")
    parts: list[str] = []
    cur: list[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("--") or not s:
            continue
        cur.append(line)
        if s.endswith(";"):
            parts.append("\n".join(cur).strip())
            cur = []
    if cur:
        parts.append("\n".join(cur).strip())
    return parts


def ensure_staging_schema(conn: sqlite3.Connection) -> None:
    for stmt in staging_ddl_statements():
        conn.execute(stmt)
    conn.commit()


def grid_ts(raw_ts: float) -> float:
    return round(float(raw_ts) / 60.0) * 60.0


def bars_to_staging_rows(
    bars: list[dict],
    *,
    batch_id: str,
    ticker: str,
    source: str,
) -> list[tuple[Any, ...]]:
    """Map normalized Schwab dicts to staging row tuples (same logic as upsert grid snap)."""
    tkr = ticker_storage_key(ticker)
    rows: list[tuple[Any, ...]] = []
    for b in bars:
        raw_ts = b.get("datetime", b.get("ts", b.get("_ts", 0)))
        try:
            raw_ts = float(raw_ts)
        except (TypeError, ValueError):
            continue
        ts = raw_ts / 1000.0 if raw_ts > 1e10 else raw_ts
        try:
            o = float(b["open"])
            h = float(b["high"])
            lo = float(b["low"])
            c = float(b["close"])
        except (KeyError, TypeError, ValueError):
            continue
        raw_vol = b.get("volume")
        try:
            vol = float(raw_vol) if raw_vol is not None else None
        except (TypeError, ValueError):
            vol = None
        if vol is not None and vol < 0:
            vol = None
        raw_ts_f = float(ts)
        bar_start = grid_ts(raw_ts_f)
        if abs(raw_ts_f - bar_start) > 30.0:
            continue
        if bar_start <= 0:
            continue
        bar_end = bar_start + 60.0
        rows.append(
            (
                batch_id,
                tkr,
                bar_start,
                bar_end,
                o,
                h,
                lo,
                c,
                vol,
                source,
            )
        )
    return rows


def fetch_schwab_minute_window(client: Any, symbol: str, start_utc: datetime, end_utc: datetime) -> list[dict]:
    import schwab as _schwab

    PH = _schwab.client.Client.PriceHistory
    last_err = None
    last_body = None
    for attempt in range(3):
        try:
            resp = client.get_price_history(
                symbol,
                period_type=None,
                period=None,
                frequency_type=PH.FrequencyType.MINUTE,
                frequency=PH.Frequency.EVERY_MINUTE,
                start_datetime=start_utc,
                end_datetime=end_utc,
                need_extended_hours_data=True,
            )
            if resp is not None and getattr(resp, "status_code", None) == 200:
                data = resp.json()
                return list(data.get("candles") or [])
            last_err = getattr(resp, "status_code", None)
            try:
                last_body = (resp.text or "")[:800] if resp is not None else None
            except Exception:
                last_body = None
        except Exception as e:
            last_err = str(e)
        time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"Schwab price history failed: {last_err} body={last_body!r}")


@dataclass
class ValidationReport:
    batch_id: str
    row_count: int
    duplicate_key_rows: int
    off_grid_rows: int
    bad_span_rows: int
    bad_ohlc_rows: int
    gap_gt_90s_intraday: int
    gap_overnight_ge_6h: int
    min_bar_start: float | None
    max_bar_start: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "row_count": self.row_count,
            "duplicate_key_rows": self.duplicate_key_rows,
            "off_grid_rows": self.off_grid_rows,
            "bad_span_rows": self.bad_span_rows,
            "bad_ohlc_rows": self.bad_ohlc_rows,
            "gap_gt_90s_intraday": self.gap_gt_90s_intraday,
            "gap_overnight_ge_6h": self.gap_overnight_ge_6h,
            "min_bar_start_ts_utc": self.min_bar_start,
            "max_bar_start_ts_utc": self.max_bar_start,
        }


def validate_staging_batch(conn: sqlite3.Connection, batch_id: str) -> ValidationReport:
    cur = conn.cursor()
    (n,) = cur.execute(
        "SELECT COUNT(*) FROM price_bars_1m_staging WHERE batch_id = ?",
        (batch_id,),
    ).fetchone()

    (dup,) = cur.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT ticker, bar_start_ts_utc, COUNT(*) AS c
            FROM price_bars_1m_staging
            WHERE batch_id = ?
            GROUP BY ticker, bar_start_ts_utc
            HAVING c > 1
        )
        """,
        (batch_id,),
    ).fetchone()

    (off_grid,) = cur.execute(
        """
        SELECT COUNT(*) FROM price_bars_1m_staging
        WHERE batch_id = ?
          AND ABS(bar_start_ts_utc - (ROUND(bar_start_ts_utc / 60.0) * 60.0)) > 0.001
        """,
        (batch_id,),
    ).fetchone()

    (bad_span,) = cur.execute(
        """
        SELECT COUNT(*) FROM price_bars_1m_staging
        WHERE batch_id = ?
          AND ABS(bar_end_ts_utc - bar_start_ts_utc - 60.0) > 0.001
        """,
        (batch_id,),
    ).fetchone()

    (bad_ohlc,) = cur.execute(
        """
        SELECT COUNT(*) FROM price_bars_1m_staging
        WHERE batch_id = ?
          AND NOT (
            high >= open AND high >= close AND high >= low
            AND low <= open AND low <= close AND high >= low
          )
        """,
        (batch_id,),
    ).fetchone()

    mn_mx = cur.execute(
        """
        SELECT MIN(bar_start_ts_utc), MAX(bar_start_ts_utc)
        FROM price_bars_1m_staging WHERE batch_id = ?
        """,
        (batch_id,),
    ).fetchone()
    mn, mx = (float(mn_mx[0]) if mn_mx[0] is not None else None, float(mn_mx[1]) if mn_mx[1] is not None else None)

    intra = 0
    overnight = 0
    if mn is not None:
        starts = [
            float(r[0])
            for r in cur.execute(
                """
                SELECT bar_start_ts_utc FROM price_bars_1m_staging
                WHERE batch_id = ? ORDER BY bar_start_ts_utc ASC
                """,
                (batch_id,),
            ).fetchall()
        ]
        for i in range(1, len(starts)):
            g = starts[i] - starts[i - 1]
            if g <= 90:
                continue
            if g >= 6 * 3600:
                overnight += 1
            else:
                intra += 1

    return ValidationReport(
        batch_id=batch_id,
        row_count=int(n),
        duplicate_key_rows=int(dup),
        off_grid_rows=int(off_grid),
        bad_span_rows=int(bad_span),
        bad_ohlc_rows=int(bad_ohlc),
        gap_gt_90s_intraday=intra,
        gap_overnight_ge_6h=overnight,
        min_bar_start=mn,
        max_bar_start=mx,
    )


def validation_sql_snippets(batch_id: str) -> str:
    """Human-readable SQL for manual re-run in sqlite3 (same checks as validate_staging_batch)."""
    b = batch_id.replace("'", "''")
    return f"""-- batch_id = {b}

-- Row count
SELECT COUNT(*) AS n FROM price_bars_1m_staging WHERE batch_id = '{b}';

-- Duplicate (ticker, bar_start) within batch
SELECT ticker, bar_start_ts_utc, COUNT(*) AS c
FROM price_bars_1m_staging WHERE batch_id = '{b}'
GROUP BY ticker, bar_start_ts_utc HAVING c > 1;

-- Off 60s grid
SELECT COUNT(*) AS off_grid FROM price_bars_1m_staging
WHERE batch_id = '{b}'
  AND ABS(bar_start_ts_utc - (ROUND(bar_start_ts_utc / 60.0) * 60.0)) > 0.001;

-- bar_end must be start + 60
SELECT COUNT(*) AS bad_span FROM price_bars_1m_staging
WHERE batch_id = '{b}' AND ABS(bar_end_ts_utc - bar_start_ts_utc - 60.0) > 0.001;

-- OHLC sanity
SELECT COUNT(*) AS bad_ohlc FROM price_bars_1m_staging
WHERE batch_id = '{b}'
  AND NOT (high >= open AND high >= close AND high >= low
           AND low <= open AND low <= close);

-- Min / max
SELECT MIN(bar_start_ts_utc), MAX(bar_start_ts_utc) FROM price_bars_1m_staging WHERE batch_id = '{b}';

-- Gaps between consecutive bars (>90s; overnight >= 6h)
WITH ordered AS (
  SELECT bar_start_ts_utc,
         bar_start_ts_utc - LAG(bar_start_ts_utc) OVER (ORDER BY bar_start_ts_utc) AS gap_sec
  FROM price_bars_1m_staging WHERE batch_id = '{b}'
)
SELECT
  SUM(CASE WHEN gap_sec > 90 AND gap_sec < 6 * 3600 THEN 1 ELSE 0 END) AS gap_gt_90s_intraday,
  SUM(CASE WHEN gap_sec >= 6 * 3600 THEN 1 ELSE 0 END) AS gap_overnight_ge_6h
FROM ordered WHERE gap_sec IS NOT NULL;

-- Sample large gaps (optional drill-down)
WITH ordered AS (
  SELECT bar_start_ts_utc,
         LAG(bar_start_ts_utc) OVER (ORDER BY bar_start_ts_utc) AS prev_start,
         bar_start_ts_utc - LAG(bar_start_ts_utc) OVER (ORDER BY bar_start_ts_utc) AS gap_sec
  FROM price_bars_1m_staging WHERE batch_id = '{b}'
)
SELECT prev_start, bar_start_ts_utc, gap_sec FROM ordered
WHERE gap_sec IS NOT NULL AND gap_sec > 90 ORDER BY gap_sec DESC LIMIT 50;
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingest Schwab 1m into price_bars_1m_staging only (SPY-first tool).")
    ap.add_argument("--db", type=Path, default=None, help="SQLite path (default: db.DB_PATH)")
    ap.add_argument("--symbol", default="SPY", help="Schwab symbol to fetch (default SPY)")
    ap.add_argument("--days", type=int, default=2, help="Calendar days of history to request (chunked)")
    ap.add_argument("--batch-id", default=None, help="Batch id (default: staging_<UTC>_<hex>)")
    ap.add_argument("--dry-run", action="store_true", help="Fetch + validate mapping only; no INSERT")
    args = ap.parse_args()

    try:
        from db import DB_PATH, configure_sqlite_connection
    except Exception:
        DB_PATH = None  # type: ignore[misc, assignment]

        def configure_sqlite_connection(conn: sqlite3.Connection, **kwargs: Any) -> None:
            pass

    db_path = args.db or DB_PATH
    if not db_path:
        print("No --db and db.DB_PATH unavailable", file=sys.stderr)
        return 2
    db_path = Path(db_path).resolve()

    batch_id = args.batch_id or f"staging_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"

    try:
        from server import get_client
    except Exception as e:
        print(json.dumps({"error": "import_server", "detail": str(e)}))
        return 2
    try:
        client = get_client()
    except Exception as e:
        print(json.dumps({"error": "get_client", "detail": str(e)}))
        return 2

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=int(args.days))

    all_candles: list[dict] = []
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS), end)
        candles = fetch_schwab_minute_window(client, args.symbol.strip(), chunk_start, chunk_end)
        all_candles.extend(candles)
        chunk_start = chunk_end
        time.sleep(SLEEP_BETWEEN_CHUNKS_SEC)

    bars = schwab_candles_to_bars(all_candles)
    rows = bars_to_staging_rows(bars, batch_id=batch_id, ticker=args.symbol, source=STAGING_SOURCE)

    out: dict[str, Any] = {
        "db_path": str(db_path),
        "batch_id": batch_id,
        "symbol": args.symbol,
        "schwab_candles": len(all_candles),
        "staging_rows_built": len(rows),
        "dry_run": bool(args.dry_run),
    }

    if args.dry_run:
        print(json.dumps(out, indent=2))
        print(
            "\n--- validation SQL (copy/paste after INSERT with the same --batch-id) ---\n",
            end="",
        )
        print(validation_sql_snippets(batch_id))
        print("Dry-run: no database connection for INSERT.", file=sys.stderr)
        return 0

    conn = sqlite3.connect(str(db_path), timeout=120.0)
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    try:
        ensure_staging_schema(conn)
        conn.executemany(
            """
            INSERT OR REPLACE INTO price_bars_1m_staging
            (batch_id, ticker, bar_start_ts_utc, bar_end_ts_utc, open, high, low, close, volume, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
        rep = validate_staging_batch(conn, batch_id)
        out["validation"] = rep.to_dict()
    finally:
        conn.close()

    print(json.dumps(out, indent=2, default=str))
    print("\n--- validation SQL (copy/paste) ---\n")
    print(validation_sql_snippets(batch_id))
    v = out["validation"]
    if v.get("duplicate_key_rows") or v.get("off_grid_rows") or v.get("bad_span_rows") or v.get("bad_ohlc_rows"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
