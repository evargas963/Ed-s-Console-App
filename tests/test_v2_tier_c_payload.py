"""server.py's tier-C payload must attach the V2 decision AFTER the decision bundle
is stamped, not before -- attaching early would silently ship a tier-C payload
built from a pre-stamp, not-yet-final decision bundle. Source-order check: the
ordering itself is the property, not derivable from behavior alone."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_tier_c_attaches_v2_decision_after_decision_bundle_stamp():
    server_source = (ROOT / "server.py").read_text(encoding="utf-8")

    stamp_idx = server_source.index("_finalize_production_decision(ms_dict, _decision_route)")
    attach_idx = server_source.index('ms_dict["v2_decision"] = _v2_decision_for_response')
    merge_idx = server_source.index("_lmp.merge_into_state(ms_dict, ticker)", attach_idx)

    assert stamp_idx < attach_idx < merge_idx


def test_tier_c_single_phase_calibration_write_after_v2_before_log_only_return():
    server_source = (ROOT / "server.py").read_text(encoding="utf-8")

    v2_idx = server_source.index("_v2_decision_for_response = build_module_a_a1_decision")
    write_idx = server_source.index("append_live_v2_calibration_decision(", v2_idx)
    log_only_idx = server_source.index("if log_only:", write_idx)

    assert v2_idx < write_idx < log_only_idx


def test_tier_c_imports_module_a_a1_adapter():
    server_source = (ROOT / "server.py").read_text(encoding="utf-8")

    assert "from v2_decision import build_module_a_a1_decision" in server_source


def test_v2_ui_card_removed_negative_lock():
    """Operator 2026-06-10: the V2 Pilot 1A advisory card was retired — every
    cell was a v1_approximation / not_implemented scaffold with no operator
    value. The v2 engine stays server-side (tests above lock the ms_dict
    attach + calibration-logging ordering). No agent may re-introduce the
    card or its renderer."""
    ui_source = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

    assert 'id="v2-pilot-card"' not in ui_source
    assert 'id="v2-a2-card"' not in ui_source
    assert "function renderV2PilotDecision" not in ui_source
    assert "renderV2PilotDecision(d)" not in ui_source
    assert "A2 0DTE Advisory" not in ui_source
    assert "Draft v2 view only. Does not replace the locked v1.1 decision policy." not in ui_source

