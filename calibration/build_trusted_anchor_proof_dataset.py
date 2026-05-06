#!/usr/bin/env python3
"""
Build a non-empty trusted calibration_decision_log using production compute_signals + writer path,
seed price_bars_1m + snapshots for anchor audit / backfill, write audit JSON.

  python -m calibration.build_trusted_anchor_proof_dataset

Output: data/calibration_anchor_proof.db, data/calibration_anchor_proof_audit.json
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["ED_CALIBRATION_LOG"] = "1"
os.environ["ED_CONSOLE_ALLOW_NONCANONICAL_DB"] = "1"

import db as db_mod
from calibration.anchor_audit import run_anchor_audit
from calibration.analyze_phase3 import analyze as analyze_phase3
from calibration.analyze_phase4 import analyze as analyze_phase4
from calibration.backfill_outcomes import backfill
from calibration.schema import ensure_calibration_schema
from calibration.validate_logging_e2e import _inp
from db import EdDB, configure_sqlite_connection
from instrument_identity import ticker_storage_key
from signals import compute_signals

N_ROWS = 30
BASE_TS = 1_712_100_000.0
TS_STEP = 100.0

PROOF_DB = ROOT / "data" / "calibration_anchor_proof.db"
AUDIT_JSON = ROOT / "data" / "calibration_anchor_proof_audit.json"


def _stub_models() -> None:
    import ml_predict
    from tests.test_calibration_logging_production_path import _fake_run_base_models_once

    ml_predict.run_base_models_once = _fake_run_base_models_once


def _seed_bars_and_snapshots(conn: sqlite3.Connection, plan: list[tuple[str, float]]) -> None:
    """plan: list of (storage_key_ticker, decision_ts_utc)."""
    for tkr, ts in plan:
        be = ts - 30.0
        bs = be - 60.0
        conn.execute(
            """
            INSERT INTO price_bars_1m (ticker, bar_start_ts_utc, bar_end_ts_utc, close, source)
            VALUES (?, ?, ?, ?, 'anchor_proof')
            """,
            (tkr, bs, be, 450.0),
        )
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                horizon_outcome_schema_version, outcome_filled,
                outcome_1c, outcome_5c, outcome_15c, outcome_60c,
                outcome_1c_pts, outcome_5c_pts, outcome_15c_pts, outcome_60c_pts
            )
            VALUES (?, '1m', ?, 'proof', 10, 30, 'rth', 450.0, 3, 1,
                    'up', 'up', 'flat', 'down',
                    0.1, 0.2, 0.3, 0.4)
            """,
            (tkr, ts),
        )


def main() -> int:
    _stub_models()

    PROOF_DB.parent.mkdir(parents=True, exist_ok=True)
    if PROOF_DB.exists():
        PROOF_DB.unlink()

    _ = EdDB(PROOF_DB)
    db_mod.DB_PATH = PROOF_DB

    conn = sqlite3.connect(str(PROOF_DB))
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)

    tickers_src = (["SPY"] * 15) + (["QQQ"] * 15)
    plan: list[tuple[str, float]] = []
    for i in range(N_ROWS):
        ts = BASE_TS + float(i) * TS_STEP
        tkr = ticker_storage_key(tickers_src[i])
        plan.append((tkr, ts))

    _seed_bars_and_snapshots(conn, plan)
    conn.commit()
    conn.close()

    edb = EdDB(PROOF_DB)
    for i in range(N_ROWS):
        ts = BASE_TS + float(i) * TS_STEP
        name = tickers_src[i]
        inp = _inp(refresh_ts_utc=ts)
        from dataclasses import replace

        inp2 = replace(inp, ticker=name)
        out = compute_signals(inp2, db=edb)
        from calibration.v2_live_logging import append_live_v2_calibration_decision
        from v2_decision import build_module_a_a1_decision

        canonical = out.canonical_forecast
        append_live_v2_calibration_decision(
            db_path=PROOF_DB,
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

    backfill(PROOF_DB, tol_sec=0.0)

    rep = run_anchor_audit(PROOF_DB, sample_limit=None, seed_sample=False)
    p3 = analyze_phase3(PROOF_DB)
    p4 = analyze_phase4(PROOF_DB)

    out = {
        "anchor_audit": rep,
        "analyze_phase3_provenance": p3.get("provenance"),
        "analyze_phase3_calibration_rows": p3.get("calibration_rows"),
        "analyze_phase4_provenance": p4.get("provenance"),
    }
    AUDIT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")

    ca = rep.get("calibration_trusted_anchor_audit") or {}
    nt = int(ca.get("trusted_rows_total", -1))
    if nt <= 0:
        print("FAIL: trusted_rows_total not positive", file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "trusted_rows_total": nt, "audit_json": str(AUDIT_JSON)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
