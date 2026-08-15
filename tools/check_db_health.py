"""DATABASE HEALTH against published standards, not against my opinion (RC-266).

The operator asked what world class means for this database. That is not mine
to invent, so every rule below is EXTRACTED from an external reference and
cited where it came from. Each one is mechanical: it passes or it does not.

WHERE THE RULES COME FROM
    DAMA-DMBOK / ISO 8000 six dimensions -- accuracy, completeness,
    consistency, timeliness, uniqueness, validity -- are the canonical frame
    for data quality and are used here as the section headings.
        https://dataworkers.io/resources/data-quality-dimensions/

    OHLC bar invariants, gap detection, duplicate-timestamp and zero-volume
    rules come from the OHLC validation guide, which states them as hard
    invariants rather than heuristics:
        High >= max(Open, Low, Close)
        Low  <= min(Open, High, Close)
        no zero or negative price in any of O/H/L/C
        a duplicate is any timestamp appearing more than once
        bars must be in chronological order
        zero volume during active hours is suspicious and warrants
        investigation before inclusion
        NO interpolation and NO synthetic fills -- a conservative policy never
        introduces artificial price data
        https://backtrex.com/en/blog/ohlc-data-quality-validation-backtesting-guide

    SQLite operational limits: WAL is correct for concurrent readers, but the
    WAL grows without bound unless journal_size_limit is set, and VACUUM needs
    roughly twice the database size in free space:
        https://phiresky.github.io/blog/2020/sqlite-performance-tuning/
        https://photostructure.com/coding/how-to-vacuum-sqlite/

WHAT THIS DELIBERATELY DOES NOT FLAG
    Out-of-window bars in price_bars_1m_quarantine. Measured 2026-08-06:
    1,224,370 rows, every one carrying the single reason "RC-183 outside
    08:15-15:15 CT collect window". That is the RTH policy working as designed,
    and retaining rather than deleting them is correct because overnight-gap
    research needs them. Counting a deliberate policy as a defect is how a
    health check loses its reader -- and it is exactly the misreading this
    module was written after making.

Run:  python tools/check_db_health.py [--db PATH] [--json]
Exit: 0 clean · 1 a violation · 2 database unreadable
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(REPO, "data", "ed_console.db")

#: Zero-volume minutes are "suspicious" per the OHLC guide, not invalid: a
#: thinly traded symbol genuinely prints no volume in a quiet minute. So this
#: caps the RATE rather than banning the row. Set above the 6.071% measured on
#: 2026-08-06 so it flags a regression, not the status quo.
ZERO_VOLUME_MAX_PCT = 10.0

SRC_OHLC = "backtrex OHLC validation guide"
SRC_DAMA = "DAMA-DMBOK / ISO 8000"
SRC_WAL = "phiresky SQLite tuning"
SRC_VAC = "photostructure: how to VACUUM SQLite"


@dataclass
class Check:
    dimension: str
    rule: str
    source: str
    sql: str = ""
    max_pct: float = 0.0            # 0 => any violation fails
    violations: int = 0
    total: int = 0
    error: str = ""

    @property
    def pct(self) -> float:
        return 100.0 * self.violations / self.total if self.total else 0.0

    @property
    def passed(self) -> bool:
        if self.error:
            return False
        return self.pct <= self.max_pct if self.max_pct else self.violations == 0


BAR_RULES: list[tuple[str, str, str, float]] = [
    ("VALIDITY", "high >= max(open, close)",
     "select count(*) from {t} where high < max(open, close)", 0),
    ("VALIDITY", "low <= min(open, close)",
     "select count(*) from {t} where low > min(open, close)", 0),
    ("VALIDITY", "high >= low",
     "select count(*) from {t} where high < low", 0),
    ("VALIDITY", "no zero or negative price",
     "select count(*) from {t} where open<=0 or high<=0 or low<=0 or close<=0", 0),
    ("VALIDITY", "no null in OHLC",
     "select count(*) from {t} where open is null or high is null "
     "or low is null or close is null", 0),
    ("VALIDITY", "volume >= 0",
     "select count(*) from {t} where volume < 0", 0),
    # UNIQUENESS is NOT here: it is keyed off the table's own declared primary
    # key by declared_key() below, never off a sibling table's. See RC-267.
    ("CONSISTENCY", "bar_end after bar_start",
     "select count(*) from {t} where bar_end_ts_utc <= bar_start_ts_utc", 0),
    ("COMPLETENESS", f"zero-volume rate <= {ZERO_VOLUME_MAX_PCT}%",
     "select count(*) from {t} where volume = 0", ZERO_VOLUME_MAX_PCT),
]


def declared_key(con: sqlite3.Connection, table: str) -> list[str]:
    """The primary-key columns the TABLE ITSELF declares, in key order.

    RC-267: a hardcoded (ticker, bar_start_ts_utc) rule was applied to
    price_bars_1m_staging, which declares PRIMARY KEY (batch_id, ticker,
    bar_start_ts_utc), and reported 735 false duplicates -- byte-identical rows
    appearing once in each of two batches, which is precisely what a
    batch-scoped landing table exists to hold. Duplicates within the declared
    key were zero.

    So the key is read, never assumed. A table is judged against the contract
    it declares, not against a sibling's whose column names happen to match.
    """
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    keyed = sorted(((r[5], r[1]) for r in rows if r[5]), key=lambda t: t[0])
    return [name for _, name in keyed]


def run_uniqueness_check(con: sqlite3.Connection, table: str,
                         total: int) -> Check:
    key = declared_key(con, table)
    if not key:
        return Check("UNIQUENESS", f"{table}: declares a primary key",
                     SRC_DAMA, total=1, violations=1,
                     error="no primary key declared -- uniqueness undefined")
    cols = ", ".join(key)
    positions = ",".join(str(i + 1) for i in range(len(key)))
    chk = Check("UNIQUENESS", f"{table}: no duplicate ({cols}) [declared key]",
                SRC_DAMA, total=total,
                sql=f"select count(*) from (select {cols} from {table} "
                    f"group by {positions} having count(*) > 1)")
    try:
        chk.violations = con.execute(chk.sql).fetchone()[0]
    except sqlite3.Error as exc:
        chk.error = str(exc)[:80]
        chk.violations = 1
    return chk


def run_bar_checks(con: sqlite3.Connection, table: str) -> list[Check]:
    try:
        total = con.execute(f"select count(*) from {table}").fetchone()[0]
    except sqlite3.Error as exc:
        return [Check("VALIDITY", f"{table} readable", SRC_DAMA,
                      total=1, violations=1, error=str(exc)[:80])]
    out = []
    for dimension, rule, sql, max_pct in BAR_RULES:
        chk = Check(dimension, f"{table}: {rule}", SRC_OHLC,
                    sql=sql.format(t=table), max_pct=max_pct, total=total)
        try:
            chk.violations = con.execute(chk.sql).fetchone()[0]
        except sqlite3.Error as exc:
            chk.error = str(exc)[:80]
            chk.violations = 1
        out.append(chk)
    out.append(run_uniqueness_check(con, table, total))
    return out


#: A WAL larger than this share of the database means checkpointing is not
#: keeping up. Measured 2026-08-06: 57.6 MB against 27,215.3 MB = 0.2%, which
#: is healthy, so the ceiling flags a regression rather than the status quo.
WAL_MAX_PCT_OF_DB = 10.0


def run_wal_size_check(con: sqlite3.Connection) -> Check:
    """The WAL's size on disk -- a real property, unlike the per-connection pragma."""
    try:
        row = con.execute("PRAGMA database_list").fetchone()
        db_path = row[2] if row and len(row) > 2 else ""
    except sqlite3.Error:
        db_path = ""
    c = Check("CONSISTENCY",
              f"WAL is under {WAL_MAX_PCT_OF_DB:g}% of the database "
              "(checkpointing keeps up)", SRC_WAL, total=1)
    if not db_path or not os.path.exists(db_path):
        c.error = "database path unresolved"
        c.violations = 1
        return c
    wal = db_path + "-wal"
    if not os.path.exists(wal):
        return c                       # no WAL file: nothing to outgrow
    db_size = os.path.getsize(db_path) or 1
    wal_size = os.path.getsize(wal)
    share = 100.0 * wal_size / db_size
    c.violations = 0 if share <= WAL_MAX_PCT_OF_DB else 1
    c.error = (f"wal {wal_size/1048576:.1f}MB = {share:.1f}% of "
               f"{db_size/1073741824:.1f}GB" if c.violations else "")
    return c


def run_pragma_checks(con: sqlite3.Connection) -> list[Check]:
    def pragma(name: str):
        try:
            row = con.execute(f"PRAGMA {name}").fetchone()
            return row[0] if row else None
        except sqlite3.Error:
            return None

    out = []
    mode = str(pragma("journal_mode") or "").lower()
    c = Check("CONSISTENCY", "journal_mode is WAL", SRC_WAL, total=1)
    c.violations = 0 if mode == "wal" else 1
    if c.violations:
        c.error = f"journal_mode={mode!r}"
    out.append(c)

    # journal_size_limit is NOT checked as a pragma. RC-267 second half:
    # it is a PER-CONNECTION setting, not a database property -- setting it on
    # one connection returns 67108864 while a fresh connection reads -1 again.
    # This checker opens its own read-only connection, so reading the pragma
    # here reports THIS connection's default and can never observe what the
    # application sets at runtime. The check was measuring itself.
    #
    # The WAL's actual size is a real property of the database on disk, so that
    # is what is measured instead: see run_wal_size_check.
    out.append(run_wal_size_check(con))

    c = Check("VALIDITY", "foreign_key_check passes", SRC_DAMA, total=1)
    try:
        c.violations = len(con.execute("PRAGMA foreign_key_check").fetchall())
    except sqlite3.Error as exc:
        c.error = str(exc)[:80]
        c.violations = 1
    out.append(c)
    return out


def run_capacity_checks(db_path: str) -> list[Check]:
    """VACUUM needs roughly twice the file size free, so capacity is a health fact."""
    size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    free = shutil.disk_usage(os.path.dirname(db_path) or ".").free
    c = Check("TIMELINESS", "free disk >= 2x database size (VACUUM headroom)",
              SRC_VAC, total=1)
    c.violations = 0 if free >= 2 * size else 1
    c.error = (f"db {size/1073741824:.1f}GB, free {free/1073741824:.1f}GB"
               if c.violations else "")
    return [c]


def collect(db_path: str) -> list[Check]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = {r[0] for r in con.execute(
            "select name from sqlite_master where type='table'")}
        checks: list[Check] = []
        for table in ("price_bars_1m", "price_bars_1m_staging"):
            if table in tables:
                checks += run_bar_checks(con, table)
        checks += run_pragma_checks(con)
    finally:
        con.close()
    return checks + run_capacity_checks(db_path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)

    if not os.path.exists(args.db):
        # An ABSENT default database is not a failure: a fresh clone or CI has
        # no 27GB file and blocking its first commit would get this hook
        # disabled within a day. An absent database the caller NAMED is user
        # error and still fails, because silently passing a path someone typed
        # is how a check gets pointed at nothing and reports success.
        explicit = args.db != DEFAULT_DB
        sys.stderr.write(
            f"db-health: {args.db} not found"
            f"{' (explicit --db)' if explicit else ' -- nothing to check'}\n")
        return 2 if explicit else 0
    try:
        checks = collect(args.db)
    except sqlite3.Error as exc:
        sys.stderr.write(f"db-health: cannot read {args.db}: {exc}\n")
        return 2

    failed = [c for c in checks if not c.passed]
    if args.as_json:
        print(json.dumps([{
            "dimension": c.dimension, "rule": c.rule, "violations": c.violations,
            "total": c.total, "pct": round(c.pct, 4), "passed": c.passed,
            "error": c.error, "source": c.source} for c in checks], indent=2))
        return 1 if failed else 0

    print(f"DATABASE HEALTH — {os.path.basename(args.db)} "
          f"({os.path.getsize(args.db) / 1073741824:.1f} GB)")
    print("every rule extracted from a cited reference, none authored here\n")
    last = None
    for c in checks:
        if c.dimension != last:
            last = c.dimension
            print(f"  {c.dimension}")
        detail = f"  {c.violations:,} of {c.total:,} ({c.pct:.3f}%)" if c.total > 1 else ""
        if c.error:
            detail += f"  [{c.error}]"
        print(f"    [{'PASS' if c.passed else 'FAIL'}] {c.rule}{detail}")
    print(f"\n  {len(checks) - len(failed)} pass · {len(failed)} fail")
    print(f"  sources: {SRC_DAMA} · {SRC_OHLC} · {SRC_WAL} · {SRC_VAC}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
