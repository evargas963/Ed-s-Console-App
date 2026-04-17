"""
Adaptive shadow similarity — analysis-only path; heuristic authority unchanged.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db import EdDB
from timeframe_config import CANONICAL_TIMEFRAME


def _seed_rows(conn, ticker: str, zone: str, n: int, base_ts: float) -> None:
    for i in range(n):
        conn.execute(
            """
            INSERT INTO snapshots (
              ticker, timeframe, ts_utc, ts_et, spot, zone, vwap_side,
              nearest_above_dist, nearest_below_dist,
              outcome_1c, outcome_3c, outcome_5c, outcome_8c, outcome_13c, outcome_15c, outcome_60c,
              horizon_outcome_schema_version
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                ticker,
                CANONICAL_TIMEFRAME,
                base_ts + i * 60,
                "t",
                100.0,
                zone,
                "above" if i % 2 == 0 else "below",
                1.0,
                1.0,
                "up",
                "up",
                "up",
                "up",
                "up",
                "up",
                "up",
                3,
            ),
        )


def test_shadow_weighted_deterministic(tmp_path):
    from adaptive_similarity_engine import run_weighted_selection

    dbp = tmp_path / "ash.db"
    db = EdDB(dbp)
    t0 = 3_000_000_000.0
    with db._connect() as c:
        _seed_rows(c, "SH", "ash_zone", 40, t0)
        c.commit()
    kw = dict(
        db=db,
        ticker="SH",
        timeframe=CANONICAL_TIMEFRAME,
        zone="ash_zone",
        vwap_side="above",
        nearest_above_dist=1.0,
        nearest_below_dist=1.0,
        n_similar=30,
        candidate_pool_cap=500,
    )
    a = run_weighted_selection(**kw)
    b = run_weighted_selection(**kw)
    assert a.selected_row_ids == b.selected_row_ids
    assert a.scores == b.scores


def test_baseline_control_matches_heuristic_ids(tmp_path):
    from adaptive_similarity_engine import run_baseline_control

    dbp = tmp_path / "ash2.db"
    db = EdDB(dbp)
    t0 = 3_100_000_000.0
    with db._connect() as c:
        _seed_rows(c, "SH2", "z2", 35, t0)
        c.commit()
    h = db.get_similar_setups(
        ticker="SH2",
        timeframe=CANONICAL_TIMEFRAME,
        zone="z2",
        vwap_side="above",
        nearest_above_dist=50.0,
        nearest_below_dist=50.0,
        n_similar=20,
        return_trace=False,
    )
    bs = run_baseline_control(
        db,
        ticker="SH2",
        timeframe=CANONICAL_TIMEFRAME,
        zone="z2",
        vwap_side="above",
        nearest_above_dist=50.0,
        nearest_below_dist=50.0,
        n_similar=20,
    )
    assert [r.get("snapshot_id") for r in h] == bs.selected_row_ids


def test_comparison_metrics_structure(tmp_path):
    from adaptive_similarity_engine import compare_heuristic_to_shadow, run_weighted_selection

    dbp = tmp_path / "ash3.db"
    db = EdDB(dbp)
    with db._connect() as c:
        _seed_rows(c, "SH3", "z3", 25, 3_200_000_000.0)
        c.commit()
    w = run_weighted_selection(
        db,
        ticker="SH3",
        timeframe=CANONICAL_TIMEFRAME,
        zone="z3",
        vwap_side="above",
        nearest_above_dist=1.0,
        nearest_below_dist=1.0,
        n_similar=15,
        candidate_pool_cap=300,
    )
    comp = compare_heuristic_to_shadow(
        w.selected_row_ids[:5],
        w,
        heuristic_tier_stop_viable=True,
        heuristic_labeled_counts=w.labeled_counts,
    )
    assert comp["schema"] == "heuristic_shadow_comparison_v1"
    for k in ("jaccard", "recall_vs_a", "precision_vs_a", "intersection"):
        assert k in comp["overlap"]


def test_ablation_structure(tmp_path):
    from adaptive_similarity_engine import run_feature_ablations, run_weighted_selection

    dbp = tmp_path / "ash4.db"
    db = EdDB(dbp)
    with db._connect() as c:
        _seed_rows(c, "SH4", "z4", 40, 3_300_000_000.0)
        c.commit()
    weighted = run_weighted_selection(
        db,
        ticker="SH4",
        timeframe=CANONICAL_TIMEFRAME,
        zone="z4",
        vwap_side="above",
        nearest_above_dist=1.0,
        nearest_below_dist=1.0,
        n_similar=20,
        candidate_pool_cap=400,
    )
    abl = run_feature_ablations(
        db,
        ticker="SH4",
        timeframe=CANONICAL_TIMEFRAME,
        zone="z4",
        vwap_side="above",
        nearest_above_dist=1.0,
        nearest_below_dist=1.0,
        n_similar=20,
        baseline_run=weighted,
        candidate_pool_cap=400,
    )
    assert len(abl) == 4
    for a in abl:
        assert "feature_removed" in a
        assert "overlap_vs_full_weighted" in a
        assert "labeled_counts" in a
        assert "score_distribution" in a


def test_ordering_experiments_valid_comparisons(tmp_path):
    from adaptive_similarity_engine import ORDERING_PRESETS, run_order_variant

    dbp = tmp_path / "ash5.db"
    db = EdDB(dbp)
    with db._connect() as c:
        _seed_rows(c, "SH5", "z5", 30, 3_400_000_000.0)
        c.commit()
    for preset in ORDERING_PRESETS:
        r = run_order_variant(
            db,
            preset,
            ticker="SH5",
            timeframe=CANONICAL_TIMEFRAME,
            zone="z5",
            vwap_side="above",
            nearest_above_dist=1.0,
            nearest_below_dist=1.0,
            n_similar=15,
            candidate_pool_cap=300,
        )
        assert r.variant.startswith("order_variant:")
        assert len(r.selected_row_ids) <= 15


def test_heuristic_engine_regression_untouched_signature(tmp_path):
    dbp = tmp_path / "ash6.db"
    db = EdDB(dbp)
    with db._connect() as c:
        _seed_rows(c, "SH6", "z6", 10, 3_500_000_000.0)
        c.commit()
    out = db.get_similar_setups(
        "SH6",
        CANONICAL_TIMEFRAME,
        "z6",
        "above",
        1.0,
        1.0,
        5,
        return_trace=False,
    )
    assert isinstance(out, list)
    assert len(out) <= 5


def test_trace_shadow_extension_additive(tmp_path):
    from similarity_audit import merge_trace_with_shadow_extension

    base_trace = {"trace_schema": "similarity_trace_issue21_v1", "chosen_tier": 2}
    merged = merge_trace_with_shadow_extension(base_trace, {"foo": 1})
    assert merged["trace_schema"] == "similarity_trace_issue21_v1"
    assert merged["chosen_tier"] == 2
    assert merged["shadow_extension"]["extension_schema"] == "similarity_trace_shadow_extension_v1"
    assert merged["shadow_extension"]["foo"] == 1


def test_build_report_json_roundtrip_keys(tmp_path):
    import importlib.util

    path = ROOT / "tools" / "adaptive_shadow_report.py"
    spec = importlib.util.spec_from_file_location("adaptive_shadow_report_mod", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    dbp = tmp_path / "ash7.db"
    db = EdDB(dbp)
    with db._connect() as c:
        _seed_rows(c, "SH7", "z7", 45, 3_600_000_000.0)
        c.commit()
    rep = mod.build_adaptive_shadow_report(
        db,
        ticker="SH7",
        timeframe=CANONICAL_TIMEFRAME,
        zone="z7",
        vwap_side="above",
        nearest_above_dist=50.0,
        nearest_below_dist=50.0,
        n_similar=25,
        candidate_pool_cap=400,
    )
    assert rep["schema"] == "adaptive_shadow_report_v1"
    s = json.dumps(rep, default=str)
    assert "heuristic_trace_with_shadow_extension" in s
    assert "feature_ablations" in rep["heuristic_trace_with_shadow_extension"]["shadow_extension"]
