#!/usr/bin/env python3
"""
Deterministic production-style accumulation: real compute_signals + writer + backfill + validators.

Builds an isolated SQLite DB, seeds price_bars_1m + snapshots, runs N successful decision events,
then proves pipeline stability (duplicates, join, anchor, resync).

  python -m calibration.run_production_accumulation_validation

Exit 0 only if all PASS gates succeed. Writes JSON report beside the DB.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["ED_CALIBRATION_LOG"] = "1"
# Isolated harness DB — must not trip EdDB non-canonical guard
os.environ["ED_CONSOLE_ALLOW_NONCANONICAL_DB"] = "1"

import db as db_mod  # noqa: E402
from calibration.anchor_audit import run_anchor_audit  # noqa: E402
from calibration.backfill_outcomes import backfill  # noqa: E402
from calibration.legacy_report import analyze as legacy_analyze  # noqa: E402
from calibration.schema import ensure_calibration_schema  # noqa: E402
from calibration.validate_outcome_join import analyze as analyze_outcome_join  # noqa: E402
from calibration.validate_logging_e2e import _inp  # noqa: E402
from db import EdDB, configure_sqlite_connection  # noqa: E402
from instrument_identity import ticker_storage_key  # noqa: E402
from signals import compute_signals  # noqa: E402

# Materially non-trivial trusted population (> MIN_SAMPLES_STATISTICAL floor).
# 4 tickers × 30 rows each → per-ticker slice power for edge validation.
N_ACCUM = 120
BASE_TS = 1_712_200_000.0
TS_STEP = 100.0
_TICKERS_ROT = (["SPY"] * 30 + ["QQQ"] * 30 + ["IWM"] * 30 + ["DIA"] * 30)

OUT_DB = ROOT / "data" / "calibration_accumulation_validation.db"
OUT_REPORT = ROOT / "data" / "calibration_accumulation_validation_report.json"


def _stub_models() -> None:
    import ml_predict
    from tests.test_calibration_logging_production_path import _fake_run_base_models_once

    ml_predict.run_base_models_once = _fake_run_base_models_once


def _outcome_row_for_index(i: int) -> tuple[str, str, str, str, float, float, float, float]:
    """Rotating 5c labels + pts so segmentation / EV discovery is not degenerate (single outcome)."""
    cycle = [
        ("up", "up", "flat", "down", 0.1, 0.22, 0.3, 0.4),
        ("down", "down", "flat", "up", 0.1, -0.18, 0.25, 0.35),
        ("flat", "flat", "down", "up", 0.05, 0.02, -0.1, 0.2),
        ("up", "up", "up", "flat", 0.12, 0.15, 0.28, 0.38),
        ("down", "down", "up", "flat", 0.08, -0.12, 0.2, 0.3),
        ("up", "up", "down", "up", 0.11, 0.28, 0.32, 0.42),
    ]
    return cycle[i % len(cycle)]


def _seed_bars_and_snapshots(conn: sqlite3.Connection, plan: list[tuple[str, float]]) -> None:
    """
    Seed one contiguous 1m series per ticker (no duplicate bar_start keys) plus snapshots.

    outcome_5c_pts blends 20-bar momentum at the decision anchor with the rotating cycle
    (harness-only; join validation unchanged).
    """
    from collections import defaultdict

    by_ticker: dict[str, list[float]] = defaultdict(list)
    for _tkr, ts in plan:
        by_ticker[_tkr].append(ts)

    anchor_close_index: dict[tuple[str, float], tuple[float, float]] = {}

    for tkr, ts_list in by_ticker.items():
        ts_min = min(ts_list)
        ts_max = max(ts_list)
        be_max = ts_max - 30.0
        be_min = ts_min - 30.0 - 60.0 * 149.0
        _th = int(hashlib.md5(tkr.encode("utf-8")).hexdigest()[:8], 16)
        phase = float(_th % 997) * 0.001
        t_be = be_min + 60.0
        k_g = 0
        bar_ends: list[float] = []
        closes: list[float] = []
        while t_be <= be_max + 1e-6:
            bs = t_be - 60.0
            close = 450.0 + 0.35 * math.sin(phase + k_g * 0.12) + (k_g % 9) * 0.02 + k_g * 0.0009
            open_ = close - 0.04 * math.sin(k_g * 0.15)
            high = max(open_, close) + 0.06
            low = min(open_, close) - 0.06
            vol = 1_200_000.0 + float(k_g) * 800.0
            conn.execute(
                """
                INSERT INTO price_bars_1m (
                    ticker, bar_start_ts_utc, bar_end_ts_utc, open, high, low, close, volume, source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'accum_validation')
                """,
                (tkr, bs, t_be, open_, high, low, close, vol),
            )
            bar_ends.append(t_be)
            closes.append(close)
            k_g += 1
            t_be += 60.0

        end_to_idx = {be: j for j, be in enumerate(bar_ends)}
        for ts in ts_list:
            be_a = ts - 30.0
            j = end_to_idx.get(be_a)
            if j is None:
                continue
            c0 = closes[j]
            c20 = closes[j - 20] if j >= 20 else closes[0]
            anchor_close_index[(tkr, ts)] = (c0, c20)

    for i, (tkr, ts) in enumerate(plan):
        o1, o5, o15, o60, p1, p5, p15, p60 = _outcome_row_for_index(i)
        pair = anchor_close_index.get((tkr, ts))
        if pair is None:
            c0, c20 = 450.0, 450.0
        else:
            c0, c20 = pair
        mom = (c0 - c20) / max(abs(c20), 1e-9)
        p5_pts = 0.5 * mom * 48.0 + 0.5 * p5
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                horizon_outcome_schema_version, outcome_filled,
                outcome_1c, outcome_5c, outcome_15c, outcome_60c,
                outcome_1c_pts, outcome_5c_pts, outcome_15c_pts, outcome_60c_pts
            )
            VALUES (?, '1m', ?, 'accum', 10, 30, 'rth', ?, 3, 1,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?)
            """,
            (tkr, ts, c0, o1, o5, o15, o60, p1, p5_pts, p15, p60),
        )


def _duplicate_key_groups(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT ticker, decision_ts_utc, COUNT(*) AS c FROM calibration_decision_log
        GROUP BY ticker, decision_ts_utc HAVING c > 1
        """
    ).fetchall()
    return [{"ticker": r["ticker"], "decision_ts_utc": r["decision_ts_utc"], "c": int(r["c"])} for r in rows]


def _unsafe_non_exact_joins(conn: sqlite3.Connection) -> int:
    r = conn.execute(
        """
        SELECT COUNT(*) FROM calibration_decision_log
        WHERE calibration_trust = 'trusted' AND outcome_5c IS NOT NULL
          AND IFNULL(outcome_join_method, '') NOT IN ('exact', '')
        """
    ).fetchone()
    return int(r[0]) if r else 0


def run() -> dict[str, Any]:
    warnings: list[str] = []
    import ml_predict

    _orig_run_base = ml_predict.run_base_models_once
    try:
        _stub_models()

        OUT_DB.parent.mkdir(parents=True, exist_ok=True)
        if OUT_DB.exists():
            OUT_DB.unlink()

        _ = EdDB(OUT_DB)
        db_mod.DB_PATH = OUT_DB

        conn = sqlite3.connect(str(OUT_DB))
        configure_sqlite_connection(conn)
        ensure_calibration_schema(conn)

        tickers_src = list(_TICKERS_ROT)
        plan: list[tuple[str, float]] = []
        for i in range(N_ACCUM):
            ts = BASE_TS + float(i) * TS_STEP
            tkr = ticker_storage_key(tickers_src[i])
            plan.append((tkr, ts))

        _seed_bars_and_snapshots(conn, plan)
        conn.commit()
        conn.close()

        edb = EdDB(OUT_DB)
        decision_events = 0
        for i in range(N_ACCUM):
            ts = BASE_TS + float(i) * TS_STEP
            name = tickers_src[i]
            inp = _inp(refresh_ts_utc=ts)
            inp2 = replace(inp, ticker=name)
            out = compute_signals(inp2, db=edb)
            from calibration.v2_live_logging import append_live_v2_calibration_decision
            from v2_decision import build_module_a_a1_decision

            canonical = out.canonical_forecast
            append_live_v2_calibration_decision(
                db_path=OUT_DB,
                calibration_payload=out.calibration_payload,
                v2_decision=build_module_a_a1_decision(
                    {
                        "ticker": name,
                        "fusion_available": True,
                        "fusion_dominant_direction": canonical.direction,
                        "fusion_dominant_prob": max(
                            float(canonical.probability_up),
                            float(canonical.probability_down),
                            float(canonical.probability_flat),
                        ),
                        "execution_mode": getattr(out.call, "execution_mode", None),
                    }
                ),
            )
            decision_events += 1

        bf1 = backfill(OUT_DB, tol_sec=0.0)
        join1 = analyze_outcome_join(OUT_DB)
        anchor1 = run_anchor_audit(OUT_DB, sample_limit=None, seed_sample=False)
        leg1 = legacy_analyze(OUT_DB)

        bf2 = backfill(OUT_DB, tol_sec=0.0)
        join2 = analyze_outcome_join(OUT_DB)

        conn = sqlite3.connect(str(OUT_DB))
        configure_sqlite_connection(conn)
        conn.row_factory = sqlite3.Row
        dups = _duplicate_key_groups(conn)
        n_trusted = int(
            conn.execute(
                "SELECT COUNT(*) FROM calibration_decision_log WHERE calibration_trust = 'trusted'"
            ).fetchone()[0]
        )
        n_legacy = int(
            conn.execute(
                "SELECT COUNT(*) FROM calibration_decision_log WHERE calibration_trust = 'legacy'"
            ).fetchone()[0]
        )
        n_total = int(conn.execute("SELECT COUNT(*) FROM calibration_decision_log").fetchone()[0])
        unsafe_join = _unsafe_non_exact_joins(conn)
        conn.close()

        ca = anchor1.get("calibration_trusted_anchor_audit") or {}
        trusted_total = int(ca.get("trusted_rows_total", -1))
        without_anchor = int(ca.get("trusted_rows_without_anchor", -1))

        pass_gates = {
            "trusted_population_non_trivial": n_trusted >= 30,
            "decision_events_match_trusted_rows": decision_events == n_trusted == N_ACCUM,
            "no_duplicate_keys": len(dups) == 0,
            "total_rows_eq_trusted_no_legacy": n_total == n_trusted and n_legacy == 0,
            "backfill_first_no_ambiguity": int(bf1.get("skipped_ambiguous_duplicate_snapshots", 0) or 0) == 0
            and int(bf1.get("ambiguous_nearest_tie", 0) or 0) == 0,
            "outcome_join_pass_first": join1.get("binary_pass") is True
            and join1.get("verification_fail", -1) == 0
            and join1.get("ambiguous_exact_ts_duplicate_snapshots", -1) == 0,
            "outcome_join_pass_after_resync": join2.get("binary_pass") is True
            and join2.get("verification_fail", -1) == 0,
            "unsafe_joins_zero": unsafe_join == 0,
            "anchor_all_trusted_anchored": without_anchor == 0 and trusted_total == n_trusted,
            "anchor_audit_binary": anchor1.get("binary_pass") is True,
        }

        overall = all(pass_gates.values())

        report: dict[str, Any] = {
            "window": {
                "kind": "deterministic_production_path_accumulation",
                "db_path": str(OUT_DB.resolve()),
                "n_decision_events": decision_events,
                "base_ts_utc": BASE_TS,
                "ts_step_sec": TS_STEP,
                "tickers_rotated": ["SPY", "QQQ"],
            },
            "counts": {
                "calibration_decision_log_total": n_total,
                "trusted_rows": n_trusted,
                "legacy_rows": n_legacy,
                "duplicate_key_groups": len(dups),
                "duplicate_detail": dups[:20],
            },
            "backfill_first": bf1,
            "backfill_second_resync": bf2,
            "outcome_join_first": {
                "calibration_row_count": join1.get("calibration_row_count"),
                "rows_with_outcomes": join1.get("rows_with_outcomes"),
                "rows_pending_outcomes": join1.get("rows_pending_outcomes"),
                "verification_pass": join1.get("verification_pass"),
                "verification_fail": join1.get("verification_fail"),
                "ambiguous_exact_ts_duplicate_snapshots": join1.get("ambiguous_exact_ts_duplicate_snapshots"),
                "binary_pass": join1.get("binary_pass"),
            },
            "outcome_join_after_second_backfill": {
                "verification_fail": join2.get("verification_fail"),
                "binary_pass": join2.get("binary_pass"),
            },
            "anchor_trusted_calibration": {
                "trusted_rows_total": trusted_total,
                "trusted_rows_without_anchor": without_anchor,
                "trusted_rows_with_anchor": ca.get("trusted_rows_with_anchor"),
            },
            "legacy_report": leg1.get("counts"),
            "unsafe_non_exact_join_rows_trusted": unsafe_join,
            "warnings": warnings,
            "pass_gates": pass_gates,
            "binary_pass": overall,
        }
        return report
    finally:
        ml_predict.run_base_models_once = _orig_run_base


def main() -> int:
    try:
        rep = run()
    except Exception as e:
        print(json.dumps({"error": str(e), "binary_pass": False}, indent=2))
        return 2
    OUT_REPORT.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print(json.dumps(rep, indent=2))
    return 0 if rep.get("binary_pass") else 3


if __name__ == "__main__":
    sys.exit(main())
