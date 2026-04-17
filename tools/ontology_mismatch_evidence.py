"""Read-only SQLite evidence for ontology / mismatch audit. No mutations."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from db import get_snapshot_sql

from timeframe_config import CANONICAL_TIMEFRAME


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite database path")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="tools.ontology_mismatch_evidence", write_capable=False)
    dbp = args.db
    conn = sqlite3.connect(str(dbp))
    conn.row_factory = sqlite3.Row

    out: dict = {"db_path": str(dbp.resolve()), "sections": {}}

    out["sections"]["zone_all_vs_labeled"] = {
        "note": f"scoped_to_timeframe={CANONICAL_TIMEFRAME!r} (canonical ontology audit)",
        "all_zones": [
            dict(r)
            for r in conn.execute(
                get_snapshot_sql("tools/ontology_mismatch_evidence.py:29"),
                (CANONICAL_TIMEFRAME,),
            )
        ],
    }

    out["sections"]["tickers_labeled_top"] = [
        dict(r)
        for r in conn.execute(
            get_snapshot_sql("tools/ontology_mismatch_evidence.py:40"),
            (CANONICAL_TIMEFRAME,),
        )
    ]

    out["sections"]["spx_ticker_variants"] = [
        dict(r)
        for r in conn.execute(
            get_snapshot_sql("tools/ontology_mismatch_evidence.py:50"),
            (CANONICAL_TIMEFRAME,),
        )
    ]

    for probe in ("SPX", "$SPX"):
        out["sections"][f"count_labeled_{probe}"] = int(
            conn.execute(
                get_snapshot_sql("tools/ontology_mismatch_evidence.py:59"),
                (probe, CANONICAL_TIMEFRAME),
            ).fetchone()[0]
        )

    out["sections"]["distinct_regime_primary_labeled"] = [
        r[0]
        for r in conn.execute(
            get_snapshot_sql("tools/ontology_mismatch_evidence.py:68"),
            (CANONICAL_TIMEFRAME,),
        )
    ]

    out["sections"]["distinct_market_session_labeled"] = [
        r[0]
        for r in conn.execute(
            get_snapshot_sql("tools/ontology_mismatch_evidence.py:77"),
            (CANONICAL_TIMEFRAME,),
        )
    ]

    out["sections"]["distinct_session_bucket_labeled"] = [
        r[0]
        for r in conn.execute(
            get_snapshot_sql("tools/ontology_mismatch_evidence.py:86"),
            (CANONICAL_TIMEFRAME,),
        )
    ]

    out["sections"]["distinct_vix_bucket_labeled"] = [
        r[0]
        for r in conn.execute(
            get_snapshot_sql("tools/ontology_mismatch_evidence.py:95"),
            (CANONICAL_TIMEFRAME,),
        )
    ]

    out["sections"]["distinct_vwap_side_labeled"] = [
        r[0]
        for r in conn.execute(
            get_snapshot_sql("tools/ontology_mismatch_evidence.py:104"),
            (CANONICAL_TIMEFRAME,),
        )
    ]

    conn.close()
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
