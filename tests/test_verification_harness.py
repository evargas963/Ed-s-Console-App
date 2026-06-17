"""Verification harness: diagnostics visibility (Phases 1–7)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


from db import EdDB
from math_exposure import MIN_SAMPLES_STATISTICAL
from multi_horizon_decision import build_multi_horizon_bundle
from prediction_engine import _literal_empirical_horizon
from timeframe_config import CANONICAL_TIMEFRAME
from verification.db_coverage import db_coverage_report
from verification.decision_explain import explain_market_state_dict, explain_reason_ladder
from verification.horizon_health import horizon_health_report
from verification.replay_diagnostic import replay_summary
from verification.similar_set_trace import full_similar_and_empirical_trace
from verification.threshold_stress import threshold_stress_on_similar


def _minimal_insert(
    conn,
    *,
    ticker: str,
    ts: float,
    zone: str,
    vwap_side: str,
    outcome_1c: str | None,
    outcome_5c: str | None,
    outcome_15c: str | None,
    outcome_60c: str | None,
    nad: float | None = 1.0,
    nbd: float | None = 1.0,
):
    conn.execute(
        """
        INSERT INTO snapshots (
          ticker, timeframe, ts_utc, ts_et, spot, zone, vwap_side,
          nearest_above_dist, nearest_below_dist,
          outcome_1c, outcome_5c, outcome_15c, outcome_60c,
          horizon_outcome_schema_version
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            ticker,
            CANONICAL_TIMEFRAME,
            ts,
            "test",
            450.0,
            zone,
            vwap_side,
            nad,
            nbd,
            outcome_1c,
            outcome_5c,
            outcome_15c,
            outcome_60c,
            1,
        ),
    )


def test_db_coverage_reports_row_counts(tmp_path: Path):
    dbp = tmp_path / "c.db"
    db = EdDB(dbp)
    with db._connect() as conn:
        for i in range(3):
            _minimal_insert(
                conn,
                ticker="SPY",
                ts=1_700_000_000.0 + i * 60,
                zone="z1",
                vwap_side="above",
                outcome_1c="up",
                outcome_5c="up",
                outcome_15c=None,
                outcome_60c="flat",
            )
        conn.commit()
    r = db_coverage_report(["SPY"], db_path=dbp, timeframe=CANONICAL_TIMEFRAME)
    row = r["machine"]["tickers"][0]
    assert row["snapshots_total"] == 3
    assert row["outcome_15c_nonnull"] == 0
    assert row["outcome_1c_labeled"] == 3


def test_many_rows_total_but_small_similar_when_few_filled(tmp_path: Path):
    dbp = tmp_path / "s.db"
    db = EdDB(dbp)
    with db._connect() as conn:
        for i in range(80):
            _minimal_insert(
                conn,
                ticker="SPY",
                ts=1_700_000_000.0 + i * 60,
                zone="wide",
                vwap_side="above",
                outcome_1c="up" if i < 12 else None,
                outcome_5c="up" if i < 12 else None,
                outcome_15c="up" if i < 12 else None,
                outcome_60c="up" if i < 12 else None,
            )
        conn.commit()
    tr = full_similar_and_empirical_trace(
        db,
        ticker="SPY",
        zone="wide",
        vwap_side="above",
        nearest_above_dist=1.0,
        nearest_below_dist=1.0,
    )
    assert tr["narrowing"]["A_base_candidate_snapshots_ticker_timeframe"] == 80
    assert tr["narrowing"]["G_final_similar_list_size"] == 12
    assert tr["empirical_horizons"]["60c"]["status"] == "WITHHELD"


def test_spy_vs_qqq_different_similar_sizes(tmp_path: Path):
    dbp = tmp_path / "p.db"
    db = EdDB(dbp)
    with db._connect() as conn:
        for i in range(60):
            _minimal_insert(
                conn,
                ticker="SPY",
                ts=1_700_000_000.0 + i * 60,
                zone="pin",
                vwap_side="above",
                outcome_1c="up",
                outcome_5c="down",
                outcome_15c="up",
                outcome_60c="flat",
            )
        for i in range(8):
            _minimal_insert(
                conn,
                ticker="QQQ",
                ts=1_701_000_000.0 + i * 60,
                zone="pin",
                vwap_side="above",
                outcome_1c="up",
                outcome_5c="down",
                outcome_15c="up",
                outcome_60c="flat",
            )
        conn.commit()
    def sz(tkr: str):
        return full_similar_and_empirical_trace(
            db,
            ticker=tkr,
            zone="pin",
            vwap_side="above",
            nearest_above_dist=1.0,
            nearest_below_dist=1.0,
        )["narrowing"]["G_final_similar_list_size"]

    assert sz("SPY") == 60
    assert sz("QQQ") == 8
    assert sz("SPY") != sz("QQQ")


def test_horizon_withheld_below_threshold():
    similar = [
        {
            "outcome_1c": "up",
            "outcome_5c": "up",
            "outcome_15c": "up",
            "outcome_60c": "up",
        }
        for _ in range(10)
    ]
    p, _sk, _n, n = _literal_empirical_horizon(similar, "outcome_5c", 5)
    assert p is None
    assert n == 10


def test_horizon_ok_at_threshold():
    similar = []
    for _i in range(MIN_SAMPLES_STATISTICAL):
        similar.append(
            {
                "outcome_1c": "up",
                "outcome_5c": "up",
                "outcome_15c": "flat",
                "outcome_60c": "down",
            }
        )
    p, _, _, n = _literal_empirical_horizon(similar, "outcome_5c", 5)
    assert p is not None
    assert n == MIN_SAMPLES_STATISTICAL


def test_no_valid_primary_sets_wait_reason():
    p = SimpleNamespace(
        up_prob_1c=None,
        down_prob_1c=None,
        flat_prob_1c=None,
        up_prob_5c=None,
        down_prob_5c=None,
        flat_prob_5c=None,
        up_prob_15c=None,
        down_prob_15c=None,
        flat_prob_15c=None,
        up_prob_60c=None,
        down_prob_60c=None,
        flat_prob_60c=None,
        avg_5c_pts=0.1,
        avg_15c_pts=0.1,
        avg_60c_pts=0.1,
    )
    inp = SimpleNamespace(
        spot=440.0,
        mins_to_close=180,
        nearest_below_val=439.0,
        nearest_above_val=441.0,
    )
    # No canonical blend: all empirical probs missing → zero valid horizon triplets;
    # the ALL-card pooled consensus (2026-06-11) must WAIT with the
    # insufficient-evidence reason (fail-closed pool floor).
    from multi_horizon_decision import WAIT_REASON_INSUFFICIENT_VALID_HORIZONS

    canonical = None
    call = SimpleNamespace(signal="long", entry=440.5, stop=438.0, target=443.0, target2=None, call_state="WATCH")
    b = build_multi_horizon_bundle(inp, p, canonical, call)
    assert b.final_decision.final_bias == "WAIT"
    assert (b.final_decision.wait_reason or "") == WAIT_REASON_INSUFFICIENT_VALID_HORIZONS


def test_explainability_reason_chain():
    ms = {
        "horizon_prob_bars": {
            "1m": {
                "up": None,
                "down": None,
                "flat": None,
                "labeled_count": 12,
                "min_samples_required": 30,
                "source": "insufficient_labeled_outcome_1c",
            }
        },
        "final_bias": "WAIT",
        "final_tradeable": False,
        "wait_reason": "no valid primary horizon",
        "fusion_available": False,
        "xgb_available": True,
    }
    ex = explain_market_state_dict(ms)
    assert "reason_ladder" in ex
    assert any("labeled_count=12" in s for s in ex["reason_ladder"])
    ladder = explain_reason_ladder(ms)
    assert len(ladder) >= 1


def test_threshold_stress_monotonic():
    similar = [{"outcome_1c": "up", "outcome_5c": "up", "outcome_15c": "up", "outcome_60c": "up"} for _ in range(28)]
    s = threshold_stress_on_similar(similar)
    assert s["thresholds"]["20"]["per_horizon"]["1c"] == "valid"
    assert s["thresholds"]["30"]["per_horizon"]["1c"] == "withheld"


def test_replay_emits_summary(tmp_path: Path):
    dbp = tmp_path / "r.db"
    db = EdDB(dbp)
    with db._connect() as conn:
        for i in range(25):
            _minimal_insert(
                conn,
                ticker="SPY",
                ts=1_702_000_000.0 + i * 60,
                zone="pin_neutral",
                vwap_side="above",
                outcome_1c="up",
                outcome_5c="up",
                outcome_15c="up",
                outcome_60c="up",
            )
        conn.commit()
    rep = replay_summary(db, tickers=("SPY",), limit_bars=10, stride=1, as_of_honest=True)
    assert "SPY" in rep["tickers"]
    assert rep["tickers"]["SPY"]["counts"]["n_slices"] == 10
    assert "percent" in rep["tickers"]["SPY"]


def test_horizon_health_report_shape():
    similar = [
        {
            "outcome_1c": "up",
            "outcome_5c": "up",
            "outcome_15c": "up",
            "outcome_60c": "up",
        }
    ]
    h = horizon_health_report(similar)
    assert h["similar_size"] == 1
    assert h["horizons"]["1c"]["status"] == "WITHHELD"
