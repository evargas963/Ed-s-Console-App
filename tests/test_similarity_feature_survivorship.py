from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db import EdDB
from similarity_feature_search import (
    diagnose_overlay_match_counts,
    matching_snapshot_overlay_for_anchor,
    resolve_overlay_for_anchor,
)
from similarity_feature_survivorship import (
    default_multi_anchor_set_v1,
    final_structure_from_survivorship,
    run_multi_anchor_survivorship,
)
from timeframe_config import CANONICAL_TIMEFRAME


def _seed(conn, ticker: str, zone: str, vwap_side: str, ts: float, sess: str, vix_b: str) -> None:
    conn.execute(
        """
        INSERT INTO snapshots (
          ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
          zone, vwap_side, nearest_above_dist, nearest_below_dist,
          session_bucket, vix_bucket, regime_primary,
          outcome_1c, outcome_5c, outcome_15c, outcome_60c,
          horizon_outcome_schema_version
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            ticker,
            CANONICAL_TIMEFRAME,
            ts,
            "t",
            10,
            30,
            "rth",
            100.0,
            zone,
            vwap_side,
            1.0,
            1.0,
            sess,
            vix_b,
            "pinning",
            "up",
            "up",
            "up",
            "up",
            3,
        ),
    )


def test_matching_overlay_per_structural_anchor(tmp_path):
    db = EdDB(tmp_path / "s.db")
    t0 = 3_000_000_000.0
    with db._connect() as c:
        _seed(c, "AB", "pin_neutral", "above", t0, "morning", "vix_normal")
        c.commit()
    o = matching_snapshot_overlay_for_anchor(
        db,
        ticker="AB",
        timeframe=CANONICAL_TIMEFRAME,
        zone="pin_neutral",
        vwap_side="above",
        nearest_above_dist=1.0,
        nearest_below_dist=1.0,
    )
    assert o.get("session_bucket") == "morning"
    assert o.get("vix_bucket") == "vix_normal"


def test_resolve_overlay_includes_audit_metadata(tmp_path):
    db = EdDB(tmp_path / "meta.db")
    t0 = 3_000_000_001.0
    with db._connect() as c:
        _seed(c, "CD", "pin_bull", "below", t0, "afternoon", "vix_high")
        c.commit()
    r = resolve_overlay_for_anchor(
        db,
        ticker="CD",
        timeframe=CANONICAL_TIMEFRAME,
        zone="pin_neutral",
        vwap_side="below",
        nearest_above_dist=1.0,
        nearest_below_dist=1.0,
    )
    assert r["overlay"].get("session_bucket") == "afternoon"
    assert "resolution" in r
    assert r["resolution"]["zone_lookup_note"] == "pin_neutral_expanded_to_pin_family"


def test_diagnose_overlay_stages_structured(tmp_path):
    db = EdDB(tmp_path / "d.db")
    t0 = 3_000_000_002.0
    with db._connect() as c:
        _seed(c, "ZZ", "pin_bull", "above", t0, "midday", "vix_normal")
        c.commit()
    d = diagnose_overlay_match_counts(
        db,
        ticker="ZZ",
        timeframe=CANONICAL_TIMEFRAME,
        zone="pin_neutral",
        vwap_side="above",
        nearest_above_dist=1.0,
        nearest_below_dist=1.0,
    )
    assert d["schema"] == "overlay_match_count_diagnosis_v1"
    assert d["stages"][1]["stage"] == "plus_exact_zone"
    assert d["first_zero_count_stage"] == "plus_exact_zone"


def test_survivorship_reproducible_structured(tmp_path):
    db = EdDB(tmp_path / "s2.db")
    t0 = 3_100_000_000.0
    with db._connect() as c:
        for i in range(24):
            _seed(
                c,
                "SPY",
                "pin_neutral",
                "above",
                t0 + i * 60,
                "morning",
                "vix_normal",
            )
        c.commit()

    anchors = [
        a
        for a in default_multi_anchor_set_v1(extra_tickers=None)
        if a["ticker"] == "SPY" and a["zone"] == "pin_neutral" and a["vwap_side"] == "above"
    ][:1]
    r1 = run_multi_anchor_survivorship(db, anchors=anchors, n_similar=15, candidate_pool_cap=80, top_k=3)
    r2 = run_multi_anchor_survivorship(db, anchors=anchors, n_similar=15, candidate_pool_cap=80, top_k=3)
    assert r1 == r2
    assert r1["schema"] == "similarity_feature_survivorship_v1"
    assert len(r1["feature_survivorship_table"]) >= 4
    fs = final_structure_from_survivorship(r1)
    assert "zone" in fs["EARLY_STRICT"]
    assert "nearest_above_dist" in fs["MID_STRICT"]
