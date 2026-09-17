"""
No-fallback lock repair (2026-09-17, FB-00927): tools/_multi_timeframe_audit_v1.py's
schema-version histogram used to default a NULL horizon_outcome_schema_version to bin NULL
rows under a fabricated sentinel value, -1 -- a real numeric value written into a report
field literally named "schema_version" that could be misread as a genuine (if nonsensical)
schema version rather than "unknown." A bare GROUP BY lets SQLite group NULL rows on their
own, so the report now carries a real None for that bucket instead of a fabricated int.
"""
from __future__ import annotations

import sqlite3


def test_no_coalesce_left_in_schema_version_histogram_source():
    import inspect

    from tools import _multi_timeframe_audit_v1 as mod

    src = inspect.getsource(mod.main)
    assert "COALESCE" not in src
    assert "horizon_outcome_schema_version AS v" in src


def test_repaired_query_groups_null_schema_version_on_its_own_not_as_negative_one():
    """
    The repaired query (see source above) can't be exercised through a fresh EdDB, since
    horizon_outcome_schema_version is NOT NULL DEFAULT 3 there and a real NULL row only
    occurs on a database that pre-dates the column. This proves the query SHAPE directly
    against a minimal nullable-column table: a NULL row groups under its own real NULL
    key (None in Python), never coerced into the fabricated sentinel -1.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE snapshots (ticker TEXT, timeframe TEXT, horizon_outcome_schema_version INTEGER)"
    )
    conn.executemany(
        "INSERT INTO snapshots (ticker, timeframe, horizon_outcome_schema_version) VALUES (?, '1m', ?)",
        [("SPY", 3), ("SPY", 3), ("QQQ", None)],
    )
    conn.commit()

    rows = conn.execute(
        """
        SELECT horizon_outcome_schema_version AS v, COUNT(*) AS n
        FROM snapshots WHERE timeframe = ?
        GROUP BY horizon_outcome_schema_version
        """,
        ("1m",),
    ).fetchall()
    conn.close()

    versions = {r["v"]: int(r["n"]) for r in rows}
    assert versions == {3: 2, None: 1}
    assert -1 not in versions
