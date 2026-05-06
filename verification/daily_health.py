"""
Daily system health aggregation (read-only SQLite).

Governed constants (DO NOT change for outcome tuning — documentation thresholds only):
  EXPLORATORY_MIN_SAMPLES = 50
  STATISTICAL_MIN_SAMPLES = 1000

Operational thresholds (structural / freshness — explicit in JSON report):
  STALE_BAR_DATA_SEC: no 1m bar within this wall-clock age => DATA FAIL per ticker
  INTRADAY_SEVERE_GAP_SEC / OVERNIGHT_GAP_SEC: intraday holes vs overnight
  Intraday severe gaps require **NYSE calendar weekday (Mon–Fri ET)** for the bar date;
  Sat/Sun bars in the 09:30–16:00 ET clock window are excluded from the FAIL count (not US cash RTH).
  FEATURE_COVERAGE_RECENT_ROWS: max rows scanned per ticker for pred completeness
  FEATURE_COVERAGE_WARN / FAIL: fractions for primary prediction triads
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from instrument_identity import ticker_storage_key
from production_universe import filter_valid_tickers
from timeframe_config import CANONICAL_TIMEFRAME

_ET = ZoneInfo("America/New_York")

# RTH bar-start window (align with pilot 1m loader: 09:30–16:00 ET, end exclusive)
RTH_START_MINS = 570
RTH_END_MINS = 960

# --- Sample tier gates (fixed; reporting only) ---
EXPLORATORY_MIN_SAMPLES = 50
STATISTICAL_MIN_SAMPLES = 1000

PRIMARY_HORIZONS: tuple[str, ...] = ("1c", "5c", "15c", "60c")
# Short horizons: triad must be present on recent rows (pipeline gate).
PRED_TRIAD_FAIL_HORIZONS: tuple[str, ...] = ("1c", "5c")
# Long horizons: sparse triads are WARN-only (often backlog / rollout; not 1c/5c breaks).
PRED_TRIAD_LONG_HORIZONS: tuple[str, ...] = ("15c", "60c")

# --- Structural / freshness (explicit in report; not model thresholds) ---
STALE_BAR_DATA_SEC = 7 * 86400
INTRADAY_SEVERE_GAP_SEC = 300
OVERNIGHT_GAP_SEC = 6 * 3600

FEATURE_COVERAGE_RECENT_ROWS = 5000
FEATURE_COVERAGE_WARN = 0.85
FEATURE_COVERAGE_FAIL = 0.50
# Below this snapshot count, skip pred triad FAIL/WARN gates (explicit WARN instead).
MIN_SNAPSHOTS_FOR_PRED_TRIAD_GATE = 200

# Vol / risk-regime inputs: not primary equity; Schwab 1m may be sparse vs NYSE RTH ladder.
MARKET_CONTEXT_ONLY_TICKERS: frozenset[str] = frozenset({"$VIX"})

REQUIRED_SNAPSHOT_COLUMNS: tuple[str, ...] = (
    "ticker",
    "timeframe",
    "ts_utc",
    "spot",
    "pred_1c_up_prob",
    "pred_1c_down_prob",
    "pred_1c_flat_prob",
    "pred_5c_up_prob",
    "pred_5c_down_prob",
    "pred_5c_flat_prob",
    "pred_15c_up_prob",
    "pred_15c_down_prob",
    "pred_15c_flat_prob",
    "pred_60c_up_prob",
    "pred_60c_down_prob",
    "pred_60c_flat_prob",
    "outcome_1c",
    "outcome_5c",
    "outcome_15c",
    "outcome_60c",
)


def _tier(n: int) -> str:
    if n < EXPLORATORY_MIN_SAMPLES:
        return "INSUFFICIENT"
    if n < STATISTICAL_MIN_SAMPLES:
        return "EXPLORATORY_PASS"
    return "STATISTICAL_PASS"


def _snapshots_columns(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("PRAGMA table_info(snapshots)").fetchall()
    return {str(r[1]) for r in rows}


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    r = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone()
    return r is not None


def _merged_ticker_keys(conn: sqlite3.Connection, *, timeframe: str) -> list[str]:
    snap = {
        str(r[0])
        for r in conn.execute(
            "SELECT DISTINCT ticker FROM snapshots WHERE timeframe = ?",
            (timeframe,),
        ).fetchall()
        if r[0]
    }
    bars: set[str] = set()
    if _table_exists(conn, "price_bars_1m"):
        bars = {
            str(r[0])
            for r in conn.execute("SELECT DISTINCT ticker FROM price_bars_1m").fetchall()
            if r[0]
        }
    merged = sorted(snap | bars)
    return filter_valid_tickers(merged)


def _logging_universe_keys(conn: sqlite3.Connection) -> frozenset[str] | None:
    if not _table_exists(conn, "logging_universe"):
        return None
    rows = conn.execute("SELECT ticker FROM logging_universe").fetchall()
    if not rows:
        return None
    return frozenset({ticker_storage_key(str(r[0])) for r in rows if r[0]})


def _resolve_universe_tickers(
    conn: sqlite3.Connection,
    *,
    timeframe: str,
    mode: str,
    checks: list[dict[str, Any]],
) -> tuple[list[str], str]:
    """
    Returns (tickers, resolution_label).

    ``mode``: ``auto`` | ``merged`` | ``logging``
    - ``merged``: all valid tickers seen in snapshots ∪ price_bars_1m.
    - ``logging``: intersect merged with ``logging_universe`` when non-empty; else merged + WARN.
    - ``auto``: same as ``logging`` when ``logging_universe`` has rows; else merged.
    """
    merged = _merged_ticker_keys(conn, timeframe=timeframe)
    lu = _logging_universe_keys(conn)
    want_intersect = mode in ("auto", "logging")
    if mode == "merged" or not want_intersect or lu is None:
        return merged, "merged_all_valid_tickers"
    hit = [t for t in merged if ticker_storage_key(t) in lu]
    if hit:
        return hit, "logging_universe_intersect"
    checks.append(
        {
            "id": "universe_logging_intersect_empty",
            "severity": "WARN",
            "message": "logging_universe non-empty but intersects no snapshot/bar tickers; using merged universe",
        }
    )
    return merged, "merged_fallback_logging_intersect_empty"


def _check_category(check_id: str) -> str:
    root = check_id.split(":")[0]
    if root.startswith("schema") or root in ("universe_empty",):
        return "STRUCTURAL"
    if root == "universe_logging_intersect_empty":
        return "UNIVERSE"
    if root.startswith("data_"):
        return "DATA"
    if root.startswith("universe_"):
        return "UNIVERSE"
    if root.startswith("feature_pred") or root.startswith("predictions_"):
        return "PREDICTION"
    if root.startswith("feature_registry"):
        return "STRUCTURAL"
    return "OTHER"


def _build_summary(checks: list[dict[str, Any]]) -> dict[str, Any]:
    fail = sum(1 for c in checks if c.get("severity") == "FAIL")
    warn = sum(1 for c in checks if c.get("severity") == "WARN")
    by_cat: dict[str, dict[str, int]] = {}
    for c in checks:
        cat = _check_category(str(c.get("id", "")))
        by_cat.setdefault(cat, {"FAIL": 0, "WARN": 0})
        sev = c.get("severity")
        if sev == "FAIL":
            by_cat[cat]["FAIL"] += 1
        elif sev == "WARN":
            by_cat[cat]["WARN"] += 1
    return {"fail_checks": fail, "warn_checks": warn, "by_category": by_cat}


def _et_date(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone(_ET).strftime("%Y-%m-%d")


def _et_minute_of_day(ts_utc: float) -> int:
    dt = datetime.fromtimestamp(float(ts_utc), tz=timezone.utc).astimezone(_ET)
    return int(dt.hour * 60 + dt.minute)


def _is_rth_bar_start(ts_utc: float) -> bool:
    m = _et_minute_of_day(ts_utc)
    return RTH_START_MINS <= m < RTH_END_MINS


def _et_weekday_mon0_sun6(ts_utc: float) -> int:
    """Python weekday on the bar's America/New_York calendar date (0=Monday)."""
    dt = datetime.fromtimestamp(float(ts_utc), tz=timezone.utc).astimezone(_ET)
    return int(dt.weekday())


def _gap_stats_bars(conn: sqlite3.Connection, ticker: str) -> dict[str, Any]:
    """
    Gap stats on consecutive 1m bar starts.

    **Intraday severe** (structural hole): same ET calendar date, **both** bar starts in
    the **RTH clock window** (09:30–16:00 ET), gap in (INTRADAY_SEVERE_GAP_SEC, OVERNIGHT_GAP_SEC],
    and that calendar date is a **US equity weekday (Mon–Fri)** in New York — excludes
    Saturday/Sunday clock-window artifacts (not NYSE regular session).

    Still excludes pre-market ↔ RTH false positives and overnight (gap > OVERNIGHT_GAP_SEC).
    """
    rows = [
        float(r[0])
        for r in conn.execute(
            "SELECT bar_start_ts_utc FROM price_bars_1m WHERE ticker=? ORDER BY bar_start_ts_utc ASC",
            (ticker,),
        ).fetchall()
    ]
    max_gap = 0.0
    intraday_severe = 0
    intraday_severe_weekend_et_skipped = 0
    overnightish = 0
    for i in range(1, len(rows)):
        gap = rows[i] - rows[i - 1]
        max_gap = max(max_gap, gap)
        if gap > OVERNIGHT_GAP_SEC:
            overnightish += 1
        elif (
            gap > INTRADAY_SEVERE_GAP_SEC
            and _et_date(rows[i]) == _et_date(rows[i - 1])
            and _is_rth_bar_start(rows[i - 1])
            and _is_rth_bar_start(rows[i])
        ):
            if _et_weekday_mon0_sun6(rows[i]) >= 5:
                intraday_severe_weekend_et_skipped += 1
                continue
            intraday_severe += 1
    return {
        "max_gap_sec": float(max_gap),
        "intraday_severe_gaps": int(intraday_severe),
        "intraday_severe_gaps_weekend_et_skipped": int(intraday_severe_weekend_et_skipped),
        "overnightish_gaps": int(overnightish),
    }


def _bars_head_tail(conn: sqlite3.Connection, ticker: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT COUNT(*), MIN(bar_end_ts_utc), MAX(bar_end_ts_utc)
        FROM price_bars_1m WHERE ticker = ?
        """,
        (ticker,),
    ).fetchone()
    n, mn, mx = int(row[0] or 0), row[1], row[2]
    return {"n_bars": n, "bar_end_min": mn, "bar_end_max": mx}


def _snapshot_pred_coverage(
    conn: sqlite3.Connection, *, ticker: str, timeframe: str
) -> dict[str, Any]:
    """Completeness of primary prediction triads on the most recent N rows for ticker."""
    lim = int(FEATURE_COVERAGE_RECENT_ROWS)
    sub = conn.execute(
        f"""
        SELECT pred_1c_up_prob, pred_1c_down_prob, pred_1c_flat_prob,
               pred_5c_up_prob, pred_5c_down_prob, pred_5c_flat_prob,
               pred_15c_up_prob, pred_15c_down_prob, pred_15c_flat_prob,
               pred_60c_up_prob, pred_60c_down_prob, pred_60c_flat_prob
        FROM snapshots WHERE ticker=? AND timeframe=? AND ts_utc IS NOT NULL
        ORDER BY ts_utc DESC LIMIT {lim}
        """,
        (ticker, timeframe),
    ).fetchall()
    if not sub:
        return {"n_recent": 0, "horizons": {}, "partial_triad_rows": 0}
    n = len(sub)
    hz: dict[str, float] = {h: 0.0 for h in PRIMARY_HORIZONS}
    partial_ct = 0
    keys = [
        ("1c", "pred_1c_up_prob", "pred_1c_down_prob", "pred_1c_flat_prob"),
        ("5c", "pred_5c_up_prob", "pred_5c_down_prob", "pred_5c_flat_prob"),
        ("15c", "pred_15c_up_prob", "pred_15c_down_prob", "pred_15c_flat_prob"),
        ("60c", "pred_60c_up_prob", "pred_60c_down_prob", "pred_60c_flat_prob"),
    ]
    for r in sub:
        row_partial = False
        for h, ku, kd, kf in keys:
            vals = [r[ku], r[kd], r[kf]]
            nn = sum(1 for x in vals if x is not None)
            if nn == 3:
                hz[h] += 1.0
            elif 0 < nn < 3:
                row_partial = True
        if row_partial:
            partial_ct += 1
    for h in hz:
        hz[h] /= n
    return {"n_recent": n, "horizons": hz, "partial_triad_rows": partial_ct}


def _labeled_counts(conn: sqlite3.Connection, *, ticker: str, timeframe: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for h in PRIMARY_HORIZONS:
        col = f"outcome_{h}"
        c = conn.execute(
            f"SELECT COUNT(*) FROM snapshots WHERE ticker=? AND timeframe=? AND {col} IN ('up','down','flat')",
            (ticker, timeframe),
        ).fetchone()[0]
        out[h] = int(c or 0)
    return out


@dataclass
class DailyHealthReport:
    generated_ts_utc: float
    db_path: str
    timeframe: str
    overall_pass: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    tickers: list[str] = field(default_factory=list)
    per_ticker: list[dict[str, Any]] = field(default_factory=list)
    constants: dict[str, Any] = field(default_factory=dict)
    feature_contract: dict[str, Any] | None = None
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_ts_utc": self.generated_ts_utc,
            "db_path": self.db_path,
            "timeframe": self.timeframe,
            "overall_pass": self.overall_pass,
            "summary": self.summary,
            "checks": self.checks,
            "tickers": self.tickers,
            "per_ticker": self.per_ticker,
            "constants": self.constants,
            "feature_contract": self.feature_contract,
        }


def run_daily_health(
    db_path: str | Path,
    *,
    all_tickers: bool = True,
    primary_horizons_only: bool = True,
    run_feature_contract: bool = False,
    ticker_filter: list[str] | None = None,
    universe_mode: str = "auto",
) -> DailyHealthReport:
    """
    Execute health checks. Read-only connection.

    If ``run_feature_contract`` is True, runs ``validate_feature_contracts`` (repo filesystem);
    failures append explicit FAIL checks (optional; can be slow / strict in partial trees).

    ``universe_mode``: ``auto`` | ``merged`` | ``logging`` — see ``_resolve_universe_tickers``.
    """
    _ = primary_horizons_only  # reserved — this module only implements primary horizons today
    path = Path(db_path)
    t0 = time.time()
    checks: list[dict[str, Any]] = []
    um = (universe_mode or "auto").strip().lower()
    if um not in ("auto", "merged", "logging"):
        um = "auto"
    # Read-only by convention (no DML). Plain path avoids Windows URI edge cases.
    conn = sqlite3.connect(str(path.resolve()), timeout=60.0)
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "snapshots"):
            checks.append(
                {
                    "id": "schema_snapshots",
                    "severity": "FAIL",
                    "message": "snapshots table missing",
                }
            )
        if not _table_exists(conn, "price_bars_1m"):
            checks.append(
                {
                    "id": "schema_price_bars_1m",
                    "severity": "WARN",
                    "message": "price_bars_1m missing — 1m bar gap/staleness checks skipped",
                }
            )

        cols = _snapshots_columns(conn) if _table_exists(conn, "snapshots") else set()
        missing = [c for c in REQUIRED_SNAPSHOT_COLUMNS if c not in cols]
        if missing:
            checks.append(
                {
                    "id": "schema_required_columns",
                    "severity": "FAIL",
                    "message": f"snapshots missing columns: {missing[:20]}{'...' if len(missing) > 20 else ''}",
                }
            )

        schema_ok = _table_exists(conn, "snapshots") and not missing

        universe_resolution = "n/a"
        if not schema_ok:
            tickers = []
            universe_resolution = "schema_not_ok"
        elif ticker_filter is not None:
            tickers = filter_valid_tickers(ticker_filter)
            universe_resolution = "explicit_ticker_filter"
        elif all_tickers:
            tickers, universe_resolution = _resolve_universe_tickers(
                conn, timeframe=CANONICAL_TIMEFRAME, mode=um, checks=checks
            )
        else:
            tickers = []
            universe_resolution = "none"
        if schema_ok and not tickers:
            checks.append(
                {
                    "id": "universe_empty",
                    "severity": "FAIL",
                    "message": "No valid tickers found in snapshots/price_bars_1m",
                }
            )

        per_ticker: list[dict[str, Any]] = []
        now = time.time()

        for tkr in tickers:
            row: dict[str, Any] = {"ticker": tkr}
            snap_n = int(
                conn.execute(
                    "SELECT COUNT(*) FROM snapshots WHERE ticker=? AND timeframe=?",
                    (tkr, CANONICAL_TIMEFRAME),
                ).fetchone()[0]
                or 0
            )
            row["snapshots_total"] = snap_n
            if _table_exists(conn, "price_bars_1m"):
                bt = _bars_head_tail(conn, tkr)
                row["bars"] = bt
                if snap_n > 0 and bt["n_bars"] == 0:
                    sym_u_bm = (tkr or "").strip().upper()
                    if sym_u_bm in MARKET_CONTEXT_ONLY_TICKERS:
                        checks.append(
                            {
                                "id": f"data_market_context_unavailable:{tkr}",
                                "severity": "FAIL",
                                "message": (
                                    f"snapshots exist for {tkr} but no price_bars_1m rows — "
                                    "MARKET_CONTEXT_ONLY symbol unavailable for risk-regime inputs"
                                ),
                            }
                        )
                    else:
                        checks.append(
                            {
                                "id": f"data_bars_missing:{tkr}",
                                "severity": "WARN",
                                "message": "snapshots exist for ticker but no price_bars_1m rows",
                            }
                        )
                stale = None
                if bt["bar_end_max"] is not None:
                    stale = now - float(bt["bar_end_max"])
                    row["stale_sec"] = stale
                    if stale > STALE_BAR_DATA_SEC:
                        checks.append(
                            {
                                "id": f"data_stale_bars:{tkr}",
                                "severity": "FAIL",
                                "message": f"stale 1m bars: last bar_end {stale/86400:.2f}d ago (limit {STALE_BAR_DATA_SEC/86400:.0f}d)",
                            }
                        )
                gs = _gap_stats_bars(conn, tkr)
                row["bar_gaps"] = gs
                wknd = int(gs.get("intraday_severe_gaps_weekend_et_skipped") or 0)
                if wknd > 0:
                    checks.append(
                        {
                            "id": f"data_rth_clock_gap_weekend_et_excluded:{tkr}",
                            "severity": "WARN",
                            "message": (
                                f"{wknd} same-ET-date RTH-clock-window bar gaps fall on Sat/Sun ET — "
                                "excluded from intraday FAIL (not NYSE cash session); see bar_gaps.intraday_severe_gaps_weekend_et_skipped"
                            ),
                        }
                    )
                if gs["intraday_severe_gaps"] > 0:
                    sym_u = (tkr or "").strip().upper()
                    base_gap_msg = (
                        f"weekday-ET same-session RTH-clock bar-start gaps in ({INTRADAY_SEVERE_GAP_SEC}s, {OVERNIGHT_GAP_SEC}s]: "
                        f"{gs['intraday_severe_gaps']} (max_gap_any={gs['max_gap_sec']:.0f}s)"
                    )
                    if sym_u in MARKET_CONTEXT_ONLY_TICKERS:
                        ctx_note = (
                            " [MARKET_CONTEXT_ONLY: retained for risk-regime / volatility context vs SPY/QQQ; "
                            "Schwab 1m may be non-equity-style — not a primary equity RTH continuity gate]"
                        )
                        if stale is not None and stale > STALE_BAR_DATA_SEC:
                            checks.append(
                                {
                                    "id": f"data_severe_intraday_gap:{tkr}",
                                    "severity": "FAIL",
                                    "message": base_gap_msg
                                    + ctx_note
                                    + f" — FAIL: stale 1m bars ({stale/86400:.2f}d > limit); see data_stale_bars",
                                }
                            )
                        else:
                            checks.append(
                                {
                                    "id": f"data_severe_intraday_gap:{tkr}",
                                    "severity": "WARN",
                                    "message": base_gap_msg + ctx_note,
                                }
                            )
                    else:
                        checks.append(
                            {
                                "id": f"data_severe_intraday_gap:{tkr}",
                                "severity": "FAIL",
                                "message": base_gap_msg,
                            }
                        )
            else:
                row["bars"] = None

            lab = _labeled_counts(conn, ticker=tkr, timeframe=CANONICAL_TIMEFRAME)
            row["labeled_counts"] = lab
            row["labeled_tier"] = {h: _tier(lab[h]) for h in PRIMARY_HORIZONS}

            cov = _snapshot_pred_coverage(conn, ticker=tkr, timeframe=CANONICAL_TIMEFRAME)
            row["pred_coverage_recent"] = cov
            skip_pred_gate = snap_n < MIN_SNAPSHOTS_FOR_PRED_TRIAD_GATE
            if skip_pred_gate:
                checks.append(
                    {
                        "id": f"universe_thin_skip_pred_gate:{tkr}",
                        "severity": "WARN",
                        "message": (
                            f"snapshots_total={snap_n} < {MIN_SNAPSHOTS_FOR_PRED_TRIAD_GATE}; "
                            "pred triad FAIL/WARN gates skipped (not production-thick)"
                        ),
                    }
                )
            if cov["n_recent"] > 0 and not skip_pred_gate:
                for h, frac in cov["horizons"].items():
                    if h in PRED_TRIAD_LONG_HORIZONS:
                        if frac < FEATURE_COVERAGE_FAIL:
                            checks.append(
                                {
                                    "id": f"feature_pred_long_horizon_sparse:{tkr}:{h}",
                                    "severity": "WARN",
                                    "message": (
                                        f"pred {h} triad {frac:.2%} < {FEATURE_COVERAGE_FAIL:.0%} "
                                        f"(last {cov['n_recent']} rows) — long horizon backlog/rollout; "
                                        "not a 1c/5c pipeline FAIL"
                                    ),
                                }
                            )
                        elif frac < FEATURE_COVERAGE_WARN:
                            checks.append(
                                {
                                    "id": f"feature_pred_coverage_warn:{tkr}:{h}",
                                    "severity": "WARN",
                                    "message": f"pred {h} triad completeness {frac:.2%} < {FEATURE_COVERAGE_WARN:.0%}",
                                }
                            )
                        continue
                    if h not in PRED_TRIAD_FAIL_HORIZONS:
                        continue
                    if frac < FEATURE_COVERAGE_FAIL:
                        checks.append(
                            {
                                "id": f"feature_pred_coverage_fail:{tkr}:{h}",
                                "severity": "FAIL",
                                "message": f"pred {h} triad completeness {frac:.2%} < {FEATURE_COVERAGE_FAIL:.0%} (last {cov['n_recent']} rows)",
                            }
                        )
                    elif frac < FEATURE_COVERAGE_WARN:
                        checks.append(
                            {
                                "id": f"feature_pred_coverage_warn:{tkr}:{h}",
                                "severity": "WARN",
                                "message": f"pred {h} triad completeness {frac:.2%} < {FEATURE_COVERAGE_WARN:.0%}",
                            }
                        )
            if cov.get("partial_triad_rows", 0) > 0:
                checks.append(
                    {
                        "id": f"predictions_partial_triad:{tkr}",
                        "severity": "WARN",
                        "message": f"rows with incomplete pred triads in recent window: {cov['partial_triad_rows']}",
                    }
                )

            per_ticker.append(row)

        fc_block: dict[str, Any] | None = None
        if run_feature_contract:
            try:
                from feature_contract_validation import validate_feature_contracts

                root_guess = Path(__file__).resolve().parents[1]
                rep = validate_feature_contracts(root_guess)
                fc_block = rep.to_dict()
                if not rep.passed:
                    checks.append(
                        {
                            "id": "feature_registry_contract",
                            "severity": "FAIL",
                            "message": f"validate_feature_contracts failed: {rep.failures[:5]}",
                        }
                    )
            except Exception as e:
                checks.append(
                    {
                        "id": "feature_registry_contract",
                        "severity": "WARN",
                        "message": f"feature contract validation skipped/error: {e}",
                    }
                )

        fail = any(c.get("severity") == "FAIL" for c in checks)
        overall_pass = not fail
        summary = _build_summary(checks)
        summary["universe_mode_requested"] = um
        summary["universe_resolution"] = universe_resolution

        const = {
            "EXPLORATORY_MIN_SAMPLES": EXPLORATORY_MIN_SAMPLES,
            "STATISTICAL_MIN_SAMPLES": STATISTICAL_MIN_SAMPLES,
            "STALE_BAR_DATA_SEC": STALE_BAR_DATA_SEC,
            "INTRADAY_SEVERE_GAP_SEC": INTRADAY_SEVERE_GAP_SEC,
            "OVERNIGHT_GAP_SEC": OVERNIGHT_GAP_SEC,
            "FEATURE_COVERAGE_RECENT_ROWS": FEATURE_COVERAGE_RECENT_ROWS,
            "FEATURE_COVERAGE_WARN": FEATURE_COVERAGE_WARN,
            "FEATURE_COVERAGE_FAIL": FEATURE_COVERAGE_FAIL,
            "MIN_SNAPSHOTS_FOR_PRED_TRIAD_GATE": MIN_SNAPSHOTS_FOR_PRED_TRIAD_GATE,
            "PRIMARY_HORIZONS": list(PRIMARY_HORIZONS),
            "PRED_TRIAD_FAIL_HORIZONS": list(PRED_TRIAD_FAIL_HORIZONS),
            "PRED_TRIAD_LONG_HORIZONS": list(PRED_TRIAD_LONG_HORIZONS),
            "RTH_BAR_START_MINUTE_RANGE": [RTH_START_MINS, RTH_END_MINS],
        }

        return DailyHealthReport(
            generated_ts_utc=t0,
            db_path=str(path.resolve()),
            timeframe=CANONICAL_TIMEFRAME,
            overall_pass=overall_pass,
            checks=checks,
            tickers=tickers,
            per_ticker=per_ticker,
            constants=const,
            feature_contract=fc_block,
            summary=summary,
        )
    finally:
        conn.close()


def write_reports(report: DailyHealthReport, *, root: Path | None = None) -> tuple[Path, Path, Path]:
    base = root if root is not None else Path(__file__).resolve().parents[1]
    out_dir = base / "reports" / "daily_health"
    hist = out_dir / "history"
    out_dir.mkdir(parents=True, exist_ok=True)
    hist.mkdir(parents=True, exist_ok=True)

    latest_json = out_dir / "latest_daily_health.json"
    latest_md = out_dir / "latest_daily_health.md"
    latest_json.write_text(json.dumps(report.to_dict(), indent=2, default=str), encoding="utf-8")

    lines = [
        "# Daily system health",
        "",
        f"- **PASS**: {report.overall_pass}",
        f"- **DB**: `{report.db_path}`",
        f"- **Timeframe**: `{report.timeframe}`",
        f"- **Tickers**: {len(report.tickers)}",
        "",
    ]
    summ = report.summary or {}
    if summ:
        lines.extend(
            [
                "## Failure categories (summary)",
                "",
                f"- **FAIL checks**: {summ.get('fail_checks', 0)}",
                f"- **WARN checks**: {summ.get('warn_checks', 0)}",
                f"- **Universe resolution**: `{summ.get('universe_resolution', '')}` "
                f"(mode requested: `{summ.get('universe_mode_requested', '')}`)",
                "",
            ]
        )
        by_cat = summ.get("by_category") or {}
        if by_cat:
            lines.append("| category | FAIL | WARN |")
            lines.append("|----------|-----:|-----:|")
            for cat in sorted(by_cat.keys()):
                d = by_cat[cat] or {}
                lines.append(f"| {cat} | {d.get('FAIL', 0)} | {d.get('WARN', 0)} |")
            lines.append("")
    lines.extend(
        [
            "## Checks",
            "",
        ]
    )
    for c in report.checks:
        lines.append(f"- **{c.get('severity')}** `{c.get('id')}`: {c.get('message')}")
    if not report.checks:
        lines.append("- (no issues)")
    lines.extend(["", "## Per-ticker summary", "", "| ticker | bars | stale(d) | intraday_severe | max_gap_s | 1c tier / n | 5c | 15c | 60c | pred1c% |", "|--------|------|----------|-----------------|-----------|-------------|----|----|-----|---------|"])
    for r in report.per_ticker:
        tkr = r["ticker"]
        b = r.get("bars") or {}
        nbar = b.get("n_bars", 0)
        stale_d = (r.get("stale_sec") or 0) / 86400.0 if r.get("stale_sec") is not None else None
        stale_s = f"{stale_d:.2f}" if stale_d is not None else ""
        bg = r.get("bar_gaps") or {}
        sev = bg.get("intraday_severe_gaps", "")
        mxg = bg.get("max_gap_sec", "")
        lt = r.get("labeled_tier") or {}
        lc = r.get("labeled_counts") or {}
        pc = (r.get("pred_coverage_recent") or {}).get("horizons") or {}
        p1 = pc.get("1c")
        p1s = f"{p1:.1%}" if isinstance(p1, float) else ""
        lines.append(
            f"| {tkr} | {nbar} | {stale_s} | {sev} | {mxg} | "
            f"{lt.get('1c','')}/{lc.get('1c','')} | {lt.get('5c','')}/{lc.get('5c','')} | "
            f"{lt.get('15c','')}/{lc.get('15c','')} | {lt.get('60c','')}/{lc.get('60c','')} | {p1s} |"
        )
    lines.append("")
    lines.append("## Constants")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(report.constants, indent=2))
    lines.append("```")
    latest_md.write_text("\n".join(lines), encoding="utf-8")

    from datetime import datetime, timezone

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    hist_json = hist / f"{stamp}_daily_health.json"
    hist_md = hist / f"{stamp}_daily_health.md"
    hist_json.write_text(latest_json.read_text(encoding="utf-8"), encoding="utf-8")
    hist_md.write_text(latest_md.read_text(encoding="utf-8"), encoding="utf-8")
    return latest_json, latest_md, hist_json
