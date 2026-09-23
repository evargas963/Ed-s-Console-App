"""Read of the persisted snapshot store: the most recent stored option chain with its spot,
queried per (ticker, timeframe) in the order of _STORED_CHAIN_TIMEFRAMES so SQLite can use
idx_snap_ticker_tf_ts. Extracted from server.py (RC-REHAB-1, 2026-09-23, forty-ninth slice).
"""
from __future__ import annotations

import json
import logging

from timeframe_config import CANONICAL_TIMEFRAME

log = logging.getLogger(__name__)


#: Timeframes to try, in order, when reading stored snapshot rows. The timeframe MUST be
#: named in any query that orders by ts_utc: the only usable index is
#: idx_snap_ticker_tf_ts (ticker, timeframe, ts_utc), and omitting the MIDDLE column makes
#: the ordering unusable, forcing a full read of every row for that ticker (MEASURED
#: 2026-07-20: >300 s vs 0.002 s).
_STORED_CHAIN_TIMEFRAMES: tuple[str, ...] = (CANONICAL_TIMEFRAME, "5m")


def _latest_chain_and_spot(ticker: str) -> tuple[list | None, float | None, float | None]:
    """Most recent stored chain + spot + its own row ts_utc for a ticker (read-only, no Schwab call).

    The row's own `ts_utc` is returned so a caller overlaying fresher streamed fields onto
    this snapshot (RC-557) can gate on "newer than THIS specific row", not merely "recent in
    absolute terms" -- the same newer_than_ts precedence every other overlay call site uses.

    MEASURED 2026-07-20 — this query was the single worst latency in the app.

    Without `timeframe` in the predicate the plan was:
        SEARCH snapshots USING INDEX idx_snap_ticker_tf_ts (ticker=?)
        USE TEMP B-TREE FOR ORDER BY
    SQLite could seek to the ticker but not use the index's ts_utc ordering, because
    timeframe sits between them in the composite key. Satisfying ORDER BY ts_utc DESC
    therefore meant reading EVERY row for that ticker -- 70,556 for SPY, each carrying an
    inline ~50 KB option_chain_json -- into a temp B-tree to sort, to return one row. It
    did not complete inside a 300 s timeout.

    Naming the timeframe closes the index gap:
        SEARCH snapshots USING INDEX idx_snap_ticker_tf_ts (ticker=? AND timeframe=?)
    No temp B-tree, no scan. MEASURED after: SPY 0.002 s, QQQ 0.005 s, NVDA 0.002 s.

    This is RC-6's root cause made concrete -- an archival blob sharing a table with the
    operational query surface is paid for on every read that touches the rows. The index
    fix removes the cost here; it does not remove the cause.
    """
    import sqlite3 as _sqlite3

    import server as _srv

    try:
        db = _srv.get_db()
    except Exception:
        return None, None, None
    con = _sqlite3.connect(f"file:{db.db_path}?mode=ro", uri=True, timeout=30.0)
    row = None
    try:
        con.row_factory = _sqlite3.Row
        # Canonical first, legacy second. Two index-served lookups are still orders of
        # magnitude cheaper than one unbounded scan, and a ticker whose history is all
        # legacy 5m rows still resolves instead of silently returning nothing.
        for tf in _STORED_CHAIN_TIMEFRAMES:
            row = con.execute(
                "SELECT spot, option_chain_json, ts_utc FROM snapshots "
                "WHERE ticker=? AND timeframe=? "
                "AND option_chain_json IS NOT NULL AND spot IS NOT NULL "
                "ORDER BY ts_utc DESC LIMIT 1",
                (ticker, tf),
            ).fetchone()
            if row:
                break
    finally:
        con.close()
    if not row:
        return None, None, None
    try:
        return json.loads(row["option_chain_json"]), float(row["spot"]), float(row["ts_utc"])
    except (ValueError, TypeError):
        return None, None, None
