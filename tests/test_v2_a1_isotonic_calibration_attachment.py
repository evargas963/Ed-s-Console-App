"""v2_decision.a1_isotonic_calibration_attachment must only attach a calibrated
probability + lineage when both the isotonic artifact and the raw probability are
actually present -- attaching a calibrated value built on a missing input would
silently misstate the decision's true calibration provenance."""
from __future__ import annotations

from pathlib import Path




















def test_server_imports_isotonic_attachment_helper():
    source = _server_source()

    assert (
        "from v2_decision.a1_isotonic_calibration_attachment "
        "import attach_a1_isotonic_calibration_to_ms_dict"
    ) in source


def test_server_logging_path_invokes_isotonic_attachment_after_conformal():
    source = _server_source()
    window = source[source.index("_v2_logging_ms_dict = _ms_to_dict(ms)") : source.index("from calibration.v2_live_logging")]

    conformal_idx = window.index("attach_a1_conformal_artifact_to_ms_dict(_v2_logging_ms_dict, ticker=ticker)")
    isotonic_idx = window.index("attach_a1_isotonic_calibration_to_ms_dict(_v2_logging_ms_dict, ticker=ticker)")
    build_idx = window.index("build_module_a_a1_decision(_v2_logging_ms_dict)")

    assert conformal_idx < isotonic_idx < build_idx


def test_server_response_path_invokes_isotonic_attachment_after_conformal():
    source = _server_source()
    build_anchor = 'ms_dict["v2_decision"] = _v2_decision_for_response or build_module_a_a1_decision(ms_dict)'
    build_pos = source.index(build_anchor)
    start = source.rindex("_attach_stack_runtime_and_governance(ms_dict, ticker=ticker)", 0, build_pos)
    end = source.index("_lmp.merge_into_state", build_pos)
    window = source[start:end]

    conformal_idx = window.index("attach_a1_conformal_artifact_to_ms_dict(ms_dict, ticker=ticker)")
    isotonic_idx = window.index("attach_a1_isotonic_calibration_to_ms_dict(ms_dict, ticker=ticker)")
    build_idx = window.index(build_anchor)

    assert conformal_idx < isotonic_idx < build_idx


def _server_source() -> str:
    return Path("server.py").read_text(encoding="utf-8")
