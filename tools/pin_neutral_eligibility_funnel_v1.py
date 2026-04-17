#!/usr/bin/env python3
"""
Pin_neutral → Issue 19 similarity eligibility funnel (read-only).

Traces why tier1/tier2 candidate counts from issue19_option_a_post_validate can be zero
despite outcome repair: documents timeframe vs anchor, zone/vwap, distance buckets, outcome_1c.

Usage:
  python tools/pin_neutral_eligibility_funnel_v1.py --db data/ed_console.db
  python tools/pin_neutral_eligibility_funnel_v1.py --db data/ed_console.db --json-out data/pin_neutral_eligibility_funnel_v1.json
"""
from __future__ import annotations

from db import get_snapshot_sql


import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from horizon_outcomes import HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1
from timeframe_config import CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME

# Reuse exact tier SQL from Issue 19 post-validate
from tools.issue19_option_a_post_validate import _count_tier_sql, load_default_anchors


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path.resolve()), timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


def _one(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    r = conn.execute(sql, params).fetchone()
    return int(r[0]) if r and r[0] is not None else 0


PIN_PARAMS = (
    CANONICAL_TIMEFRAME,
    DERIVED_TIMEFRAME,
    HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
    HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
)


def collect_funnel(conn: sqlite3.Connection, db_path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {
        "schema": "pin_neutral_eligibility_funnel_v1",
        "db_path": str(db_path.resolve()),
        "generated_ts_utc": time.time(),
        "reference_code": {
            "issue19_tier_sql": "tools/issue19_option_a_post_validate.py::_count_tier_sql",
            "similarity_sql": "db.py:get_similar_setups tiers 1–2 (timeframe = ?)",
            "live_fill_outcomes": "server.py after insert_snapshot: fill_outcomes(ticker, CANONICAL_TIMEFRAME, _snap_ts)",
            "fill_outcomes_gate": "db.py:fill_outcomes returns immediately if timeframe != CANONICAL_TIMEFRAME",
        },
    }

    # --- Stage 1: cohort (same structural scope as pin_neutral repair) ---
    n_total = _one(
        conn,
        get_snapshot_sql("tools/pin_neutral_eligibility_funnel_v1.py:stage_total"),
        PIN_PARAMS,
    )
    n_unfilled = _one(
        conn,
        get_snapshot_sql("tools/pin_neutral_eligibility_funnel_v1.py:stage_unfilled"),
        PIN_PARAMS,
    )
    n_filled = _one(
        conn,
        get_snapshot_sql("tools/pin_neutral_eligibility_funnel_v1.py:stage_filled"),
        PIN_PARAMS,
    )

    n_1m = _one(
        conn,
        get_snapshot_sql("tools/pin_neutral_eligibility_funnel_v1.py:stage_tf"),
        PIN_PARAMS + (CANONICAL_TIMEFRAME,),
    )
    n_5m = _one(
        conn,
        get_snapshot_sql("tools/pin_neutral_eligibility_funnel_v1.py:stage_tf"),
        PIN_PARAMS + (DERIVED_TIMEFRAME,),
    )

    n_1m_o1 = _one(
        conn,
        get_snapshot_sql("tools/pin_neutral_eligibility_funnel_v1.py:stage_tf_o1"),
        PIN_PARAMS + (CANONICAL_TIMEFRAME,),
    )
    n_5m_o1 = _one(
        conn,
        get_snapshot_sql("tools/pin_neutral_eligibility_funnel_v1.py:stage_tf_o1"),
        PIN_PARAMS + (DERIVED_TIMEFRAME,),
    )

    # Anchor feasibility for still-unfilled (audit-style)
    n_unfilled_no_anchor = _one(
        conn,
        get_snapshot_sql("tools/pin_neutral_eligibility_funnel_v1.py:unfilled_no_anchor"),
        PIN_PARAMS,
    )
    n_unfilled_anchor_but_stuck = n_unfilled - n_unfilled_no_anchor

    out["funnel_stages"] = {
        "1_total_pin_neutral_bar_anchor_scope": n_total,
        "2_outcome_filled_1": n_filled,
        "2b_outcome_filled_0": n_unfilled,
        "3_timeframe_1m_rows": n_1m,
        "3_timeframe_5m_rows": n_5m,
        "4_outcome_1c_nonnull_1m": n_1m_o1,
        "4b_outcome_1c_nonnull_5m": n_5m_o1,
        "5_unfilled_no_completed_anchor_bar": n_unfilled_no_anchor,
        "5b_unfilled_has_anchor_bar_but_not_filled": n_unfilled_anchor_but_stuck,
    }

    out["interpretation_note"] = (
        "Issue 19 post_validate tier counts use each anchor's timeframe (default '1m' from survivorship JSON). "
        "get_similar_setups SQL requires snapshots.timeframe to equal the query timeframe. "
        "Historical pin_neutral repair cohort is mostly '5m'; live server inserts use CANONICAL_TIMEFRAME ('1m') only."
    )

    # --- Per-anchor: official tier counts + counterfactual 5m ---
    anchors = load_default_anchors(ROOT)
    pin_anchors = [a for a in anchors if (a.get("zone") or "") == "pin_neutral"]
    per_anchor: list[dict[str, Any]] = []

    for a in pin_anchors:
        t1_official = _count_tier_sql(
            conn,
            tier=1,
            ticker=a["ticker"],
            timeframe=a["timeframe"],
            zone=a["zone"],
            vwap_side=a["vwap_side"],
            nearest_above_dist=a.get("nearest_above_dist"),
            nearest_below_dist=a.get("nearest_below_dist"),
        )
        t2_official = _count_tier_sql(
            conn,
            tier=2,
            ticker=a["ticker"],
            timeframe=a["timeframe"],
            zone=a["zone"],
            vwap_side=a["vwap_side"],
            nearest_above_dist=a.get("nearest_above_dist"),
            nearest_below_dist=a.get("nearest_below_dist"),
        )

        # Counterfactual: same anchor but pool = 5m rows only (proves timeframe mismatch)
        from math_exposure import bucket_hi, bucket_lo, dist_bucket

        above_bucket = dist_bucket(a.get("nearest_above_dist"))
        below_bucket = dist_bucket(a.get("nearest_below_dist"))
        alo, ahi = bucket_lo(above_bucket), bucket_hi(above_bucket)
        blo, bhi = bucket_lo(below_bucket), bucket_hi(below_bucket)
        t = (a["ticker"] or "").upper().strip()
        t1_5m = int(
            conn.execute(
                get_snapshot_sql("tools/pin_neutral_eligibility_funnel_v1.py:169"),
                (
                    t,
                    DERIVED_TIMEFRAME,
                    a["zone"],
                    a["vwap_side"],
                    a.get("nearest_above_dist"),
                    alo,
                    ahi,
                    a.get("nearest_below_dist"),
                    blo,
                    bhi,
                ),
            ).fetchone()["n"]
        )

        t2_5m = int(
            conn.execute(
                get_snapshot_sql("tools/pin_neutral_eligibility_funnel_v1.py:199"),
                (t, DERIVED_TIMEFRAME, a["zone"], a["vwap_side"], a.get("nearest_above_dist"), alo, ahi),
            ).fetchone()["n"]
        )

        per_anchor.append(
            {
                "anchor_id": a.get("anchor_id"),
                "ticker": a["ticker"],
                "anchor_timeframe": a["timeframe"],
                "zone": a["zone"],
                "vwap_side": a["vwap_side"],
                "tier1_count_at_anchor_timeframe": t1_official,
                "tier2_count_at_anchor_timeframe": t2_official,
                "tier1_count_if_timeframe_were_5m": t1_5m,
                "tier2_count_if_timeframe_were_5m": t2_5m,
            }
        )

    out["pin_neutral_anchors_official_vs_5m_counterfactual"] = per_anchor

    # --- Drop analysis: remove one filter at a time on 5m + outcome_1c ---
    n_5m_pin_o1 = _one(
        conn,
        get_snapshot_sql("tools/pin_neutral_eligibility_funnel_v1.py:five_m_pin_o1"),
        PIN_PARAMS + (DERIVED_TIMEFRAME,),
    )
    out["five_m_labeled_pin_neutral"] = n_5m_pin_o1

    # Possibility matrix (A–H) — boolean evidence
    out["root_cause_hypothesis_evidence"] = {
        "A_remaining_unlabeled": {
            "true_if": n_unfilled > 0,
            "count_unfilled": n_unfilled,
            "severity": "high" if n_unfilled > 50 else "low",
        },
        "B_missing_bar_coverage": {
            "true_if": n_unfilled_no_anchor > 0,
            "count_unfilled_without_anchor_bar": n_unfilled_no_anchor,
            "severity": "high" if n_unfilled_no_anchor > 0 else "none",
        },
        "C_ticker_mismatch": {
            "note": "snapshots.ticker vs price_bars_1m.ticker uses same string in audit EXISTS; upsert uses ticker_storage_key",
            "spx_rows_use_dollar_prefix": _one(
                conn,
                get_snapshot_sql("tools/pin_neutral_eligibility_funnel_v1.py:spx_like"),
                PIN_PARAMS,
            ),
        },
        "D_zone_mismatch": {
            "note": "tier SQL requires zone = pin_neutral; pool rows must be zone pin_neutral",
            "labeled_1m_pin_neutral": _one(
                conn,
                get_snapshot_sql("tools/pin_neutral_eligibility_funnel_v1.py:labeled_1m_spx"),
                ("$SPX", CANONICAL_TIMEFRAME),
            ),
        },
        "E_vwap_side_mismatch": {
            "note": "anchor fixes vwap_side; pool must match anchor vwap_side exactly",
        },
        "F_timeframe_mismatch_primary": {
            "true_if": n_5m_o1 > 0 and all(x["tier1_count_at_anchor_timeframe"] == 0 for x in per_anchor),
            "labeled_5m_pin_neutral_outcome_1c": n_5m_o1,
            "labeled_1m_pin_neutral_outcome_1c": n_1m_o1,
            "conclusion": "If anchors use timeframe '1m' but labeled pin_neutral history is on '5m', official tier counts stay 0.",
        },
        "G_tier_sql_overconstraint": {
            "note": "Even on 5m, tier1 needs both distance buckets; see tier1_count_if_timeframe_were_5m vs tier2",
        },
        "H_other": {"note": "Reserved — e.g. outcome_1c NULL while other horizons set (should be rare)"},
    }

    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--json-out", type=Path, default=None)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="tools.pin_neutral_eligibility_funnel_v1", write_capable=False)
    if not args.db.is_file():
        raise SystemExit(f"DB not found: {args.db}")

    conn = connect(args.db)
    try:
        bundle = collect_funnel(conn, args.db)
    finally:
        conn.close()

    text = json.dumps(bundle, indent=2, default=str) + "\n"
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
