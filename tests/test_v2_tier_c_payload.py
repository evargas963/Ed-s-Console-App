"""server.py's tier-C payload must attach the V2 decision AFTER the decision bundle
is stamped, not before -- attaching early would silently ship a tier-C payload
built from a pre-stamp, not-yet-final decision bundle. Source-order check: the
ordering itself is the property, not derivable from behavior alone."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_tier_c_attaches_v2_decision_after_decision_bundle_stamp():
    # RC-REHAB-1 (thirty-seventh slice): the finalize/attach/merge run inside
    # server_state_publish._finalize_and_publish_state, in this order.
    pub = (ROOT / "server_state_publish.py").read_text(encoding="utf-8")
    fn_at = pub.index("def _finalize_and_publish_state(")
    stamp_idx = pub.index("_finalize_decision(ms_dict, ms,", fn_at)
    attach_idx = pub.index('ms_dict["v2_decision"] = v2_decision or build_module_a_a1_decision(ms_dict)', fn_at)
    merge_idx = pub.index("_srv._lmp.merge_into_state(ms_dict, ticker)", attach_idx)
    assert stamp_idx < attach_idx < merge_idx


def test_tier_c_single_phase_calibration_write_after_v2_before_log_only_return():
    """RC-REHAB-1 (Phase 4, _fetch_state decomposition, nineteenth slice):
    append_live_v2_calibration_decision now lives inside
    _post_publish_persistence_tail, promoted to a module-level function
    (defined BEFORE _fetch_state in the file, so a forward text search from the
    v2-build site inside _fetch_state can no longer find it there). Re-derived
    as an execution-order claim instead: v2 decision built, THEN the tail is
    called on the log_only path (which is where the calibration write actually
    executes for that path), THEN the log_only return -- and the write call
    itself still lives inside the tail's own body."""
    server_source = (ROOT / "server.py").read_text(encoding="utf-8")

    # RC-REHAB-1 (thirty-fifth slice): the v2 build is _v2_decision_for_state.
    v2_idx = server_source.index("_v2_decision_for_response, _v2_logging_ms_dict = _v2_decision_for_state(")
    log_only_tail_call_idx = server_source.index(
        '_post_publish_persistence_tail(\n        None, _v2_decision_for_response', v2_idx
    )
    log_only_return_idx = server_source.index("return {}", log_only_tail_call_idx)
    assert v2_idx < log_only_tail_call_idx < log_only_return_idx

    # RC-REHAB-1 (2026-09-23, module extraction, twentieth slice): the tail moved out of
    # server.py entirely into server_state_persistence_tail.py -- checked there now.
    tail_source = (ROOT / "server_state_persistence_tail.py").read_text(encoding="utf-8")
    assert "append_live_v2_calibration_decision(" in tail_source, (
        "the persistence tail no longer performs the calibration write"
    )


def test_tier_c_imports_module_a_a1_adapter():
    # RC-REHAB-1 (thirty-fifth/-seventh slices): the v2 build and the publish own the calls.
    for mod in ("server_state_decision.py", "server_state_publish.py"):
        assert "from v2_decision import build_module_a_a1_decision" in (ROOT / mod).read_text(encoding="utf-8")


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

