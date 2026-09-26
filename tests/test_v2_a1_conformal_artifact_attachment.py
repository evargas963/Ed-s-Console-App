"""v2_decision.a1_conformal_artifact_attachment must attach the loaded conformal
artifact to the decision only when the loader actually returns one -- attaching a
stale/absent artifact would silently misrepresent the decision's calibration
lineage."""
from __future__ import annotations

from pathlib import Path














def test_server_imports_attachment_helper():
    source = _server_source()

    assert (
        "from v2_decision.a1_conformal_artifact_attachment "
        "import attach_a1_conformal_artifact_to_ms_dict"
    ) in source


def test_server_logging_path_invokes_attachment_between_stamp_and_build():
    source = _server_source()
    window = source[source.index("_v2_logging_ms_dict = _ms_to_dict(ms)") : source.index("from calibration.v2_live_logging")]

    stamp_idx = window.index("stamp_decision_bundle(_v2_logging_ms_dict)")
    attach_idx = window.index("attach_a1_conformal_artifact_to_ms_dict(_v2_logging_ms_dict, ticker=ticker)")
    build_idx = window.index("build_module_a_a1_decision(_v2_logging_ms_dict)")

    assert stamp_idx < attach_idx < build_idx


def test_server_response_path_invokes_attachment_before_v2_decision_build():
    source = _server_source()
    build_anchor = 'ms_dict["v2_decision"] = _v2_decision_for_response or build_module_a_a1_decision(ms_dict)'
    build_pos = source.index(build_anchor)
    start = source.rindex("_attach_stack_runtime_and_governance(ms_dict, ticker=ticker)", 0, build_pos)
    end = source.index("_lmp.merge_into_state", build_pos)
    window = source[start:end]

    stamp_idx = window.index("_finalize_production_decision(ms_dict, _decision_route)")
    attach_idx = window.index("attach_a1_conformal_artifact_to_ms_dict(ms_dict, ticker=ticker)")
    build_idx = window.index(build_anchor)

    assert stamp_idx < attach_idx < build_idx


def _server_source() -> str:
    return Path("server.py").read_text(encoding="utf-8")
