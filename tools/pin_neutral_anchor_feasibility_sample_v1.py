"""Sample oldest/newest pin_neutral row and show bar-anchor feasibility vs price_bars_1m."""
from __future__ import annotations

import argparse
import bisect
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from db import get_snapshot_sql
from horizon_outcomes import OUTCOME_BAR_SPECS, bar_complete_by_utc, forward_bar_start_utc
from instrument_identity import ticker_storage_key
from timeframe_config import CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("which", nargs="?", choices=("oldest", "newest"), default="oldest")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="tools.pin_neutral_anchor_feasibility_sample_v1", write_capable=False)

    conn = sqlite3.connect(str(args.db.resolve()))
    conn.row_factory = sqlite3.Row
    key = (
        "tools/pin_neutral_anchor_feasibility_sample_v1.py:sample_oldest"
        if args.which == "oldest"
        else "tools/pin_neutral_anchor_feasibility_sample_v1.py:sample_newest"
    )
    row = conn.execute(
        get_snapshot_sql(key),
        (CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME),
    ).fetchone()
    if not row:
        print("no matching row")
        return

    tkr = ticker_storage_key(row["ticker"])
    tsu = float(row["ts_utc"])
    print("sample", dict(row), "ticker_key", tkr)

    bars = conn.execute(
        "SELECT COUNT(*) AS n FROM price_bars_1m WHERE ticker=? AND bar_end_ts_utc <= ?",
        (tkr, tsu),
    ).fetchone()["n"]
    print("bars with bar_end <= ts_utc:", int(bars))

    tz = time.time()
    bar_end_rows = conn.execute(
        """
        SELECT bar_end_ts_utc, close FROM price_bars_1m
        WHERE ticker = ? AND bar_start_ts_utc >= ? AND bar_end_ts_utc <= ?
        ORDER BY bar_end_ts_utc ASC
        """,
        (tkr, tsu - 5000.0, tz),
    ).fetchall()
    bar_ends = [float(r["bar_end_ts_utc"]) for r in bar_end_rows]
    print(
        "bar_ends in range",
        len(bar_ends),
        "first/last",
        (bar_ends[:2], bar_ends[-2:]) if len(bar_ends) > 2 else bar_ends,
    )

    anch_idx = bisect.bisect_right(bar_ends, tsu) - 1
    print("anch_idx", anch_idx)

    close_by_start = {
        float(r["bar_start_ts_utc"]): float(r["close"])
        for r in conn.execute(
            """
            SELECT bar_start_ts_utc, close FROM price_bars_1m
            WHERE ticker = ? AND bar_start_ts_utc >= ? AND bar_start_ts_utc <= ?
            """,
            (tkr, tsu - 5000.0, tz + 3600.0),
        ).fetchall()
    }
    for _odir, _opt, n_min in OUTCOME_BAR_SPECS[:3]:
        b_start = forward_bar_start_utc(tsu, n_min)
        ok = bar_complete_by_utc(b_start, tz)
        fc = close_by_start.get(float(b_start))
        print(f"horizon {n_min}m b_start={b_start} complete={ok} fwd_close={fc}")

    conn.close()


if __name__ == "__main__":
    main()
