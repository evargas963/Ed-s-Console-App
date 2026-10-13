"""STREAM-DB-SWITCH's one-time copy (ACTIVE_PROGRAM.md; docs/DATA_FLOW.md §2 D4): a new stream_capture.db
with the writer's schema and its receipt-time indexes (stream_spine.CaptureWriter on a new file), holding the
newest SESSIONS_KEPT trading sessions of the old file, as the daily keep would leave them
(time_et.sessions_since over the old file's own /markets answers): every row of every kept table received
since they began, except option quotes and option books, of which each ET day's 0DTE contracts are copied (a
ticker with no expiration that day: its nearest; a ticker is its option root, as every watchlist ticker's
contracts are on production's file). The newest watchlist row is copied whenever it was received. The old
file is opened read-only; the new file must not exist; spill files beside the old file stop the copy (their
messages are not in the file yet). Prints the rows per table and per ET day, old against new. Deleted after
the switch.

    python tools/stream_db_switch_copy.py <old stream_capture.db> <new file> [--now 2026-10-12T20:30]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app.market_data.schwab.streaming.capture import SESSIONS_KEPT  # noqa: E402
from instrument_identity import vendor_option_root  # noqa: E402
from stream_spine import KEPT_BY_TIME, CaptureWriter  # noqa: E402
from time_et import ET, record_markets, sessions_since  # noqa: E402

#: the option rows of each table: (table, the SQL that picks them out)
OPTION_ROWS = {"stream_options_quotes_raw": "1", "stream_book_raw": "service = 'OPTIONS_BOOK'"}
COPY_ROWS = 5000


def _expiry(symbol: str) -> "date | None":
    """A contract's expiration from its 21-character Schwab symbol (root, YYMMDD, C/P, strike)."""
    if not vendor_option_root(symbol):
        return None
    return date(2000 + int(symbol[6:8]), int(symbol[8:10]), int(symbol[10:12]))


def _starts(since: datetime, now: datetime) -> "list[float]":
    """The start (00:00 ET) of each ET day from `since` to `now`, as times."""
    out, day = [], since.date()
    while day <= now.date():
        out.append(datetime.combine(day, datetime.min.time(), ET).timestamp())
        day += timedelta(days=1)
    return out


def _day(column: str, starts: "list[float]") -> str:
    """SQL for the index into `starts` of the ET day a row's `column` falls on."""
    return "CASE " + " ".join(f"WHEN {column} < {starts[i + 1]!r} THEN {i}" for i in range(len(starts) - 1)) + \
        f" ELSE {len(starts) - 1} END"


def _zero_dte(pairs: "dict[tuple[str, int], int]", starts: "list[float]") -> "set[tuple[str, int]]":
    """The (contract, ET day) pairs kept, from every option row of both option tables: per day and
    ticker, the contracts expiring that day, or the ticker's nearest expiration after it when none does."""
    by: "dict[tuple[int, str], dict[date, list[str]]]" = {}
    for symbol, d in pairs:
        expiry = _expiry(symbol)
        if expiry is not None and expiry >= datetime.fromtimestamp(starts[d], ET).date():
            by.setdefault((d, vendor_option_root(symbol)), {}).setdefault(expiry, []).append(symbol)
    return {(s, d) for (d, _root), expiries in by.items() for s in expiries[min(expiries)]}


def _copy(old, new, table: str, cols: "list[str]", rowids: np.ndarray) -> int:
    """The old rows `rowids` (ascending) into the new table, in that order."""
    names, n = ",".join(cols), 0
    insert = f"INSERT INTO {table}({names}) VALUES({','.join('?' * len(cols))})"
    for i in range(0, len(rowids), COPY_ROWS):
        part = [int(r) for r in rowids[i:i + COPY_ROWS]]
        rows = old.execute(f"SELECT {names} FROM {table} WHERE rowid IN ({','.join('?' * len(part))}) "
                           "ORDER BY rowid", part).fetchall()
        new.executemany(insert, rows)
        new.commit()
        n += len(rows)
    return n


def copy(old_path: Path, new_path: Path, now: datetime) -> "dict[str, dict[str, tuple[int, int]]]":
    """The copy; {table: {ET day: (old rows, new rows)}}."""
    if new_path.exists():
        raise SystemExit(f"{new_path} exists: the copy writes a new file only")
    spills = sorted(old_path.parent.glob(f"{old_path.stem}.*.spill"))
    if spills:
        raise SystemExit(f"spill files beside the old file hold messages it does not: {[s.name for s in spills]}")
    old = sqlite3.connect(f"file:{old_path}?mode=ro", uri=True)
    for (body,) in old.execute("SELECT native_json FROM stream_markets_raw WHERE status = 200 ORDER BY ts_recv"):
        record_markets(json.loads(body))
    since = sessions_since(now, SESSIONS_KEPT)
    if since is None:
        raise SystemExit(f"fewer than {SESSIONS_KEPT} sessions in the old file's /markets answers: nothing copied")
    starts = _starts(since, now)
    label = [datetime.fromtimestamp(s, ET).date().isoformat() for s in starts]
    pairs = {table: {(s, d): n for s, d, n in old.execute(        # each contract's rows per day, per table
        f"SELECT symbol, {_day('ts_recv', starts)} AS d, COUNT(*) FROM {table} WHERE ts_recv >= ? AND {option} "
        "GROUP BY symbol, d", (since.timestamp(),))} for table, option in OPTION_ROWS.items()}
    kept = _zero_dte({p: 0 for table in pairs.values() for p in table}, starts)   # one choice for both tables
    CaptureWriter(new_path)                                    # the writer's schema and receipt-time indexes
    new = sqlite3.connect(new_path)
    counts: "dict[str, dict[str, tuple[int, int]]]" = {}
    for table, column in KEPT_BY_TIME:
        have = {r[1] for r in old.execute(f"PRAGMA table_info({table})")}
        cols = [r[1] for r in new.execute(f"PRAGMA table_info({table})") if r[1] in have]
        day = _day(column, starts)
        old_n = [0] * len(starts)
        new_n = [0] * len(starts)
        parts = []
        option = OPTION_ROWS.get(table)
        if option is not None:                                  # the kept contracts' rows, per day
            for (s, d), n in pairs[table].items():
                old_n[d] += n
                if (s, d) in kept:
                    end = starts[d + 1] if d + 1 < len(starts) else float("inf")
                    parts.append(np.fromiter((r for (r,) in old.execute(
                        f"SELECT rowid FROM {table} WHERE symbol = ? AND {column} >= ? AND {column} < ? AND {option}",
                        (s, starts[d], end))), dtype=np.int64))
                    new_n[d] += n
        rest = f"NOT ({option})" if option and option != "1" else ("0" if option else "1")
        for d, n in old.execute(f"SELECT {day} AS d, COUNT(*) FROM {table} WHERE {column} >= ? AND {rest} GROUP BY d",
                                (since.timestamp(),)):
            old_n[d] += n
            new_n[d] += n
        parts.append(np.fromiter((r for (r,) in old.execute(
            f"SELECT rowid FROM {table} WHERE {column} >= ? AND {rest}", (since.timestamp(),))), dtype=np.int64))
        extra = {}
        if table == "stream_watchlist":                         # the newest row always stays
            newest = old.execute("SELECT MAX(rowid), MAX(ts_recv) FROM stream_watchlist").fetchone()
            if newest[0] is not None and newest[1] < since.timestamp():
                parts.append(np.array([newest[0]], dtype=np.int64))
                extra["before"] = (0, 1)
        rowids = np.unique(np.concatenate(parts))               # ascending: the order they were written
        copied = _copy(old, new, table, cols, rowids)
        if copied != len(rowids):
            raise SystemExit(f"{table}: {copied} of {len(rowids)} rows copied")
        counts[table] = {**extra, **{label[d]: (old_n[d], new_n[d]) for d in range(len(starts)) if old_n[d]}}
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
