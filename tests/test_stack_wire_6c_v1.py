"""STACK-WIRE-6c — live-vs-replay parity validation for ms_dict reconstruction.

Closes the third component of STACK-WIRE-6: every field that ``ms_dict_from_snapshot_row``
reconstructs from a persisted snapshot row must match the equivalent live ms_dict field,
with provenance stamped to ``reconstructed_from_snapshot``.
"""

from __future__ import annotations

import json

from calibration.v2_advisory_backfill import (
    RECONSTRUCTED_LIVE_MS_SOURCE,
    ms_dict_from_snapshot_row,
)


def _sample_snapshot_row() -> dict:
    """Snapshot row shape produced by the live server during _fetch_state."""
    return {
        "ticker": "SPY",
        "snapshot_id": 12345,
        "ts_utc": 1715000000.0,  # 2025-05-06 14:13:20 UTC = 10:13 ET
        # rules_* live keys (mapped to canonical names by ms_dict_from_snapshot_row)
        "rules_summary": "long → 500 CALL",
        "rules_entry": 480.0,
        "rules_stop": 478.0,
        "rules_target": 485.0,
        "call_target2": 488.0,
        # contract identity
        "expiry": "2026-05-09",
        "call_spread": 0.10,
        "call_strike": 500.0,
        "call_option_right": "CALL",
        "dte": 3,
        # replay_context_json — produced by realized_contract_eval.build_replay_context_payload
        "replay_context_json": json.dumps(
            {
                "version": 1,
                "regime_primary": "trend",
                "regime_confidence": "high",
                "zone": "mid",
                "vol_regime": "normal",
                "trade_type": "trend_continuation",
                "time_qualifier": "~15min",
                "vwap": 481.5,
                "vwap_side": "long",
                "option_chain_selection_proof": {
                    "winner": {"strike": 500.0, "expression": "500 CALL"},
                    "status": "actionable",
                },
            }
        ),
    }


def test_ms_dict_reconstruction_aliases_rules_summary_to_rules_headline():
    """FIND-WIRE6c-1: rules_summary → rules_headline alias propagates with provenance stamp."""
    row = _sample_snapshot_row()
    ms = ms_dict_from_snapshot_row(row)
    assert ms["rules_headline"] == "long → 500 CALL"
    assert ms["live_ms_field_sources"]["rules_headline"] == RECONSTRUCTED_LIVE_MS_SOURCE


def test_ms_dict_reconstruction_aliases_entry_stop_target_target2():
    """FIND-WIRE6c-1: rules_{entry,stop,target}/call_target2 → entry/stop/target/target2 alias chain."""
    row = _sample_snapshot_row()
    ms = ms_dict_from_snapshot_row(row)
    assert ms["entry"] == 480.0
    assert ms["stop"] == 478.0
    assert ms["target"] == 485.0
    assert ms["target2"] == 488.0
    fs = ms["live_ms_field_sources"]
    for k in ("entry", "stop", "target", "target2"):
        assert fs[k] == RECONSTRUCTED_LIVE_MS_SOURCE, f"missing provenance stamp on {k}"


def test_ms_dict_reconstruction_aliases_expiry_strike_side_spread():
    """FIND-WIRE6c-1: expiry/call_strike/call_option_right/call_spread → contract identity aliases."""
    row = _sample_snapshot_row()
    ms = ms_dict_from_snapshot_row(row)
    assert ms["selected_exp"] == "2026-05-09"
    assert ms["call_option_expiry"] == "2026-05-09"
    assert ms["rec_strike"] == 500.0
    assert ms["rec_side"] == "CALL"
    assert ms["spread"] == 0.10
    assert ms["dte_warn"] == "3DTE"


def test_ms_dict_reconstruction_propagates_replay_context_fields():
    """FIND-WIRE6c-2: regime_primary, zone, vol_regime, trade_type, time_qualifier, vwap*, proof
    propagate from replay_context_json with provenance stamp."""
    row = _sample_snapshot_row()
    ms = ms_dict_from_snapshot_row(row)
    expected = {
        "regime_primary": "trend",
        "regime_confidence": "high",
        "zone": "mid",
        "vol_regime": "normal",
        "trade_type": "trend_continuation",
        "time_qualifier": "~15min",
        "vwap": 481.5,
        "vwap_side": "long",
    }
    for k, v in expected.items():
        assert ms[k] == v, f"replay context field {k} not propagated"
        assert ms["live_ms_field_sources"][k] == RECONSTRUCTED_LIVE_MS_SOURCE
    assert ms["option_chain_selection_proof"]["winner"]["strike"] == 500.0
    assert ms["option_chain_selection_proof"]["winner"]["expression"] == "500 CALL"


def test_ms_dict_reconstruction_derives_et_clock_from_ts_utc():
    """FIND-WIRE6c-3: et_hour, et_minute, market_session derived from ts_utc with provenance."""
    row = _sample_snapshot_row()
    ms = ms_dict_from_snapshot_row(row)
    assert ms["et_hour"] is not None
    assert ms["et_minute"] is not None
    assert ms["market_session"] is not None
    fs = ms["live_ms_field_sources"]
    assert fs["et_hour"] == RECONSTRUCTED_LIVE_MS_SOURCE
    assert fs["et_minute"] == RECONSTRUCTED_LIVE_MS_SOURCE
    assert fs["market_session"] == RECONSTRUCTED_LIVE_MS_SOURCE


def test_ms_dict_reconstruction_stamps_reconstruction_source_globally():
    """FIND-WIRE6c-4: live_ms_reconstruction_source set to the sentinel + stack_runtime/governance/signal_chain blocks stamped."""
    row = _sample_snapshot_row()
    ms = ms_dict_from_snapshot_row(row)
    assert ms["live_ms_reconstruction_source"] == RECONSTRUCTED_LIVE_MS_SOURCE
    for block in ("stack_runtime", "stack_governance", "signal_chain"):
        assert isinstance(ms[block], dict)
        assert ms[block].get("source") == RECONSTRUCTED_LIVE_MS_SOURCE
        assert ms["live_ms_field_sources"][block] == RECONSTRUCTED_LIVE_MS_SOURCE


def test_ms_dict_reconstruction_does_not_overwrite_existing_keys():
    """FIND-WIRE6c-5: parity rule — if target key already present (live ms_dict pass-through),
    the alias does NOT clobber it; provenance is also NOT stamped (no reconstruction occurred)."""
    row = _sample_snapshot_row()
    # Already-present live keys take precedence over alias source
    row["rules_headline"] = "PRE-EXISTING headline"
    row["entry"] = 999.9
    ms = ms_dict_from_snapshot_row(row)
    assert ms["rules_headline"] == "PRE-EXISTING headline"
    assert ms["entry"] == 999.9
    # No reconstruction stamp on these because they were already present
    fs = ms["live_ms_field_sources"]
    assert "rules_headline" not in fs
    assert "entry" not in fs


def test_ms_dict_reconstruction_sets_decision_id_buildts_timems_defaults():
    """FIND-WIRE6c-7 (audit-added): decision_generation_id ← snapshot_id; _server_build_ts ← ts_utc;
    decision_time_ms ← int(ts_utc * 1000). Each set via setdefault so live values pass through."""
    row = _sample_snapshot_row()
    ms = ms_dict_from_snapshot_row(row)
    assert ms["decision_generation_id"] == 12345  # snapshot_id
    assert ms["_server_build_ts"] == 1715000000.0  # ts_utc passthrough
    assert ms["decision_time_ms"] == int(1715000000.0 * 1000)


def test_ms_dict_reconstruction_passes_through_existing_decision_id():
    """FIND-WIRE6c-7 (audit-added): live decision_generation_id is preserved (setdefault contract)."""
    row = _sample_snapshot_row()
    row["decision_generation_id"] = 99999  # already-stamped live value
    ms = ms_dict_from_snapshot_row(row)
    assert ms["decision_generation_id"] == 99999  # NOT clobbered by snapshot_id


def test_ms_dict_reconstruction_infers_fusion_fields_from_triplet():
    """FIND-WIRE6c-8 (audit-added): _infer_fusion_fields fills fusion_available + dominant_direction + dominant_prob from complete triplet."""
    row = _sample_snapshot_row()
    row["fusion_prob_up"] = 0.6
    row["fusion_prob_down"] = 0.2
    row["fusion_prob_flat"] = 0.2
    ms = ms_dict_from_snapshot_row(row)
    assert ms["fusion_available"] is True  # complete triplet
    assert ms["fusion_dominant_direction"] == "up"  # 0.6 > 0.2, 0.2
    assert ms["fusion_dominant_prob"] == 0.6  # max of triplet


def test_ms_dict_reconstruction_fusion_unavailable_when_triplet_incomplete_and_no_dominant():
    """FIND-WIRE6c-8 (audit-added): no triplet + no dominant_direction → fusion_available stays False."""
    row = _sample_snapshot_row()
    # Triplet partial (one None); no fusion_dominant_direction or _prob
    row["fusion_prob_up"] = 0.6
    row["fusion_prob_down"] = None
    row["fusion_prob_flat"] = 0.2
    ms = ms_dict_from_snapshot_row(row)
    assert ms["fusion_available"] is False


def test_ms_dict_reconstruction_handles_missing_replay_context():
    """FIND-WIRE6c-6: when replay_context_json is missing/invalid, replay-context-sourced fields stay None
    (no fabricated defaults); reconstruction still completes for ts_utc-derived clock + alias chain."""
    row = _sample_snapshot_row()
    row["replay_context_json"] = None
    ms = ms_dict_from_snapshot_row(row)
    # Alias chain still works (top-level rules_summary, rules_entry etc. still present)
    assert ms["rules_headline"] == "long → 500 CALL"
    assert ms["entry"] == 480.0
    # ET clock still derives from ts_utc
    assert ms["et_hour"] is not None
    # Replay-context fields stay None (no fabricated defaults)
    assert ms.get("regime_primary") is None
    assert ms.get("trade_type") is None
    assert ms.get("vwap") is None
    # Provenance sentinel still stamps the reconstruction source
    assert ms["live_ms_reconstruction_source"] == RECONSTRUCTED_LIVE_MS_SOURCE
