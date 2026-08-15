#!/usr/bin/env python3
"""Durable Collect G1–G4 operable-surface gate (all-ticker research_excluded=0).

Authority for "clean" claims. Sentinel-only (SPY/QQQ/IWM) counts are reported
separately and must never alone authorize OPERABLE_SURFACE_CLEAN.

Usage:
  python -m tools.operable_surface_gate --db data/ed_console.db
  python -m tools.operable_surface_gate --db data/ed_console.db --write-report
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.daily_scoreboard import BACKFILL_JOIN_TOL_SEC
# The only write path to calibration_decision_log.research_excluded lives in
# calibration/ (audited surface). This tool stays read-only.
from calibration.operable_surface_quarantine import (  # noqa: F401 - re-exported for the CLI
    OLD_AGE_SEC,
    QUARANTINE_REASON,
    operable_filter_sql,
    quarantine_old_unattached,
)

LIVE_WINDOW_SEC = 30 * 60
MAX_ATTACH_GAP_SEC = 59.0
LIVE_COLOCATED_MIN_RATE = 0.95
SENTINEL_TICKERS = ("SPY", "QQQ", "IWM")
REPORT_LATEST = ROOT / "reports" / "operable_surface_gate_latest.json"


def _connect(db_path: Path, *, readonly: bool) -> sqlite3.Connection:
    if readonly:
        uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=60.0)
    else:
        conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    try:
        from db import configure_sqlite_connection

        configure_sqlite_connection(conn)
    except Exception:
        # institutional-swallow-ok: sqlite pragma tuning is best-effort; the connection
        # works with defaults if configuration is unavailable.
        pass
    return conn


def _has_col(conn: sqlite3.Connection, table: str, col: str) -> bool:
    return col in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _operable_filter(conn: sqlite3.Connection) -> str:
    """Delegates to the single definition in calibration/ (see operable_filter_sql)."""
    return operable_filter_sql(conn)


def evaluate_operable_surface(
    db_path: Path,
    *,
    now_utc: float | None = None,
) -> dict[str, Any]:
    """Run G1–G4. Scope: trusted + research_excluded=0, all tickers."""
    now = float(now_utc if now_utc is not None else time.time())
    old_cut = now - OLD_AGE_SEC
    live_cut = now - LIVE_WINDOW_SEC
    conn = _connect(db_path, readonly=True)
    try:
        operable = _operable_filter(conn)
        has_snap = _has_col(conn, "snapshots", "ts_utc")

        old_missing_all = int(
            conn.execute(
                f"""
                SELECT COUNT(*) AS n FROM calibration_decision_log
                WHERE calibration_trust='trusted'
                  AND {operable}
                  AND decision_ts_utc < ?
                  AND matched_snapshot_ts_utc IS NULL
                """,
                (old_cut,),
            ).fetchone()["n"]
        )
        old_missing_sentinel = int(
            conn.execute(
                f"""
                SELECT COUNT(*) AS n FROM calibration_decision_log
                WHERE calibration_trust='trusted'
                  AND {operable}
                  AND decision_ts_utc < ?
                  AND matched_snapshot_ts_utc IS NULL
                  AND ticker IN ('SPY','QQQ','IWM')
                """,
                (old_cut,),
            ).fetchone()["n"]
        )

        future_decisions = int(
            conn.execute(
                """
                SELECT COUNT(*) AS n FROM calibration_decision_log
                WHERE decision_ts_utc > ?
                """,
                (now + 1.0,),
            ).fetchone()["n"]
        )
        future_snapshots = 0
        if has_snap:
            future_snapshots = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM snapshots WHERE ts_utc > ?",
                    (now + 1.0,),
                ).fetchone()["n"]
            )

        inv = conn.execute(
            f"""
            SELECT COUNT(*) AS n,
                   COALESCE(MAX(ABS(matched_snapshot_ts_utc - decision_ts_utc)), 0) AS max_gap,
                   SUM(CASE WHEN ABS(matched_snapshot_ts_utc - decision_ts_utc) > ?
                            THEN 1 ELSE 0 END) AS gt59,
                   SUM(CASE WHEN ABS(matched_snapshot_ts_utc - decision_ts_utc) > ?
                             AND ABS(matched_snapshot_ts_utc - decision_ts_utc) <= ?
                            THEN 1 ELSE 0 END) AS band_29_59
            FROM calibration_decision_log
            WHERE calibration_trust='trusted'
              AND {operable}
              AND matched_snapshot_ts_utc IS NOT NULL
            """,
            (MAX_ATTACH_GAP_SEC, BACKFILL_JOIN_TOL_SEC, MAX_ATTACH_GAP_SEC),
        ).fetchone()
        attach_gt59 = int(inv["gt59"] or 0)
        max_attach_gap = float(inv["max_gap"] or 0.0)
        band_29_59 = int(inv["band_29_59"] or 0)

        # Inversion: matched snapshot more than 59s away already counted;
        # signed extremes for disclosure.
        signed = conn.execute(
            f"""
            SELECT
              COALESCE(MAX(matched_snapshot_ts_utc - decision_ts_utc), 0) AS max_pos,
              COALESCE(MIN(matched_snapshot_ts_utc - decision_ts_utc), 0) AS max_neg
            FROM calibration_decision_log
            WHERE calibration_trust='trusted'
              AND {operable}
              AND matched_snapshot_ts_utc IS NOT NULL
            """
        ).fetchone()
        max_pos = float(signed["max_pos"] or 0.0)
        max_neg = float(signed["max_neg"] or 0.0)
        inversions_gt59 = int(
            conn.execute(
                f"""
                SELECT COUNT(*) AS n FROM calibration_decision_log
                WHERE calibration_trust='trusted'
                  AND {operable}
                  AND matched_snapshot_ts_utc IS NOT NULL
                  AND ABS(matched_snapshot_ts_utc - decision_ts_utc) > ?
                """,
                (MAX_ATTACH_GAP_SEC,),
            ).fetchone()["n"]
        )

        live_rows = conn.execute(
            f"""
            SELECT id, ticker, decision_ts_utc, matched_snapshot_ts_utc
            FROM calibration_decision_log
            WHERE calibration_trust='trusted'
              AND {operable}
              AND decision_ts_utc >= ?
            ORDER BY decision_ts_utc DESC
            """,
            (live_cut,),
        ).fetchall()
        colocated = 0
        for r in live_rows:
            ts = float(r["decision_ts_utc"])
            if has_snap:
                hit = conn.execute(
                    """
                    SELECT 1 FROM snapshots
                    WHERE ticker=? AND ABS(ts_utc - ?) <= 1e-9
                    LIMIT 1
                    """,
                    (str(r["ticker"]), ts),
                ).fetchone()
                if hit:
                    colocated += 1
            elif r["matched_snapshot_ts_utc"] is not None and abs(
                float(r["matched_snapshot_ts_utc"]) - ts
            ) <= 1e-9:
                colocated += 1
        live_n = len(live_rows)
        live_rate = (colocated / live_n) if live_n else 1.0

        research_excluded = 0
        if _has_col(conn, "calibration_decision_log", "research_excluded"):
            research_excluded = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM calibration_decision_log "
                    "WHERE COALESCE(research_excluded,0)=1"
                ).fetchone()["n"]
            )

        g1 = old_missing_all == 0
        g2 = (
            future_decisions == 0
            and future_snapshots == 0
            and inversions_gt59 == 0
        )
        g3 = attach_gt59 == 0
        g4 = live_n == 0 or live_rate >= LIVE_COLOCATED_MIN_RATE

        sentinel_clean = old_missing_sentinel == 0
        if g1 and g2 and g3 and g4:
            verdict = "OPERABLE_SURFACE_CLEAN"
        elif sentinel_clean and g2 and g3 and g4 and not g1:
            verdict = "SENTINEL_SURFACE_CLEAN"
        else:
            verdict = "OPERABLE_SURFACE_NOT_CLEAN"

        return {
            "schema": "operable_surface_gate_v1",
            "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "db_path": str(db_path),
            "definitions": {
                "operable": "calibration_trust='trusted' AND COALESCE(research_excluded,0)=0",
                "scope": "all tickers (not sentinel-only)",
                "old_missing": (
                    "operable AND decision_ts_utc < now-70m AND matched_snapshot_ts_utc IS NULL"
                ),
                "G4": "live last-30m decisions with a snapshots row at the same ts_utc",
                "production_join_tol_sec": BACKFILL_JOIN_TOL_SEC,
                "historical_attach_cap_sec": MAX_ATTACH_GAP_SEC,
            },
            "counts": {
                "old_missing_all_ticker": old_missing_all,
                "old_missing_sentinel": old_missing_sentinel,
                "future_decisions": future_decisions,
                "future_snapshots": future_snapshots,
                "attach_gap_gt_59": attach_gt59,
                "max_attach_gap_sec": max_attach_gap,
                "nearest_band_29_59": band_29_59,
                "signed_gap_max_pos": max_pos,
                "signed_gap_max_neg": max_neg,
                "research_excluded": research_excluded,
                "live_30m_n": live_n,
                "live_30m_colocated": colocated,
                "live_30m_rate": live_rate,
            },
            "gates": {
                "G1_operable_old_missing_zero_all_ticker": g1,
                "G2_no_clock_anomalies": g2,
                "G3_no_attach_gap_gt_59": g3,
                "G4_live_colocated_ge_95pct": g4,
                "sentinel_old_missing_zero": sentinel_clean,
            },
            "verdict": verdict,
            "label_law": (
                "OPERABLE_SURFACE_CLEAN requires all-ticker G1. "
                "SENTINEL_SURFACE_CLEAN is allowed when only SPY/QQQ/IWM G1 holds; "
                "never call that OPERABLE_SURFACE_CLEAN."
            ),
        }
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Operable surface G1–G4 gate")
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--write-report", action="store_true")
    ap.add_argument(
        "--require-clean",
        action="store_true",
        help="Exit 1 unless verdict is OPERABLE_SURFACE_CLEAN",
    )
    args = ap.parse_args(argv)
    try:
        from db import DB_PATH
    except Exception:
        DB_PATH = None  # type: ignore[misc, assignment]
    db_path = args.db or (Path(DB_PATH) if DB_PATH else ROOT / "data" / "ed_console.db")
    if not Path(db_path).is_file():
        print(f"operable_surface_gate: missing db {db_path}", file=sys.stderr)
        return 2
    report = evaluate_operable_surface(Path(db_path))
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.write_report:
        REPORT_LATEST.parent.mkdir(parents=True, exist_ok=True)
        REPORT_LATEST.write_text(text + "\n", encoding="utf-8")
        # Keep triangulation-era filename current with honest label.
        legacy = ROOT / "reports" / "fp_e2e_health_proof_latest.json"
        legacy.write_text(
            json.dumps(
                {
                    "generated_utc": report["generated_utc"],
                    "old_missing": report["counts"]["old_missing_all_ticker"],
                    "old_missing_sentinel": report["counts"]["old_missing_sentinel"],
                    "gates": {
                        "G1_operable_old_missing_zero": report["gates"][
                            "G1_operable_old_missing_zero_all_ticker"
                        ],
                        "G2_no_clock_anomalies": report["gates"]["G2_no_clock_anomalies"],
                        "G3_no_attach_gap_gt_59": report["gates"]["G3_no_attach_gap_gt_59"],
                        "G4_live_colocated_ge_95pct": report["gates"][
                            "G4_live_colocated_ge_95pct"
                        ],
                    },
                    "verdict": report["verdict"],
                    "authority": "tools/operable_surface_gate.py",
                    "live_30m": {
                        "n": report["counts"]["live_30m_n"],
                        "colocated": report["counts"]["live_30m_colocated"],
                        "rate": report["counts"]["live_30m_rate"],
                    },
                    "research_excluded": report["counts"]["research_excluded"],
                    "disclosed": {
                        "nearest_band_29_59": report["counts"]["nearest_band_29_59"],
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    if args.require_clean and report["verdict"] != "OPERABLE_SURFACE_CLEAN":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
