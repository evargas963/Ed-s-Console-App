#!/usr/bin/env python3
"""
End-of-day signal scoreboard: logged per-horizon fusion predictions vs realized outcomes.

Data flow (all existing surfaces — no new persistence):
  1. calibration.backfill_outcomes.backfill() attaches snapshot outcome labels
     (outcome_1c/5c/15c/60c) to calibration_decision_log rows (exact ts join).
  2. Each trusted decision row carries the per-horizon fusion triplets in
     model_outputs_json -> stack_probs_bundle -> multi_horizon_ml_fusion_bundle.by_horizon.
  3. This module scores dominant_direction vs the attached outcome label per
     (ticker x horizon) and writes reports/daily_scoreboard/<date>.{json,html}.

Usage (operator / scheduled task):
  python -m calibration.daily_scoreboard                  # today (ET), backfill first, write reports
  python -m calibration.daily_scoreboard --date 2026-06-09 --open
  python -m calibration.daily_scoreboard SPY QQQ IWM --no-backfill
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Optional
from zoneinfo import ZoneInfo

from arch_competition.atomic_io import write_json_file_atomically
from calibration.backfill_outcomes import backfill
from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from calibration.schema import ensure_calibration_schema
# SCHWAB_CSV_CHECKED: COH-SA-2 timezone-authority redirect only.
# This edit reads, derives, renames, emits, and maps no Schwab market-data field;
# CSV row authority does not apply to this non-market-field change.
from time_et import ET  # COH-SA-2: America/New_York ZoneInfo authority lives only in time_et.py

log = logging.getLogger(__name__)

HORIZON_SLUGS = ("1c", "5c", "15c", "60c")
# ALL-card pseudo-horizon: the consolidated entry signal (multi_horizon final_bias),
# scored against the outcome label of the logged primary (trade-plan) horizon.
ALL_CARD_SLUG = "all"
_FINAL_BIAS_TO_LABEL = {"LONG": "up", "SHORT": "down", "WAIT": "flat"}
SCHEMA_VERSION = "2"
DEFAULT_REPORT_DIR = Path(__file__).resolve().parents[1] / "reports" / "daily_scoreboard"

# Live writer stamps decision_ts_utc at wall-clock (sub-second) while snapshots_1m_normalized
# rows sit on bar-aligned minute timestamps, so tol=0 exact join attaches nothing for live rows
# (2026-06-09 probe: 14,047/17,763 pending skipped_no_exact_match). 29s keeps the nearest-join
# unambiguous between 60s bars; backfill_outcomes skips ties regardless.
BACKFILL_JOIN_TOL_SEC = 29.0


def et_day_utc_bounds(et_date: str) -> tuple[float, float]:
    """[start, end) epoch-UTC bounds of one ET calendar date ('YYYY-MM-DD')."""
    day = datetime.strptime(et_date, "%Y-%m-%d").replace(tzinfo=ET)
    return day.timestamp(), (day + timedelta(days=1)).timestamp()


def _per_horizon_prediction_rows(
    conn: sqlite3.Connection, et_date: str, tickers: Optional[list[str]]
) -> Iterator[dict[str, Any]]:
    """One dict per (decision row x horizon) with prediction + attached outcome label."""
    lo, hi = et_day_utc_bounds(et_date)
    sql = (
        "SELECT ticker, decision_ts_utc, model_outputs_json, multi_horizon_json,"
        " outcome_1c, outcome_5c, outcome_15c, outcome_60c"
        " FROM calibration_decision_log"
        " WHERE calibration_trust='trusted' AND decision_ts_utc >= ? AND decision_ts_utc < ?"
    )
    params: list[Any] = [lo, hi]
    if tickers:
        sql += f" AND ticker IN ({','.join('?' * len(tickers))})"
        params.extend(tickers)
    from time_et import is_rth_ts_utc

    for row in conn.execute(sql + " ORDER BY decision_ts_utc", params):
        if not is_rth_ts_utc(float(row["decision_ts_utc"])):
            continue  # after-hours decisions have no snapshot/outcome row to score against
        try:
            bundle = json.loads(row["model_outputs_json"] or "{}")
        except (TypeError, ValueError):
            continue
        sb = bundle.get("stack_probs_bundle")
        mh = (sb or {}).get("multi_horizon_ml_fusion_bundle") or {}
        by_hz = mh.get("by_horizon") or {}
        for hz in HORIZON_SLUGS:
            hz_blk = by_hz.get(hz)
            if not isinstance(hz_blk, dict) or not hz_blk.get("horizon_fusion_available"):
                continue
            pred = hz_blk.get("dominant_direction")
            if pred not in ("up", "down", "flat"):
                continue
            yield {
                "ticker": str(row["ticker"]),
                "decision_ts_utc": float(row["decision_ts_utc"]),
                "horizon": hz,
                "pred": pred,
                "top_probability": hz_blk.get("top_probability"),
                "truth": row[f"outcome_{hz}"],
            }
        all_row = _all_card_row(row)
        if all_row is not None:
            yield all_row


def _all_card_row(row: sqlite3.Row) -> Optional[dict[str, Any]]:
    """
    ALL-card scoring row from one decision-log entry (operator 2026-06-10).

    The consolidated final_bias (LONG/SHORT/WAIT) is the trade-entry signal; it is
    scored against the outcome label of the logged primary horizon — the horizon
    the trade plan (entry/stop/targets/hold) is built on.
    """
    try:
        mh = json.loads(row["multi_horizon_json"] or "null")
    except (TypeError, ValueError):
        return None
    if not isinstance(mh, dict):
        return None
    pred = _FINAL_BIAS_TO_LABEL.get(str(mh.get("final_bias") or "").upper())
    primary_hz = str(mh.get("primary_horizon") or "")
    if pred is None or primary_hz not in HORIZON_SLUGS:
        return None
    return {
        "ticker": str(row["ticker"]),
        "decision_ts_utc": float(row["decision_ts_utc"]),
        "horizon": ALL_CARD_SLUG,
        "pred": pred,
        "top_probability": mh.get("final_confidence"),
        "truth": row[f"outcome_{primary_hz}"],
    }


# ── Rolling per-horizon skill weights for ALL-card pooling ───────────────────
# Forecast-combination weights (Bates & Granger 1969; pooling per Genest & Zidek
# 1986): each horizon's weight in the ALL-card logarithmic opinion pool is its
# rolling out-of-sample skill vs the uniform baseline, skill = ln(3) - log_loss.
# Fail-closed: equal weights unless ALL four horizons have enough scored rows in
# the clean-data window (post serve-stack repair floor — never the poisoned era).
SKILL_LOOKBACK_DAYS_DEFAULT = 10
SKILL_MIN_SCORED_ROWS_PER_HORIZON = 150
_PROB_CLIP_MIN = 1e-6


def rolling_horizon_log_loss(
    db_path: Path | str = DEFAULT_DB,
    tickers: Optional[list[str]] = None,
    *,
    lookback_days: float = SKILL_LOOKBACK_DAYS_DEFAULT,
    now_ts_utc: Optional[float] = None,
) -> dict[str, dict[str, Any]]:
    """
    Mean multiclass NLL of each horizon's logged fusion triplet vs its attached
    outcome label over the trailing window. Returns {hz: {"n": int, "log_loss": float|None}}.
    """
    import math
    import time

    from calibration.fusion_temperature import FIT_WINDOW_FLOOR_UTC
    from time_et import is_rth_ts_utc

    now = float(now_ts_utc) if now_ts_utc is not None else time.time()
    lo = max(now - float(lookback_days) * 86400.0, FIT_WINDOW_FLOOR_UTC)
    sql = (
        "SELECT ticker, decision_ts_utc, model_outputs_json,"
        " outcome_1c, outcome_5c, outcome_15c, outcome_60c"
        " FROM calibration_decision_log"
        " WHERE calibration_trust='trusted' AND outcomes_attached_ts_utc IS NOT NULL"
        " AND decision_ts_utc >= ? AND decision_ts_utc < ?"
    )
    params: list[Any] = [lo, now]
    if tickers:
        sql += f" AND ticker IN ({','.join('?' * len(tickers))})"
        params.extend(tickers)
    acc: dict[str, dict[str, float]] = {hz: {"n": 0.0, "nll_sum": 0.0} for hz in HORIZON_SLUGS}
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        for row in conn.execute(sql, params):
            if not is_rth_ts_utc(float(row["decision_ts_utc"])):
                continue  # same RTH gate as _per_horizon_prediction_rows — skill must score RTH rows only
            try:
                bundle = json.loads(row["model_outputs_json"] or "{}")
            except (TypeError, ValueError):
                continue
            by_hz = (
                (bundle.get("stack_probs_bundle") or {}).get("multi_horizon_ml_fusion_bundle")
                or {}
            ).get("by_horizon") or {}
            for hz in HORIZON_SLUGS:
                blk = by_hz.get(hz)
                truth = row[f"outcome_{hz}"]
                if not isinstance(blk, dict) or truth not in ("up", "down", "flat"):
                    continue
                if not blk.get("horizon_fusion_available"):
                    continue
                p = blk.get(f"prob_{truth}")
                try:
                    p_f = float(p)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(p_f):
                    continue
                acc[hz]["n"] += 1.0
                acc[hz]["nll_sum"] += -math.log(max(min(p_f, 1.0), _PROB_CLIP_MIN))
    finally:
        conn.close()
    out: dict[str, dict[str, Any]] = {}
    for hz in HORIZON_SLUGS:
        n = int(acc[hz]["n"])
        out[hz] = {"n": n, "log_loss": (acc[hz]["nll_sum"] / n) if n else None}
    return out


def horizon_skill_weights(
    db_path: Path | str = DEFAULT_DB,
    tickers: Optional[list[str]] = None,
    *,
    lookback_days: float = SKILL_LOOKBACK_DAYS_DEFAULT,
    min_rows: int = SKILL_MIN_SCORED_ROWS_PER_HORIZON,
    now_ts_utc: Optional[float] = None,
) -> dict[str, Any]:
    """
    Normalized ALL-card pooling weights per horizon. skill = max(0, ln(3) - log_loss)
    (improvement over the uniform forecast). Equal weights (fallback_equal=True)
    unless every horizon has >= min_rows scored rows AND at least one shows skill.
    """
    import math

    ll = rolling_horizon_log_loss(
        db_path, tickers, lookback_days=lookback_days, now_ts_utc=now_ts_utc
    )
    uniform_ll = math.log(3.0)
    equal = {hz: 1.0 / len(HORIZON_SLUGS) for hz in HORIZON_SLUGS}
    if any(ll[hz]["n"] < int(min_rows) or ll[hz]["log_loss"] is None for hz in HORIZON_SLUGS):
        return {"weights": equal, "fallback_equal": True, "per_horizon": ll}
    skills = {hz: max(0.0, uniform_ll - float(ll[hz]["log_loss"])) for hz in HORIZON_SLUGS}
    total = sum(skills.values())
    if total <= 0.0:
        return {"weights": equal, "fallback_equal": True, "per_horizon": ll}
    return {
        "weights": {hz: skills[hz] / total for hz in HORIZON_SLUGS},
        "fallback_equal": False,
        "per_horizon": ll,
    }


def _new_cell() -> dict[str, Any]:
    return {
        "n_pred": 0,
        "n_scored": 0,
        "hits": 0,
        "n_directional": 0,
        "directional_hits": 0,
        "top_prob_sum_hit": 0.0,
        "top_prob_sum_miss": 0.0,
    }


def _finalize_cell(c: dict[str, Any]) -> dict[str, Any]:
    misses = c["n_scored"] - c["hits"]
    return {
        "n_pred": c["n_pred"],
        "n_scored": c["n_scored"],
        "hits": c["hits"],
        "accuracy": (c["hits"] / c["n_scored"]) if c["n_scored"] else None,
        "n_directional": c["n_directional"],
        "directional_hits": c["directional_hits"],
        "directional_accuracy": (
            (c["directional_hits"] / c["n_directional"]) if c["n_directional"] else None
        ),
        "mean_top_prob_on_hits": (c["top_prob_sum_hit"] / c["hits"]) if c["hits"] else None,
        "mean_top_prob_on_misses": (c["top_prob_sum_miss"] / misses) if misses else None,
    }


def build_daily_scoreboard(
    db_path: Path | str,
    et_date: str,
    tickers: Optional[list[str]] = None,
    run_backfill: bool = True,
) -> dict[str, Any]:
    """Score logged per-horizon fusion predictions against attached outcome labels."""
    backfill_stats: Optional[dict[str, Any]] = None
    if run_backfill:
        backfill_stats = backfill(Path(db_path), tol_sec=BACKFILL_JOIN_TOL_SEC)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_calibration_schema(conn)

    cells: dict[tuple[str, str], dict[str, Any]] = {}
    rollup: dict[str, dict[str, Any]] = {
        hz: _new_cell() for hz in (*HORIZON_SLUGS, ALL_CARD_SLUG)
    }
    try:
        for r in _per_horizon_prediction_rows(conn, et_date, tickers):
            for cell in (
                cells.setdefault((r["ticker"], r["horizon"]), _new_cell()),
                rollup[r["horizon"]],
            ):
                cell["n_pred"] += 1
                truth = r["truth"]
                if truth not in ("up", "down", "flat"):
                    continue  # outcome not attached/labelable yet
                cell["n_scored"] += 1
                hit = r["pred"] == truth
                if hit:
                    cell["hits"] += 1
                tp = r["top_probability"]
                if isinstance(tp, (int, float)):
                    cell["top_prob_sum_hit" if hit else "top_prob_sum_miss"] += float(tp)
                if r["pred"] != "flat":
                    cell["n_directional"] += 1
                    if hit:
                        cell["directional_hits"] += 1
    finally:
        conn.close()

    by_ticker: dict[str, dict[str, Any]] = {}
    for (ticker, hz), cell in sorted(cells.items()):
        by_ticker.setdefault(ticker, {})[hz] = _finalize_cell(cell)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": datetime.now(tz=ZoneInfo("UTC")).isoformat(),
        "et_date": et_date,
        "db_path": str(Path(db_path).resolve()),
        "tickers_filter": tickers,
        "backfill_stats": backfill_stats,
        "by_horizon": {
            hz: _finalize_cell(rollup[hz]) for hz in (*HORIZON_SLUGS, ALL_CARD_SLUG)
        },
        "by_ticker": by_ticker,
    }


# ── SCOREBOARD_ACTIONABILITY_JOIN_V1 (Phase 1 — report-only) ─────────────────
# Segments logged decision rows into actionable vs stale/pending/runtime/UI
# buckets WITHOUT changing scoreboard totals, live horizon_skill_weights, or
# rolling_horizon_log_loss. The freshness budget is READ from server.py's
# existing contract constants (CACHE_TTL x ANALYTICS_STALE_GRACE_CYCLES) —
# never redefined here; unreadable budget fails closed to UNKNOWN states.
# States are derived with explicit provenance:
#   gap_arithmetic_inferred  — consecutive decision rows per (ticker, expiry)
#                              define the bundle lifetime; the fraction inside
#                              the budget is actionable_fraction.
#   harness_annotation       — sparse payload-to-DOM harness evidence; ABSENCE
#                              of harness data never implies UI match or veto
#                              absence (fail-closed to the gap/unknown states).
#   runtime_window_overlay   — operator-supplied runtime failure windows.
#   unknown_*                — tail rows / missing budget / underivable.
# Schwab CSV authority checked: yes
# CSV row(s): NO_SCHWAB_EQUIVALENT — report-only segmentation of already-logged
#   decision rows; no market field read, derivation, or emission changed.
# Derived-field disposition: none required (no derived market field touched).
# All consumers checked: yes — new artifact only; scoreboard JSON/HTML schema
#   and the live skill-weight path are unchanged (locked by tests).
# SCHWAB_CSV_CHECKED
ACTIONABILITY_SCHEMA_VERSION = "1"
ACTIONABILITY_STATES = (
    "ACTIONABLE",
    "STALE",
    "PENDING_NO_BUNDLE",
    "PENDING_KEY_MISMATCH",
    "VETO_WITHHELD",
    "UI_MISMATCH",
    "RUNTIME_ERROR",
    "UNKNOWN",
)
_HARNESS_ANNOTATION_WINDOW_SEC = 600.0
DEFAULT_UI_TRANSPORT_DIR = Path(__file__).resolve().parents[1] / "reports" / "ui_transport"
_DEFAULT_SERVER_PY = Path(__file__).resolve().parents[1] / "server.py"


def read_freshness_budget_sec(server_py: Path | str = _DEFAULT_SERVER_PY) -> Optional[float]:
    """Read ttl x grace from server.py module-level constants via AST.
    Returns None (fail-closed -> UNKNOWN states) if either cannot be read."""
    import ast as _ast

    try:
        tree = _ast.parse(Path(server_py).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return None
    found: dict[str, float] = {}
    for node in tree.body:
        name = None
        value = None
        if isinstance(node, _ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], _ast.Name):
            name, value = node.targets[0].id, node.value
        elif isinstance(node, _ast.AnnAssign) and isinstance(node.target, _ast.Name):
            name, value = node.target.id, node.value
        if name in ("CACHE_TTL", "ANALYTICS_STALE_GRACE_CYCLES") and isinstance(value, _ast.Constant):
            if isinstance(value.value, (int, float)):
                found[name] = float(value.value)
    if "CACHE_TTL" not in found or "ANALYTICS_STALE_GRACE_CYCLES" not in found:
        return None
    return found["CACHE_TTL"] * found["ANALYTICS_STALE_GRACE_CYCLES"]


def _actionability_decision_rows(
    conn: sqlite3.Connection, et_date: str, tickers: Optional[list[str]]
) -> list[dict[str, Any]]:
    """Per-decision rows (trusted, RTH — same gates as the scoreboard)."""
    from time_et import is_rth_ts_utc

    lo, hi = et_day_utc_bounds(et_date)
    sql = (
        "SELECT ticker, decision_ts_utc, expiry, session_label, decision_source"
        " FROM calibration_decision_log"
        " WHERE calibration_trust='trusted' AND decision_ts_utc >= ? AND decision_ts_utc < ?"
    )
    params: list[Any] = [lo, hi]
    if tickers:
        sql += f" AND ticker IN ({','.join('?' * len(tickers))})"
        params.extend(tickers)
    out = []
    for row in conn.execute(sql + " ORDER BY ticker, expiry, decision_ts_utc", params):
        if not is_rth_ts_utc(float(row["decision_ts_utc"])):
            continue
        out.append(
            {
                "ticker": str(row["ticker"]),
                "decision_ts_utc": float(row["decision_ts_utc"]),
                "expiry": row["expiry"],
                "session_label": row["session_label"],
                "decision_source": row["decision_source"],
            }
        )
    return out


def classify_actionability_rows(
    rows: list[dict[str, Any]],
    budget_sec: Optional[float],
    *,
    runtime_error_windows: tuple[tuple[float, float], ...] = (),
    harness_annotations: tuple[dict[str, Any], ...] = (),
) -> list[dict[str, Any]]:
    """State + actionable_fraction per row. Precedence: runtime window overlay >
    harness annotation > gap arithmetic > UNKNOWN. Keys on row fields only —
    no ticker/roster/session/horizon special-casing."""
    by_key: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
    for r in rows:
        by_key.setdefault((r["ticker"], r["expiry"]), []).append(r)
    out: list[dict[str, Any]] = []
    for _key, group in sorted(by_key.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        group.sort(key=lambda r: r["decision_ts_utc"])
        for i, r in enumerate(group):
            ts = r["decision_ts_utc"]
            gap = (group[i + 1]["decision_ts_utc"] - ts) if i + 1 < len(group) else None
            state: str
            frac: Optional[float]
            prov: str
            ann_state = None
            for ann in harness_annotations:
                if (
                    ann.get("ticker") == r["ticker"]
                    and ann.get("state") in ACTIONABILITY_STATES
                    and float(ann.get("ts_lo", 0.0)) <= ts < float(ann.get("ts_hi", 0.0))
                ):
                    ann_state = str(ann["state"])
                    break
            if any(lo <= ts < hi for lo, hi in runtime_error_windows):
                state, frac, prov = "RUNTIME_ERROR", None, "runtime_window_overlay"
            elif ann_state is not None:
                state, frac, prov = ann_state, None, "harness_annotation"
            elif budget_sec is None:
                state, frac, prov = "UNKNOWN", None, "unknown_no_budget"
            elif gap is None or gap <= 0.0:
                state, frac, prov = "UNKNOWN", None, "unknown_no_next_row"
            else:
                frac = min(1.0, float(budget_sec) / float(gap))
                state = "ACTIONABLE" if gap <= float(budget_sec) else "STALE"
                prov = "gap_arithmetic_inferred"
            out.append(
                {
                    **r,
                    "state": state,
                    "actionable_fraction": frac,
                    "gap_to_next_decision_sec": gap,
                    "provenance": prov,
                }
            )
    return out


def load_harness_annotations(
    et_date: str, ui_transport_dir: Path | str = DEFAULT_UI_TRANSPORT_DIR
) -> tuple[tuple[dict[str, Any], ...], int]:
    """Sparse annotations from card-fidelity harness artifacts for the date.
    Returns (annotations, files_loaded). Absent dir/files/fields -> ((), 0):
    absence NEVER implies UI match or veto absence."""
    d = Path(ui_transport_dir)
    if not d.is_dir():
        return (), 0
    anns: list[dict[str, Any]] = []
    files = 0
    for p in sorted(d.glob(f"universal_card_fidelity_*{et_date}*.json")):
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        gen = doc.get("generated_at_utc")
        try:
            gen_ts = datetime.fromisoformat(str(gen)).timestamp()
        except (TypeError, ValueError):
            continue
        files += 1
        for tkr, res in (doc.get("ticker_results") or {}).items():
            bd = (res or {}).get("browser_dom") or {}
            statuses = {
                str(x.get("parity_status") or "") for x in (bd.get("parity_rows") or [])
            }
            state = None
            if any("MISMATCH" in s.upper() for s in statuses):
                state = "UI_MISMATCH"
            elif any("VETO" in s.upper() for s in statuses):
                state = "VETO_WITHHELD"
            if state is not None:
                anns.append(
                    {
                        "ticker": str(tkr),
                        "ts_lo": gen_ts - _HARNESS_ANNOTATION_WINDOW_SEC,
                        "ts_hi": gen_ts,
                        "state": state,
                        "source": p.name,
                    }
                )
    return tuple(anns), files


def build_actionability_report(
    db_path: Path | str,
    et_date: str,
    tickers: Optional[list[str]] = None,
    *,
    server_py: Path | str = _DEFAULT_SERVER_PY,
    ui_transport_dir: Path | str = DEFAULT_UI_TRANSPORT_DIR,
    runtime_error_windows: tuple[tuple[float, float], ...] = (),
) -> dict[str, Any]:
    """Report-only actionability segmentation of the date's decision rows."""
    budget = read_freshness_budget_sec(server_py)
    annotations, harness_files = load_harness_annotations(et_date, ui_transport_dir)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_calibration_schema(conn)
    try:
        rows = _actionability_decision_rows(conn, et_date, tickers)
    finally:
        conn.close()
    classified = classify_actionability_rows(
        rows,
        budget,
        runtime_error_windows=runtime_error_windows,
        harness_annotations=annotations,
    )
    by_state = {s: 0 for s in ACTIONABILITY_STATES}
    by_prov: dict[str, int] = {}
    by_ticker: dict[str, dict[str, Any]] = {}
    for r in classified:
        by_state[r["state"]] += 1
        by_prov[r["provenance"]] = by_prov.get(r["provenance"], 0) + 1
        t = by_ticker.setdefault(
            r["ticker"], {"n": 0, "actionable_fraction_sum": 0.0, "n_with_fraction": 0}
        )
        t["n"] += 1
        if isinstance(r["actionable_fraction"], float):
            t["actionable_fraction_sum"] += r["actionable_fraction"]
            t["n_with_fraction"] += 1
    for t in by_ticker.values():
        t["mean_actionable_fraction"] = (
            t["actionable_fraction_sum"] / t["n_with_fraction"] if t["n_with_fraction"] else None
        )
        del t["actionable_fraction_sum"]
    n_total = len(classified)
    return {
        "schema_version": ACTIONABILITY_SCHEMA_VERSION,
        "generated_utc": datetime.now(tz=ZoneInfo("UTC")).isoformat(),
        "et_date": et_date,
        "db_path": str(Path(db_path).resolve()),
        "tickers_filter": tickers,
        "freshness_budget_sec": budget,
        "harness_evidence_files_loaded": harness_files,
        "runtime_error_windows": [list(w) for w in runtime_error_windows],
        "states_supported": list(ACTIONABILITY_STATES),
        "summary": {
            "n_rows": n_total,
            "by_state": by_state,
            "by_provenance": by_prov,
            "unknown_share": (by_state["UNKNOWN"] / n_total) if n_total else None,
            "by_ticker": by_ticker,
        },
        "rows": classified,
    }


def write_actionability_report(
    report: dict[str, Any], out_dir: Path | str = DEFAULT_REPORT_DIR
) -> str:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / f"actionability_{report['et_date']}.json"
    write_json_file_atomically(json_path, report)
    (out / "latest_actionability.json").write_text(
        json_path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return str(json_path)


def _fmt_pct(v: Optional[float]) -> str:
    return f"{100.0 * v:.1f}%" if isinstance(v, (int, float)) else "—"


def render_html(scoreboard: dict[str, Any]) -> str:
    """Self-contained HTML report (opened by the scheduled task at end of day)."""
    date = scoreboard["et_date"]
    head_cells = "".join(
        f"<th>{h}</th>" for h in ("n scored", "accuracy", "directional n", "directional acc")
    )

    def _row(label: str, cell: dict[str, Any]) -> str:
        return (
            f"<tr><td>{label}</td><td>{cell['n_scored']}</td>"
            f"<td>{_fmt_pct(cell['accuracy'])}</td>"
            f"<td>{cell['n_directional']}</td>"
            f"<td>{_fmt_pct(cell['directional_accuracy'])}</td></tr>"
        )

    sections = ["<h2>All tickers — by horizon</h2>", f"<table><tr><th>horizon</th>{head_cells}</tr>"]
    sections += [_row(hz, c) for hz, c in scoreboard["by_horizon"].items()]
    sections.append("</table>")
    for ticker, by_hz in scoreboard["by_ticker"].items():
        sections.append(f"<h2>{ticker}</h2>")
        sections.append(f"<table><tr><th>horizon</th>{head_cells}</tr>")
        sections += [_row(hz, c) for hz, c in by_hz.items()]
        sections.append("</table>")
    body = "\n".join(sections)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Daily signal scoreboard — {date}</title>
<style>
 body {{ font-family: Segoe UI, sans-serif; background: #14161a; color: #e6e6e6; margin: 2rem; }}
 h1 {{ font-size: 1.4rem; }} h2 {{ font-size: 1.1rem; margin-top: 1.5rem; }}
 table {{ border-collapse: collapse; }} td, th {{ border: 1px solid #3a3f47; padding: 4px 12px; text-align: right; }}
 th {{ background: #20242b; }} td:first-child, th:first-child {{ text-align: left; }}
</style></head>
<body><h1>Daily signal scoreboard — {date}</h1>
<p>Accuracy = dominant fusion direction vs realized outcome label (same labels training uses).
Directional = rows where the model called up/down (not flat).
The <b>all</b> row is the consolidated ALL card (trade-entry signal): final_bias scored
against the logged primary-horizon outcome; LONG/SHORT map to up/down, WAIT to flat.</p>
{body}
</body></html>
"""


def write_reports(scoreboard: dict[str, Any], out_dir: Path | str = DEFAULT_REPORT_DIR) -> dict[str, str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    date = scoreboard["et_date"]
    json_path = out / f"scoreboard_{date}.json"
    html_path = out / f"scoreboard_{date}.html"
    write_json_file_atomically(json_path, scoreboard)
    html_path.write_text(render_html(scoreboard), encoding="utf-8")
    for latest, src in (("latest.json", json_path), ("latest.html", html_path)):
        (out / latest).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return {"json": str(json_path), "html": str(html_path)}


def main() -> int:
    ap = argparse.ArgumentParser(description="End-of-day per-horizon signal scoreboard")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--date", default=None, help="ET date YYYY-MM-DD (default: today ET)")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_REPORT_DIR)
    ap.add_argument("--no-backfill", action="store_true", help="Skip outcome attachment pass")
    ap.add_argument("--open", action="store_true", help="Open the HTML report when done (Windows)")
    ap.add_argument("tickers", nargs="*", metavar="TICKER", help="Optional ticker filter")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()

    if not args.db.is_file():
        print(f"DB not found: {args.db}", file=sys.stderr)
        return 1
    require_canonical_db_target(args, tool_name="calibration.daily_scoreboard", write_capable=True)

    et_date = args.date or datetime.now(tz=ET).strftime("%Y-%m-%d")
    tickers = [t.strip().upper() for t in args.tickers if t.strip()] or None
    scoreboard = build_daily_scoreboard(
        args.db, et_date, tickers=tickers, run_backfill=not args.no_backfill
    )
    paths = write_reports(scoreboard, args.out_dir)
    # SCOREBOARD_ACTIONABILITY_JOIN_V1 — report-only companion artifact; a
    # failure here must never break the daily scoreboard itself.
    try:
        act = build_actionability_report(args.db, et_date, tickers=tickers)
        paths["actionability"] = write_actionability_report(act, args.out_dir)
    except Exception as _act_e:  # noqa: BLE001 — report-only tail
        log.warning("actionability report failed (scoreboard unaffected): %s", _act_e)
    print(json.dumps({"et_date": et_date, "by_horizon": scoreboard["by_horizon"], "reports": paths}, indent=2))
    if args.open:
        os.startfile(paths["html"])  # noqa: S606 — operator-facing Windows report open
    return 0


if __name__ == "__main__":
    sys.exit(main())
