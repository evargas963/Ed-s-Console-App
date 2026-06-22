"""Tests for card direction integrity classification helpers (deterministic)."""
from __future__ import annotations

from verification.card_direction_integrity import (
    CLASS_FROZEN_BACKEND,
    CLASS_STALE_PAYLOAD,
    CLASS_VALID_REVERSAL,
    aggregate_horizon_metrics,
    classify_long_during_decline,
    direction_hit,
    direction_sign,
    find_decline_intervals,
    forward_return_at_index,
    mhap_direction_map,
    stale_conflict,
    trailing_conflict,
    trailing_return_at_index,
    ui_card_state_from_probe,
)


def test_direction_hit_long_forward_positive():
    assert direction_hit("LONG", 0.002) is True


def test_direction_hit_long_forward_negative():
    assert direction_hit("LONG", -0.003) is False


def test_reversal_candidate_long_trailing_neg_forward_pos():
    tags = classify_long_during_decline(
        displayed_direction="LONG",
        trailing_return_1m=-0.001,
        trailing_return_60m=-0.01,
        forward_return_1m=0.002,
        forward_return_60m=-0.001,
        data_age_seconds=30,
        payload_frozen=False,
        fusion_stayed_long=True,
        histogram_stayed_long=True,
        final_tradeable=False,
    )
    assert CLASS_VALID_REVERSAL in tags


def test_stale_conflict_long_trailing_negative_stale_timestamp():
    assert trailing_conflict("LONG", -0.002) is True
    assert stale_conflict(trailing_conflict_flag=True, data_age_seconds=300.0) is True
    tags = classify_long_during_decline(
        displayed_direction="LONG",
        trailing_return_1m=-0.002,
        trailing_return_60m=-0.01,
        forward_return_1m=-0.001,
        forward_return_60m=-0.002,
        data_age_seconds=300.0,
        payload_frozen=False,
        fusion_stayed_long=True,
        histogram_stayed_long=True,
        final_tradeable=False,
    )
    assert CLASS_STALE_PAYLOAD in tags


def test_frozen_payload_classification():
    tags = classify_long_during_decline(
        displayed_direction="LONG",
        trailing_return_1m=-0.002,
        trailing_return_60m=-0.01,
        forward_return_1m=-0.001,
        forward_return_60m=-0.002,
        data_age_seconds=30.0,
        payload_frozen=True,
        fusion_stayed_long=True,
        histogram_stayed_long=True,
        final_tradeable=False,
    )
    assert CLASS_FROZEN_BACKEND in tags


def test_all_plan_non_tradeable_does_not_erase_horizon_direction():
    ui = ui_card_state_from_probe(
        {
            "final_bias": "LONG",
            "final_tradeable": False,
            "entry_state": "no_setup",
            "mhap_rows": [{"horizon": "1c", "call": "LONG", "confidence": 0.41}],
        }
    )
    assert ui["ALL_direction"] == "FLAT"
    assert ui["PLAN_state"] == "NO SETUP"
    mhap = mhap_direction_map([{"horizon": "1c", "call": "LONG"}])
    assert mhap["1c"] == "LONG"


def test_find_decline_interval_on_synthetic_series():
    ts = [float(i * 60) for i in range(120)]
    prices = [100.0 - i * 0.05 for i in range(120)]
    intervals = find_decline_intervals(ts, prices, min_decline_minutes=30, min_drawdown_fraction=0.001)
    assert intervals


def test_forward_and_trailing_returns():
    prices = [100.0, 101.0, 102.0, 101.0, 100.0]
    assert trailing_return_at_index(prices, 2, 2) == 0.02
    assert forward_return_at_index(prices, 1, 2) == 0.0


def test_aggregate_horizon_metrics():
    rows = [
        {
            "horizon_1c": {
                "direction_hit": True,
                "trailing_conflict": True,
                "stale_conflict": False,
            }
        },
        {
            "horizon_1c": {
                "direction_hit": False,
                "trailing_conflict": True,
                "stale_conflict": True,
            }
        },
    ]
    m = aggregate_horizon_metrics(rows, "1c")
    assert m["direction_hits"] == 1
    assert m["direction_misses"] == 1
    assert m["trailing_conflict_count"] == 2


def test_direction_sign_neutral():
    assert direction_sign("WAIT") == 0
    assert direction_sign("FLAT") == 0


def test_load_price_series_falls_back_to_snapshots(tmp_path):
    import sqlite3
    from tools.check_card_direction_integrity import load_price_series

    db = tmp_path / "audit.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE snapshots_1m_normalized (ticker TEXT, ts_utc REAL, spot REAL)")
    conn.execute("CREATE TABLE snapshots (ticker TEXT, ts_utc REAL, spot REAL)")
    conn.executemany(
        "INSERT INTO snapshots (ticker, ts_utc, spot) VALUES (?,?,?)",
        [("SPY", 1000.0, 500.0), ("SPY", 1060.0, 499.0)],
    )
    conn.commit()
    ts_list, prices, _, source = load_price_series(conn, "SPY", 900.0, 1100.0)
    assert source == "snapshots"
    assert len(ts_list) == 2
    assert prices[0] == 500.0


def test_fusion_override_empirical_classification():
    from verification.card_signal_fidelity import (
        CLASS_EMPIRICAL_CONFLICTS_SIGNAL,
        CLASS_FUSION_OVERRIDE_EMPIRICAL,
        fusion_vs_empirical_classification,
    )

    tags = fusion_vs_empirical_classification(
        fusion_direction="LONG",
        histogram_direction="SHORT",
        displayed_direction="LONG",
    )
    assert CLASS_FUSION_OVERRIDE_EMPIRICAL in tags
    assert CLASS_EMPIRICAL_CONFLICTS_SIGNAL in tags


def test_trailing_price_conflict_semantics_reversal_long():
    from verification.card_signal_fidelity import CLASS_REVERSAL_LONG, classify_signal_semantics

    tags = classify_signal_semantics(
        displayed_direction="LONG",
        trailing_return_1m=-0.002,
        trailing_return_60m=-0.01,
        forward_return_1m=0.003,
        fusion_direction="LONG",
        histogram_direction="SHORT",
    )
    assert CLASS_REVERSAL_LONG in tags


def test_all_plan_blocked_while_horizon_long_not_ui_bug():
    from verification.card_signal_fidelity import CLASS_PLAN_CORRECTLY_BLOCKED, enrich_timeline_row_provenance

    row = enrich_timeline_row_provenance(
        {
            "final_tradeable": False,
            "horizon_1c": {"displayed_direction": "LONG", "fusion_direction": "LONG"},
            "horizon_5c": {"displayed_direction": "LONG"},
            "horizon_15c": {"displayed_direction": "LONG"},
            "horizon_60c": {"displayed_direction": "LONG"},
            "trailing_return_1m": -0.001,
            "trailing_return_60m": -0.005,
            "horizon_prob_bars": {"1m": {"up": 0.2, "down": 0.6, "flat": 0.2}},
            "payload_frozen": False,
            "data_age_seconds": 30,
        }
    )
    assert row.get("plan_block_classification") == CLASS_PLAN_CORRECTLY_BLOCKED


def test_stale_feature_timestamp_classification():
    from verification.card_signal_fidelity import classify_stale_feature_risk

    assert classify_stale_feature_risk(data_age_seconds=300, payload_frozen=False) is True
    assert classify_stale_feature_risk(data_age_seconds=30, payload_frozen=True) is True
    assert classify_stale_feature_risk(data_age_seconds=30, payload_frozen=False) is False


def test_fusion_overrides_bearish_histogram_classification():
    from verification.card_signal_fidelity import (
        HIST_FUSION_OVERRIDES_BEARISH,
        HIST_VALID_REVERSAL_DESPITE_BEARISH,
        classify_histogram_shape_cell,
    )

    override = classify_histogram_shape_cell(
        trailing_tape="DOWN",
        histogram_dominant="SHORT",
        fusion_dominant="LONG",
        card_direction="LONG",
        forward_realized_return=-0.001,
        histogram_flat=False,
        data_degraded=False,
        stale_feature_risk=False,
    )
    assert HIST_FUSION_OVERRIDES_BEARISH in override

    reversal = classify_histogram_shape_cell(
        trailing_tape="DOWN",
        histogram_dominant="SHORT",
        fusion_dominant="LONG",
        card_direction="LONG",
        forward_realized_return=0.002,
        histogram_flat=False,
        data_degraded=False,
        stale_feature_risk=False,
    )
    assert HIST_VALID_REVERSAL_DESPITE_BEARISH in reversal


def test_histogram_underconditioned_when_tape_down_hist_not_short():
    from verification.card_signal_fidelity import HIST_UNDERCONDITIONED, classify_histogram_shape_cell

    tags = classify_histogram_shape_cell(
        trailing_tape="DOWN",
        histogram_dominant="LONG",
        fusion_dominant="LONG",
        card_direction="LONG",
        forward_realized_return=-0.001,
        histogram_flat=False,
        data_degraded=False,
        stale_feature_risk=False,
    )
    assert HIST_UNDERCONDITIONED in tags


def test_histogram_shape_audit_builds_cells():
    from verification.card_signal_fidelity import (
        HIST_FUSION_OVERRIDES_BEARISH,
        build_histogram_shape_audit,
        enrich_timeline_row_provenance,
    )

    row = enrich_timeline_row_provenance(
        {
            "ts_et": "2026-06-17 12:43:48 ET",
            "ts_utc": 1.0,
            "trailing_return_1m": -0.002,
            "trailing_return_5m": -0.003,
            "trailing_return_15m": -0.004,
            "trailing_return_60m": -0.005,
            "horizon_prob_bars": {"1m": {"up": 0.2, "down": 0.6, "flat": 0.2}},
            "fusion_triplets": {"1c": {"up": 0.5, "down": 0.3, "flat": 0.2}},
            "mhap_rows": [{"horizon": "1c", "call": "LONG", "confidence": 0.44}],
            "horizon_1c": {
                "displayed_direction": "LONG",
                "fusion_direction": "LONG",
                "histogram_direction": "SHORT",
                "forward_realized_return": -0.001,
            },
            "horizon_5c": {"displayed_direction": "LONG"},
            "horizon_15c": {"displayed_direction": "LONG"},
            "horizon_60c": {"displayed_direction": "LONG"},
            "payload_frozen": False,
            "data_age_seconds": 30,
        }
    )
    audit = build_histogram_shape_audit([row], normalized_rows_rth=374)
    assert audit["cell_count"] == 4
    one_c = next(c for c in audit["cells"] if c["horizon"] == "1c")
    assert one_c["histogram_dominant"] == "SHORT"
    assert one_c["fusion_dominant"] == "LONG"
    assert HIST_FUSION_OVERRIDES_BEARISH in one_c["classifications"]
