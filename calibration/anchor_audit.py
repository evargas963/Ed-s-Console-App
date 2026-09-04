#!/usr/bin/env python3
"""
Reproducible BAR_ANCHOR_V1 anchor-feasibility audit (snapshots vs price_bars_1m).

Contract (matches horizon_outcomes + db.fill_outcomes):
  Anchor at snapshot time T: EXISTS row in price_bars_1m with same ticker key as
  ticker_storage_key(snapshots.ticker) and MAX(bar_end_ts_utc) <= T is not NULL
  (equivalently: at least one bar with bar_end_ts_utc <= T).

This module measures miss rates and root-cause buckets. Use:
  python -m calibration.anchor_audit --db data/ed_console.db
"""

from __future__ import annotations

import argparse
import bisect
import json
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from calibration.schema import ensure_calibration_schema
from calibration.statistical_integrity import bucket_gate, verify_anchor_audit_no_numeric_leak
from math_probabilities import MIN_SAMPLES_STATISTICAL
from timeframe_config import CANONICAL_TIMEFRAME

try:
    from db import configure_sqlite_connection
except Exception:

    def configure_sqlite_connection(conn, **kwargs):
        pass

from db import get_snapshot_sql
from app.domain.instrument_identity import ticker_storage_key
import logging

log = logging.getLogger(__name__)



def _miss_rate_gated(miss: int, n: int) -> tuple[float | None, dict[str, Any]]:
    g = bucket_gate(n, MIN_SAMPLES_STATISTICAL)
    if not g["sufficient_sample"]:
        return None, g
    return round(miss / max(n, 1), 6), g


def _miss_bucket_row(nk: int, mk: int) -> dict[str, Any]:
    mr, rg = _miss_rate_gated(mk, nk)
    return {"n": nk, "miss": mk, "miss_rate": mr, "miss_rate_sample_gate": rg}


def snapshot_has_bar_anchor(conn: sqlite3.Connection, ticker: str, ts_utc: float) -> bool:
    """
    True iff BAR_ANCHOR_V1 anchor exists: some price_bars_1m row for ticker_storage_key(ticker)
    has bar_end_ts_utc <= ts_utc.
    """
    tnorm = ticker_storage_key(ticker)
    r = conn.execute(
        """
        SELECT 1 FROM price_bars_1m
        WHERE ticker=? AND bar_end_ts_utc <= ?
        LIMIT 1
        """,
        (tnorm, ts_utc),
    ).fetchone()
    return r is not None


def _max_bar_end_lte_sorted(bar_ends: list[float], ts: float) -> float | None:
    """Largest bar_end with bar_end <= ts (bar_ends sorted ascending)."""
    if not bar_ends:
        return None
    i = bisect.bisect_right(bar_ends, ts) - 1
    if i < 0:
        return None
    return float(bar_ends[i])


def _rth_flag(market_session: str | None) -> str:
    s = (market_session or "").strip().lower()
    return "rth" if s == "rth" else "non_rth_or_unknown"


def _classify_anchor_miss_root_cause(ends_norm: list[float], ts_utc: float) -> str:
    """Why BAR_ANCHOR_V1 failed for normalized ticker at ts_utc (mutually exclusive buckets)."""
    if not ends_norm:
        return "no_rows_price_bars_1m_for_norm_ticker"
    if ts_utc < ends_norm[0]:
        return "decision_ts_before_earliest_bar_end_retained_history_boundary"
    return "sparse_gap_or_anomaly_no_bar_end_lte_ts"


def _snapshot_session_for_ts(
    conn: sqlite3.Connection, ticker_norm: str, ts_utc: float, canon_tf: str
) -> str | None:
    from ml_data_common import market_session_from_ts_utc

    try:
        return market_session_from_ts_utc(float(ts_utc))
    except (TypeError, ValueError):
        return None


def _audit_trusted_calibration_anchors(
    conn: sqlite3.Connection,
    bar_ends_map: dict[str, list[float]],
    canon_tf: str,
) -> dict[str, Any]:
    """
    Full accumulation-scale metrics for trusted calibration rows only (legacy excluded).
    Uses same BAR_ANCHOR_V1 rule as snapshot_has_bar_anchor / analyze_phase3/4.
    """
    rows = conn.execute(
        """
        SELECT id, ticker, decision_ts_utc FROM calibration_decision_log
        WHERE COALESCE(canonical_timeframe, '1m') = ? AND calibration_trust = 'trusted'
        ORDER BY id
        """,
        (canon_tf,),
    ).fetchall()

    by_ticker_n: dict[str, int] = defaultdict(int)
    by_ticker_miss: dict[str, int] = defaultdict(int)
    by_sess_n: dict[str, int] = defaultdict(int)
    by_sess_miss: dict[str, int] = defaultdict(int)
    by_date_n: dict[str, int] = defaultdict(int)
    by_date_miss: dict[str, int] = defaultdict(int)
    by_rth_n: dict[str, int] = defaultdict(int)
    by_rth_miss: dict[str, int] = defaultdict(int)

    rc_counts: dict[str, int] = defaultdict(int)
    hits = 0
    misses = 0

    for cr in rows:
        ct = float(cr["decision_ts_utc"])
        tk = cr["ticker"]
        tnorm = ticker_storage_key(tk)
        if tnorm not in bar_ends_map:
            bar_ends_map[tnorm] = [
                float(x[0])
                for x in conn.execute(
                    """
                    SELECT bar_end_ts_utc FROM price_bars_1m
                    WHERE ticker=? ORDER BY bar_end_ts_utc ASC
                    """,
                    (tnorm,),
                ).fetchall()
            ]
        ends = bar_ends_map[tnorm]
        mx = _max_bar_end_lte_sorted(ends, ct)
        anchored = mx is not None

        day = time.gmtime(ct)
        dkey = f"{day.tm_year:04d}-{day.tm_mon:02d}-{day.tm_mday:02d}"

        ms = _snapshot_session_for_ts(conn, tnorm, ct, canon_tf)
        sess = (ms or "") or "unknown"
        rb = _rth_flag(ms)

        by_ticker_n[tnorm] += 1
        by_date_n[dkey] += 1
        by_sess_n[sess] += 1
        by_rth_n[rb] += 1

        if anchored:
            hits += 1
        else:
            misses += 1
            by_ticker_miss[tnorm] += 1
            by_date_miss[dkey] += 1
            by_sess_miss[sess] += 1
            by_rth_miss[rb] += 1
            rc_counts[_classify_anchor_miss_root_cause(ends, ct)] += 1

    n_tot = len(rows)
    per_tk = []
    for tk, nt in sorted(by_ticker_n.items()):
        m = by_ticker_miss.get(tk, 0)
        mr, rg = _miss_rate_gated(m, nt)
        per_tk.append(
            {
                "ticker": tk,
                "n": nt,
                "miss": m,
                "miss_rate": mr,
                "miss_rate_sample_gate": rg,
            }
        )
    per_tk.sort(key=lambda x: (-x["miss"], -x["n"]))

    dates_sorted = sorted(by_date_n.keys())
    by_date_list = []
    for d in dates_sorted:
        nd = by_date_n[d]
        md = by_date_miss.get(d, 0)
        mr, rg = _miss_rate_gated(md, nd)
        by_date_list.append(
            {
                "utc_date": d,
                "n": nd,
                "miss": md,
                "miss_rate": mr,
                "miss_rate_sample_gate": rg,
            }
        )

    amr, amrg = _miss_rate_gated(misses, n_tot)

    return {
        "trusted_rows_total": n_tot,
        "trusted_rows_with_anchor": hits,
        "trusted_rows_without_anchor": misses,
        "anchor_miss_rate_overall": amr,
        "anchor_miss_rate_overall_gate": amrg,
        "by_ticker": per_tk,
        "by_market_session_bucket": {
            k: _miss_bucket_row(by_sess_n[k], by_sess_miss.get(k, 0))
            for k in sorted(by_sess_n.keys())
        },
        "by_utc_date": {
            "date_count": len(dates_sorted),
            "date_range_utc": {
                "min": dates_sorted[0] if dates_sorted else None,
                "max": dates_sorted[-1] if dates_sorted else None,
            },
            "per_date": by_date_list,
        },
        "by_rth_bucket": {
            k: _miss_bucket_row(by_rth_n[k], by_rth_miss.get(k, 0))
            for k in sorted(by_rth_n.keys())
        },
        "root_cause_counts_trusted_calibration_misses": dict(rc_counts),
        "root_cause_miss_sum_check": sum(rc_counts.values()) == misses,
    }


def run_anchor_audit(
    db_path: Path,
    *,
    sample_limit: int | None = 5000,
    seed_sample: bool = True,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "meta": {
            "db": str(db_path),
            "ts": time.time(),
            "anchor_rule": (
                "BAR_ANCHOR_V1: require EXISTS price_bars_1m row with "
                "ticker = ticker_storage_key(snapshots.ticker) AND bar_end_ts_utc <= snapshots.ts_utc"
            ),
            "canonical_timeframe": CANONICAL_TIMEFRAME,
        },
        "population": {},
        "overall": {},
        "by_ticker": {},
        "by_market_session_bucket": {},
        "by_utc_date": {},
        "by_rth_bucket": {},
        "root_cause_counts": {},
        "note_calibration": "",
    }

    if not db_path.is_file():
        out["error"] = "db not found"
        return out

    conn = sqlite3.connect(str(db_path), timeout=120.0)
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)

    has_bars = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='price_bars_1m' LIMIT 1"
    ).fetchone()
    if not has_bars:
        out["error"] = "price_bars_1m missing"
        conn.close()
        return out

    try:
        ensure_calibration_schema(conn)
    except Exception as e:
        log.debug("anchor audit: %s", e, exc_info=True)
    # Population: all 1m snapshots (or sample)
    base_sql = get_snapshot_sql("calibration/anchor_audit.py:base_population")
    params: list[Any] = [CANONICAL_TIMEFRAME]
    if sample_limit and seed_sample:
        base_sql += " ORDER BY RANDOM() LIMIT ? "
        params.append(sample_limit)
    elif sample_limit:
        base_sql += " LIMIT ? "
        params.append(sample_limit)

    rows = conn.execute(base_sql, params).fetchall()
    n_total = len(rows)

    unique_keys: set[str] = set()
    for r in rows:
        tk0 = r["ticker"]
        unique_keys.add(tk0)
        unique_keys.add(ticker_storage_key(tk0))
    unique_keys.discard("")

    bar_ends_map: dict[str, list[float]] = {}
    for k in unique_keys:
        bar_ends_map[k] = [
            float(x[0])
            for x in conn.execute(
                """
                SELECT bar_end_ts_utc FROM price_bars_1m
                WHERE ticker=? ORDER BY bar_end_ts_utc ASC
                """,
                (k,),
            ).fetchall()
        ]

    miss_audit_rule = 0  # normalized key — authoritative
    by_ticker_miss: dict[str, int] = defaultdict(int)
    by_ticker_n: dict[str, int] = defaultdict(int)
    by_sess: dict[str, int] = defaultdict(int)
    by_sess_miss: dict[str, int] = defaultdict(int)
    by_date_miss: dict[str, int] = defaultdict(int)
    by_date_n: dict[str, int] = defaultdict(int)
    by_rth_n: dict[str, int] = defaultdict(int)
    by_rth_miss: dict[str, int] = defaultdict(int)

    rc_ts_before_min_bar_end = 0
    rc_no_bars_for_ticker_norm = 0
    rc_other_true_gap = 0
    hits_norm_key_fixes_raw_miss = 0

    for r in rows:
        tk = r["ticker"]
        ts = float(r["ts_utc"])
        from ml_data_common import row_market_session_from_ts_utc

        sess = row_market_session_from_ts_utc(r) or "unknown"
        by_sess[sess] += 1
        tnorm = ticker_storage_key(tk)
        by_ticker_n[tk] += 1

        day = time.gmtime(ts)
        dkey = f"{day.tm_year:04d}-{day.tm_mon:02d}-{day.tm_mday:02d}"
        by_date_n[dkey] += 1

        rb = _rth_flag(sess)
        by_rth_n[rb] += 1

        ends_norm = bar_ends_map.get(tnorm, [])
        ends_raw = bar_ends_map.get(tk, [])
        mx_norm = _max_bar_end_lte_sorted(ends_norm, ts)
        mx_raw = _max_bar_end_lte_sorted(ends_raw, ts)

        if mx_norm is not None:
            if mx_raw is None:
                hits_norm_key_fixes_raw_miss += 1
            continue

        miss_audit_rule += 1
        by_ticker_miss[tk] += 1
        by_sess_miss[sess] += 1
        by_date_miss[dkey] += 1
        by_rth_miss[rb] += 1

        if not ends_norm:
            rc_no_bars_for_ticker_norm += 1
        elif ts < ends_norm[0]:
            rc_ts_before_min_bar_end += 1
        else:
            rc_other_true_gap += 1

    out["population"] = {
        "snapshots_rows_scanned": n_total,
        "sample_random": bool(sample_limit and seed_sample),
        "sample_limit": sample_limit,
        "note": (
            "Snapshot-side miss rates describe the scanned subset (random sample when sample_random); "
            "calibration_trusted_anchor_audit uses full trusted calibration_decision_log population."
        ),
    }
    mr_ov, mr_ov_g = _miss_rate_gated(miss_audit_rule, n_total)
    out["overall"] = {
        "miss_rate_authoritative_rule": mr_ov,
        "miss_rate_authoritative_rule_gate": mr_ov_g,
        "miss_count_authoritative": miss_audit_rule,
        "hit_count": n_total - miss_audit_rule,
        "hits_where_raw_ticker_would_miss_but_norm_key_hits": hits_norm_key_fixes_raw_miss,
    }
    out["root_cause_counts"] = {
        "hits_saved_by_ticker_storage_key_vs_raw_sql": hits_norm_key_fixes_raw_miss,
        "true_miss_total": miss_audit_rule,
        "subcause_no_rows_price_bars_1m_for_norm_ticker": rc_no_bars_for_ticker_norm,
        "subcause_ts_before_min_bar_end_for_norm_ticker": rc_ts_before_min_bar_end,
        "subcause_sparse_gap_or_anomaly": rc_other_true_gap,
        "subcause_sum_check": rc_no_bars_for_ticker_norm
        + rc_ts_before_min_bar_end
        + rc_other_true_gap,
    }

    # By ticker (top missers)
    per_tk = []
    for tk, nt in sorted(by_ticker_n.items(), key=lambda x: -x[1]):
        m = by_ticker_miss.get(tk, 0)
        if nt == 0:
            continue
        mr, rg = _miss_rate_gated(m, nt)
        per_tk.append(
            {
                "ticker": tk,
                "n": nt,
                "miss": m,
                "miss_rate": mr,
                "miss_rate_sample_gate": rg,
            }
        )
    per_tk.sort(key=lambda x: -x["miss"])
    out["by_ticker"] = {"top_40_by_miss_count": per_tk[:40]}

    # Session
    out["by_market_session_bucket"] = {
        k: _miss_bucket_row(by_sess[k], by_sess_miss.get(k, 0)) for k in sorted(by_sess.keys())
    }

    out["by_rth_bucket"] = {
        k: _miss_bucket_row(by_rth_n[k], by_rth_miss.get(k, 0)) for k in sorted(by_rth_n.keys())
    }

    # Last 14 days by date (if present in sample)
    dates_sorted = sorted(by_date_n.keys())
    recent_days: list[dict[str, Any]] = []
    for d in dates_sorted[-14:]:
        nd = by_date_n[d]
        md = by_date_miss.get(d, 0)
        mr, rg = _miss_rate_gated(md, nd)
        recent_days.append(
            {
                "utc_date": d,
                "n": nd,
                "miss": md,
                "miss_rate": mr,
                "miss_rate_sample_gate": rg,
            }
        )
    out["by_utc_date"] = {
        "date_count_in_sample": len(dates_sorted),
        "recent_days": recent_days,
    }

    out["note_calibration"] = (
        "Calibration rows join outcomes on snapshots(ts_utc); BAR_ANCHOR_V1 outcomes require "
        "price_bars_1m under ticker_storage_key. Use authoritative miss_rate; raw-ticker-only "
        "audits overstate misses when SPX/$SPX-style keys diverge."
    )

    # Calibration decision log: trusted rows only gate study safety; legacy rows are quarantined.
    n_cal_legacy = int(
        conn.execute(
            """
            SELECT COUNT(*) FROM calibration_decision_log
            WHERE COALESCE(canonical_timeframe, '1m') = ? AND calibration_trust = 'legacy'
            """,
            (CANONICAL_TIMEFRAME,),
        ).fetchone()[0]
    )
    n_cal_trusted = int(
        conn.execute(
            """
            SELECT COUNT(*) FROM calibration_decision_log
            WHERE COALESCE(canonical_timeframe, '1m') = ? AND calibration_trust = 'trusted'
            """,
            (CANONICAL_TIMEFRAME,),
        ).fetchone()[0]
    )
    cal_detail = _audit_trusted_calibration_anchors(conn, bar_ends_map, CANONICAL_TIMEFRAME)
    cal_miss = int(cal_detail.get("trusted_rows_without_anchor", 0))
    frac_miss, frac_gate = _miss_rate_gated(cal_miss, n_cal_trusted)
    out["calibration_decision_log"] = {
        "rows_total": n_cal_trusted + n_cal_legacy,
        "rows_trusted": n_cal_trusted,
        "rows_legacy_quarantined": n_cal_legacy,
        "rows_without_bar_anchor_at_decision_ts_trusted_only": cal_miss,
        "fraction_trusted_without_anchor": frac_miss,
        "fraction_trusted_without_anchor_gate": frac_gate,
        "empirical_study_note": (
            "analyze_phase3/4 include only trusted rows where snapshot_has_bar_anchor(...) is true; "
            "unanchored trusted rows never enter labeled_sample_count."
        ),
    }
    out["calibration_trusted_anchor_audit"] = cal_detail
    # Strict: all trusted rows anchored. Use --workflow-safe when misses exist but phase 3/4 still exclude them.
    out["binary_pass"] = cal_miss == 0
    leak_ok = verify_anchor_audit_no_numeric_leak(out)
    out["statistical_integrity"] = {
        "binary_pass": leak_ok,
        "thresholds_reference": (
            "math_probabilities.MIN_SAMPLES_STATISTICAL (30) via calibration.statistical_integrity"
        ),
    }

    conn.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--sample", type=int, default=5000, help="0 = full table scan (slow)")
    ap.add_argument("--full-scan", action="store_true", help="Scan all 1m snapshots (ignore --sample)")
    ap.add_argument(
        "--workflow-safe",
        action="store_true",
        help="Exit 0 even if some calibration rows lack anchor (analyze_phase3/4 exclude them).",
    )
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="calibration.anchor_audit", write_capable=False)
    lim = None if args.full_scan else max(1, args.sample)
    data = run_anchor_audit(args.db, sample_limit=lim, seed_sample=not args.full_scan)
    print(json.dumps(data, indent=2))
    if "error" in data:
        return 1
    if args.workflow_safe:
        return 0
    return 0 if data.get("binary_pass") else 2


if __name__ == "__main__":
    sys.exit(main())
