"""Validation helper for issue19 repair — snapshot / pin_neutral / ticker identity counts."""
from __future__ import annotations

from db import get_snapshot_sql


import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from horizon_outcomes import HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1
from timeframe_config import CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="tools.repair_validation_counts_v1", write_capable=False)
    conn = sqlite3.connect(str(args.db.resolve()))
    conn.row_factory = sqlite3.Row

    r1 = conn.execute(
        get_snapshot_sql("tools/repair_validation_counts_v1.py:27"),
        (CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME),
    ).fetchone()["n"]
    r2 = conn.execute(
        get_snapshot_sql("tools/repair_validation_counts_v1.py:33"),
        (CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME),
    ).fetchone()["n"]
    r3 = conn.execute(
        get_snapshot_sql("tools/repair_validation_counts_v1.py:38"),
        (CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME),
    ).fetchone()["n"]

    print("pin_neutral unfilled+schema3:", int(r1))
    print("pin_neutral outcome_1c not null:", int(r2))
    print("pin_neutral outcome_1c null schema3:", int(r3))

    for sym in ("SPX", "$SPX"):
        c = conn.execute(
            get_snapshot_sql("tools/repair_validation_counts_v1.py:47"),
            (sym, CANONICAL_TIMEFRAME),
        ).fetchone()["n"]
        print(f"labeled {sym!r}:", int(c))

    tf_rows = conn.execute(
        get_snapshot_sql("tools/repair_validation_counts_v1.py:53")
    ).fetchall()
    print("pin_neutral by timeframe:", [(r["timeframe"], int(r["n"])) for r in tf_rows])

    backfill_sql_n = conn.execute(
        get_snapshot_sql("tools/repair_validation_counts_v1.py:58"),
        (
            CANONICAL_TIMEFRAME,
            DERIVED_TIMEFRAME,
            HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
            HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
        ),
    ).fetchone()["n"]
    print(
        "backfill SQL match count (1m+5m):",
        int(backfill_sql_n),
        "CANONICAL_TIMEFRAME=",
        repr(CANONICAL_TIMEFRAME),
    )

    for label, qkey, params in (
        (
            "pin_neutral outcome_filled IS NULL",
            "tools/repair_validation_counts_v1.py:loop_is_null",
            (CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME),
        ),
        (
            "pin_neutral outcome_filled = 0",
            "tools/repair_validation_counts_v1.py:loop_eq0",
            (CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME),
        ),
        (
            "pin_neutral COALESCE(outcome_filled,0)=0",
            "tools/repair_validation_counts_v1.py:loop_coalesce0",
            (CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME),
        ),
    ):
        n = int(conn.execute(get_snapshot_sql(qkey), params).fetchone()["n"])
        print(label + ":", n)

    anchor_feasible = int(
        conn.execute(
            get_snapshot_sql("tools/repair_validation_counts_v1.py:101"),
            (
                CANONICAL_TIMEFRAME,
                DERIVED_TIMEFRAME,
                HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
            ),
        ).fetchone()["n"]
    )
    print(
        "pin_neutral repair-scope rows with at least one anchor bar (bar_end <= ts_utc):",
        anchor_feasible,
        "of",
        int(backfill_sql_n),
    )

    conn.close()


if __name__ == "__main__":
    main()
