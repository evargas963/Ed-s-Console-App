"""Greeks backfill from the chain archive — Phase 0 (census) + Phase 1 (certification).

P0 — Preflight & slice census (read-only): exact per-ticker chain-bearing row
counts and date ranges via SQL, plus a parsed per-blob slice census on a
deterministic row stride (full parse of 5.1 GB of blobs is an operator-host
run; the stride census is the in-lane preflight). Emits the strike-count
histogram, span percentiles, expiry-mix and floor-failure shares that gate P1.

P1 — Certification parity machine (read-only): post-epoch rows (ts_utc >=
F1_GREEKS_ERA_FLOOR_TS_UTC) are recomputed from their own blobs through the
PRODUCTION aggregation (math_exposure_core.compute_exposures_by_strike, i.e.
the sanitized gamma path) and diffed against the stored snapshots.net_gamma.
Hard gate: parity >= 99.0% or exit non-zero with STOP_PARITY_FAILURE — a
parity failure is a discovery (file an RC), never a tolerance to loosen.

Truth notes (audit 2026-07-24): blobs live in the canonical `snapshots` table
of data/ed_console.db (snapshots_1m_normalized holds byte-identical duplicates,
RC-6); the blob-length floor reuses REPLAY_BUNDLE_MIN_JSON_LENGTH.

Usage:
  python tools/backfill_greeks_from_chain_archive_v1.py --phase p0
  python tools/backfill_greeks_from_chain_archive_v1.py --phase p1
  python tools/backfill_greeks_from_chain_archive_v1.py --phase both --tickers SPY QQQ
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from replay_bundle_coverage import REPLAY_BUNDLE_MIN_JSON_LENGTH  # noqa: E402

DEFAULT_DB = str(REPO_ROOT / "data" / "ed_console.db")
P0_REPORT = REPO_ROOT / "reports" / "backfill_greeks_p0_census_v1.json"
P1_REPORT = REPO_ROOT / "reports" / "backfill_greeks_p1_certification_v1.json"

PARITY_GATE = 0.99
DEFAULT_REL_TOL = 1e-3
DEFAULT_CENSUS_STRIDE = 25
EXPECTED_SLICE_CONTRACTS = 40
MIN_DISTINCT_STRIKES = 20          # RC-12 wall-selection floor
JSON_FAILURE_STOP_SHARE = 0.05     # >5% unparseable/short blobs => STOP + RC


def _era_floor() -> float:
    from research.pilot_step3.f1_input_gates import F1_GREEKS_ERA_FLOOR_TS_UTC

    return float(F1_GREEKS_ERA_FLOOR_TS_UTC)


@dataclass
class SliceCensus:
    n_contracts: int
    n_distinct_strikes: int
    strike_min: float | None
    strike_max: float | None
    span_pct: float | None
    expiry_mix: list[int]
    n_gamma_plausible: int
    oi_total: float
    oi_gamma_rejected: float
    quote_time_span_ms: int | None
    parse_ok: bool


def _num(v: Any) -> float | None:
    """Numeric read of an archived Schwab greek leaf, rejecting NaN/inf (RC-38 class).

    The isinstance guard passed `float('nan')` straight through — NaN IS a float — so a poisoned
    archived greek entered the gamma census as a value instead of an absence. One canonical reader.
    """
    from numeric_contract import float_finite_or_none

    return float_finite_or_none(v)


def _census_one_contract(
    ct: dict[str, Any],
    strikes: set[float],
    expiries: set[int],
    qtimes: list[int],
) -> tuple[float, bool]:
    """Accumulate one contract; returns (oi, gamma_plausible)."""
    from math_exposure_core import gamma_is_plausible

    sp = _num(ct.get("strikePrice"))
    if sp is not None:
        strikes.add(sp)
    dte = _num(ct.get("daysToExpiration"))
    if dte is not None:
        expiries.add(int(dte))
    qt = _num(ct.get("quoteTimeInLong"))
    if qt is not None:
        qtimes.append(int(qt))
    oi = _num(ct.get("openInterest")) or 0.0
    plaus = gamma_is_plausible(_num(ct.get("gamma")), _num(ct.get("delta")))
    return oi, plaus


def census_from_chain(chain: Any, spot: float | None) -> SliceCensus:
    """Pure per-blob slice census (P0 unit; also the future provenance columns)."""
    if not isinstance(chain, list) or not chain:
        return SliceCensus(0, 0, None, None, None, [], 0, 0.0, 0.0, None, False)
    strikes: set[float] = set()
    expiries: set[int] = set()
    qtimes: list[int] = []
    n_plaus = 0
    oi_total = 0.0
    oi_rej = 0.0
    for ct in chain:
        if not isinstance(ct, dict):
            continue
        oi_f, plaus = _census_one_contract(ct, strikes, expiries, qtimes)
        oi_total += oi_f
        if plaus:
            n_plaus += 1
        else:
            oi_rej += oi_f
    s_min = min(strikes) if strikes else None
    s_max = max(strikes) if strikes else None
    span = None
    if s_min is not None and s_max is not None and spot and spot > 0:
        span = (s_max - s_min) / float(spot)
    return SliceCensus(
        n_contracts=len(chain),
        n_distinct_strikes=len(strikes),
        strike_min=s_min,
        strike_max=s_max,
        span_pct=span,
        expiry_mix=sorted(expiries),
        n_gamma_plausible=n_plaus,
        oi_total=oi_total,
        oi_gamma_rejected=oi_rej,
        quote_time_span_ms=(max(qtimes) - min(qtimes)) if qtimes else None,
        parse_ok=True,
    )


def recompute_net_gamma(chain: list[dict[str, Any]], spot: float | None) -> float | None:
    """Slice net dealer gamma in the STORED convention: dollar GEX per 1% move.

    P1's first run discovered the convention empirically (STOP_PARITY_FAILURE
    with sign_parity 1.000 and per-ticker ratios equal to spot^2/100 exactly —
    $SPX 554,000 = 7,443^2/100): stored snapshots.net_gamma = sum(gamma*OI*S^2)
    with the call-positive / put-negative dealer sign, i.e. gamma*OI*mult*S^2*0.01
    per the gamma-flip audit's gex formula. Aggregation runs through the
    PRODUCTION compute_exposures_by_strike (sanitized gamma), then dollarizes.
    """
    from math_exposure_core import compute_exposures_by_strike

    if spot is None or not (float(spot) > 0):
        return None
    exposures, _diag = compute_exposures_by_strike(chain, spot=spot, require_oi=True)
    total = 0.0
    seen = False
    for bucket in exposures.values():
        cg = bucket.get("call_gamma")
        pg = bucket.get("put_gamma")
        if isinstance(cg, (int, float)):
            total += float(cg)
            seen = True
        if isinstance(pg, (int, float)):
            total -= float(pg)
            seen = True
    if not seen:
        return None
    s = float(spot)
    return total * s * s / 100.0


def parity_match(stored: float, recomputed: float, *, rel_tol: float) -> bool:
    if not (math.isfinite(stored) and math.isfinite(recomputed)):
        return False
    denom = max(abs(stored), abs(recomputed), 1e-12)
    return abs(stored - recomputed) / denom <= rel_tol


def _iter_chain_rows(
    db_path: str,
    *,
    tickers: list[str] | None,
    min_ts: float | None,
    stride: int,
) -> Iterator[sqlite3.Row]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    sql = (
        "SELECT snapshot_id, ticker, ts_utc, spot, net_gamma, option_chain_json "
        "FROM snapshots WHERE timeframe = '1m' "
        "AND option_chain_json IS NOT NULL AND LENGTH(option_chain_json) > ?"
    )
    params: list[Any] = [int(REPLAY_BUNDLE_MIN_JSON_LENGTH)]
    if tickers:
        sql += f" AND ticker IN ({','.join('?' * len(tickers))})"
        params.extend(tickers)
    if min_ts is not None:
        sql += " AND ts_utc >= ?"
        params.append(float(min_ts))
    sql += " ORDER BY ticker, ts_utc"
    try:
        for i, row in enumerate(con.execute(sql, params)):
            if i % max(1, stride) == 0:
                yield row
    finally:
        con.close()


def _sql_counts(db_path: str, tickers: list[str] | None) -> list[dict[str, Any]]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    sql = (
        "SELECT ticker, COUNT(*), MIN(ts_utc), MAX(ts_utc), SUM(LENGTH(option_chain_json)) "
        "FROM snapshots WHERE timeframe='1m' "
        "AND option_chain_json IS NOT NULL AND LENGTH(option_chain_json) > ? "
    )
    params: list[Any] = [int(REPLAY_BUNDLE_MIN_JSON_LENGTH)]
    if tickers:
        sql += f" AND ticker IN ({','.join('?' * len(tickers))}) "
        params.extend(tickers)
    sql += "GROUP BY ticker ORDER BY ticker"
    try:
        return [
            {
                "ticker": r[0],
                "n_chain_rows": int(r[1]),
                "ts_min": float(r[2]),
                "ts_max": float(r[3]),
                "blob_bytes": int(r[4]),
            }
            for r in con.execute(sql, params)
        ]
    finally:
        con.close()


def _pct(sorted_vals: list[float], q: float) -> float | None:
    if not sorted_vals:
        return None
    return sorted_vals[min(len(sorted_vals) - 1, max(0, int(q * (len(sorted_vals) - 1))))]


@dataclass
class _P0Acc:
    contract_hist: dict[int, int] = field(default_factory=dict)
    spans: list[float] = field(default_factory=list)
    n_sampled: int = 0
    n_parse_fail: int = 0
    n_expiry_not_0dte: int = 0
    n_floor_fail: int = 0
    n_pre_epoch: int = 0


def _p0_accumulate(row: sqlite3.Row, acc: _P0Acc, era: float) -> None:
    acc.n_sampled += 1
    if float(row["ts_utc"]) < era:
        acc.n_pre_epoch += 1
    try:
        chain = json.loads(row["option_chain_json"])
    except (TypeError, ValueError):
        acc.n_parse_fail += 1
        return
    c = census_from_chain(chain, row["spot"])
    if not c.parse_ok:
        acc.n_parse_fail += 1
        return
    acc.contract_hist[c.n_contracts] = acc.contract_hist.get(c.n_contracts, 0) + 1
    if c.span_pct is not None:
        acc.spans.append(c.span_pct)
    if c.expiry_mix != [0]:
        acc.n_expiry_not_0dte += 1
    if c.n_distinct_strikes < MIN_DISTINCT_STRIKES:
        acc.n_floor_fail += 1


def run_p0(db_path: str, tickers: list[str] | None, stride: int) -> dict[str, Any]:
    t0 = time.perf_counter()
    era = _era_floor()
    counts = _sql_counts(db_path, tickers)
    acc = _P0Acc()
    for row in _iter_chain_rows(db_path, tickers=tickers, min_ts=None, stride=stride):
        _p0_accumulate(row, acc, era)
    contract_hist = acc.contract_hist
    spans = acc.spans
    n_sampled = acc.n_sampled
    n_parse_fail = acc.n_parse_fail
    n_expiry_not_0dte = acc.n_expiry_not_0dte
    n_floor_fail = acc.n_floor_fail
    n_pre_epoch = acc.n_pre_epoch
    spans.sort()
    parse_fail_share = (n_parse_fail / n_sampled) if n_sampled else 0.0
    modes = sorted(contract_hist.items(), key=lambda kv: -kv[1])
    multi_modal = len([m for m in modes if m[1] >= max(5, n_sampled // 50)]) > 1
    report = {
        "schema": "backfill_greeks_p0_census_v1",
        "generated_utc": datetime.now(tz=timezone.utc).isoformat(),
        "db_path": db_path,
        "era_floor_ts_utc": era,
        "blob_len_floor": int(REPLAY_BUNDLE_MIN_JSON_LENGTH),
        "census_stride": stride,
        "per_ticker_counts": counts,
        "n_chain_rows_total": sum(c["n_chain_rows"] for c in counts),
        "blob_bytes_total": sum(c["blob_bytes"] for c in counts),
        "sampled": {
            "n_sampled": n_sampled,
            "n_pre_epoch": n_pre_epoch,
            "parse_fail_share": round(parse_fail_share, 5),
            "n_contracts_histogram": {str(k): v for k, v in sorted(contract_hist.items())},
            "dominant_mode": modes[0][0] if modes else None,
            "multi_modal_slice_types": multi_modal,
            "span_pct_p5": _pct(spans, 0.05),
            "span_pct_p50": _pct(spans, 0.50),
            "span_pct_p95": _pct(spans, 0.95),
            "expiry_not_0dte_share": round(n_expiry_not_0dte / n_sampled, 5) if n_sampled else None,
            "strike_floor_fail_share": round(n_floor_fail / n_sampled, 5) if n_sampled else None,
        },
        "gates": {
            "parse_failure_stop": parse_fail_share > JSON_FAILURE_STOP_SHARE,
            "expected_slice_contracts": EXPECTED_SLICE_CONTRACTS,
        },
        "verdict": (
            "STOP_PARSE_FAILURES"
            if parse_fail_share > JSON_FAILURE_STOP_SHARE
            else "P0_OK_MULTI_MODAL_FLAGGED"
            if multi_modal
            else "P0_OK"
        ),
        "run_sec": round(time.perf_counter() - t0, 2),
    }
    P0_REPORT.parent.mkdir(parents=True, exist_ok=True)
    P0_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


@dataclass
class _P1State:
    n_rows: int = 0
    n_no_stored: int = 0
    n_parse_fail: int = 0
    n_recompute_none: int = 0
    n_compared: int = 0
    n_match: int = 0
    n_sign_match: int = 0
    mismatches: list[dict[str, Any]] = field(default_factory=list)


def _p1_compare(row: sqlite3.Row, st: _P1State, rel_tol: float) -> None:
    st.n_rows += 1
    stored = row["net_gamma"]
    if stored is None:
        st.n_no_stored += 1
        return
    try:
        chain = json.loads(row["option_chain_json"])
    except (TypeError, ValueError):
        st.n_parse_fail += 1
        return
    rc = recompute_net_gamma(chain, row["spot"])
    if rc is None:
        st.n_recompute_none += 1
        return
    st.n_compared += 1
    stored_f = float(stored)
    if (stored_f >= 0) == (rc >= 0):
        st.n_sign_match += 1
    if parity_match(stored_f, rc, rel_tol=rel_tol):
        st.n_match += 1
    elif len(st.mismatches) < 25:
        st.mismatches.append(
            {
                "ticker": row["ticker"],
                "ts_utc": float(row["ts_utc"]),
                "stored": stored_f,
                "recomputed": rc,
                "ratio": (rc / stored_f) if stored_f else None,
            }
        )


def run_p1(db_path: str, tickers: list[str] | None, rel_tol: float) -> dict[str, Any]:
    t0 = time.perf_counter()
    era = _era_floor()
    st = _P1State()
    for row in _iter_chain_rows(db_path, tickers=tickers, min_ts=era, stride=1):
        _p1_compare(row, st, rel_tol)
    n_rows = st.n_rows
    n_no_stored = st.n_no_stored
    n_parse_fail = st.n_parse_fail
    n_recompute_none = st.n_recompute_none
    n_compared = st.n_compared
    n_match = st.n_match
    mismatches = st.mismatches
    parity = (n_match / n_compared) if n_compared else 0.0
    sign_parity = (st.n_sign_match / n_compared) if n_compared else 0.0
    certified = n_compared > 0 and parity >= PARITY_GATE
    report = {
        "schema": "backfill_greeks_p1_certification_v1",
        "generated_utc": datetime.now(tz=timezone.utc).isoformat(),
        "db_path": db_path,
        "era_floor_ts_utc": era,
        "rel_tol": rel_tol,
        "parity_gate": PARITY_GATE,
        "n_post_epoch_chain_rows": n_rows,
        "n_no_stored_net_gamma": n_no_stored,
        "n_parse_fail": n_parse_fail,
        "n_recompute_none": n_recompute_none,
        "n_compared": n_compared,
        "n_match": n_match,
        "parity": round(parity, 6),
        "sign_parity": round(sign_parity, 6),
        "mismatch_examples": mismatches,
        "verdict": "CERTIFIED" if certified else "STOP_PARITY_FAILURE",
        "run_sec": round(time.perf_counter() - t0, 2),
    }
    P1_REPORT.parent.mkdir(parents=True, exist_ok=True)
    P1_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


# ── Phase 2: append-only recompute write (operator-authorized DB write) ───────

RECOMPUTE_VERSION = "greeks_rc_v1_dollar_gex_1pct"
P2_BATCH_ROWS = 2000
P2_OI_REJECT_LOW_TRUST_SHARE = 0.05
P2_REPORT = REPO_ROOT / "reports" / "backfill_greeks_p2_write_v1.json"

_P2_DDL = (
    """
    CREATE TABLE IF NOT EXISTS greeks_recomputed_v1 (
        snapshot_id INTEGER PRIMARY KEY,
        ticker TEXT NOT NULL,
        ts_utc REAL NOT NULL,
        net_gamma_rc REAL,
        n_contracts INTEGER NOT NULL,
        n_distinct_strikes INTEGER NOT NULL,
        n_gamma_plausible INTEGER NOT NULL,
        oi_total REAL NOT NULL,
        oi_gamma_rejected REAL NOT NULL,
        span_pct REAL,
        expiry_mix TEXT NOT NULL,
        slice_type TEXT NOT NULL,
        quote_time_span_ms INTEGER,
        low_trust INTEGER NOT NULL,
        recompute_version TEXT NOT NULL,
        written_utc REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS greeks_recomputed_v1_meta (
        recompute_version TEXT PRIMARY KEY,
        certified_parity REAL NOT NULL,
        certification_report TEXT NOT NULL,
        started_utc REAL NOT NULL,
        completed_utc REAL,
        full_run INTEGER NOT NULL,
        n_rows_written INTEGER NOT NULL
    )
    """,
)


def recomputed_greeks_ready(conn: sqlite3.Connection) -> bool:
    """READ-SIDE GATE: loaders must route the rebuilt_from_chain_archive escape
    through this. True only for a COMPLETED FULL run under a CERTIFIED version —
    partial (--limit / --tickers) runs, in-flight runs, and uncertified versions
    all read as not-ready. Fail-closed on missing tables."""
    try:
        row = conn.execute(
            "SELECT completed_utc, full_run, certified_parity "
            "FROM greeks_recomputed_v1_meta WHERE recompute_version = ?",
            (RECOMPUTE_VERSION,),
        ).fetchone()
    except sqlite3.OperationalError:
        return False
    if row is None:
        return False
    completed, full_run, parity = row
    return completed is not None and int(full_run) == 1 and float(parity) >= PARITY_GATE


def _p1_certified_or_none() -> float | None:
    """Mechanical precondition: P2 refuses to start without a CERTIFIED P1 on disk."""
    if not P1_REPORT.exists():
        return None
    try:
        rep = json.loads(P1_REPORT.read_text(encoding="utf-8"))
    except ValueError:
        return None
    if rep.get("verdict") != "CERTIFIED":
        return None
    return float(rep.get("parity", 0.0))


def _p2_row_payload(row: sqlite3.Row, now_utc: float) -> tuple | None:
    try:
        chain = json.loads(row["option_chain_json"])
    except (TypeError, ValueError):
        return None
    c = census_from_chain(chain, row["spot"])
    if not c.parse_ok:
        return None
    rc = recompute_net_gamma(chain, row["spot"])
    oi_rej_share = (c.oi_gamma_rejected / c.oi_total) if c.oi_total > 0 else 0.0
    low_trust = int(
        c.n_distinct_strikes < MIN_DISTINCT_STRIKES
        or oi_rej_share > P2_OI_REJECT_LOW_TRUST_SHARE
        or rc is None
    )
    slice_kind = "0dte" if c.expiry_mix == [0] else "front_mixed"
    return (
        int(row["snapshot_id"]), str(row["ticker"]), float(row["ts_utc"]), rc,
        c.n_contracts, c.n_distinct_strikes, c.n_gamma_plausible,
        c.oi_total, c.oi_gamma_rejected, c.span_pct,
        json.dumps(c.expiry_mix), f"{slice_kind}_{c.n_contracts}c",
        c.quote_time_span_ms, low_trust, RECOMPUTE_VERSION, now_utc,
    )


def run_p2(db_path: str, tickers: list[str] | None, limit: int) -> dict[str, Any]:
    """Append-only write of recomputed greeks + provenance (same INSERT, atomic
    per row by construction). INSERT OR IGNORE => idempotent resume; per-batch
    transactions so an exception rolls back only the in-flight batch."""
    from db import configure_sqlite_connection

    t0 = time.perf_counter()
    parity = _p1_certified_or_none()
    if parity is None:
        return {
            "schema": "backfill_greeks_p2_write_v1",
            "verdict": "STOP_P1_NOT_CERTIFIED",
            "detail": "run --phase p1 to CERTIFIED before any write phase",
        }
    full_run = 1 if (not tickers and limit <= 0) else 0
    wcon = sqlite3.connect(db_path, timeout=60.0)
    configure_sqlite_connection(wcon)
    now = time.time()
    try:
        for ddl in _P2_DDL:
            wcon.execute(ddl)
        wcon.execute(
            "INSERT OR REPLACE INTO greeks_recomputed_v1_meta "
            "(recompute_version, certified_parity, certification_report, started_utc,"
            " completed_utc, full_run, n_rows_written) VALUES (?,?,?,?,NULL,?,0)",
            (RECOMPUTE_VERSION, parity, str(P1_REPORT), now, full_run),
        )
        wcon.commit()
        ctr = _p2_write_rows(wcon, db_path, tickers, limit, now)
        wcon.execute(
            "UPDATE greeks_recomputed_v1_meta SET completed_utc = ?, n_rows_written = ? "
            "WHERE recompute_version = ?",
            (time.time(), ctr.n_written, RECOMPUTE_VERSION),
        )
        wcon.commit()
    finally:
        wcon.close()
    n_seen = ctr.n_seen
    n_written = ctr.n_written
    n_skipped_existing = ctr.n_skipped
    n_parse_fail = ctr.n_parse_fail
    n_low_trust = ctr.n_low_trust
    rcon = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        ready = recomputed_greeks_ready(rcon)
    finally:
        rcon.close()
    report = {
        "schema": "backfill_greeks_p2_write_v1",
        "generated_utc": datetime.now(tz=timezone.utc).isoformat(),
        "recompute_version": RECOMPUTE_VERSION,
        "certified_parity_precondition": parity,
        "full_run": bool(full_run),
        "n_rows_seen": n_seen,
        "n_rows_written": n_written,
        "n_skipped_existing_append_only": n_skipped_existing,
        "n_parse_fail": n_parse_fail,
        "n_low_trust_flagged": n_low_trust,
        "read_gate_ready": ready,
        "verdict": "P2_COMPLETE" if full_run else "P2_PARTIAL_NOT_READY_BY_DESIGN",
        "run_sec": round(time.perf_counter() - t0, 2),
    }
    P2_REPORT.parent.mkdir(parents=True, exist_ok=True)
    P2_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


@dataclass
class _P2Counters:
    n_seen: int = 0
    n_written: int = 0
    n_skipped: int = 0
    n_parse_fail: int = 0
    n_low_trust: int = 0


def _p2_write_rows(
    wcon: sqlite3.Connection,
    db_path: str,
    tickers: list[str] | None,
    limit: int,
    now: float,
) -> _P2Counters:
    """Batched append-only insert loop (provenance rides in the same INSERT)."""
    ctr = _P2Counters()
    batch: list[tuple] = []
    for row in _iter_chain_rows(db_path, tickers=tickers, min_ts=None, stride=1):
        ctr.n_seen += 1
        payload = _p2_row_payload(row, now)
        if payload is None:
            ctr.n_parse_fail += 1
            continue
        ctr.n_low_trust += int(payload[13])
        batch.append(payload)
        if len(batch) >= P2_BATCH_ROWS:
            ctr.n_written, ctr.n_skipped = _p2_flush(wcon, batch, ctr.n_written, ctr.n_skipped)
            batch = []
        if limit > 0 and ctr.n_seen >= limit:
            break
    if batch:
        ctr.n_written, ctr.n_skipped = _p2_flush(wcon, batch, ctr.n_written, ctr.n_skipped)
    return ctr


def _p2_flush(
    wcon: sqlite3.Connection, batch: list[tuple], n_written: int, n_skipped: int
) -> tuple[int, int]:
    try:
        before = wcon.total_changes
        wcon.executemany(
            "INSERT OR IGNORE INTO greeks_recomputed_v1 VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            batch,
        )
        wcon.commit()
        inserted = wcon.total_changes - before
        return n_written + inserted, n_skipped + (len(batch) - inserted)
    except sqlite3.Error:
        wcon.rollback()
        raise


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--phase", choices=("p0", "p1", "both", "p2"), default="p0")
    ap.add_argument("--tickers", nargs="*", default=None)
    ap.add_argument("--census-stride", type=int, default=DEFAULT_CENSUS_STRIDE)
    ap.add_argument("--rel-tol", type=float, default=DEFAULT_REL_TOL)
    ap.add_argument("--limit", type=int, default=0, help="p2: max rows (0 = full run)")
    args = ap.parse_args()
    if args.phase == "p2":
        rep = run_p2(args.db, args.tickers, args.limit)
        print(json.dumps(rep, indent=2))
        return 0 if rep.get("verdict", "").startswith("P2_") else 4
    exit_code = 0
    out: dict[str, Any] = {}
    if args.phase in ("p0", "both"):
        p0 = run_p0(args.db, args.tickers, max(1, args.census_stride))
        out["p0"] = {k: p0[k] for k in ("verdict", "n_chain_rows_total", "sampled", "run_sec")}
        if p0["verdict"] == "STOP_PARSE_FAILURES":
            exit_code = 2
    if args.phase in ("p1", "both") and exit_code == 0:
        p1 = run_p1(args.db, args.tickers, args.rel_tol)
        out["p1"] = {
            k: p1[k]
            for k in (
                "verdict", "n_post_epoch_chain_rows", "n_compared",
                "parity", "sign_parity", "run_sec",
            )
        }
        if p1["verdict"] != "CERTIFIED":
            exit_code = 3
    out["reports"] = {"p0": str(P0_REPORT), "p1": str(P1_REPORT)}
    print(json.dumps(out, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
