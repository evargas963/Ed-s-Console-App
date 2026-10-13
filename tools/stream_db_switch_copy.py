"""STREAM-DB-SWITCH's one-time copy (ACTIVE_PROGRAM.md; docs/DATA_FLOW.md §2 D4): a new stream_capture.db
with the writer's schema and its receipt-time indexes (stream_spine.CaptureWriter on a new file), holding the
newest SESSIONS_KEPT trading sessions of the old file, as the daily keep would leave them
(time_et.sessions_since over the old file's own /markets answers): every row of every kept table received
since they began, except option quotes and option books, of which each day's 0DTE contracts are copied (a
ticker with no expiration that day: its nearest). The newest watchlist row is copied whenever it was received.
The old file is opened read-only; the new file must not exist. Prints the rows per table and per ET day, old
against new. Deleted after the switch.

    python tools/stream_db_switch_copy.py <old stream_capture.db> <new file> [--now 2026-10-12T20:30]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from bisect import bisect_right
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app.market_data.schwab.streaming.capture import SESSIONS_KEPT  # noqa: E402
from instrument_identity import vendor_option_root  # noqa: E402
from stream_spine import KEPT_BY_TIME, CaptureWriter  # noqa: E402
from time_et import ET, record_markets, sessions_since  # noqa: E402

OPTION_TABLES = ("stream_options_quotes_raw", "stream_book_raw")
COPY_ROWS = 5000


def _expiry(symbol: str) -> "date | None":
    """A contract's expiration from its 21-character Schwab symbol (root, YYMMDD, C/P, strike)."""
    if not vendor_option_root(symbol):
        return None
    return date(2000 + int(symbol[6:8]), int(symbol[8:10]), int(symbol[10:12]))


def _days(since: datetime, now: datetime) -> "list[float]":
    """The start (00:00 ET) of each ET day from `since` to `now`, as times."""
    out, day = [], since.date()
    while day <= now.date():
        out.append(datetime.combine(day, datetime.min.time(), ET).timestamp())
        day += timedelta(days=1)
    return out


def _zero_dte(old: sqlite3.Connection, starts: "list[float]") -> "dict[int, set[str]]":
    """Per ET day (index into `starts`), the option contracts kept: for each root, those expiring that day,
    or the root's nearest expiration after it when none does."""
    keep: "dict[int, set[str]]" = {}
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else float("inf")
        day = datetime.fromtimestamp(start, ET).date()
        by_root: "dict[str, dict[date, set[str]]]" = {}
        for table in OPTION_TABLES:
            service = " AND service = 'OPTIONS_BOOK'" if table == "stream_book_raw" else ""
            for (symbol,) in old.execute(f"SELECT DISTINCT symbol FROM {table} WHERE ts_recv >= ? AND ts_recv < ?"
                                         f"{service}", (start, end)):
                expiry = _expiry(symbol)
                if expiry is not None and expiry >= day:
                    by_root.setdefault(vendor_option_root(symbol), {}).setdefault(expiry, set()).add(symbol)
        keep[i] = {s for expiries in by_root.values() for s in expiries[min(expiries)]}
    return keep


def _columns(new: sqlite3.Connection, old: sqlite3.Connection, table: str) -> "list[str]":
    have = {r[1] for r in old.execute(f"PRAGMA table_info({table})")}
    return [r[1] for r in new.execute(f"PRAGMA table_info({table})") if r[1] in have]


def _copy(old, new, table: str, cols: "list[str]", rowids) -> int:
    """The old rows `rowids` (ascending) into the new table, in that order."""
    n, names = 0, ",".join(cols)
    insert = f"INSERT INTO {table}({names}) VALUES({','.join('?' * len(cols))})"
    batch: list = []
    for rowid in rowids:
        batch.append(rowid)
        if len(batch) == COPY_ROWS:
            n += _copy_batch(old, new, table, names, insert, batch)
            batch = []
    if batch:
        n += _copy_batch(old, new, table, names, insert, batch)
    return n


def _copy_batch(old, new, table, names, insert, batch) -> int:
    rows = old.execute(f"SELECT {names} FROM {table} WHERE rowid IN ({','.join('?' * len(batch))}) ORDER BY rowid",
                       batch).fetchall()
    new.executemany(insert, rows)
    new.commit()
    return len(rows)


def copy(old_path: Path, new_path: Path, now: datetime) -> "dict[str, dict[str, tuple[int, int]]]":
    """The copy; {table: {ET day: (old rows, new rows)}}."""
    if new_path.exists():
        raise SystemExit(f"{new_path} exists: the copy writes a new file only")
    old = sqlite3.connect(f"file:{old_path}?mode=ro", uri=True)
    for (body,) in old.execute("SELECT native_json FROM stream_markets_raw WHERE status = 200 ORDER BY ts_recv"):
        record_markets(json.loads(body))
    since = sessions_since(now, SESSIONS_KEPT)
    if since is None:
        raise SystemExit(f"fewer than {SESSIONS_KEPT} sessions in the old file's /markets answers: nothing copied")
    CaptureWriter(new_path)                                    # the writer's schema and receipt-time indexes
    new = sqlite3.connect(new_path)
    starts = _days(since, now)
    keep = _zero_dte(old, starts)
    label = [datetime.fromtimestamp(s, ET).date().isoformat() for s in starts]
    counts: "dict[str, dict[str, tuple[int, int]]]" = {}
    for table, column in KEPT_BY_TIME:
        cols = _columns(new, old, table)
        # what the choice needs only (an index on symbol and time answers it without reading the rows)
        rows = old.execute(f"SELECT rowid, {column}, {'symbol' if table in OPTION_TABLES else 'NULL'}, "
                           f"{'service' if table == 'stream_book_raw' else 'NULL'} FROM {table} "
                           f"WHERE {column} >= ?", (since.timestamp(),))
        per_day: "dict[str, list[int]]" = {}
        take: "list[int]" = []
        for rowid, received, symbol, service in rows:
            d = bisect_right(starts, received) - 1
            per_day.setdefault(label[d], [0, 0])[0] += 1
            option = table == "stream_options_quotes_raw" or service == "OPTIONS_BOOK"
            if not option or symbol in keep[d]:
                take.append(rowid)
                per_day[label[d]][1] += 1
        if table == "stream_watchlist":                         # the newest row always stays
            newest = old.execute("SELECT MAX(rowid) FROM stream_watchlist").fetchone()[0]
            if newest is not None and newest not in take:
                take.append(newest)
                per_day.setdefault("before", [0, 0])[1] += 1
        copied = _copy(old, new, table, cols, sorted(take))       # in the order they were received
        assert copied == len(take), f"{table}: {copied} of {len(take)} copied"
        counts[table] = {d: (o, n) for d, (o, n) in sorted(per_day.items())}
    new.close()
    old.close()
    return counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("old", type=Path)
    ap.add_argument("new", type=Path)
    ap.add_argument("--now", help="ET time the sessions are counted at (default: now)")
    args = ap.parse_args()
    now = datetime.fromisoformat(args.now).replace(tzinfo=ET) if args.now else datetime.now(ET)
    for table, days in copy(args.old, args.new, now).items():
        print(f"{table}: old {sum(o for o, _ in days.values())} -> new {sum(n for _, n in days.values())}")
        for day, (o, n) in days.items():
            print(f"    {day}: old {o} -> new {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
