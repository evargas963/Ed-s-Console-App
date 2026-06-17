"""edge_discovery fail-closed buckets, gating, and integrity."""

from __future__ import annotations

from pathlib import Path

import pytest

from calibration.edge_discovery import (
    MIN_N,
    _alignment_state_bucket,
    _bootstrap_gated,
    _canonical_confidence_bucket,
    aggregate_slice,
    feature_importance_naive,
    main,
)
from calibration.statistical_integrity import (
    MIN_SAMPLES_STATISTICAL,
    bucket_gate,
    verify_edge_discovery_no_numeric_leak,
)
from calibration.v2_a1_calibration import axis_reliability_bucket_value as a1_axis


def _labeled_row(*, pts: float = 0.1) -> dict:
    return {
        "outcome_5c": "up",
        "outcome_5c_pts": pts,
        "final_signal": "long",
        "canonical_json": "{}",
        "fusion_json": "{}",
        "_features": {"brier_row": 0.1},
    }


def test_alignment_state_missing_distinct_from_unknown():
    assert _alignment_state_bucket(None) == a1_axis(None)
    assert _alignment_state_bucket("UNKNOWN") == "UNKNOWN"
    assert _alignment_state_bucket(None) != "UNKNOWN"


def test_canonical_confidence_missing_invalid_distinct():
    missing = _canonical_confidence_bucket(None)
    invalid = _canonical_confidence_bucket("garbled")
    low = _canonical_confidence_bucket("low")
    assert missing == a1_axis(None)
    assert invalid == "__invalid__"
    assert low == "low"
    assert len({missing, invalid, low}) == 3


def test_aggregate_slice_withholds_means_below_min_n():
    members = [_labeled_row(pts=0.01 * i) for i in range(MIN_SAMPLES_STATISTICAL - 1)]
    agg = aggregate_slice("test|n=small", "marginal:test", members)
    assert agg["gate_sufficient"] is False
    assert agg["mean_ev_actual_final_signal"] is None
    assert agg["mean_brier"] is None
    assert agg["bootstrap_actual_minus_long"]["mean_delta"] is None

    report = {
        "slices_all": [agg],
        "feature_importance_naive": {
            "pearson_n": 0,
            "pearson_sample_gate": {"sufficient_sample": False, "n": 0},
            "pearson_fusion_prob_up_vs_outcome_5c_pts": None,
        },
    }
    assert verify_edge_discovery_no_numeric_leak(report) is True


def test_verify_edge_discovery_fails_when_ungated_mean_present():
    report = {
        "slices_all": [{"n": 5, "mean_ev_actual_final_signal": 0.01}],
        "feature_importance_naive": {
            "pearson_n": 0,
            "pearson_sample_gate": {"sufficient_sample": False},
            "pearson_fusion_prob_up_vs_outcome_5c_pts": None,
        },
    }
    assert verify_edge_discovery_no_numeric_leak(report) is False


def test_edge_discovery_module_has_no_md_write_text():
    source = Path(__file__).resolve().parents[1] / "calibration" / "edge_discovery.py"
    assert ".write_text(" not in source.read_text(encoding="utf-8")


@pytest.mark.parametrize("n,expected_ok", [(MIN_N - 1, False), (MIN_N, True)])
def test_feature_importance_pearson_gate_matches_bucket_gate(n, expected_ok):
    rows = [
        {
            "outcome_5c_pts": float(i),
            "fusion_json": '{"prob_up": 0.5}',
        }
        for i in range(n)
    ]
    fi = feature_importance_naive(rows)
    base = bucket_gate(n, MIN_N)
    gate = fi["pearson_sample_gate"]
    assert gate["n"] == base["n"]
    assert gate["min_required"] == base["min_required"]
    assert gate["sufficient_sample"] is expected_ok
    assert gate["status"] == base["status"]


def test_bootstrap_gated_sets_gate_sufficient_from_gate_ok():
    actual = [0.1, 0.2, 0.3, 0.4]
    baseline = [0.0, 0.1, 0.2, 0.3]
    ok_boot = _bootstrap_gated(actual, baseline, gate_ok=True)
    assert ok_boot["gate_sufficient"] is True
    assert ok_boot["mean_delta"] is not None

    withheld = _bootstrap_gated(actual, baseline, gate_ok=False)
    assert withheld["gate_sufficient"] is False
    assert withheld["mean_delta"] is None
    assert withheld["ci95_low"] is None
    assert withheld["ci95_high"] is None


def test_pearson_gate_coerces_negative_n_via_bucket_gate():
    gate = bucket_gate(-5, MIN_N)
    assert gate["n"] == 0
    assert gate["sufficient_sample"] is False
    assert gate["status"] == "insufficient_sample"


def test_main_uses_atomic_md_write(monkeypatch, tmp_path):
    json_calls: list[tuple] = []
    md_calls: list[tuple] = []

    def _json(path, payload, **kw):
        json_calls.append((path, payload, kw))

    def _md(path, text, **kw):
        md_calls.append((path, text, kw))

    rep = {
        "meta": {
            "raw_labeled_trusted": 0,
            "labeled_anchored_count": 0,
            "excluded_no_bar_anchor": 0,
        },
        "per_row_feature_extract": [],
        "slices_all": [],
        "slices_edge_only": [],
        "slices_ranked_worst_delta_vs_long": [],
        "feature_importance_naive": feature_importance_naive([]),
        "system_level": {"FINAL_SYSTEM_EDGE": "NO_EDGE", "any_marginal_EDGE": 0},
        "statistical_integrity": {"binary_pass": True},
    }
    monkeypatch.setattr("calibration.edge_discovery.pick_db_path", lambda _db: tmp_path / "db.sqlite")
    monkeypatch.setattr("calibration.edge_discovery.enforce_resolved_path", lambda *a, **k: None)
    monkeypatch.setattr("calibration.edge_discovery.run_discovery", lambda _db: rep)
    monkeypatch.setattr("calibration.edge_discovery.write_json_file_atomically", _json)
    monkeypatch.setattr("calibration.edge_discovery.write_text_atomically", _md)
    monkeypatch.setattr("calibration.edge_discovery.ROOT", tmp_path)
    (tmp_path / "db.sqlite").write_bytes(b"")
    monkeypatch.setattr("sys.argv", ["edge_discovery", "--db", str(tmp_path / "db.sqlite")])

    assert main() == 1
    assert len(json_calls) == 1
    assert len(md_calls) == 1
    assert md_calls[0][0] == tmp_path / "docs" / "calibration_edge_discovery_v1.md"
    assert "# Calibration edge discovery (v1)" in md_calls[0][1]
