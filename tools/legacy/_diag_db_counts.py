"""Diagnostic: QQQ vs SPY DB totals + get_similar_setups behavior (live proxy params)."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db import DB_PATH, get_db, get_snapshot_sql
from timeframe_config import CANONICAL_TIMEFRAME
from prediction_engine import _count_labeled  # same as compute_prediction

TF = CANONICAL_TIMEFRAME


def labeled_in_snapshots(cur, tkr: str, col: str) -> int:
    return cur.execute(
        get_snapshot_sql("tools/_diag_db_counts.py:36") + f"AND {col} IN ('up','down','flat')",
        (tkr, TF),
    ).fetchone()[0]


def main() -> None:
    print("DB_PATH:", DB_PATH, "exists:", DB_PATH.exists())
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    has_norm = "snapshots_1m_normalized" in tables

    print("\n========== PART 1 — TOTAL DATABASE COUNTS ==========\n")
    print("A. snapshots (canonical timeframe=%r)\n" % (TF,))
    for tkr in ("QQQ", "SPY"):
        n = cur.execute(
            get_snapshot_sql("tools/_diag_db_counts.py:36"),
            (tkr, TF),
        ).fetchone()[0]
        print(f"  {tkr}: total rows = {n}")

    print("\nB. snapshots_1m_normalized\n")
    if not has_norm:
        print("  (table not present)\n")
    else:
        for tkr in ("QQQ", "SPY"):
            n = cur.execute(
                "SELECT COUNT(*) FROM snapshots_1m_normalized WHERE ticker=?",
                (tkr,),
            ).fetchone()[0]
            print(f"  {tkr}: total rows = {n}")

    print("\nC. snapshots — labeled counts (outcome IN up|down|flat)\n")
    cols = ("outcome_1c", "outcome_5c", "outcome_15c", "outcome_60c")
    for tkr in ("QQQ", "SPY"):
        print(f"  {tkr}:")
        for c in cols:
            print(f"    {c}: {labeled_in_snapshots(cur, tkr, c)}")

    print("\nD. snapshots_1m_normalized — labeled counts\n")
    if not has_norm:
        print("  (skip)\n")
    else:
        for tkr in ("QQQ", "SPY"):
            print(f"  {tkr}:")
            for c in cols:
                n = cur.execute(
                    f"SELECT COUNT(*) FROM snapshots_1m_normalized WHERE ticker=? AND {c} IN ('up','down','flat')",
                    (tkr,),
                ).fetchone()[0]
                print(f"    {c}: {n}")

    print("\n========== PART 2 — LIVE APP FILTERED COUNTS ==========\n")
    print(
        "get_similar_setups (db.py) does NOT pre-count all rows; it runs tiered SQL\n"
        "and returns the FIRST query with >= 20 rows (else tier 5), each capped at LIMIT 500.\n"
        "All tiers require outcome_1c IS NOT NULL (not necessarily up|down|flat in SQL).\n"
        "Empirical MIN_SAMPLES_STATISTICAL=30 applies in Python to the RETURNED list only.\n"
    )

    db = get_db()
    for tkr in ("QQQ", "SPY"):
        row = conn.execute(
            get_snapshot_sql("tools/_diag_db_counts.py:83"),
            (tkr, TF),
        ).fetchone()
        if not row:
            print(f"{tkr}: no snapshots — skip similar-set simulation")
            continue
        zone = row["zone"] or "unknown"
        vwap_side = row["vwap_side"] or "above"
        nad, nbd = row["nearest_above_dist"], row["nearest_below_dist"]
        print(f"\n--- {tkr} (proxy: latest snapshot ts_utc={row['ts_utc']}) ---")
        print(f"  params: zone={zone!r} vwap_side={vwap_side!r} nearest_above_dist={nad} nearest_below_dist={nbd}")

        # Tier raw counts (full DB, no LIMIT) for this ticker+tf — shows pool size per tier
        from math_exposure import bucket_lo, bucket_hi, dist_bucket

        ab = dist_bucket(nad)
        bb = dist_bucket(nbd)
        t1 = cur.execute(
            get_snapshot_sql("tools/_diag_db_counts.py:103"),
            (
                tkr,
                TF,
                zone,
                vwap_side,
                nad,
                bucket_lo(ab),
                bucket_hi(ab),
                nbd,
                bucket_lo(bb),
                bucket_hi(bb),
            ),
        ).fetchone()[0]
        t2 = cur.execute(
            get_snapshot_sql("tools/_diag_db_counts.py:122"),
            (tkr, TF, zone, vwap_side, nad, bucket_lo(ab), bucket_hi(ab)),
        ).fetchone()[0]
        t3 = cur.execute(
            get_snapshot_sql("tools/_diag_db_counts.py:129"),
            (tkr, TF, zone, vwap_side),
        ).fetchone()[0]
        t4 = cur.execute(
            get_snapshot_sql("tools/_diag_db_counts.py:135"),
            (tkr, TF, zone),
        ).fetchone()[0]
        t5 = cur.execute(
            get_snapshot_sql("tools/_diag_db_counts.py:141"),
            (tkr, TF),
        ).fetchone()[0]
        print("  DB pool sizes (no LIMIT):")
        print(f"    tier1 zone+vwap+both_dist+bucket: {t1}")
        print(f"    tier2 zone+vwap+above_dist_bucket: {t2}")
        print(f"    tier3 zone+vwap: {t3}")
        print(f"    tier4 zone only: {t4}")
        print(f"    tier5 ticker+timeframe only: {t5}")

        similar = db.get_similar_setups(
            ticker=tkr,
            timeframe=TF,
            zone=zone,
            vwap_side=vwap_side,
            nearest_above_dist=nad,
            nearest_below_dist=nbd,
            n_similar=500,
        )
        mt = similar[0].get("match_tier") if similar else None
        print(f"  chosen match_tier (narrowest tier with full empirical viability per horizon): {mt}")
        print(f"  final similar list len (returned to compute_prediction): {len(similar)}")
        for c in cols:
            lc = _count_labeled(similar, c)
            print(f"    _count_labeled(..., {c!r}) in returned list: {lc}")

    conn.close()


if __name__ == "__main__":
    main()
