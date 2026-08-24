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
from instrument_identity import ticker_storage_key
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
# v4 (SCOREBOARD_TARGET_TRUTH_V1, operator packet 2026-07-13): ALL card scored as
# a TRADE-DECISION surface (LONG/SHORT = directional trade calls, WAIT = abstention
# — never a flat-price prediction); per-horizon confusion matrices, balanced
# accuracy, macro F1, MCC, prediction/truth distributions, always-flat + majority
# baselines, both-nonflat directional accuracy; mechanically derived warnings
# (collapse, baseline failure, sample size, identity cohorts, placeholder
# thresholds); embedded metric definitions + source identity. The v2/v3 fields are
# preserved byte-identically; the legacy ALL triclass metric is retained ONLY for
# reproducibility and labeled LEGACY_INVALID_FOR_TRADE_EDGE.
SCHEMA_VERSION = "4"
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
        " outcome_1c, outcome_5c, outcome_15c, outcome_60c,"
        " outcome_join_method, matched_snapshot_ts_utc, execution_identity_sha256"
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
        cohort = _join_identity_cohort(row)
        bundle_identity_proven = bool(row["execution_identity_sha256"])
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
                "join_cohort": cohort,
                "bundle_identity_proven": bundle_identity_proven,
            }
        all_row = _all_card_row(row)
        if all_row is not None:
            all_row["join_cohort"] = cohort
            all_row["bundle_identity_proven"] = bundle_identity_proven
            yield all_row


# ── SCOREBOARD_TARGET_TRUTH_V1 (v4) — identity cohorts ───────────────────────
# Explicit identity outranks time inference; approximate historical joins are
# disclosed as separate cohorts, never silently pooled as trusted alignment.
JOIN_COHORTS = (
    "identity",
    "exact_timestamp",
    "nearest_earlier",
    "nearest_later",
    "unknown_join",
)

# RC-32 (governance/root_cause_log.md): cohorts whose rows may enter the SCORED
# confusion matrix. `nearest_later` outcomes were attached from a snapshot whose
# anchor bar closes AFTER the decision (measured 2026-07-23: 28,622 rows, 43.9%
# of the nearest_within_tol cohort) — future-anchored truth. `unknown_join` has
# no provable alignment. Both stay DISCLOSED in identity_cohorts but are
# excluded from accuracy/MCC/confusion; exclusion is counted per cell.
# Explicit membership, never complement (drift-audit classification rule).
_V4_SCORED_JOIN_COHORTS = ("identity", "exact_timestamp", "nearest_earlier")


def _join_identity_cohort(row: sqlite3.Row) -> str:
    """Cohort of the row's decision→snapshot outcome join (Phase 12 taxonomy)."""
    method = str(row["outcome_join_method"] or "")
    if method == "identity":
        return "identity"
    if method == "exact":
        return "exact_timestamp"
    if method == "nearest_within_tol":
        m_ts = row["matched_snapshot_ts_utc"]
        if m_ts is not None:
            # REGISTER_SCOPE_EXCLUDED: prefix=calibration token=delta id=ds-join-delta-assign class=timestamp_difference impact=NO_REGISTER_IMPACT trace="epoch-seconds difference between internal decision-log timestamps (matched_snapshot_ts_utc minus decision_ts_utc); units are seconds; feeds only the nearest_earlier/nearest_later report cohort label; not the options greek; no Schwab primitive read; no V4 register field emitted; no persistence or trade-determinative effect; leaf disposition NO_SCHWAB_EQUIVALENT"
            delta = float(m_ts) - float(row["decision_ts_utc"])
            # REGISTER_SCOPE_EXCLUDED: prefix=calibration token=delta id=ds-join-delta-sign class=timestamp_difference impact=NO_REGISTER_IMPACT trace="sign test on the epoch-seconds timestamp difference above, selecting the nearest_earlier or nearest_later join cohort label for the scoreboard report; not the options greek; no Schwab primitive read; no V4 register field emitted; no persistence or trade-determinative effect; leaf disposition NO_SCHWAB_EQUIVALENT"
            return "nearest_earlier" if delta < 0 else "nearest_later"
        return "unknown_join"
    return "unknown_join"


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
        t = out.setdefault(ticker_storage_key(row["ticker"]), _new_t())  # RC-345/F25: canonical scoreboard key
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


# ── SCOREBOARD_TARGET_TRUTH_V1 (v4) — institutional descriptive metrics ──────
# Schwab CSV authority checked: yes
# CSV row(s): NO_SCHWAB_EQUIVALENT — descriptive statistics over rows the
#   scoreboard already logs; no market field is read, derived, renamed, or
#   emitted here beyond counts/rates of existing logged decisions/outcomes.
# Derived-field disposition: none required (no derived market field touched);
#   the v2/v3 hit math and live skill-weight paths are byte-identical.
# All consumers checked: yes — additive JSON keys only; legacy keys unchanged.
# SCHWAB_CSV_CHECKED
_CLASSES = ("up", "down", "flat")
# Collapse/baseline warnings require a governed minimum sample so a two-row cell
# cannot fire NEAR_CONSTANT; the directional floor mirrors QC_MIN_SCORED_CELL_N.
WARN_MIN_N = 10
NEAR_CONSTANT_SHARE = 0.90
DIRECTIONAL_MIN_N = 30
# Operator display policy (documented, descriptive-only): trade-call coverage
# below this share is flagged for prominence so a selective-call accuracy can
# never present as broad performance. Statistical sample gating is separately
# governed by DIRECTIONAL_MIN_N/QC_MIN_SCORED_CELL_N (binomial floor); this
# constant is a DISPLAY prominence rule, not a money-path threshold.
LOW_COVERAGE_DISPLAY_POLICY = 0.05
SCOREBOARD_WARNINGS = (
    "LOSES_TO_ALWAYS_FLAT",
    "LOSES_TO_MAJORITY",
    "ALWAYS_FLAT_CLASSIFIER",
    "NEAR_CONSTANT_CLASSIFIER",
    "DIRECTIONAL_SAMPLE_TOO_SMALL",
    "UNDER_SAMPLED",
    "EFFECTIVE_SAMPLE_NOT_PROVEN",
    "PRIMARY_HORIZON_IDENTITY_NOT_PROVEN",
    "BUNDLE_IDENTITY_NOT_PROVEN",
    "TIMESTAMP_IDENTITY_NOT_PROVEN",
    "PLACEHOLDER_THRESHOLD_IN_USE",
    "INVALID_THRESHOLD_FALLBACK_RISK",
    "OUTCOME_LINEAGE_NOT_PROVEN",
    "CALIBRATION_NOT_PROVEN",
    "TRAIN_LIVE_PARITY_NOT_PROVEN",
    "LEAKAGE_ABSENCE_NOT_PROVEN",
)
_HZ_MINUTES = {"1c": 1, "5c": 5, "15c": 15, "60c": 60}

# ── Canonical display contracts (DEFECT-1 root cause fix) ────────────────────
# Single governed semantic-definition source for EVERY human-facing renderer of
# scoreboard metrics (HTML + console). Renderers must consume these constants —
# never hard-code their own explanatory text — so a future renderer cannot
# silently present the legacy triclass ALL metric as the governed trade-call
# metric. Embedded in metric_definitions for machine readability.
LEGACY_ALL_DISPLAY_CONTRACT = {
    "display_name": "Legacy ALL triclass accuracy (LEGACY_INVALID_FOR_TRADE_EDGE)",
    "semantic_version": "v2-legacy",
    "classification": "legacy",
    "prediction_class_treatment": "triclass (up/down/flat over LONG/SHORT/WAIT)",
    "wait_treatment": "WAIT scored as a flat-price class under this LEGACY metric",
    "intended_use": "historical reproduction and comparison only",
    "comparison_restriction": "NOT comparable to governed v4 trade-call accuracy; not valid for evaluating trade edge",
}
TRADE_CALL_DISPLAY_CONTRACT = {
    "display_name": "Governed trade-call accuracy (schema v4)",
    "semantic_version": "v4",
    "classification": "governed",
    "prediction_class_treatment": "LONG/SHORT directional trade calls only",
    "wait_treatment": "WAIT excluded as abstention (no trade call) — never scored as a flat prediction",
    "intended_use": "descriptive trade-call quality with mandatory coverage and cohort context",
    "comparison_restriction": "high conditional accuracy with low coverage is NOT sufficient evidence of predictive edge",
    "coverage_requirement": "trade-call coverage and eligible call counts must be displayed adjacent to accuracy",
}


def _new_v4_cell() -> dict[str, Any]:
    return {
        "confusion": {p: {t: 0 for t in _CLASSES} for p in _CLASSES},
        "cohorts": {c: 0 for c in JOIN_COHORTS},
        "bundle_identity_unproven": 0,
        "windows": set(),
        "n_pred": 0,
        "n_excluded_lookahead_join": 0,
    }


def _v4_accumulate(cell: dict[str, Any], r: dict[str, Any]) -> None:
    cell["n_pred"] += 1
    hz_min = _HZ_MINUTES.get(r["horizon"])
    if hz_min:
        cell["windows"].add(int(r["decision_ts_utc"] // (hz_min * 60.0)))
    if r["truth"] in _CLASSES:
        cohort = r.get("join_cohort") or "unknown_join"
        cell["cohorts"][cohort] += 1
        if cohort not in _V4_SCORED_JOIN_COHORTS:
            # RC-32: future-anchored / unprovable joins are disclosed, never scored.
            cell["n_excluded_lookahead_join"] += 1
            return
        cell["confusion"][r["pred"]][r["truth"]] += 1
        if not r.get("bundle_identity_proven"):
            cell["bundle_identity_unproven"] += 1


def _wilson_ci(hits: int, n: int) -> Optional[tuple[float, float]]:
    """95% Wilson score interval — sample-size honesty for small trade-call counts."""
    import math

    if n <= 0:
        return None
    z = 1.959963984540054
    p = hits / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, center - half), min(1.0, center + half))


def _finalize_v4_cell(cell: dict[str, Any]) -> dict[str, Any]:
    cm = cell["confusion"]
    n_scored = sum(cm[p][t] for p in _CLASSES for t in _CLASSES)
    pred_dist = {p: sum(cm[p][t] for t in _CLASSES) for p in _CLASSES}
    truth_dist = {t: sum(cm[p][t] for p in _CLASSES) for t in _CLASSES}
    hits = sum(cm[c][c] for c in _CLASSES)
    # Per-class recall/precision -> balanced accuracy / macro F1 (absent classes excluded).
    recalls, f1s = [], []
    per_class = {}
    for c in _CLASSES:
        tp = cm[c][c]
        prec = (tp / pred_dist[c]) if pred_dist[c] else None
        rec = (tp / truth_dist[c]) if truth_dist[c] else None
        f1 = (
            (2 * prec * rec / (prec + rec))
            if prec is not None and rec is not None and (prec + rec) > 0
            else (0.0 if (prec is not None and rec is not None) else None)
        )
        per_class[c] = {"precision": prec, "recall": rec, "f1": f1}
        if rec is not None:
            recalls.append(rec)
        if f1 is not None:
            f1s.append(f1)
    # Multiclass MCC (Gorodkin) — None when degenerate.
    mcc = None
    if n_scored:
        import math

        s = n_scored
        corr = hits * s - sum(pred_dist[c] * truth_dist[c] for c in _CLASSES)
        den_p = s * s - sum(pred_dist[c] ** 2 for c in _CLASSES)
        den_t = s * s - sum(truth_dist[c] ** 2 for c in _CLASSES)
        if den_p > 0 and den_t > 0:
            mcc = corr / math.sqrt(den_p * den_t)
    dir_called_n = sum(pred_dist[p] for p in ("up", "down"))
    dir_called_hits = cm["up"]["up"] + cm["down"]["down"]
    both_n = sum(cm[p][t] for p in ("up", "down") for t in ("up", "down"))
    both_hits = cm["up"]["up"] + cm["down"]["down"]
    accuracy = (hits / n_scored) if n_scored else None
    always_flat = (truth_dist["flat"] / n_scored) if n_scored else None
    majority = (max(truth_dist.values()) / n_scored) if n_scored else None
    return {
        "n_pred": cell["n_pred"],
        "n_scored": n_scored,
        "accuracy": accuracy,
        "balanced_accuracy": (sum(recalls) / len(recalls)) if recalls else None,
        "macro_f1": (sum(f1s) / len(f1s)) if f1s else None,
        "mcc": mcc,
        "confusion_matrix": cm,
        "per_class": per_class,
        "pred_distribution": pred_dist,
        "truth_distribution": truth_dist,
        "baselines": {"always_flat": always_flat, "majority_class": majority},
        "directional_called": {
            "n": dir_called_n,
            "hits": dir_called_hits,
            "accuracy": (dir_called_hits / dir_called_n) if dir_called_n else None,
            "definition": "prediction is up/down; truth may be flat",
        },
        "both_nonflat_directional": {
            "n": both_n,
            "hits": both_hits,
            "accuracy": (both_hits / both_n) if both_n else None,
            "definition": "prediction AND truth are both up/down",
        },
        "flat_pred_rate": (pred_dist["flat"] / n_scored) if n_scored else None,
        "flat_truth_rate": always_flat,
        "identity_cohorts": dict(cell["cohorts"]),
        "n_excluded_lookahead_join": cell["n_excluded_lookahead_join"],
        "n_bundle_identity_unproven": cell["bundle_identity_unproven"],
        "n_independent_windows": len(cell["windows"]),
    }


def _v4_cell_warnings(fin: dict[str, Any], threshold_flags: list[str]) -> list[str]:
    w: list[str] = []
    n = fin["n_scored"]
    acc = fin["accuracy"]
    if n >= WARN_MIN_N and acc is not None:
        if fin["baselines"]["always_flat"] is not None and acc < fin["baselines"]["always_flat"]:
            w.append("LOSES_TO_ALWAYS_FLAT")
        if fin["baselines"]["majority_class"] is not None and acc < fin["baselines"]["majority_class"]:
            w.append("LOSES_TO_MAJORITY")
    if fin["n_pred"] >= WARN_MIN_N:
        pd = fin["pred_distribution"]
        total_pred_scored = sum(pd.values())
        if total_pred_scored:
            top_share = max(pd.values()) / total_pred_scored
            if pd["flat"] == total_pred_scored:
                w.append("ALWAYS_FLAT_CLASSIFIER")
            elif top_share >= NEAR_CONSTANT_SHARE:
                w.append("NEAR_CONSTANT_CLASSIFIER")
    if fin["directional_called"]["n"] < DIRECTIONAL_MIN_N:
        w.append("DIRECTIONAL_SAMPLE_TOO_SMALL")
    if n and n < QC_MIN_SCORED_CELL_N:
        w.append("UNDER_SAMPLED")
    if n > fin["n_independent_windows"]:
        w.append("EFFECTIVE_SAMPLE_NOT_PROVEN")
    coh = fin["identity_cohorts"]
    if n and (coh["nearest_earlier"] + coh["nearest_later"] + coh["unknown_join"]) > 0:
        w.append("TIMESTAMP_IDENTITY_NOT_PROVEN")
    if fin["n_bundle_identity_unproven"] > 0:
        w.append("BUNDLE_IDENTITY_NOT_PROVEN")
    w.extend(threshold_flags)
    return w


def _threshold_source_identity() -> dict[str, Any]:
    """Threshold provenance embedded in every v4 report: file, hash, placeholder
    status per governed horizon, fallback-risk detection. Never hand-entered."""
    import hashlib

    from movement_target_threshold import (
        BY_HORIZON_PATH,
        load_movement_thresholds_by_horizon_v1,
    )

    cfg = load_movement_thresholds_by_horizon_v1()
    try:
        sha = hashlib.sha256(Path(BY_HORIZON_PATH).read_bytes()).hexdigest()
    except OSError:
        sha = None
    horizons = cfg.get("horizons") or {}
    notes = str(cfg.get("notes") or "")
    per_hz: dict[str, Any] = {}
    flags: list[str] = []
    placeholder = "placeholder" in notes.lower()
    invalid_horizons: list[str] = []
    for hz in HORIZON_SLUGS:
        blk = horizons.get(hz) or {}
        raw = blk.get("threshold_move_pts")
        ratified = blk.get("selected_percentile") is not None
        try:
            invalid = raw is None or float(raw) <= 0.0
        except (TypeError, ValueError):
            invalid = True
        per_hz[hz] = {
            "threshold_move_pts": raw,
            "selected_percentile": blk.get("selected_percentile"),
            "ratified": ratified,
            "invalid": invalid,
        }
        if invalid:
            invalid_horizons.append(hz)
        if not ratified:
            placeholder = True
    if placeholder:
        flags.append("PLACEHOLDER_THRESHOLD_IN_USE")
    if invalid_horizons:
        flags.append("INVALID_THRESHOLD_FALLBACK_RISK")
    return {
        "source_path": str(BY_HORIZON_PATH),
        "source_sha256": sha,
        "source_notes": notes,
        "per_horizon": per_hz,
        # Horizons whose governed threshold is missing/non-positive: the truth
        # writer would resolve a row-wise ungoverned fallback there, so their
        # labels are NOT trusted-scoreable in v4 (excluded, disclosed, warned).
        "invalid_horizons": invalid_horizons,
        "units": "price points (|forward_close - anchor_close|)",
        "warning_flags": flags,
        "attribution": (
            "current-configuration resolution; historical per-row applied VALUES"
            " are persisted (snapshots.threshold_move_*) but source-file identity"
            " for historical rows is INFERRED, not proven"
        ),
    }


def _all_card_trade_metrics(all_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """ALL card as a TRADE-DECISION surface: LONG/SHORT are directional trade
    calls scored against the decision-time primary-horizon outcome; WAIT is
    abstention and is NEVER scored as a flat-price prediction."""
    n_long = sum(1 for r in all_rows if r["pred"] == "up")
    n_short = sum(1 for r in all_rows if r["pred"] == "down")
    n_wait = sum(1 for r in all_rows if r["pred"] == "flat")
    n_total = len(all_rows)

    def _side(side_pred: str) -> dict[str, Any]:
        scored = [r for r in all_rows if r["pred"] == side_pred and r["truth"] in _CLASSES]
        hits = sum(1 for r in scored if r["truth"] == side_pred)
        ci = _wilson_ci(hits, len(scored))
        return {
            "n_calls": n_long if side_pred == "up" else n_short,
            "n_scored": len(scored),
            "hits": hits,
            "accuracy": (hits / len(scored)) if scored else None,
            "precision": (hits / len(scored)) if scored else None,
            "wilson_95ci": list(ci) if ci else None,
        }

    long_m = _side("up")
    short_m = _side("down")
    comb_n = long_m["n_scored"] + short_m["n_scored"]
    comb_hits = long_m["hits"] + short_m["hits"]
    ci = _wilson_ci(comb_hits, comb_n)
    # Fail-closed presentation status (DEFECT-C): the insufficiency status leads
    # and accuracy is descriptive-only unless sample AND coverage support it.
    coverage = ((n_long + n_short) / n_total) if n_total else None
    if comb_n == 0:
        pres_status = "NO_SCORED_CALLS"
    elif comb_n == 1:
        pres_status = "SINGLE_CALL"
    elif comb_n < DIRECTIONAL_MIN_N:
        pres_status = "SAMPLE_BELOW_GOVERNED_MINIMUM"
    elif long_m["n_scored"] == 0 or short_m["n_scored"] == 0:
        pres_status = "ONE_SIDED_CALLS"
    elif coverage is not None and coverage < LOW_COVERAGE_DISPLAY_POLICY:
        pres_status = "LOW_COVERAGE"
    else:
        pres_status = "SUFFICIENT"
    decision_valid = pres_status == "SUFFICIENT"
    if pres_status == "NO_SCORED_CALLS":
        leading = "no scored trade calls — accuracy not applicable"
    elif decision_valid:
        leading = (
            f"sample status SUFFICIENT ({comb_n} scored calls,"
            f" coverage {coverage:.1%}) — descriptive metric; not predictive validation"
        )
    else:
        leading = (
            f"sample status {pres_status} ({comb_n} scored call(s) of {n_total} eligible,"
            f" coverage {coverage:.1%}) — accuracy is descriptive only and NOT decision-valid"
        )
    accuracy_presentation = {
        "status": pres_status,
        "decision_valid": decision_valid,
        "leading_text": leading,
        "policy_sources": {
            "sample_floor": f"DIRECTIONAL_MIN_N={DIRECTIONAL_MIN_N} (statistical rule, binomial normal-approx floor)",
            "coverage_prominence": f"LOW_COVERAGE_DISPLAY_POLICY={LOW_COVERAGE_DISPLAY_POLICY} (documented operator display policy, descriptive-only)",
        },
    }
    wait_scored = [r for r in all_rows if r["pred"] == "flat" and r["truth"] in _CLASSES]
    wait_dist = {c: sum(1 for r in wait_scored if r["truth"] == c) for c in _CLASSES}
    warnings: list[str] = []
    if comb_n < DIRECTIONAL_MIN_N:
        warnings.append("DIRECTIONAL_SAMPLE_TOO_SMALL")
    if comb_n and comb_n < QC_MIN_SCORED_CELL_N:
        warnings.append("UNDER_SAMPLED")
    return {
        "contract": (
            "LONG/SHORT are trade-entry directional calls scored against the logged"
            " decision-time primary-horizon outcome; WAIT is trade abstention and is"
            " excluded from trade-call accuracy (it is NOT a flat-price prediction)"
        ),
        "n_eligible_decisions": n_total,
        "n_long": n_long,
        "n_short": n_short,
        "n_wait": n_wait,
        "trade_call_coverage": ((n_long + n_short) / n_total) if n_total else None,
        "abstention_rate": (n_wait / n_total) if n_total else None,
        "long": long_m,
        "short": short_m,
        "combined_trade_calls": {
            "n_scored": comb_n,
            "hits": comb_hits,
            "accuracy": (comb_hits / comb_n) if comb_n else None,
            "wilson_95ci": list(ci) if ci else None,
        },
        "accuracy_presentation": accuracy_presentation,
        "outcome_distribution_during_wait": {
            "n_scored": len(wait_scored),
            "distribution": wait_dist,
            "note": "descriptive opportunity analysis only — WAIT rows carry no trade",
        },
        "n_primary_horizon_identity_not_proven": 0,  # filled by caller from tallies
        "warnings": warnings,
        "legacy_triclass_reference": {
            "location": "by_horizon['all'] / by_ticker[<t>]['all']",
            "label": "LEGACY_INVALID_FOR_TRADE_EDGE",
            "reason": (
                "legacy metric maps WAIT to a flat-price prediction and mixes"
                " abstention with price-state classification; retained only for"
                " historical reproducibility"
            ),
        },
    }


class DisplayContractViolationError(RuntimeError):
    """Raised fail-closed when display contracts and executable metric behavior
    disagree — no report may be emitted, written, or printed in that state."""


def _require_display_contracts_bound() -> None:
    errs = validate_display_contracts()
    if errs:
        raise DisplayContractViolationError(
            "scoreboard display contracts violated — report emission refused: "
            + "; ".join(errs)
        )


def validate_display_contracts() -> list[str]:
    """DEFECT-G: bidirectional binding between the hand-authored display
    contracts and EXECUTABLE metric behavior. Runs canonical micro-fixtures
    through the production formulas and cross-checks the contract text.
    Returns a list of mismatch errors (empty = contracts bound to behavior)."""
    errors: list[str] = []
    # Executable behavior probes.
    rows = [
        {"ticker": "Z", "decision_ts_utc": 1.0, "horizon": "all", "pred": "up",
         "truth": "up", "top_probability": 0.9, "join_cohort": "identity",
         "bundle_identity_proven": True},
        {"ticker": "Z", "decision_ts_utc": 2.0, "horizon": "all", "pred": "down",
         "truth": "up", "top_probability": 0.9, "join_cohort": "identity",
         "bundle_identity_proven": True},
        {"ticker": "Z", "decision_ts_utc": 3.0, "horizon": "all", "pred": "flat",
         "truth": "down", "top_probability": 0.5, "join_cohort": "identity",
         "bundle_identity_proven": True},
    ]
    m = _all_card_trade_metrics(rows)
    wait_excluded = m["combined_trade_calls"]["n_scored"] == 2 and m["n_wait"] == 1
    if not wait_excluded:
        errors.append("behavior: WAIT not excluded from trade-call scoring")
    if "excluded as abstention" not in TRADE_CALL_DISPLAY_CONTRACT["wait_treatment"]:
        errors.append("governed contract text does not state WAIT abstention exclusion")
    if wait_excluded and "scored as a flat-price class" not in LEGACY_ALL_DISPLAY_CONTRACT["wait_treatment"]:
        errors.append("legacy contract text does not state WAIT-as-scored-class")
    # Legacy mapping binds to the executable map.
    if _FINAL_BIAS_TO_LABEL != {"LONG": "up", "SHORT": "down", "WAIT": "flat"}:
        errors.append("legacy _FINAL_BIAS_TO_LABEL diverged from the documented triclass mapping")
    # Coverage denominator = eligible decisions; scored = LONG+SHORT eligible.
    if m["trade_call_coverage"] != (m["n_long"] + m["n_short"]) / m["n_eligible_decisions"]:
        errors.append("behavior: coverage denominator is not eligible decisions")
    if "coverage" not in TRADE_CALL_DISPLAY_CONTRACT.get("coverage_requirement", ""):
        errors.append("governed contract text lacks the coverage requirement")
    # Zero scored calls -> no accuracy, fail-closed presentation.
    z = _all_card_trade_metrics([dict(rows[2])])
    if z["combined_trade_calls"]["accuracy"] is not None:
        errors.append("behavior: zero-call accuracy is not None")
    if z["accuracy_presentation"]["status"] != "NO_SCORED_CALLS" or z["accuracy_presentation"]["decision_valid"]:
        errors.append("behavior: zero-call presentation is not fail-closed")
    # Low-sample presentation fail-closed.
    if m["accuracy_presentation"]["decision_valid"]:
        errors.append("behavior: 2-call sample presented as decision-valid")
    # Historical-only + trade-edge restriction present in legacy contract.
    if "historical" not in LEGACY_ALL_DISPLAY_CONTRACT["intended_use"]:
        errors.append("legacy contract lacks historical-only purpose")
    if "not valid for evaluating trade edge" not in LEGACY_ALL_DISPLAY_CONTRACT["comparison_restriction"]:
        errors.append("legacy contract lacks trade-edge restriction")
    return errors


def _v4_metric_definitions() -> dict[str, Any]:
    return {
        "accuracy": "3-class hits/n_scored (pred == truth over up/down/flat)",
        "balanced_accuracy": "mean per-class recall over classes present in truth",
        "macro_f1": "mean per-class F1 over classes with defined precision+recall",
        "mcc": "multiclass Matthews correlation (Gorodkin); None when degenerate",
        "always_flat_baseline": "accuracy of predicting flat for every scored row",
        "majority_class_baseline": "accuracy of predicting the day's majority truth class",
        "directional_called_accuracy": "prediction is up/down (truth may be flat)",
        "both_nonflat_directional_accuracy": "prediction AND truth are both up/down",
        "identity_cohorts": (
            "outcome-join provenance per scored row: identity (persisted decision_id"
            " link) > exact_timestamp > nearest_earlier/nearest_later (inferred,"
            " approximate) > unknown_join; inferred cohorts are disclosed, never"
            " silently trusted"
        ),
        "n_independent_windows": (
            "distinct non-overlapping horizon windows covered by scored rows;"
            " n_scored above this count means overlapping labels — rows are NOT"
            " independent trials (EFFECTIVE_SAMPLE_NOT_PROVEN)"
        ),
        "legacy_invalid_for_trade_edge": [
            "by_horizon['all'] (triclass ALL accuracy: WAIT scored as flat prediction)",
            "by_ticker[<t>]['all'] (same defect at ticker level)",
            "directional_accuracy in v2 cells (prediction-only condition; kept as directional_called)",
        ],
        "display_contracts": {
            "legacy_all": LEGACY_ALL_DISPLAY_CONTRACT,
            "trade_call": TRADE_CALL_DISPLAY_CONTRACT,
        },
        "standing_not_proven_disclosures": [
            "OUTCOME_LINEAGE_NOT_PROVEN: snapshot outcome columns carry no writer/mutation lineage; bar-mutation refresh recomputes labels in place",
            # REGISTER_SCOPE_EXCLUDED: prefix=calibration token=confidence id=ds-calnp-confidence-text class=static_disclosure_text impact=NO_REGISTER_IMPACT trace="static fail-closed operator disclosure string (CALIBRATION_NOT_PROVEN) that denies any calibration-validity claim; no numeric confidence computation at this site; no Schwab primitive read; no V4 register field emitted; no model or policy behavior change; leaf disposition NO_SCHWAB_EQUIVALENT"
            "CALIBRATION_NOT_PROVEN: descriptive confidence only; no calibration-validity claim",
            "TRAIN_LIVE_PARITY_NOT_PROVEN: training/live feature identity not proven by this report",
            "LEAKAGE_ABSENCE_NOT_PROVEN: no leakage-control claim is made by this report",
        ],
        "warnings_supported": list(SCOREBOARD_WARNINGS),
        "warning_thresholds": {
            "WARN_MIN_N": WARN_MIN_N,
            "NEAR_CONSTANT_SHARE": NEAR_CONSTANT_SHARE,
            "DIRECTIONAL_MIN_N": DIRECTIONAL_MIN_N,
            "QC_MIN_SCORED_CELL_N": QC_MIN_SCORED_CELL_N,
        },
    }


def _v4_source_identity(db_path: Path | str) -> dict[str, Any]:
    import subprocess

    from horizon_outcomes import HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1

    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
            timeout=10,
        ).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        sha = None
    return {
        "repository_sha": sha,
        "db_path": str(Path(db_path).resolve()),
        "horizon_outcome_schema_version": HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
        "threshold_source": _threshold_source_identity(),
        "generator": f"calibration.daily_scoreboard schema_version={SCHEMA_VERSION}",
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
        roster = [t for t in roster if ticker_storage_key(t) in {ticker_storage_key(x) for x in tickers}]  # RC-345/F25: canonical roster membership

    cells: dict[tuple[str, str], dict[str, Any]] = {}
    rollup: dict[str, dict[str, Any]] = {
        hz: _new_cell() for hz in (*HORIZON_SLUGS, ALL_CARD_SLUG)
    }
    # v4 accumulators ride BESIDE the legacy cells — legacy hit math is untouched.
    # Invalid-threshold horizons are mechanically excluded from EVERY trusted v4
    # metric (mandatory pre-proof correction): their rows land in an
    # invalid-target cohort instead of n_scored/accuracy/baselines/confusion.
    source_identity = _v4_source_identity(db_path)
    threshold_flags = list(source_identity["threshold_source"]["warning_flags"])
    invalid_horizons = set(source_identity["threshold_source"]["invalid_horizons"])
    invalid_target_cohort: dict[str, int] = {hz: 0 for hz in sorted(invalid_horizons)}
    v4_cells: dict[tuple[str, str], dict[str, Any]] = {}
    v4_rollup: dict[str, dict[str, Any]] = {hz: _new_v4_cell() for hz in HORIZON_SLUGS}
    all_rows_v4: list[dict[str, Any]] = []
    try:
        for r in _per_horizon_prediction_rows(conn, et_date, tickers):
            if r["horizon"] == ALL_CARD_SLUG:
                all_rows_v4.append(r)
            elif r["horizon"] in invalid_horizons:
                invalid_target_cohort[r["horizon"]] += 1
            else:
                _v4_accumulate(
                    v4_cells.setdefault((r["ticker"], r["horizon"]), _new_v4_cell()), r
                )
                _v4_accumulate(v4_rollup[r["horizon"]], r)
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

    def _v4_final(cell: dict[str, Any]) -> dict[str, Any]:
        fin = _finalize_v4_cell(cell)
        fin["warnings"] = _v4_cell_warnings(fin, threshold_flags)
        return fin

    by_horizon_extended = {hz: _v4_final(v4_rollup[hz]) for hz in HORIZON_SLUGS}
    for hz in invalid_horizons:
        by_horizon_extended[hz]["invalid_target_cohort"] = {
            "n_rows_excluded_from_trusted_scoring": invalid_target_cohort[hz],
            "reason": (
                "governed threshold for this horizon is missing/non-positive —"
                " labels are untrusted; rows are excluded from every trusted"
                " metric denominator and reported here instead"
            ),
        }
    by_ticker_extended: dict[str, dict[str, Any]] = {}
    for (ticker, hz), cell in sorted(v4_cells.items()):
        by_ticker_extended.setdefault(ticker, {})[hz] = _v4_final(cell)

    all_card = _all_card_trade_metrics(all_rows_v4)
    # ALL rows rejected fail-closed for a missing/invalid persisted primary
    # horizon are counted by the production tallies (they never reach scoring).
    all_card["n_primary_horizon_identity_not_proven"] = sum(
        t["hz"][ALL_CARD_SLUG]["n_fusion_unavailable"] for t in tallies.values()
    )
    if all_card["n_primary_horizon_identity_not_proven"]:
        all_card["warnings"].append("PRIMARY_HORIZON_IDENTITY_NOT_PROVEN")
    # DEFECT-B: target/threshold validity is part of the governed semantic UNIT —
    # a copied all_card must carry its own validity context, not rely on a
    # distant section. Placeholder/invalid targets ⇒ never trusted trade-edge
    # evidence, stated inside the unit.
    ts_src = source_identity["threshold_source"]
    cfg_governed = not ts_src["warning_flags"] and not ts_src["invalid_horizons"]
    # Phase-8 language safety: CONFIGURATION status and TARGET VALIDITY are
    # different axes — a ratified configuration NEVER implies economic target
    # validity, label-contract correctness, trade edge, or predictive validity.
    all_card["target_threshold_validity"] = {
        "threshold_source_sha256": ts_src["source_sha256"],
        "per_horizon": {
            hz: {"ratified": blk["ratified"], "invalid": blk["invalid"]}
            for hz, blk in ts_src["per_horizon"].items()
        },
        "warning_flags": list(ts_src["warning_flags"]),
        "configuration_status": (
            "GOVERNED_RATIFIED" if cfg_governed
            else ("INVALID_PRESENT" if ts_src["invalid_horizons"] else "PLACEHOLDER")
        ),
        "metric_scoring_eligibility": not ts_src["invalid_horizons"],
        "target_economic_validity": (
            "NOT_PROVEN (parent status — configuration ratification alone never"
            " proves economic target validity)"
        ),
        "label_contract_validity": "NOT_PROVEN (parent status)",
        "trade_edge_validity": (
            "NOT_PROVEN (never derivable from configuration status)"
        ),
        "statement": (
            (
                "governed threshold configuration present (ratified) — this is a"
                " CONFIGURATION status only and is NOT a claim of target economic"
                " validity, label-contract correctness, or trade edge (parent"
                " statuses remain NOT_PROVEN)"
            )
            if cfg_governed
            else (
                "target/threshold configuration NOT governed (placeholder/invalid"
                " thresholds) — this metric is NOT trusted trade-edge evidence"
            )
        ),
    }
    all_card["warnings"].extend(
        f for f in ts_src["warning_flags"] if f not in all_card["warnings"]
    )

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
        # v4 (SCOREBOARD_TARGET_TRUTH_V1): institutional descriptive metrics.
        "by_horizon_extended": by_horizon_extended,
        "by_ticker_extended": by_ticker_extended,
        "all_card": all_card,
        "metric_definitions": _v4_metric_definitions(),
        "source_identity": source_identity,
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
    """Self-contained HTML report (opened by the scheduled task at end of day).

    Fail-closed: display-contract validation runs before ANY markup is built, so
    a direct render_html call can never emit semantics that contradict the
    executable metric behavior."""
    _require_display_contracts_bound()
    date = scoreboard["et_date"]
    head_cells = "".join(
        f'<th scope="col">{h}</th>'
        for h in ("n scored", "accuracy", "directional n", "directional acc")
    )

    def _row(label: str, cell: dict[str, Any]) -> str:
        # DEFECT-1: the 'all' row is the LEGACY triclass metric — it must never
        # render as an unqualified horizon row (contract text, not styling).
        shown = f"all — {LEGACY_ALL_DISPLAY_CONTRACT['display_name']}" if label == "all" else label
        return (
            f"<tr><td>{shown}</td><td>{cell['n_scored']}</td>"
            f"<td>{_fmt_pct(cell['accuracy'])}</td>"
            f"<td>{cell['n_directional']}</td>"
            f"<td>{_fmt_pct(cell['directional_accuracy'])}</td></tr>"
        )

    lac = LEGACY_ALL_DISPLAY_CONTRACT
    tcc = TRADE_CALL_DISPLAY_CONTRACT
    sections = [
        "<h2>All tickers — by horizon (row-weighted pooled; legacy metric semantics)</h2>",
        f"<p><b>{lac['display_name']}</b>: {lac['prediction_class_treatment']};"
        f" {lac['wait_treatment']}. Purpose: {lac['intended_use']}."
        f" {lac['comparison_restriction']}.</p>",
        "<table><caption>Pooled per-horizon accuracy (row-weighted); the 'all' row"
        f" is the {lac['display_name']}.</caption>"
        f"<tr><th scope=\"col\">horizon</th>{head_cells}</tr>",
    ]
    sections += [_row(hz, c) for hz, c in scoreboard["by_horizon"].items()]
    sections.append("</table>")

    # Governed v4 trade-call section — coverage and call counts render in the
    # SAME section as accuracy; zero calls never display a misleading number.
    ac = scoreboard.get("all_card") or {}
    if ac:
        comb = ac.get("combined_trade_calls") or {}
        n_calls = int(comb.get("n_scored") or 0)
        pres = ac.get("accuracy_presentation") or {}
        validity = ac.get("target_threshold_validity") or {}
        # DEFECT-C: the sample/coverage status LEADS; a bare percentage never
        # opens the governed unit. DEFECT-B: target/threshold validity renders
        # INSIDE the same unit, prominently, before any accuracy number.
        if n_calls > 0 and pres.get("decision_valid"):
            acc_txt = (
                f"accuracy {_fmt_pct(comb.get('accuracy'))} (95% CI"
                f" {_fmt_pct((comb.get('wilson_95ci') or [None, None])[0])}–"
                f"{_fmt_pct((comb.get('wilson_95ci') or [None, None])[1])})"
            )
        elif n_calls > 0:
            acc_txt = (
                f"descriptive-only accuracy {_fmt_pct(comb.get('accuracy'))} (95% CI"
                f" {_fmt_pct((comb.get('wilson_95ci') or [None, None])[0])}–"
                f"{_fmt_pct((comb.get('wilson_95ci') or [None, None])[1])}) — NOT decision-valid"
            )
        else:
            acc_txt = "no scored trade calls — accuracy not applicable"
        warn_txt = ", ".join(ac.get("warnings") or []) or "none"
        sections.append(f"<h2>{tcc['display_name']}</h2>")
        sections.append(
            f"<p><b>Target/threshold validity:</b> {validity.get('statement', 'validity unknown')}.</p>"
            f"<p><b>{pres.get('leading_text', 'sample status unknown')}.</b></p>"
            f"<p>{tcc['wait_treatment']}. {tcc['comparison_restriction']}.</p>"
            f"<p>Eligible decisions: {ac.get('n_eligible_decisions')};"
            f" LONG {ac.get('n_long')} / SHORT {ac.get('n_short')} / WAIT {ac.get('n_wait')};"
            f" trade-call coverage {_fmt_pct(ac.get('trade_call_coverage'))};"
            f" abstention rate {_fmt_pct(ac.get('abstention_rate'))};"
            f" scored trade calls: {n_calls}; {acc_txt}.</p>"
            f"<p>Warnings: {warn_txt}.</p>"
        )
    # Invalid-target cohorts and per-horizon v4 warnings stay visible.
    ext = scoreboard.get("by_horizon_extended") or {}
    inv_bits = []
    warn_bits = []
    for hz, cell in ext.items():
        cohort = cell.get("invalid_target_cohort")
        if cohort:
            inv_bits.append(
                f"{hz}: {cohort['n_rows_excluded_from_trusted_scoring']} row(s) excluded"
                " (invalid governed threshold — labels untrusted)"
            )
        if cell.get("warnings"):
            warn_bits.append(f"{hz}: {', '.join(cell['warnings'])}")
    if inv_bits:
        sections.append("<p><b>Invalid-target cohorts:</b> " + "; ".join(inv_bits) + ".</p>")
    if warn_bits:
        sections.append("<p><b>Per-horizon v4 warnings:</b> " + "; ".join(warn_bits) + ".</p>")

    # v3 denominator-first sections (coverage + equal-weight + eligible grid).
    ew = scoreboard.get("by_horizon_equal_weight") or {}
    if ew:
        sections.append(
            "<h2>All tickers — by horizon (equal weight per ticker; legacy metric semantics)</h2>"
        )
        sections.append(
            "<table><caption>Equal-weight per-horizon accuracy; the 'all' row is the"
            f" {LEGACY_ALL_DISPLAY_CONTRACT['display_name']}.</caption>"
            "<tr><th scope=\"col\">horizon</th><th scope=\"col\">tickers scored</th>"
            "<th scope=\"col\">mean accuracy</th></tr>"
        )
        for hz, c in ew.items():
            shown_hz = (
                f"all — {LEGACY_ALL_DISPLAY_CONTRACT['display_name']}" if hz == "all" else hz
            )
            sections.append(
                f"<tr><td>{shown_hz}</td><td>{c['n_tickers']}</td>"
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

        def _grid_th(hz: str) -> str:
            # DEFECT-A: the 'all' column heading is structurally qualified so a
            # copied column/row can never read as governed accuracy.
            if hz == "all":
                return f"<th scope=\"col\">all — {LEGACY_ALL_DISPLAY_CONTRACT['display_name']}</th>"
            return f"<th scope=\"col\">{hz}</th>"

        sections.append("<h2>Eligible grid — every governed ticker × horizon (legacy metric semantics)</h2>")
        sections.append(
            "<table><caption>Eligible grid: per-cell LEGACY triclass accuracy —"
            f" {lac['wait_treatment']}; {lac['comparison_restriction']}.</caption>"
            "<tr><th scope=\"col\">ticker</th>" + "".join(_grid_th(hz) for hz in hz_order) + "</tr>"
        )
        for tkr, cells_by_hz in grid.items():
            tds = []
            for hz in hz_order:
                cell = cells_by_hz[hz]
                if cell["score_status"] == "SCORED":
                    # Cell-level binding for the legacy ALL metric: survives
                    # copying a single row without its heading.
                    suffix = " — legacy triclass, not trade-call accuracy" if hz == "all" else ""
                    tds.append(
                        f"<td>{_fmt_pct(cell.get('accuracy'))} (n={cell['n_scored']}){suffix}</td>"
                    )
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
            "<table><caption>Quality-circle ranking: worst tickers by mean accuracy"
            " over trusted true-horizon cells (legacy ALL metric excluded from this"
            " ranking).</caption>"
            "<tr><th scope=\"col\">ticker</th><th scope=\"col\">mean accuracy (trusted)</th>"
            "<th scope=\"col\">trusted horizons</th><th scope=\"col\">n scored</th></tr>"
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
        sections.append(
            f"<table><caption>{ticker} per-horizon accuracy; the 'all' row is the"
            f" {LEGACY_ALL_DISPLAY_CONTRACT['display_name']}.</caption>"
            f"<tr><th scope=\"col\">horizon</th>{head_cells}</tr>"
        )
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
<p>Horizon rows (1c/5c/15c/60c): accuracy = dominant fusion direction vs realized outcome
label (same labels training uses); "directional" counts rows where the model called up/down
(truth may still be flat). The <b>all</b> row is the
{LEGACY_ALL_DISPLAY_CONTRACT["display_name"]}: {LEGACY_ALL_DISPLAY_CONTRACT["wait_treatment"]};
retained for {LEGACY_ALL_DISPLAY_CONTRACT["intended_use"]} —
{LEGACY_ALL_DISPLAY_CONTRACT["comparison_restriction"]}. The governed trade-call view
(WAIT excluded as abstention) is the separate "{TRADE_CALL_DISPLAY_CONTRACT["display_name"]}" section below.</p>
{body}
</body></html>
"""


def write_reports(scoreboard: dict[str, Any], out_dir: Path | str = DEFAULT_REPORT_DIR) -> dict[str, str]:
    # Fail-closed BEFORE any filesystem effect: a contract violation writes
    # nothing (no partial report, no stale 'latest' overwrite).
    _require_display_contracts_bound()
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
    tickers = [ticker_storage_key(t) for t in args.tickers if t.strip()] or None  # RC-345/F25: canonical CLI ticker list
    # Fail-closed for the whole production entrypoint: contract violation aborts
    # before computation, emission, or console output (non-zero exit for the
    # scheduled task; error is explicit in its log).
    _require_display_contracts_bound()
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
    print(
        json.dumps(
            {
                "et_date": et_date,
                # Console/log renderer (operator-facing): the legacy summary must
                # carry the same canonical semantic contracts as the HTML report.
                "by_horizon_legacy_semantics": LEGACY_ALL_DISPLAY_CONTRACT,
                "by_horizon": scoreboard["by_horizon"],
                "governed_trade_call": {
                    "contract": TRADE_CALL_DISPLAY_CONTRACT,
                    "summary": {
                        k: scoreboard["all_card"].get(k)
                        for k in (
                            "n_eligible_decisions", "n_long", "n_short", "n_wait",
                            "trade_call_coverage", "abstention_rate",
                            "combined_trade_calls", "warnings",
                        )
                    },
                },
                "reports": paths,
            },
            indent=2,
        )
    )
    if args.open:
        os.startfile(paths["html"])  # noqa: S606 — operator-facing Windows report open
    return 0


if __name__ == "__main__":
    sys.exit(main())
