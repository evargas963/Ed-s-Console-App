#!/usr/bin/env python3

# DEPRECATED — 7-horizon era (pre Phase D3 schema drop).
# Targets retired outcome_3c/8c/13c columns; do not run against post-D3 databases.
# Relocated to tools/legacy/horizon_7/ for audit history only.
"""Phase 4E — governed dataset adequacy metrics (stdout JSON)."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

DEFAULT_DB = ROOT / "data" / "ed_console.db"

HORIZON_COLS = [
    "outcome_1c",
    "outcome_3c",
    "outcome_5c",
    "outcome_8c",
    "outcome_13c",
    "outcome_15c",
    "outcome_60c",
]


def _median(vals: list[int]) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    m = len(s) // 2
    if len(s) % 2:
        return float(s[m])
    return (s[m - 1] + s[m]) / 2.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = ap.parse_args()
    db_path = args.db.resolve()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    gov_sql = """
SELECT COUNT(*) AS n FROM snapshots s
WHERE s.timeframe = '1m'
  AND s.horizon_outcome_schema_version = 3
  AND EXISTS (
    SELECT 1 FROM price_bars_1m p
    WHERE p.ticker = s.ticker AND p.bar_end_ts_utc <= s.ts_utc
  )
  AND s.outcome_1c IS NOT NULL AND s.outcome_3c IS NOT NULL AND s.outcome_5c IS NOT NULL
  AND s.outcome_8c IS NOT NULL AND s.outcome_13c IS NOT NULL AND s.outcome_15c IS NOT NULL
  AND s.outcome_60c IS NOT NULL
"""
    n_gov = int(conn.execute(gov_sql).fetchone()["n"])

    n_all = int(conn.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()["n"])
    n_1m = int(conn.execute("SELECT COUNT(*) AS n FROM snapshots WHERE timeframe = '1m'").fetchone()["n"])

    sch_rows = conn.execute(
        """
        SELECT COALESCE(horizon_outcome_schema_version, -1) AS v, COUNT(*) AS c
        FROM snapshots WHERE timeframe = '1m'
        GROUP BY horizon_outcome_schema_version
        """
    ).fetchall()
    schema_breakdown_1m = {int(r["v"]): int(r["c"]) for r in sch_rows}

    n_legacy_tf = int(conn.execute("SELECT COUNT(*) AS n FROM snapshots WHERE timeframe != '1m'").fetchone()["n"])
    n_legacy_sch = int(
        conn.execute(
            "SELECT COUNT(*) AS n FROM snapshots WHERE timeframe = '1m' AND horizon_outcome_schema_version != 3"
        ).fetchone()["n"]
    )

    per_h: dict[str, int] = {}
    for c in HORIZON_COLS:
        per_h[c] = int(
            conn.execute(
                f"SELECT COUNT(*) AS n FROM snapshots WHERE timeframe = '1m' "
                f"AND horizon_outcome_schema_version = 3 AND {c} IS NOT NULL"
            ).fetchone()["n"]
        )

    dup_groups = int(
        conn.execute(
            """
            SELECT COUNT(*) FROM (
              SELECT ticker, timeframe, ts_utc, COUNT(*) AS c FROM snapshots
              GROUP BY ticker, timeframe, ts_utc HAVING c > 1
            )
            """
        ).fetchone()[0]
    )

    rows = conn.execute(
        """
        SELECT ticker, market_session, outcome_1c, outcome_3c, outcome_5c, outcome_8c,
               outcome_13c, outcome_15c, outcome_60c, ts_utc,
               regime_primary, realized_vol
        FROM snapshots s
        WHERE s.timeframe = '1m' AND s.horizon_outcome_schema_version = 3
          AND EXISTS (
            SELECT 1 FROM price_bars_1m p
            WHERE p.ticker = s.ticker AND p.bar_end_ts_utc <= s.ts_utc
          )
          AND s.outcome_1c IS NOT NULL AND s.outcome_3c IS NOT NULL AND s.outcome_5c IS NOT NULL
          AND s.outcome_8c IS NOT NULL AND s.outcome_13c IS NOT NULL
          AND s.outcome_15c IS NOT NULL AND s.outcome_60c IS NOT NULL
        """
    ).fetchall()

    ts_row = conn.execute(
        "SELECT MIN(ts_utc) AS a, MAX(ts_utc) AS b FROM snapshots WHERE timeframe = '1m' AND horizon_outcome_schema_version = 3"
    ).fetchone()

    # Per-day counts for gap heuristic
    by_day = conn.execute(
        """
        SELECT strftime('%Y-%m-%d', ts_utc, 'unixepoch') AS d, COUNT(*) AS n
        FROM snapshots
        WHERE timeframe = '1m' AND horizon_outcome_schema_version = 3
        GROUP BY d ORDER BY d
        """
    ).fetchall()
    day_counts = [int(r["n"]) for r in by_day]

    tc = Counter(r["ticker"] for r in rows)
    ticker_vals = sorted(tc.values())

    sc = Counter((r["market_session"] or "unknown") for r in rows)

    def dist_col(col: str) -> dict:
        o = Counter(r[col] for r in rows)
        tot = len(rows)
        return {k: {"n": o[k], "pct": round(100.0 * o[k] / tot, 4)} for k in sorted(o.keys())}

    out_dists = {c: dist_col(c) for c in HORIZON_COLS}

    rc = Counter((r["regime_primary"] or "NULL") for r in rows)

    def rv_bucket(rv: float | None) -> str:
        if rv is None:
            return "rv_null"
        x = float(rv)
        if x < 0.05:
            return "rv_lt_0.05"
        if x < 0.15:
            return "rv_0.05_0.15"
        if x < 0.35:
            return "rv_0.15_0.35"
        return "rv_ge_0.35"

    vc = Counter(rv_bucket(r["realized_vol"]) for r in rows)

    # Concentration: top ticker share
    tot_rows = len(rows)
    top1 = tc.most_common(1)[0][1] if tc else 0
    top3 = sum(x for _, x in tc.most_common(3))

    out = {
        "db_path": str(db_path),
        "governed_dataset_sql": " ".join(gov_sql.split()),
        "governed_row_count": n_gov,
        "snapshots_total_all_timeframes": n_all,
        "snapshots_1m_total": n_1m,
        "schema_breakdown_1m": schema_breakdown_1m,
        "legacy_rows_non_1m_timeframe": n_legacy_tf,
        "legacy_rows_1m_not_schema_3": n_legacy_sch,
        "per_horizon_non_null_schema3_incomplete_ok": per_h,
        "duplicate_ticker_timeframe_ts_groups": dup_groups,
        "governed_rows_used_for_distributions": tot_rows,
        "temporal_min_ts_utc": ts_row["a"],
        "temporal_max_ts_utc": ts_row["b"],
        "distinct_utc_dates_with_any_schema3_1m": len(by_day),
        "per_day_snapshot_count_min_max_median": {
            "min": min(day_counts) if day_counts else None,
            "max": max(day_counts) if day_counts else None,
            "median": _median(day_counts) if day_counts else None,
        },
        "ticker_count_governed": len(tc),
        "ticker_row_counts_min_max_median": {
            "min": min(ticker_vals) if ticker_vals else None,
            "max": max(ticker_vals) if ticker_vals else None,
            "median": _median(ticker_vals) if ticker_vals else None,
        },
        "ticker_concentration": {
            "top1_ticker_share_pct": round(100.0 * top1 / tot_rows, 4) if tot_rows else None,
            "top3_tickers_share_pct": round(100.0 * top3 / tot_rows, 4) if tot_rows else None,
        },
        "session_distribution_governed": {k: {"n": sc[k], "pct": round(100.0 * sc[k] / tot_rows, 4)} for k in sorted(sc.keys())},
        "outcome_distributions_governed_by_horizon": out_dists,
        "regime_primary_counts_top15": dict(rc.most_common(15)),
        "realized_vol_proxy_buckets": dict(vc.most_common(20)),
    }
    conn.close()
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
