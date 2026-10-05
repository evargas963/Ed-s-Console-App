"""Commit hook: a fixture a commit adds or changes is the database record it names, re-queried.

Each staged added or modified tests/fixtures/**/*.json (its staged content) is refused unless it
carries a top-level `provenance` block and its `rows` equal, exactly, what the block's query returns
now from the named database opened read-only:

    "provenance": {
      "database": "data/stream_capture.db, opened read-only",   names stream_capture.db or ed_console.db
      "symbols": ["SPY", "TSLA"],
      "<x>_from_et": "2026-09-24T04:00", "<x>_to_et": "2026-09-25T20:00",   ET wall time, [from, to)
      "query": "SELECT ... FROM stream_bars_raw WHERE symbol=? AND bar_start_ms>=? AND bar_start_ms<? ...",
      ...                                                       any other key is free text
    },
    "rows": [ {column: value, ...}, ... ]

The query is `SELECT <column>, ... FROM <table> WHERE ...`: its select list is bare column names
(no expression, alias, literal or function, which could make a value the record does not hold) and
it reads one table (no other SELECT, JOIN, UNION, INTERSECT, EXCEPT or WITH) that is a table of the
named database (a `type='table'` row of its sqlite_master: not a view, not a table-valued function
such as `json_each` or a `pragma_*`, which return values no record holds). Its placeholders are,
in this order, `<symbol column>=?`, `<range column> >= ?` and `<range column> < ?`. It runs once per
symbol, with the range in the range column's unit (epoch milliseconds when the column ends in `_ms`,
else epoch seconds). Each result row becomes an object keyed by column; a column `<x>_json` becomes
`<x>`, decoded by json_blob_codec. The rows must equal the results of the symbols in their listed
order. A top-level key other than `provenance` and `rows`, and a key of the block other than
`database`, `symbols`, `query` and the `<x>_from_et` / `<x>_to_et` pair, may not hold a number, or
a number written as text, since nothing checks it.

The databases are db_authority.canonical_stream_db_path() and canonical_console_db_path(), which
in a linked worktree resolve to the primary checkout's data/ (runtime_layout). When the named
database is not there or cannot be read, the fixture is refused with the reason.

    python tools/check_fixture_provenance.py
Exit 0: every staged fixture equals its record. Exit 1: refused, each fixture named with the reason.
Exit 2: the check itself failed (git unavailable).
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_no_new_patches import ToolError, _git  # noqa: E402
from db_authority import canonical_console_db_path, canonical_stream_db_path  # noqa: E402
from json_blob_codec import decode_json_blob  # noqa: E402
from time_et import ET  # noqa: E402

FIXTURES = "tests/fixtures/"
DATABASES = ("stream_capture.db", "ed_console.db")
PLACEHOLDER = re.compile(r"(\w+)\s*(>=|<=|=|>|<)\s*\?")
QUERY = re.compile(r"(?is)\s*SELECT\s+(.+?)\s+FROM\s+(\w+)\s+WHERE\s+(.+)")
COMPOUND = re.compile(r"(?i)\b(SELECT|JOIN|UNION|INTERSECT|EXCEPT|WITH)\b")
REQUIRED = ("database", "symbols", "query")


def _has_number(o) -> bool:
    if isinstance(o, dict):
        return any(_has_number(v) for v in o.values())
    if isinstance(o, list):
        return any(_has_number(v) for v in o)
    if isinstance(o, str):
        try:
            float(o)
        except ValueError:
            return False
        return True
    return isinstance(o, (int, float)) and not isinstance(o, bool)


def _epoch(text: str, column: str) -> float | int:
    t = datetime.fromisoformat(text)
    t = t.replace(tzinfo=ET) if t.tzinfo is None else t
    return int(t.timestamp() * 1000) if column.endswith("_ms") else t.timestamp()


def _plan(prov: dict) -> tuple[str, float | int, float | int] | str:
    """The query's table and (from, to) parameters, or why the block does not give them."""
    shape = QUERY.fullmatch(prov["query"])
    if shape is None or COMPOUND.search(shape.group(3)) or not all(
            re.fullmatch(r"\w+", c.strip()) for c in shape.group(1).split(",")):
        return ("provenance.query must be `SELECT <column>, ... FROM <table> WHERE ...` with bare "
                "column names, reading one table")
    found = PLACEHOLDER.findall(prov["query"])
    if [op for _, op in found] != ["=", ">=", "<"] or prov["query"].count("?") != 3:
        return ("provenance.query's placeholders must be, in order, `<symbol column>=?`, "
                "`<range column> >= ?` and `<range column> < ?`")
    froms = [k for k in prov if k.endswith("_from_et")]
    to_key = froms[0][:-len("_from_et")] + "_to_et" if len(froms) == 1 else None
    if to_key not in prov:
        return "provenance must carry one `<x>_from_et` / `<x>_to_et` pair"
    column = found[1][0]
    return shape.group(2), _epoch(prov[froms[0]], column), _epoch(prov[to_key], column)


def _rows(con: sqlite3.Connection, query: str, params: list) -> list[dict]:
    cur = con.execute(query, params)
    cols = [d[0] for d in cur.description]
    return [{(c[:-5] if c.endswith("_json") else c): (decode_json_blob(v) if c.endswith("_json") else v)
             for c, v in zip(cols, row)} for row in cur.fetchall()]


def check_fixture(text: str, dbs: dict[str, Path]) -> list[str]:
    """Why this fixture is refused (empty: it equals its record). `dbs`: database file name -> path."""
    data = json.loads(text)
    prov = data.get("provenance") if isinstance(data, dict) else None
    if not isinstance(prov, dict):
        return ["no top-level provenance block: a fixture without one cannot be checked against the "
                "record it came from"]
    missing = [k for k in REQUIRED if not prov.get(k)]
    if missing:
        return [f"provenance lacks {', '.join(missing)}"]
    if not isinstance(data.get("rows"), list) or not data["rows"]:
        return ["no rows: nothing to check against the record"]
    extra = sorted(k for k, v in data.items() if k not in ("provenance", "rows") and _has_number(v))
    if extra:
        return [f"top-level {', '.join(extra)} hold numbers outside the checked rows"]
    loose = sorted(k for k, v in prov.items() if k not in REQUIRED and not k.endswith(("_from_et", "_to_et"))
                   and _has_number(v))
    if loose:
        return [f"provenance {', '.join(loose)} hold numbers outside the checked rows"]
    named = [d for d in DATABASES if d in prov["database"]]
    if len(named) != 1:
        return [f"provenance.database names none or both of {', '.join(DATABASES)}"]
    plan = _plan(prov)
    if isinstance(plan, str):
        return [plan]
    table, *rng = plan
    path = dbs[named[0]]
    if not path.is_file():
        return [f"cannot verify: the record {path} is not here"]
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? COLLATE NOCASE",
                           (table,)).fetchone() is None:
                return [f"provenance.query reads {table}, which is not a table of {named[0]}"]
            record = [r for s in prov["symbols"] for r in _rows(con, prov["query"], [s, *rng])]
        finally:
            con.close()
    except sqlite3.Error as e:
        return [f"cannot verify: reading {path} failed: {e}"]
    rows = data["rows"]
    if len(rows) != len(record):
        return [f"{len(rows)} rows, the record has {len(record)}"]
    for i, (mine, theirs) in enumerate(zip(rows, record)):
        if mine != theirs:
            keys = sorted(k for k in set(mine) | set(theirs) if mine.get(k, ...) != theirs.get(k, ...))
            return [f"row {i} differs from the record in {', '.join(keys)}"]
    return []


def violations(root: Path, dbs: dict[str, Path]) -> list[str]:
    staged = [f for f in _git(root, "diff", "--cached", "--name-only", "--diff-filter=AM").splitlines()
              if f.startswith(FIXTURES) and f.endswith(".json")]
    out = []
    for path in staged:
        try:
            found = check_fixture(_git(root, "show", f":{path}"), dbs)
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            found = [f"not a readable fixture or provenance block: {type(e).__name__}: {e}"]
        out += [f"{path}: {why}" for why in found]
    return out


def main() -> int:
    dbs = {"stream_capture.db": canonical_stream_db_path(), "ed_console.db": canonical_console_db_path()}
    try:
        found = violations(Path.cwd(), dbs)
    except ToolError as e:
        print(f"the check failed: {e}", file=sys.stderr)
        return 2
    for v in found:
        print(v)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
