from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from v2_decision import a2_lifecycle_sidecar
from v2_decision.a2_lifecycle_sidecar import LIFECYCLE_GAP_NAMES, build_a2_lifecycle_sidecar
from v2_decision.a2_session_calendar import SessionInfo
from v2_decision.a2_lifecycle_health import (
    build_a2_pin_risk_event_source,
    derive_a2_pin_risk_health,
    resolve_a2_option_right,
    select_a2_pin_risk_audit_row,
)


ET = ZoneInfo("America/New_York")


def _epoch_ms_et(year: int, month: int, day: int, hour: int, minute: int) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=ET).timestamp() * 1000)


def _proof(*, strike: float = 500.0, wall_distance: float | None = 0.5, wall_score=None, wall_proximity=None) -> dict:
    row = {
        "strike": strike,
        "side": "CALL",
        "wall_score_component": wall_score,
        "wall_proximity_component": wall_proximity,
        "wall_bias_component": 0.25,
        "wall_contribution_detail": {
            "proximity_detail": [],
            "bias_notes": ["dom_gamma_call_confluence"],
        },
    }
    if wall_distance is not None:
        row["wall_contribution_detail"]["proximity_detail"].append(
            {
                "level": "dom_gamma_wall",
                "strike": strike + wall_distance,
                "contrib": 1.1,
            }
        )
    return {
        "status": "ok",
        "winner": {
            "strike": strike,
            "side": "CALL",
            "chain_row": {"symbol": "SPY260505C00500000"},
        },
        "chain_rows_scored": [row],
    }


def _ms(**overrides) -> dict:
    base = {
        "ticker": "SPY",
        "rec_strike": 500.0,
        "rec_side": "CALL",
        "call_option_right": "CALL",
        "call_signal": "long",
        "entry_state": "armed",
        "decision_time_ms": _epoch_ms_et(2026, 5, 5, 10, 30),
        "selected_exp": "2026-05-05",
        "option_chain_selection_proof": _proof(),
    }
    base.update(overrides)
    return base


def _set_calendar(monkeypatch, session_type: str | None):
    if session_type is None:
        monkeypatch.setattr(a2_lifecycle_sidecar, "load_a2_session_calendar", lambda **kw: None)
        return
    monkeypatch.setattr(a2_lifecycle_sidecar, "load_a2_session_calendar", lambda **kw: {"calendar": "present"})
    monkeypatch.setattr(
        a2_lifecycle_sidecar,
        "get_session_info",
        lambda **kw: SessionInfo(
            session_type=session_type,
            session_open_et="09:30",
            session_close_et="16:00",
            decision_date_et="2026-05-05",
            decision_minute_et=630,
        ),
    )


def test_pin_risk_elevated_emits_one_event(monkeypatch):
    _set_calendar(monkeypatch, "normal_rth")

    event = build_a2_lifecycle_sidecar(_ms())["event_sources"][0]

    assert event["event_type"] == "pin_risk"
    assert event["status"] == "elevated"
    assert event["reasons"] == ["selected_strike_near_gamma_or_oi_wall"]
    assert event["nearest_wall"]["level"] == "dom_gamma_wall"
    assert event["selected_strike"] == 500.0
    assert event["session_type"] == "normal_rth"
    assert event["source_classification"] == "derived_because_schwab_does_not_provide"


def test_pin_risk_watch_emits_one_event(monkeypatch):
    _set_calendar(monkeypatch, "normal_rth")
    proof = _proof(wall_distance=2.0, wall_score=1.25)

    event_sources = build_a2_lifecycle_sidecar(_ms(option_chain_selection_proof=proof))["event_sources"]

    assert len(event_sources) == 1
    assert event_sources[0]["event_type"] == "pin_risk"
    assert event_sources[0]["status"] == "watch"
    assert event_sources[0]["reasons"] == ["material_wall_contribution"]


def test_pin_risk_not_detected_emits_no_event(monkeypatch):
    _set_calendar(monkeypatch, "normal_rth")
    proof = _proof(wall_distance=None, wall_score=0.2, wall_proximity=0.2)

    assert build_a2_lifecycle_sidecar(_ms(option_chain_selection_proof=proof))["event_sources"] == []


def test_pin_risk_missing_selected_strike_emits_no_event(monkeypatch):
    _set_calendar(monkeypatch, "normal_rth")
    ms = _ms(rec_strike=None)
    ms["option_chain_selection_proof"]["winner"].pop("strike")
    ms["option_chain_selection_proof"]["chain_rows_scored"][0].pop("strike")

    assert build_a2_lifecycle_sidecar(ms)["event_sources"] == []


def test_pin_risk_missing_nearest_wall_emits_no_event(monkeypatch):
    _set_calendar(monkeypatch, "normal_rth")
    proof = _proof(wall_distance=None)

    assert build_a2_lifecycle_sidecar(_ms(option_chain_selection_proof=proof))["event_sources"] == []


def test_pin_risk_full_closure_suppresses_event(monkeypatch):
    _set_calendar(monkeypatch, "full_closure")

    assert build_a2_lifecycle_sidecar(_ms())["event_sources"] == []


def test_pin_risk_out_of_session_suppresses_event(monkeypatch):
    _set_calendar(monkeypatch, "out_of_session")

    assert build_a2_lifecycle_sidecar(_ms())["event_sources"] == []


def test_pin_risk_calendar_absent_emits_calendar_unavailable(monkeypatch):
    _set_calendar(monkeypatch, None)

    event = build_a2_lifecycle_sidecar(_ms())["event_sources"][0]

    assert event["status"] == "elevated"
    assert event["session_type"] == "calendar_unavailable"


def test_pin_risk_calendar_info_none_emits_calendar_unavailable(monkeypatch):
    monkeypatch.setattr(a2_lifecycle_sidecar, "load_a2_session_calendar", lambda **kw: {"calendar": "present"})
    monkeypatch.setattr(a2_lifecycle_sidecar, "get_session_info", lambda **kw: None)

    event = build_a2_lifecycle_sidecar(_ms())["event_sources"][0]

    assert event["status"] == "elevated"
    assert event["session_type"] == "calendar_unavailable"


def test_pin_risk_normal_rth_event_has_normal_rth_session_type(monkeypatch):
    _set_calendar(monkeypatch, "normal_rth")

    assert build_a2_lifecycle_sidecar(_ms())["event_sources"][0]["session_type"] == "normal_rth"


def test_pin_risk_early_close_event_has_early_close_session_type(monkeypatch):
    _set_calendar(monkeypatch, "early_close")

    assert build_a2_lifecycle_sidecar(_ms())["event_sources"][0]["session_type"] == "early_close"


def test_pin_risk_composes_with_eod_force_exit_without_overriding_action(monkeypatch):
    _set_calendar(monkeypatch, None)

    sidecar = build_a2_lifecycle_sidecar(
        _ms(
            entry_state="filled",
            decision_time_ms=_epoch_ms_et(2026, 5, 5, 15, 50),
            selected_exp="2026-05-05",
        )
    )

    assert sidecar["lifecycle_action"] == "force_exit_recommended"
    assert sidecar["event_sources"][0]["event_type"] == "pin_risk"


def test_pin_risk_sidecar_does_not_mutate_ms_dict(monkeypatch):
    _set_calendar(monkeypatch, "normal_rth")
    ms = _ms()
    before = deepcopy(ms)

    build_a2_lifecycle_sidecar(ms)

    assert ms == before


def test_pin_risk_gap_is_retired_from_runtime_gap_names():
    assert "a2_lifecycle_pin_risk_handler_not_implemented" not in LIFECYCLE_GAP_NAMES


def test_derive_pin_risk_health_uses_o37_threshold_precedence():
    health = derive_a2_pin_risk_health(
        selected_audit={
            "strike": 500.0,
            "wall_score_component": 2.0,
            "wall_proximity_component": 0.9,
            "wall_contribution_detail": {
                "proximity_detail": [{"level": "wall", "strike": 500.5, "contrib": 1.0}],
            },
        },
        strike=500.0,
    )

    assert health["status"] == "elevated"
    assert health["reasons"] == ["selected_strike_near_gamma_or_oi_wall"]


def test_build_pin_risk_event_source_suppresses_not_detected_missing_strike_and_wall():
    assert build_a2_pin_risk_event_source(
        pin_risk_health={"status": "not_detected", "selected_strike": 500.0, "nearest_wall": {"level": "x"}},
        session_type="normal_rth",
    ) is None
    assert build_a2_pin_risk_event_source(
        pin_risk_health={"status": "elevated", "selected_strike": None, "nearest_wall": {"level": "x"}},
        session_type="normal_rth",
    ) is None
    assert build_a2_pin_risk_event_source(
        pin_risk_health={"status": "elevated", "selected_strike": 500.0, "nearest_wall": None},
        session_type="normal_rth",
    ) is None


def test_pin_risk_ingress_resolver_uses_canonical_option_expression_source_order():
    """Schwab-canonical chain_row.putCall is primary; app-side aliases are
    legacy fallbacks per OP-011 / CSV-R8 (Schwab-first, not Schwab-last)."""
    winner = {"side": "CALL", "putCall": "PUT"}

    # Schwab-canonical chain_row.putCall wins over conflicting app-side aliases.
    assert resolve_a2_option_right(
        {"call_option_right": "CALL", "rec_side": "CALL"},
        {"side": "CALL", "chain_row": {"putCall": "PUT"}},
    ) == "PUT"

    # When chain_row.putCall is absent, the app-side aliases serve as fallbacks
    # in the legacy order: call_option_right -> rec_side -> winner.side.
    assert resolve_a2_option_right({"call_option_right": "PUT", "rec_side": "CALL"}, winner) == "PUT"
    assert resolve_a2_option_right({"rec_side": "PUT"}, winner) == "PUT"
    assert resolve_a2_option_right({"option_right": "PUT"}, winner) == "CALL"
    # winner.putCall at the root (not under chain_row) is NOT a Schwab-canonical
    # source: only chain_row.putCall is. Root-level putCall is ignored.
    assert resolve_a2_option_right({}, {"putCall": "PUT"}) == "NONE"
    assert resolve_a2_option_right({"call_option_right": "C"}, winner) == "NONE"


def test_pin_risk_ingress_selects_audit_row_with_canonical_side_filter():
    proof = {
        "winner": {"strike": 500.0, "side": "", "wall_score_component": 9.0},
        "chain_rows_scored": [
            {"strike": 500.0, "side": "CALL", "wall_score_component": 1.0},
            {"strike": 500.0, "side": "PUT", "wall_score_component": 2.0},
        ],
    }

    assert select_a2_pin_risk_audit_row(
        proof=proof,
        winner=proof["winner"],
        strike=500.0,
        option_right="PUT",
    )["wall_score_component"] == 2.0
    assert select_a2_pin_risk_audit_row(
        proof=proof,
        winner=proof["winner"],
        strike=500.0,
        option_right="NONE",
    ) == proof["winner"]


def test_sidecar_uses_shared_ingress_and_does_not_match_by_strike_when_side_unknown(monkeypatch):
    _set_calendar(monkeypatch, "normal_rth")
    proof = {
        "winner": {
            "strike": 500.0,
            "putCall": "CALL",
            "chain_row": {"symbol": "SPY260505C00500000"},
        },
        "chain_rows_scored": [
            {
                "strike": 500.0,
                "side": "CALL",
                "wall_contribution_detail": {
                    "proximity_detail": [{"level": "dom_gamma_wall", "strike": 500.5, "contrib": 1.0}],
                },
            }
        ],
    }
    ms = _ms(
        call_option_right=None,
        rec_side=None,
        option_right="CALL",
        option_chain_selection_proof=proof,
    )

    assert resolve_a2_option_right(ms, proof["winner"]) == "NONE"
    assert build_a2_lifecycle_sidecar(ms)["event_sources"] == []
