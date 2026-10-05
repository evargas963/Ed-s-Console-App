"""FIXTURE-PROVENANCE (operator 2026-10-04): a captured fixture is the record it names, re-queried.

Commit hook. Each staged added or modified tests/fixtures/**/*.json (its staged content) is refused
unless it carries a top-level `provenance` block of this shape and its `rows` equal, exactly, what
the block's query returns now from the named database opened read-only:

    "provenance": {
      "sent_by": "Schwab streamer CHART_EQUITY",        what Schwab sent; or, for a value the
      "computed_by": "Ed Console",                      console computed, this one instead
      "database": "production data/stream_capture.db, opened read-only",
                                                        names stream_capture.db or ed_console.db
      "table": "stream_bars_raw",
      "symbols": ["SPY", "TSLA"],
      "<x>_from_et": "2026-09-24T04:00", "<x>_to_et": "2026-09-25T20:00",
                                                        the range, ET wall time, [from, to)
      "captured_utc": "2026-10-04T06:00:00+00:00",
      "query": "SELECT ... FROM stream_bars_raw WHERE symbol=? AND bar_start_ms>=? AND bar_start_ms<? ORDER BY ...",
      "recorded_by": ..., "note": ...                   optional, free text
    },
    "rows": [ {column: value, ...}, ... ]

The query is one SELECT from `table` whose placeholders are, in any order, `<symbol column>=?`,
`<range column> >= ?` (or >) and `<range column> < ?` (or <=). It runs once per symbol with the
symbol and the range in the range column's unit (epoch milliseconds when the column ends in `_ms`,
else epoch seconds). Each result row becomes an object keyed by column; a column `<x>_json` becomes
`<x>`, decoded by the one JSON blob reader (json_blob_codec; null stays null). The fixture's rows of each symbol (by the symbol column)
must equal that symbol's result rows, in order; when the rows carry no symbol column, all rows must
equal the results of the symbols in their listed order. A top-level key other than `provenance` and
`rows` may not hold a number.

Which record is Schwab's is computed from the capture daemon's writers: the stream_capture.db
tables stream_spine._INSERTS writes Schwab's item into (a `native_json` column), and the
ed_console.db table its ChainSweep writes Schwab's option chains into
(calibration.complete_chain_capture.TABLE_SQL). `sent_by` must name one of those tables in its
database; `computed_by` must name a table that is not one of them, so a computed value
is never presented as Schwab's and Schwab's record is never presented as computed. Data whose source
is neither the daemon's record nor a named console table (a REST capture written straight to a file,
a hand-built file) has no record to re-query: it is refused.

The databases are the production record: db_authority.canonical_stream_db_path() and
canonical_console_db_path(), which in a linked worktree resolve to the primary checkout's data/
(runtime_layout). When the named database is not there or cannot be read, the fixture is refused
with the reason: it is never passed unverified.

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
from calibration.complete_chain_capture import TABLE_SQL as CHAIN_TABLE_SQL  # noqa: E402
from check_no_new_patches import ToolError, _git  # noqa: E402
from db_authority import canonical_console_db_path, canonical_stream_db_path  # noqa: E402
from json_blob_codec import decode_json_blob  # noqa: E402
from stream_spine import _INSERTS  # noqa: E402
from time_et import ET  # noqa: E402

FIXTURES = "tests/fixtures/"
DATABASES = ("stream_capture.db", "ed_console.db")
PLACEHOLDER = re.compile(r"(\w+)\s*(>=|<=|=|>|<)\s*\?")
REQUIRED = ("database", "table", "symbols", "captured_utc", "query")


def schwab_tables() -> set[tuple[str, str]]:
    """(database, table) of each record the capture daemon writes what Schwab sent into."""
    out = {("ed_console.db", re.search(r"CREATE TABLE IF NOT EXISTS (\w+)", CHAIN_TABLE_SQL).group(1))}
    for sql, _ in _INSERTS.values():
        m = re.match(r"INSERT INTO (\w+)\(([^)]*)\)", sql)
        if m and "native_json" in m.group(2).split(","):
            out.add(("stream_capture.db", m.group(1)))
    return out


def _has_number(o) -> bool:
    if isinstance(o, dict):
        return any(_has_number(v) for v in o.values())
    if isinstance(o, list):
        return any(_has_number(v) for v in o)
    return isinstance(o, (int, float)) and not isinstance(o, bool)


def _epoch(text: str, column: str) -> float | int:
    t = datetime.fromisoformat(text)
    t = t.replace(tzinfo=ET) if t.tzinfo is None else t
    return int(t.timestamp() * 1000) if column.endswith("_ms") else t.timestamp()


def _plan(prov: dict) -> tuple[str, list[str], dict[str, float | int]] | str:
    """(symbol column, placeholder roles in order, {"from", "to"} values), or why the query is not
    one this hook can re-run."""
    query = prov["query"].strip().rstrip(";")
    if not re.match(r"(?is)^SELECT\b", query) or ";" in query:
        return "provenance.query is not one SELECT statement"
    tables = re.findall(r"(?i)\bFROM\s+(\w+)", query)
    if tables != [prov["table"]]:
        return f"provenance.query reads {tables}, not the table it names ({prov['table']})"
    if query.count("?") != len(PLACEHOLDER.findall(query)):
        return "provenance.query has a placeholder that is not `<column> <op> ?`"
    roles, symcol, rangecol = [], None, None
    for col, op in PLACEHOLDER.findall(query):
        if op == "=":
            roles.append("symbol")
            symcol = col
        else:
            roles.append("from" if op in (">=", ">") else "to")
            rangecol = rangecol or col
    froms = [k for k in prov if k.endswith("_from_et")]
    if sorted(roles) != ["from", "symbol", "to"] or len(froms) != 1:
        return "provenance.query must filter `<symbol column>=?` and a range `<column> >= ?` / `< ?`, " \
               "with one `<x>_from_et` / `<x>_to_et` pair in the block"
    to_key = froms[0][:-len("_from_et")] + "_to_et"
    if to_key not in prov:
        return f"provenance has {froms[0]} but no {to_key}"
    return symcol, roles, {"from": _epoch(prov[froms[0]], rangecol), "to": _epoch(prov[to_key], rangecol)}


def _rows(con: sqlite3.Connection, query: str, params: list) -> list[dict]:
    cur = con.execute(query, params)
    cols = [d[0] for d in cur.description]
    out = []
    for row in cur.fetchall():
        rec = {}
        for c, v in zip(cols, row):
            if c.endswith("_json"):
                rec[c[:-5]] = decode_json_blob(v) if v is not None else None
            else:
                rec[c] = v
        out.append(rec)
    return out


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
    if ("sent_by" in prov) == ("computed_by" in prov):
        return ["provenance names exactly one of sent_by (what Schwab sent) or computed_by (what the "
                "console computed)"]
    if not isinstance(data.get("rows"), list) or not data["rows"]:
        return ["no rows: nothing to check against the record"]
    extra = sorted(k for k, v in data.items() if k not in ("provenance", "rows") and _has_number(v))
    if extra:
        return [f"top-level {', '.join(extra)} hold numbers outside the checked rows"]
    named = [d for d in DATABASES if d in prov["database"]]
    if len(named) != 1:
        return [f"provenance.database names none or both of {', '.join(DATABASES)}"]
    schwab = schwab_tables()
    if "sent_by" in prov and (named[0], prov["table"]) not in schwab:
        return [f"sent_by names {named[0]} {prov['table']}, which is not the capture daemon's record of what "
                f"Schwab sent ({', '.join(f'{d} {t}' for d, t in sorted(schwab))})"]
    if "computed_by" in prov and (named[0], prov["table"]) in schwab:
        return [f"computed_by names {prov['table']}, which is the daemon's record of what Schwab sent"]
    plan = _plan(prov)
    if isinstance(plan, str):
        return [plan]
    symcol, roles, rng = plan
    path = dbs[named[0]]
    if not path.is_file():
        return [f"cannot verify: the record {path} is not here (refused, never passed unverified)"]
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            con.execute("PRAGMA query_only=1")
            record = {s: _rows(con, prov["query"], [s if r == "symbol" else rng[r] for r in roles])
                      for s in prov["symbols"]}
        finally:
            con.close()
    except sqlite3.Error as e:
        return [f"cannot verify: reading {path} failed: {e} (refused, never passed unverified)"]
    rows = data["rows"]
    out = []
    if all(isinstance(r, dict) and symcol in r for r in rows):
        strays = sorted({str(r[symcol]) for r in rows} - set(prov["symbols"]))
        if strays:
            out.append(f"rows of {', '.join(strays)}, which provenance.symbols does not list")
        for s in prov["symbols"]:
            mine = [r for r in rows if r[symcol] == s]
            if mine != record[s]:
                out.append(_difference(s, mine, record[s]))
    elif rows != [r for s in prov["symbols"] for r in record[s]]:
        out.append(_difference(", ".join(prov["symbols"]), rows, [r for s in prov["symbols"] for r in record[s]]))
    return out


def _difference(symbol: str, mine: list, record: list) -> str:
    if len(mine) != len(record):
        return f"{symbol}: {len(mine)} rows, the record has {len(record)}"
    i = next(k for k, (a, b) in enumerate(zip(mine, record)) if a != b)
    keys = sorted(k for k in set(mine[i]) | set(record[i]) if mine[i].get(k, ...) != record[i].get(k, ...))
    return f"{symbol}: row {i} differs from the record in {', '.join(keys)}"


def violations(root: Path, dbs: dict[str, Path]) -> list[str]:
    staged = [f for f in _git(root, "diff", "--cached", "--name-only", "--diff-filter=AM").splitlines()
              if f.startswith(FIXTURES) and f.endswith(".json")]
    out = []
    for path in staged:
        try:
            found = check_fixture(_git(root, "show", f":{path}"), dbs)
        except (ValueError, KeyError, TypeError) as e:
            found = [f"not a readable fixture or provenance block: {type(e).__name__}: {e}"]
        out += [f"{path}: {why}" for why in found]
    return out


def main(argv: list[str] | None = None) -> int:
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
