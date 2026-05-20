#!/usr/bin/env python3
"""
Post-fix Schwab theta / timestamp coverage on archived `snapshots.option_chain_json`.

Read-only. Intended for S008 closure evidence (see `governance/SCHWAB_REMEDIATION_SLICE_PLAN_V1.md`
S008 row and `governance/SCHWAB_REMEDIATION_SLICE_CLOSURE_AUDIT_V1.md`). Filter snapshots by
`created_at` cut (deployment / schema-repair conservative window); aggregate contract-level
metrics grouped by ticker × UTC calendar date (from `ts_utc` by default).

Examples:
  python tools/measure_post_fix_theta_v1.py \\
    --since \"2026-05-09 02:37:16\" \\
    --ticker SPY --ticker QQQ

  python tools/measure_post_fix_theta_v1.py --since \"2026-05-09 02:37:16\" --format csv --csv-out theta_matrix.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, DefaultDict, Iterable, TextIO

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from math_exposure import MISSING_GREEK_SENTINEL


@dataclass
class Agg:
    snapshots: int = 0
    chain_parse_errors: int = 0
    snapshots_without_chain: int = 0
    n_contracts: int = 0
    theta_key_missing: int = 0
    theta_present_null: int = 0
    theta_present_numeric: int = 0
    theta_present_sentinel: int = 0
    theta_present_other: int = 0
    quote_time_present: int = 0
    trade_time_present: int = 0


def _utc_date_from_ts_utc(ts: float | None) -> str | None:
    if ts is None:
        return None
    try:
        t = float(ts)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat()


def _utc_date_from_created_at(created_at: str | None) -> str | None:
    if not created_at or not isinstance(created_at, str):
        return None
    s = created_at.strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return None


def _contract_in_scope(ct: dict, scope: str) -> bool:
    if scope == "all":
        return True
    if scope == "zero_dte":
        dte = ct.get("daysToExpiration")
        if dte is None:
            return False
        try:
            return int(float(dte)) == 0
        except (TypeError, ValueError):
            return False
    raise ValueError(f"unknown scope {scope!r}")


def _classify_theta(ct: dict) -> str:
    """Bucket a chain row's ``theta`` field for S008 measurement.

    Schwab uses ``-999.0`` to mark a "missing greek" while still emitting the
    key as numeric. We bucket those separately as ``present_sentinel`` so
    they cannot inflate the ``present_numeric`` rate the operator uses to
    choose Branch A/B/C.
    """
    if "theta" not in ct:
        return "key_missing"
    v = ct["theta"]
    if v is None:
        return "present_null"
    if isinstance(v, bool):
        return "present_other"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if isinstance(v, float) and not math.isfinite(v):
            return "present_other"
        if float(v) == MISSING_GREEK_SENTINEL:
            return "present_sentinel"
        return "present_numeric"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "present_other"
    if f == MISSING_GREEK_SENTINEL:
        return "present_sentinel"
    return "present_numeric"


def _present_long_field(ct: dict, key: str) -> bool:
    if key not in ct:
        return False
    v = ct[key]
    if v is None:
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if isinstance(v, float) and not math.isfinite(v):
            return False
        return True
    if isinstance(v, str) and v.strip() == "":
        return False
    try:
        int(v)
        return True
    except (TypeError, ValueError):
        return False


def _rate(num: int, den: int) -> float | None:
    if den <= 0:
        return None
    return round(num / den, 6)


def _branch_hint(
    *,
    miss_r: float | None,
    null_r: float | None,
    numeric_r: float | None,
    sentinel_r: float | None = None,
    n_contracts: int,
) -> dict[str, Any]:
    """Heuristic only — operator must pick A/B/C per proof-row contract."""
    out: dict[str, Any] = {
        "branch_hint": "insufficient_data",
        "rationale": "",
        "disclaimer": (
            "Heuristic suggestion only. Operator must select Branch A, B, or C with evidence "
            "per the S008 / proof-row Post-Fix Measurement rules."
        ),
    }
    if n_contracts < 50:
        out["rationale"] = f"Very small contract sample (n={n_contracts}); wait for more post-fix data."
        return out
    if miss_r is None or null_r is None or numeric_r is None:
        out["rationale"] = "No contract observations in scope."
        return out
    # Schwab's -999.0 sentinel is functionally equivalent to "theta missing"
    # even though the key is present and numeric. A high sentinel rate is the
    # same diagnosis as a high null rate: Schwab is signalling missing theta.
    sr = sentinel_r if sentinel_r is not None else 0.0
    if sr >= 0.05:
        out["branch_hint"] = "Branch_B_or_C_likely"
        out["rationale"] = (
            f"Material theta -999 sentinel rate ({sr:.3f}); Schwab is reporting theta missing on a "
            "non-trivial share of contracts. Investigate Schwab/API conditioning before choosing B vs C."
        )
        return out
    # Loose thresholds — large samples should drive interpretation.
    if miss_r <= 0.001 and null_r <= 0.02 and sr <= 0.001:
        out["branch_hint"] = "Branch_A_likely"
        out["rationale"] = (
            "theta key missingness ~0, null rate low, sentinel rate ~0; "
            "consistent with Schwab theta reaching archive."
        )
        return out
    if miss_r >= 0.05:
        out["branch_hint"] = "Branch_B_or_C_likely"
        out["rationale"] = (
            "Material theta key missingness; investigate Schwab/API vs serialization before choosing B vs C."
        )
        return out
    out["branch_hint"] = "Branch_C_possible"
    out["rationale"] = (
        "Mixed middle ground: review endpoint/session/shape conditioning and subsamples (SPY vs QQQ, expiry)."
    )
    return out


def _load_rows(
    conn: sqlite3.Connection,
    *,
    since: str,
    tickers: list[str],
) -> Iterable[sqlite3.Row]:
    placeholders = ",".join("?" * len(tickers))
    sql = f"""
        SELECT snapshot_id, ticker, created_at, ts_utc, option_chain_json
        FROM snapshots
        WHERE ticker IN ({placeholders})
          AND created_at > ?
          AND option_chain_json IS NOT NULL
          AND length(option_chain_json) > 10
        ORDER BY ticker ASC, created_at ASC
    """
    params = [*tickers, since]
    return conn.execute(sql, params)


def run_measure(
    db_path: Path,
    *,
    since: str,
    tickers: list[str],
    contract_scope: str,
    date_source: str,
    row_limit: int | None,
) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path), timeout=120)
    conn.row_factory = sqlite3.Row
    try:
        by_key: DefaultDict[tuple[str, str], Agg] = defaultdict(Agg)
        total = Agg()

        cur = _load_rows(conn, since=since, tickers=tickers)
        n_seen = 0
        for row in cur:
            if row_limit is not None and n_seen >= row_limit:
                break
            n_seen += 1
            tkr = str(row["ticker"] or "").upper()
            raw_json = row["option_chain_json"]
            ts_utc = row["ts_utc"]
            created_at = row["created_at"]

            if date_source == "ts_utc":
                dkey = _utc_date_from_ts_utc(float(ts_utc) if ts_utc is not None else None)
                if dkey is None:
                    dkey = _utc_date_from_created_at(created_at) or "unknown_date"
            else:
                dkey = _utc_date_from_created_at(created_at) or (
                    _utc_date_from_ts_utc(float(ts_utc) if ts_utc is not None else None) or "unknown_date"
                )

            key = (tkr, dkey)
            by_key[key].snapshots += 1
            total.snapshots += 1

            try:
                arr = json.loads(raw_json)
            except Exception:
                by_key[key].chain_parse_errors += 1
                total.chain_parse_errors += 1
                continue
            if not isinstance(arr, list) or not arr:
                by_key[key].snapshots_without_chain += 1
                total.snapshots_without_chain += 1
                continue

            for ct in arr:
                if not isinstance(ct, dict):
                    continue
                if not _contract_in_scope(ct, contract_scope):
                    continue
                by_key[key].n_contracts += 1
                total.n_contracts += 1

                tc = _classify_theta(ct)
                if tc == "key_missing":
                    by_key[key].theta_key_missing += 1
                    total.theta_key_missing += 1
                elif tc == "present_null":
                    by_key[key].theta_present_null += 1
                    total.theta_present_null += 1
                elif tc == "present_numeric":
                    by_key[key].theta_present_numeric += 1
                    total.theta_present_numeric += 1
                elif tc == "present_sentinel":
                    by_key[key].theta_present_sentinel += 1
                    total.theta_present_sentinel += 1
                else:
                    by_key[key].theta_present_other += 1
                    total.theta_present_other += 1

                if _present_long_field(ct, "quoteTimeInLong"):
                    by_key[key].quote_time_present += 1
                    total.quote_time_present += 1
                if _present_long_field(ct, "tradeTimeInLong"):
                    by_key[key].trade_time_present += 1
                    total.trade_time_present += 1

        rows_out: list[dict[str, Any]] = []
        for (tkr, dkey) in sorted(by_key.keys()):
            a = by_key[(tkr, dkey)]
            n = a.n_contracts
            rows_out.append(
                {
                    "ticker": tkr,
                    "utc_date": dkey,
                    "snapshot_count": a.snapshots,
                    "contract_observations": n,
                    "chain_parse_errors": a.chain_parse_errors,
                    "snapshots_empty_chain": a.snapshots_without_chain,
                    "theta_key_missing_rate": _rate(a.theta_key_missing, n),
                    "theta_present_null_rate": _rate(a.theta_present_null, n),
                    "theta_present_numeric_rate": _rate(a.theta_present_numeric, n),
                    "theta_present_sentinel_rate": _rate(a.theta_present_sentinel, n),
                    "theta_present_non_numeric_rate": _rate(a.theta_present_other, n),
                    "quoteTimeInLong_present_rate": _rate(a.quote_time_present, n),
                    "tradeTimeInLong_present_rate": _rate(a.trade_time_present, n),
                }
            )

        tn = total.n_contracts
        totals_dict = {
            "snapshot_rows_scanned": total.snapshots,
            "contract_observations": tn,
            "chain_parse_errors": total.chain_parse_errors,
            "snapshots_empty_chain": total.snapshots_without_chain,
            "theta_key_missing_rate": _rate(total.theta_key_missing, tn),
            "theta_present_null_rate": _rate(total.theta_present_null, tn),
            "theta_present_numeric_rate": _rate(total.theta_present_numeric, tn),
            "theta_present_sentinel_rate": _rate(total.theta_present_sentinel, tn),
            "quoteTimeInLong_present_rate": _rate(total.quote_time_present, tn),
            "tradeTimeInLong_present_rate": _rate(total.trade_time_present, tn),
        }
        hint = _branch_hint(
            miss_r=totals_dict["theta_key_missing_rate"],
            null_r=totals_dict["theta_present_null_rate"],
            numeric_r=totals_dict["theta_present_numeric_rate"],
            sentinel_r=totals_dict["theta_present_sentinel_rate"],
            n_contracts=tn,
        )

        return {
            "tool": "measure_post_fix_theta_v1",
            "since_created_at": since,
            "tickers": tickers,
            "contract_scope": contract_scope,
            "utc_date_source": date_source,
            "archive_scope_note": (
                "option_chain_json is written per selected expiry only (see "
                "realized_contract_eval.serialize_option_chain_for_eval). "
                "Contract-scope `all` means all contracts in that archived expiry slice; "
                "other expiries are not present in this column."
            ),
            "matrix": rows_out,
            "totals": totals_dict,
            "recommendation": hint,
        }
    finally:
        conn.close()


def _emit_csv(report: dict[str, Any], stream: TextIO) -> None:
    matrix: list[dict[str, Any]] = report["matrix"]
    if not matrix:
        w = csv.writer(stream)
        w.writerow(["(no rows)"])
        return
    fields = list(matrix[0].keys())
    w = csv.DictWriter(stream, fieldnames=fields)
    w.writeheader()
    for r in matrix:
        w.writerow(r)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="S008 post-fix theta / timestamp rates from snapshots.option_chain_json (read-only).",
    )
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite path (default: canonical Ed DB)")
    register_allow_noncanonical_flag(ap)
    ap.add_argument(
        "--since",
        required=True,
        help="SQL filter: created_at > this value (e.g. '2026-05-09 02:37:16' UTC-aligned string).",
    )
    ap.add_argument(
        "--ticker",
        action="append",
        dest="tickers",
        metavar="SYM",
        help="Ticker to include (repeatable). Default: SPY and QQQ.",
    )
    ap.add_argument(
        "--contract-scope",
        choices=("all", "zero_dte"),
        default="all",
        help="all = every contract in chain JSON; zero_dte = daysToExpiration == 0 only.",
    )
    ap.add_argument(
        "--utc-date-source",
        choices=("ts_utc", "created_at"),
        default="ts_utc",
        help="Group key for UTC date: snapshot ts_utc (default) or created_at string prefix.",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Max snapshot rows to scan (testing / smoke).",
    )
    ap.add_argument("--format", choices=("json", "csv"), default="json")
    ap.add_argument(
        "--csv-out",
        type=Path,
        default=None,
        help="Write CSV matrix to this path (only when --format csv).",
    )
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="measure_post_fix_theta_v1", write_capable=False)

    tickers = args.tickers or ["SPY", "QQQ"]
    tickers = [str(t).strip().upper() for t in tickers if str(t).strip()]

    report = run_measure(
        args.db.resolve(),
        since=args.since.strip(),
        tickers=tickers,
        contract_scope=args.contract_scope,
        date_source=args.utc_date_source,
        row_limit=args.limit,
    )

    if args.format == "json":
        print(json.dumps(report, indent=2, default=str))
        return 0

    if args.csv_out:
        args.csv_out.parent.mkdir(parents=True, exist_ok=True)
        with args.csv_out.open("w", newline="", encoding="utf-8") as f:
            _emit_csv(report, f)
        print(json.dumps({"wrote_csv": str(args.csv_out.resolve())}, indent=2))
        return 0

    _emit_csv(report, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
