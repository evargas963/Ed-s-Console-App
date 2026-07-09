#!/usr/bin/env python3
"""
End-of-day signal scoreboard: logged per-horizon fusion predictions vs realized outcomes.

QUALITY CIRCLE PURPOSE (operator 2026-07-09): this scoreboard is part of the
Quality Circle / continuous signal-refinement loop. Its purpose is not merely
to display daily stats — it measures signal quality across the ELIGIBLE
ticker x horizon grid so weak signals, missing coverage, horizon failures,
ticker gaps, calibration issues, and outcome-attachment gaps can be identified
and fed back into future refinement. It must therefore never be
viewer/activity biased: every eligible cell is represented (SCORED or
NOT_SCORED with a reason), row-weighted aggregates are labeled as such, an
equal-weight rollup prevents high-activity dominance, and the quality_circle
section ranks worst tickers/horizons, coverage laggards, missing-outcome
cells, and splits cells by sample-size trust.

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
# v3 (DAILY_SCOREBOARD_DENOMINATOR_FIRST_V1, operator-approved 2026-07-09): the
# eligible governed ticker x horizon grid is enumerated BEFORE scoring; every
# eligible cell is emitted as SCORED or NOT_SCORED with an explicit reason; an
# equal-weight-per-ticker rollup rides beside the existing pooled rollup, which
# is now labeled row_weighted_pooled so activity volume cannot masquerade as
# equal ticker performance. All v2 keys/fields are preserved (additive).
SCHEMA_VERSION = "3"
NOT_SCORED_REASONS = (
    "NO_ROWS_PRODUCED",
    "NOT_IN_ACTIVE_LOGGER",
    "FUSION_UNAVAILABLE",
    "OUTCOME_PENDING",
    "NON_RTH",
    "UNTRUSTED_CALIBRATION",
    "UNPARSEABLE_BUNDLE",
    "UNSUPPORTED_TICKER_OR_HORIZON",
)
# Quality-circle per-cell sample-size trust floor: below ~30 scored rows the
# binomial normal approximation for an accuracy estimate is unreliable (classic
# np>=5 / n(1-p)>=5 rule at p~0.5), so cells under this floor are reported as
# UNDER_SAMPLED and must not drive refinement decisions on their own.
QC_MIN_SCORED_CELL_N = 30
# Ranked quality-circle lists are truncated for readability; every list carries
# its untruncated n_total so truncation is never silent.
QC_LIST_LIMIT = 10
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


# ── DAILY_SCOREBOARD_DENOMINATOR_FIRST_V1 (v3 grid — operator-approved) ──────
# Schwab CSV authority checked: yes
# CSV row(s): NO_SCHWAB_EQUIVALENT — denominator-first accounting over rows the
#   scoreboard already logs; no market field is read, derived, renamed, or
#   emitted here beyond counts/statuses of existing logged decisions.
# Derived-field disposition: none required (no derived market field touched);
#   hit math and the live skill-weight paths are byte-identical (locked by tests).
# All consumers checked: yes — additive JSON keys + HTML sections only; v2 keys
#   and per-cell fields unchanged (tests/test_calibration_daily_scoreboard.py).
# SCHWAB_CSV_CHECKED
def _eligible_roster(conn: sqlite3.Connection) -> tuple[list[str], str]:
    """Governed eligibility roster: the logging_universe enrollment authority
    (core + pinned + panel_auto + user_persisted — db.logging_universe_authoritative_tickers
    semantics). Falls back, labeled, when the table is absent (fixture DBs)."""
    try:
        rows = conn.execute(
            "SELECT ticker FROM logging_universe"
            " WHERE category IN ('core','pinned','panel_auto','user_persisted')"
            " ORDER BY ticker COLLATE NOCASE"
        ).fetchall()
        if rows:
            return [str(r[0]).upper() for r in rows], "logging_universe"
    except sqlite3.Error:
        pass
    return [], "logging_universe_unavailable"


def _production_tallies(
    conn: sqlite3.Connection, et_date: str, tickers: Optional[list[str]]
) -> tuple[dict[str, dict[str, Any]], Optional[set[str]]]:
    """Per-ticker exclusion/production tallies over ALL of today's calibration rows
    (including untrusted and non-RTH, which the scoring pass never sees), plus
    snapshot-presence evidence used to distinguish NOT_IN_ACTIVE_LOGGER from
    NO_ROWS_PRODUCED. Never mutates anything."""
    from time_et import is_rth_ts_utc

    lo, hi = et_day_utc_bounds(et_date)
    sql = (
        "SELECT ticker, decision_ts_utc, calibration_trust, model_outputs_json,"
        " multi_horizon_json,"
        " outcome_1c, outcome_5c, outcome_15c, outcome_60c"
        " FROM calibration_decision_log"
        " WHERE decision_ts_utc >= ? AND decision_ts_utc < ?"
    )
    params: list[Any] = [lo, hi]
    if tickers:
        sql += f" AND ticker IN ({','.join('?' * len(tickers))})"
        params.extend(tickers)

    def _new_t() -> dict[str, Any]:
        return {
            "n_rows_total": 0,
            "n_non_rth": 0,
            "n_untrusted": 0,
            "n_unparseable": 0,
            "hz": {
                hz: {"n_pred": 0, "n_outcome_pending": 0, "n_fusion_unavailable": 0}
                for hz in (*HORIZON_SLUGS, ALL_CARD_SLUG)
            },
        }

    out: dict[str, dict[str, Any]] = {}
    for row in conn.execute(sql, params):
        t = out.setdefault(str(row["ticker"]).upper(), _new_t())
        t["n_rows_total"] += 1
        if not is_rth_ts_utc(float(row["decision_ts_utc"])):
            t["n_non_rth"] += 1
            continue
        if str(row["calibration_trust"]) != "trusted":
            t["n_untrusted"] += 1
            continue
        try:
            bundle = json.loads(row["model_outputs_json"] or "{}")
        except (TypeError, ValueError):
            t["n_unparseable"] += 1
            continue
        by_hz = (
            (bundle.get("stack_probs_bundle") or {}).get("multi_horizon_ml_fusion_bundle") or {}
        ).get("by_horizon") or {}
        for hz in HORIZON_SLUGS:
            blk = by_hz.get(hz)
            cell = t["hz"][hz]
            if (
                not isinstance(blk, dict)
                or not blk.get("horizon_fusion_available")
                or blk.get("dominant_direction") not in ("up", "down", "flat")
            ):
                cell["n_fusion_unavailable"] += 1
                continue
            cell["n_pred"] += 1
            if row[f"outcome_{hz}"] not in ("up", "down", "flat"):
                cell["n_outcome_pending"] += 1
        all_cell = t["hz"][ALL_CARD_SLUG]
        all_row = _all_card_row(row)
        if all_row is None:
            all_cell["n_fusion_unavailable"] += 1
        else:
            all_cell["n_pred"] += 1
            if all_row["truth"] not in ("up", "down", "flat"):
                all_cell["n_outcome_pending"] += 1

    snaps: Optional[set[str]] = None
    try:
        from db import get_snapshot_sql

        snaps = {
            str(r[0]).upper()
            for r in conn.execute(
                get_snapshot_sql("calibration/daily_scoreboard.py:active_logger_tickers_day"),
                (lo, hi),
            )
        }
    except (sqlite3.Error, ImportError, KeyError, FileNotFoundError):
        snaps = None
    return out, snaps


def _cell_not_scored_reason(
    tallies: Optional[dict[str, Any]],
    hz: str,
    snapshot_tickers: Optional[set[str]],
    ticker: str,
) -> str:
    """Explicit reason ladder for an eligible cell with n_scored == 0."""
    if tallies is None or tallies["n_rows_total"] == 0:
        if snapshot_tickers is not None and ticker not in snapshot_tickers:
            return "NOT_IN_ACTIVE_LOGGER"
        return "NO_ROWS_PRODUCED"
    cell = tallies["hz"][hz]
    if cell["n_pred"] > 0:
        return "OUTCOME_PENDING"
    if cell["n_fusion_unavailable"] > 0:
        return "FUSION_UNAVAILABLE"
    if tallies["n_untrusted"] > 0 and tallies["n_untrusted"] + tallies["n_non_rth"] >= tallies["n_rows_total"]:
        return "UNTRUSTED_CALIBRATION"
    if tallies["n_non_rth"] >= tallies["n_rows_total"]:
        return "NON_RTH"
    if tallies["n_unparseable"] > 0:
        return "UNPARSEABLE_BUNDLE"
    return "NO_ROWS_PRODUCED"


def _build_eligible_grid(
    roster: list[str],
    roster_source: str,
    tallies: dict[str, dict[str, Any]],
    snapshot_tickers: Optional[set[str]],
    by_ticker_scored: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Denominator-first grid: every eligible (ticker, horizon) cell is emitted as
    SCORED or NOT_SCORED with a reason — zero-row tickers are never hidden."""
    grid: dict[str, dict[str, Any]] = {}
    tickers = sorted(set(roster) | set(tallies) | set(by_ticker_scored))
    for tk in tickers:
        t_tal = tallies.get(tk)
        rows_today = t_tal["n_rows_total"] if t_tal else 0
        cells: dict[str, Any] = {}
        for hz in (*HORIZON_SLUGS, ALL_CARD_SLUG):
            scored_cell = (by_ticker_scored.get(tk) or {}).get(hz)
            n_pred = scored_cell["n_pred"] if scored_cell else 0
            n_scored = scored_cell["n_scored"] if scored_cell else 0
            rec: dict[str, Any] = {
                "eligibility": "ELIGIBLE" if tk in roster or roster_source != "logging_universe" else "OBSERVED_ONLY",
                "n_pred": n_pred,
                "n_scored": n_scored,
                "n_unscored": n_pred - n_scored,
                "n_outcome_pending": (t_tal["hz"][hz]["n_outcome_pending"] if t_tal else 0),
                "n_fusion_unavailable": (t_tal["hz"][hz]["n_fusion_unavailable"] if t_tal else 0),
                "rows_today": rows_today,
            }
            if n_scored > 0:
                rec["score_status"] = "SCORED"
                rec["accuracy"] = scored_cell["accuracy"]
            else:
                rec["score_status"] = "NOT_SCORED"
                rec["not_scored_reason"] = _cell_not_scored_reason(
                    t_tal, hz, snapshot_tickers, tk
                )
            cells[hz] = rec
        grid[tk] = cells
    return grid


def _equal_weight_rollup(by_ticker_scored: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Equal-weight-per-ticker accuracy: each ticker contributes its own accuracy
    once per horizon, so a high-row-volume ticker cannot dominate the mean."""
    out: dict[str, Any] = {}
    for hz in (*HORIZON_SLUGS, ALL_CARD_SLUG):
        accs = [
            cells[hz]["accuracy"]
            for cells in by_ticker_scored.values()
            if hz in cells and cells[hz]["accuracy"] is not None
        ]
        out[hz] = {
            "n_tickers": len(accs),
            "mean_accuracy_equal_weight": (sum(accs) / len(accs)) if accs else None,
        }
    return out


def _coverage_diagnostics(
    roster: list[str],
    roster_source: str,
    tallies: dict[str, dict[str, Any]],
    grid: dict[str, Any],
) -> dict[str, Any]:
    tickers_with_rows = sorted(t for t, v in tallies.items() if v["n_rows_total"] > 0)
    zero = sorted(t for t in roster if t not in tickers_with_rows)
    hz_cov: dict[str, Any] = {}
    denom = len(grid) or 1
    for hz in (*HORIZON_SLUGS, ALL_CARD_SLUG):
        scored = sum(1 for cells in grid.values() if cells[hz]["score_status"] == "SCORED")
        hz_cov[hz] = {"tickers_scored": scored, "pct_of_grid": scored / denom}
    return {
        "roster_source": roster_source,
        "eligible_tickers": len(roster),
        "tickers_with_rows": len(tickers_with_rows),
        "tickers_zero_rows": len(zero),
        "zero_row_tickers": zero,
        "ticker_coverage_pct": (len(tickers_with_rows) / len(roster)) if roster else None,
        "horizon_coverage": hz_cov,
        "rows_per_ticker": {t: v["n_rows_total"] for t, v in sorted(tallies.items())},
    }


def _quality_circle_summary(
    grid: dict[str, Any], by_ticker_scored: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Continuous-improvement rankings over the eligible grid (contract item 8):
    worst tickers/horizons by accuracy, lowest-coverage tickers, highest
    missing-outcome cells, and the sample-size trust split. Pure function of
    already-computed grid/score data — no extra DB reads, no ticker literals."""
    # Worst tickers: mean accuracy across the ticker's TRUSTED true-horizon
    # cells only (n_scored >= QC_MIN_SCORED_CELL_N; ALL-card excluded — it is
    # the consolidated trade signal, not a horizon). Operator safeguard: a
    # low-sample cell is never ranked as "bad" — tickers with scored rows but
    # no trusted cell are listed separately as under-sampled/not-trustworthy.
    ticker_acc: list[dict[str, Any]] = []
    under_tickers: list[dict[str, Any]] = []
    for tk, cells in by_ticker_scored.items():
        trusted_accs = [
            cells[hz]["accuracy"]
            for hz in HORIZON_SLUGS
            if hz in cells
            and cells[hz]["accuracy"] is not None
            and cells[hz]["n_scored"] >= QC_MIN_SCORED_CELL_N
        ]
        n_scored_total = sum(
            cells[hz]["n_scored"] for hz in HORIZON_SLUGS if hz in cells
        )
        if trusted_accs:
            ticker_acc.append(
                {
                    "ticker": tk,
                    "mean_accuracy_trusted": sum(trusted_accs) / len(trusted_accs),
                    "n_trusted_horizons": len(trusted_accs),
                    "n_scored_total": n_scored_total,
                }
            )
        elif n_scored_total > 0:
            under_tickers.append(
                {
                    "ticker": tk,
                    "n_scored_total": n_scored_total,
                    "trust": "UNDER_SAMPLED_NOT_TRUSTWORTHY",
                }
            )
    ticker_acc.sort(key=lambda r: (r["mean_accuracy_trusted"], r["ticker"]))
    under_tickers.sort(key=lambda r: r["ticker"])  # alphabetical — never a badness rank

    # Worst horizons: equal-weight mean accuracy per horizon over TRUSTED cells
    # only, ascending; horizons with no trusted cell are flagged
    # insufficient_sample and rank last, not best/worst.
    hz_rank: list[dict[str, Any]] = []
    for hz in HORIZON_SLUGS:
        trusted_accs = []
        n_under = 0
        for cells in by_ticker_scored.values():
            if hz not in cells or cells[hz]["accuracy"] is None:
                continue
            if cells[hz]["n_scored"] >= QC_MIN_SCORED_CELL_N:
                trusted_accs.append(cells[hz]["accuracy"])
            else:
                n_under += 1
        hz_rank.append(
            {
                "horizon": hz,
                "mean_accuracy_equal_weight": (
                    sum(trusted_accs) / len(trusted_accs) if trusted_accs else None
                ),
                "n_tickers_trusted": len(trusted_accs),
                "n_tickers_under_sampled": n_under,
                "insufficient_sample": not trusted_accs,
            }
        )
    hz_rank.sort(
        key=lambda r: (
            r["insufficient_sample"],
            r["mean_accuracy_equal_weight"]
            if r["mean_accuracy_equal_weight"] is not None
            else 0.0,
        )
    )

    # Lowest-coverage tickers: fewest scored true-horizon cells first, then
    # fewest rows — zero-row eligible tickers rank first by construction.
    cov_rank = sorted(
        (
            {
                "ticker": tk,
                "n_horizons_scored": sum(
                    1 for hz in HORIZON_SLUGS if cells[hz]["score_status"] == "SCORED"
                ),
                "rows_today": cells[HORIZON_SLUGS[0]]["rows_today"],
            }
            for tk, cells in grid.items()
        ),
        key=lambda r: (r["n_horizons_scored"], r["rows_today"], r["ticker"]),
    )

    # Highest missing-outcome cells: predictions made, outcomes not yet attached.
    pending = sorted(
        (
            {
                "ticker": tk,
                "horizon": hz,
                "n_outcome_pending": cells[hz]["n_outcome_pending"],
            }
            for tk, cells in grid.items()
            for hz in (*HORIZON_SLUGS, ALL_CARD_SLUG)
            if cells[hz]["n_outcome_pending"] > 0
        ),
        key=lambda r: (-r["n_outcome_pending"], r["ticker"], r["horizon"]),
    )

    # Sample-size trust split over scored cells.
    trusted: list[dict[str, Any]] = []
    under: list[dict[str, Any]] = []
    for tk, cells in grid.items():
        for hz in (*HORIZON_SLUGS, ALL_CARD_SLUG):
            n = cells[hz]["n_scored"]
            if n <= 0:
                continue
            rec = {
                "ticker": tk,
                "horizon": hz,
                "n_scored": n,
                "accuracy": cells[hz].get("accuracy"),
            }
            (trusted if n >= QC_MIN_SCORED_CELL_N else under).append(rec)
    trusted.sort(key=lambda r: (-r["n_scored"], r["ticker"], r["horizon"]))
    under.sort(key=lambda r: (-r["n_scored"], r["ticker"], r["horizon"]))

    def _bounded(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {"n_total": len(rows), "list_limit": QC_LIST_LIMIT, "rows": rows[:QC_LIST_LIMIT]}

    return {
        "purpose": (
            "quality-circle signal-refinement inputs: rankings over the eligible"
            " grid so weak signals, coverage gaps, horizon failures, and"
            " outcome-attachment gaps feed back into refinement"
        ),
        "min_scored_for_trust": QC_MIN_SCORED_CELL_N,
        "worst_tickers_by_accuracy": _bounded(ticker_acc),
        "under_sampled_tickers": _bounded(under_tickers),
        "worst_horizons_by_accuracy": hz_rank,
        "lowest_coverage_tickers": _bounded(cov_rank),
        "highest_missing_outcome_cells": _bounded(pending),
        "trusted_cells": _bounded(trusted),
        "under_sampled_cells": _bounded(under),
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

    # DENOMINATOR-FIRST (v3): enumerate the eligible governed grid and the
    # per-ticker production/exclusion tallies BEFORE any scoring pass runs.
    roster, roster_source = _eligible_roster(conn)
    tallies, snapshot_tickers = _production_tallies(conn, et_date, tickers)
    if tickers:
        roster = [t for t in roster if t in {x.upper() for x in tickers}]

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

    eligible_grid = _build_eligible_grid(
        roster, roster_source, tallies, snapshot_tickers, by_ticker
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": datetime.now(tz=ZoneInfo("UTC")).isoformat(),
        "et_date": et_date,
        "db_path": str(Path(db_path).resolve()),
        "tickers_filter": tickers,
        "backfill_stats": backfill_stats,
        # Pooled rollup: raw scored rows across all tickers — activity volume
        # weights this aggregate (a high-row ticker dominates it by construction).
        "by_horizon_aggregation": "row_weighted_pooled",
        "by_horizon": {
            hz: _finalize_cell(rollup[hz]) for hz in (*HORIZON_SLUGS, ALL_CARD_SLUG)
        },
        # Equal-weight rollup: one vote per scored ticker per horizon.
        "by_horizon_equal_weight": _equal_weight_rollup(by_ticker),
        "by_ticker": by_ticker,
        "eligible_grid": eligible_grid,
        "coverage": _coverage_diagnostics(roster, roster_source, tallies, eligible_grid),
        # Quality Circle (operator contract 2026-07-09 item 8): refinement inputs.
        "quality_circle": _quality_circle_summary(eligible_grid, by_ticker),
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

    sections = [
        "<h2>All tickers — by horizon (row-weighted pooled)</h2>",
        f"<table><tr><th>horizon</th>{head_cells}</tr>",
    ]
    sections += [_row(hz, c) for hz, c in scoreboard["by_horizon"].items()]
    sections.append("</table>")

    # v3 denominator-first sections (coverage + equal-weight + eligible grid).
    ew = scoreboard.get("by_horizon_equal_weight") or {}
    if ew:
        sections.append("<h2>All tickers — by horizon (equal weight per ticker)</h2>")
        sections.append("<table><tr><th>horizon</th><th>tickers scored</th><th>mean accuracy</th></tr>")
        for hz, c in ew.items():
            sections.append(
                f"<tr><td>{hz}</td><td>{c['n_tickers']}</td>"
                f"<td>{_fmt_pct(c['mean_accuracy_equal_weight'])}</td></tr>"
            )
        sections.append("</table>")
    cov = scoreboard.get("coverage") or {}
    if cov:
        zero = ", ".join(cov.get("zero_row_tickers") or []) or "none"
        sections.append(
            f"<p><b>Coverage:</b> {cov.get('tickers_with_rows')}/{cov.get('eligible_tickers')} eligible"
            f" tickers produced rows ({_fmt_pct(cov.get('ticker_coverage_pct'))});"
            f" roster source: {cov.get('roster_source')};"
            f" zero-row tickers: {zero}.</p>"
        )
    grid = scoreboard.get("eligible_grid") or {}
    if grid:
        hz_order = list(next(iter(grid.values())).keys())
        sections.append("<h2>Eligible grid — every governed ticker × horizon</h2>")
        sections.append(
            "<table><tr><th>ticker</th>" + "".join(f"<th>{hz}</th>" for hz in hz_order) + "</tr>"
        )
        for tkr, cells_by_hz in grid.items():
            tds = []
            for hz in hz_order:
                cell = cells_by_hz[hz]
                if cell["score_status"] == "SCORED":
                    tds.append(f"<td>{_fmt_pct(cell.get('accuracy'))} (n={cell['n_scored']})</td>")
                else:
                    tds.append(f"<td>{cell['not_scored_reason']}</td>")
            sections.append(f"<tr><td>{tkr}</td>" + "".join(tds) + "</tr>")
        sections.append("</table>")

    qc = scoreboard.get("quality_circle") or {}
    if qc:
        sections.append("<h2>Quality circle — refinement inputs</h2>")
        wt = qc["worst_tickers_by_accuracy"]
        us = qc["under_sampled_tickers"]
        sections.append(
            f"<p>Worst tickers by mean accuracy over trusted cells"
            f" (n_scored &gt;= {qc['min_scored_for_trust']}; {wt['n_total']} rankable,"
            f" {us['n_total']} under-sampled/not-trustworthy — listed, not ranked):</p>"
            "<table><tr><th>ticker</th><th>mean accuracy (trusted)</th>"
            "<th>trusted horizons</th><th>n scored</th></tr>"
        )
        for r in wt["rows"]:
            sections.append(
                f"<tr><td>{r['ticker']}</td><td>{_fmt_pct(r['mean_accuracy_trusted'])}</td>"
                f"<td>{r['n_trusted_horizons']}</td><td>{r['n_scored_total']}</td></tr>"
            )
        sections.append("</table>")
        if us["rows"]:
            sections.append(
                "<p>Under-sampled tickers (alphabetical): "
                + ", ".join(f"{r['ticker']} (n={r['n_scored_total']})" for r in us["rows"])
                + ".</p>"
            )
        hz_bits = ", ".join(
            f"{r['horizon']}={_fmt_pct(r['mean_accuracy_equal_weight'])}"
            f" (trusted n={r['n_tickers_trusted']}, under-sampled n={r['n_tickers_under_sampled']})"
            for r in qc["worst_horizons_by_accuracy"]
        )
        sections.append(
            f"<p>Worst horizons (equal weight): {hz_bits}.</p>"
            f"<p>Trusted cells (n_scored &gt;= {qc['min_scored_for_trust']}):"
            f" {qc['trusted_cells']['n_total']};"
            f" under-sampled: {qc['under_sampled_cells']['n_total']};"
            f" cells with pending outcomes:"
            f" {qc['highest_missing_outcome_cells']['n_total']}.</p>"
        )

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
