#!/usr/bin/env python3
"""
Database health audit for EdWebConsole (SQLite).

Runs structural checks (integrity, schema), snapshot inventory, normalized-table
rules from snapshot_normalizer, and optional recompute of flow_imbalance from
option_chain_json to detect drift.

Exit code: 0 if no critical findings AND (unless --strict-flow) flow drift within limits.
Use --strict-flow with --deep-flow for a hard gate on 100% flow checks.

Examples:
  python db_health_audit.py
  python db_health_audit.py --deep-flow --strict-flow
  python db_health_audit.py --flow-sample 2000 --flow-tol 0.025
  python db_health_audit.py --json > audit.json
"""
from __future__ import annotations

from db import get_snapshot_sql, sql_flow_audit_count_where, sql_flow_audit_rows_where


import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

from backfill_flow_imbalance import _contracts_from_chain_json
from math_exposure_core import compute_exposures_by_strike
from math_probabilities import flow_imbalance_normalized_with_fallback
from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from snapshot_normalizer import validate_normalization
from timeframe_config import CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME

# Minimum columns expected for training / replay sanity (extend as needed)
SNAPSHOTS_REQUIRED_COLUMNS = (
    "snapshot_id",
    "ticker",
    "timeframe",
    "ts_utc",
    "ts_et",
    "spot",
    "option_chain_json",
    "flow_imbalance",
    "smart_money_score",
    "smart_money_direction",
)


def _connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db), timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


def _pragma(conn: sqlite3.Connection, name: str) -> Any:
    cur = conn.execute(f"PRAGMA {name}")
    row = cur.fetchone()
    return row[0] if row else None


def check_integrity(conn: sqlite3.Connection) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": True, "integrity_check": None, "quick_check": None, "errors": []}
    ic = conn.execute("PRAGMA integrity_check").fetchone()[0]
    out["integrity_check"] = ic
    if ic.lower() != "ok":
        out["ok"] = False
        out["errors"].append(f"integrity_check: {ic}")
    try:
        qc = conn.execute("PRAGMA quick_check").fetchone()[0]
        out["quick_check"] = qc
        if qc and qc.lower() != "ok":
            out["ok"] = False
            out["errors"].append(f"quick_check: {qc}")
    except sqlite3.OperationalError:
        out["quick_check"] = "(unsupported)"
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    out["foreign_key_violations"] = len(fk)
    if fk:
        out["ok"] = False
        out["errors"].append(f"foreign_key_check: {len(fk)} row(s)")
    return out


def check_schema(conn: sqlite3.Connection) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": True, "tables": [], "snapshots_columns_ok": False, "errors": []}
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]
    out["tables"] = tables
    if "snapshots" not in tables:
        out["ok"] = False
        out["errors"].append("missing table: snapshots")
        return out
    cols = {
        r[1]
        for r in conn.execute("PRAGMA table_info(snapshots)").fetchall()
    }
    missing = [c for c in SNAPSHOTS_REQUIRED_COLUMNS if c not in cols]
    out["missing_columns"] = missing
    out["snapshots_columns_ok"] = len(missing) == 0
    if missing:
        out["ok"] = False
        out["errors"].append(f"snapshots missing columns: {missing}")
    return out


def snapshot_inventory(conn: sqlite3.Connection) -> dict[str, Any]:
    out: dict[str, Any] = {}
    tf_rows = conn.execute(
        get_snapshot_sql("db_health_audit.py:115")
    ).fetchall()
    out["by_timeframe"] = {r[0]: r[1] for r in tf_rows}
    total = sum(int(r[1]) for r in tf_rows)
    out["snapshots_total"] = total
    dup_id = conn.execute(
        get_snapshot_sql("db_health_audit.py:121"),
        (CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME),
    ).fetchall()
    out["duplicate_snapshot_ids"] = len(dup_id)
    out["duplicate_snapshot_ids_ok"] = len(dup_id) == 0

    r_chain = conn.execute(
        get_snapshot_sql("db_health_audit.py:132"),
        (CANONICAL_TIMEFRAME,),
    ).fetchone()
    out["chain_json"] = {
        "n": r_chain[0],
        "has_chain": r_chain[1],
        "chain_empty_flow": r_chain[2],
    }

    r_fr = conn.execute(
        get_snapshot_sql("db_health_audit.py:151"),
        (CANONICAL_TIMEFRAME,),
    ).fetchone()
    out["flow_range"] = {
        "min_f": r_fr[0],
        "max_f": r_fr[1],
        "out_of_range": r_fr[2] or 0,
    }
    return out


def _recomputed_flow(chain_json: str, spot: float) -> tuple[float | None, str]:
    contracts = _contracts_from_chain_json(chain_json)
    if len(contracts) < 3:
        return None, "skip_few_contracts"
    exposures, _diag = compute_exposures_by_strike(contracts, spot=spot, require_oi=False)
    flow_norm, src = flow_imbalance_normalized_with_fallback(exposures, spot)
    return flow_norm, src


def audit_flow_consistency(
    conn: sqlite3.Connection,
    *,
    limit: int | None,
    random_sample: bool,
    tol: float,
    progress_every: int = 5000,
) -> dict[str, Any]:
    base_where = """
        WHERE timeframe = ?
          AND option_chain_json IS NOT NULL
          AND length(option_chain_json) > 15
          AND spot IS NOT NULL AND spot > 0
    """
    n_eligible = conn.execute(
        sql_flow_audit_count_where(base_where),
        (CANONICAL_TIMEFRAME,),
    ).fetchone()[0]

    q = sql_flow_audit_rows_where(base_where)
    if random_sample and limit is not None:
        q += f" ORDER BY RANDOM() LIMIT {int(limit)}"
    elif limit is not None:
        q += f" LIMIT {int(limit)}"

    t0 = time.perf_counter()
    rows = conn.execute(q, (CANONICAL_TIMEFRAME,)).fetchall()
    checked = 0
    skipped_contracts = 0
    mismatch = 0
    null_stale = 0  # DB NULL but recompute non-negligible
    zero_stale = 0  # DB 0 but recompute differs beyond tol
    examples: list[dict[str, Any]] = []

    for i, row in enumerate(rows):
        if progress_every and i > 0 and i % progress_every == 0:
            print(f"  flow audit progress: {i}/{len(rows)}", file=sys.stderr)
        sid = int(row["snapshot_id"])
        spot = float(row["spot"])
        raw = row["option_chain_json"]
        stored = row["flow_imbalance"]
        rec, src = _recomputed_flow(raw, spot)
        checked += 1
        if rec is None:
            skipped_contracts += 1
            continue
        if stored is None:
            if abs(rec) > tol:
                null_stale += 1
                if len(examples) < 12:
                    examples.append(
                        {
                            "snapshot_id": sid,
                            "issue": "null_db_nonzero_recompute",
                            "stored": None,
                            "recomputed": rec,
                            "source": src,
                        }
                    )
            continue
        try:
            sf = float(stored)
        except (TypeError, ValueError):
            mismatch += 1
            continue
        if abs(sf - rec) > tol:
            mismatch += 1
            if len(examples) < 12:
                examples.append(
                    {
                        "snapshot_id": sid,
                        "issue": "value_drift",
                        "stored": sf,
                        "recomputed": rec,
                        "delta": round(sf - rec, 4),
                        "source": src,
                    }
                )
        if abs(sf) < 1e-9 and abs(rec) > tol:
            zero_stale += 1

    elapsed = time.perf_counter() - t0
    return {
        "eligible_rows": n_eligible,
        "rows_scanned": len(rows),
        "rows_checked": checked,
        "skipped_few_contracts": skipped_contracts,
        "mismatch_stored_vs_recompute": mismatch,
        "null_stale": null_stale,
        "zero_vs_recompute_stale": zero_stale,
        "tolerance": tol,
        "sample_random": random_sample,
        "examples": examples,
        "elapsed_sec": round(elapsed, 2),
    }


def run_audit(
    db_path: Path,
    *,
    flow_sample: int | None,
    deep_flow: bool,
    flow_tol: float,
    strict_flow: bool,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "db": str(db_path.resolve()),
        "critical_ok": True,
        "warnings": [],
        "sections": {},
    }
    if not db_path.exists():
        report["critical_ok"] = False
        report["fatal"] = "database file not found"
        return report

    conn = _connect(db_path)
    try:
        report["sections"]["journal_mode"] = _pragma(conn, "journal_mode")
        report["sections"]["integrity"] = check_integrity(conn)
        if not report["sections"]["integrity"]["ok"]:
            report["critical_ok"] = False

        report["sections"]["schema"] = check_schema(conn)
        if not report["sections"]["schema"]["ok"]:
            report["critical_ok"] = False

        inv = snapshot_inventory(conn)
        report["sections"]["snapshots"] = inv
        if not inv.get("duplicate_snapshot_ids_ok", True):
            report["critical_ok"] = False

        nz = inv.get("flow_range") or {}
        if int(nz.get("out_of_range") or 0) > 0:
            report["warnings"].append(
                f"flow_imbalance outside [-1,1]: {nz['out_of_range']} rows"
            )

        norm = validate_normalization(db_path)
        report["sections"]["normalized_1m"] = norm
        if not norm.get("ok", False):
            report["critical_ok"] = False

        try:
            n1 = conn.execute(
                get_snapshot_sql("db_health_audit.py:327")
            ).fetchone()[0]
            n5 = conn.execute(
                get_snapshot_sql("db_health_audit.py:330")
            ).fetchone()[0]
        except sqlite3.Error:
            n1 = n5 = None
        report["sections"]["timeframe_counts_raw"] = {"1m": n1, "5m": n5}

        # Flow consistency
        if deep_flow:
            flow_limit: int | None = None
            rnd = False
        elif flow_sample is None or flow_sample <= 0:
            flow_limit = None  # skip flow recompute
            rnd = False
        else:
            flow_limit = flow_sample
            rnd = True

        if flow_limit is None and not deep_flow:
            report["sections"]["flow_recompute_audit"] = {
                "skipped": True,
                "reason": "--flow-sample 0 (disabled); omit for default sample or use --deep-flow",
            }
        else:
            fr = audit_flow_consistency(
                conn,
                limit=flow_limit,
                random_sample=rnd,
                tol=flow_tol,
            )
            report["sections"]["flow_recompute_audit"] = fr
            total_issues = (
                int(fr.get("mismatch_stored_vs_recompute") or 0)
                + int(fr.get("null_stale") or 0)
            )
            scanned = int(fr.get("rows_scanned") or 0)
            if strict_flow and scanned > 0 and total_issues > 0:
                report["critical_ok"] = False
            elif scanned > 0 and total_issues > max(3, scanned * 0.05):
                report["warnings"].append(
                    f"flow recompute drift >5% or many issues in sample "
                    f"(mismatch={fr.get('mismatch_stored_vs_recompute')}, "
                    f"null_stale={fr.get('null_stale')}); run backfill with --force"
                )
    finally:
        conn.close()

    return report


def _print_human(report: dict[str, Any]) -> None:
    print("DB:", report.get("db"))
    if report.get("fatal"):
        print("FATAL:", report["fatal"])
        return
    print("critical_ok:", report.get("critical_ok"))
    for w in report.get("warnings") or []:
        print("WARN:", w)
    sec = report.get("sections") or {}
    if "journal_mode" in sec:
        print("  journal_mode:", sec["journal_mode"])
    ing = sec.get("integrity") or {}
    print("  integrity ok:", ing.get("ok"), "| check:", ing.get("integrity_check"))
    for e in ing.get("errors") or []:
        print("   ", e)
    sch = sec.get("schema") or {}
    print(
        "  schema ok:",
        sch.get("ok"),
        "| snapshots columns ok:",
        sch.get("snapshots_columns_ok"),
    )
    for e in sch.get("errors") or []:
        print("   ", e)
    snap = sec.get("snapshots") or {}
    print("  snapshots total:", snap.get("snapshots_total"))
    print("  by_timeframe:", snap.get("by_timeframe"))
    print("  duplicate snapshot_id groups:", snap.get("duplicate_snapshot_ids"))
    print("  chain_json:", snap.get("chain_json"))
    print("  flow_range:", snap.get("flow_range"))
    print("  raw timeframe counts:", sec.get("timeframe_counts_raw"))
    nrm = sec.get("normalized_1m") or {}
    print("  normalized_1m ok:", nrm.get("ok"), "| rows:", nrm.get("row_count"))
    for e in nrm.get("errors") or []:
        print("   ", e)
    fl = sec.get("flow_recompute_audit") or {}
    if fl.get("skipped"):
        print("  flow_recompute_audit: SKIPPED -", fl.get("reason"))
    else:
        print(
            "  flow_recompute_audit: scanned",
            fl.get("rows_scanned"),
            "/ eligible",
            fl.get("eligible_rows"),
            "| mismatch",
            fl.get("mismatch_stored_vs_recompute"),
            "| null_stale",
            fl.get("null_stale"),
            f"| {fl.get('elapsed_sec')}s",
        )
        if fl.get("examples"):
            print("    examples:")
            print(json.dumps(fl["examples"], indent=2, default=str))


def main() -> None:
    ap = argparse.ArgumentParser(description="SQLite DB health audit")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    register_allow_noncanonical_flag(ap)
    ap.add_argument(
        "--flow-sample",
        type=int,
        default=500,
        help="Random rows with chain JSON to recompute flow (0=skip)",
    )
    ap.add_argument(
        "--deep-flow",
        action="store_true",
        help="Recompute flow for every eligible row (slow)",
    )
    ap.add_argument("--flow-tol", type=float, default=0.02, help="|stored-recompute| max")
    ap.add_argument(
        "--strict-flow",
        action="store_true",
        help="Exit non-zero if any flow mismatch in scanned set",
    )
    ap.add_argument("--json", action="store_true", help="Machine-readable report only")
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="db_health_audit", write_capable=False)

    report = run_audit(
        args.db,
        flow_sample=args.flow_sample,
        deep_flow=args.deep_flow,
        flow_tol=args.flow_tol,
        strict_flow=args.strict_flow,
    )

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        sys.exit(0 if report.get("critical_ok") else 1)

    _print_human(report)
    sys.exit(0 if report.get("critical_ok") else 1)


if __name__ == "__main__":
    main()
