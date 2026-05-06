from __future__ import annotations

from pathlib import Path


def test_attachment_sets_artifact_when_loader_returns_one(monkeypatch):
    from v2_decision import a1_conformal_artifact_attachment as attachment

    artifact = {"calibration_run_id": "cal-test-run"}
    monkeypatch.setattr(attachment, "load_a1_conformal_artifact", lambda **kwargs: artifact)
    ms_dict = {"primary_horizon": "5c"}

    attachment.attach_a1_conformal_artifact_to_ms_dict(ms_dict, ticker="SPY")

    assert ms_dict["a1_conformal_artifact"] == artifact


def test_attachment_sets_none_when_loader_returns_none(monkeypatch):
    from v2_decision import a1_conformal_artifact_attachment as attachment

    monkeypatch.setattr(attachment, "load_a1_conformal_artifact", lambda **kwargs: None)
    ms_dict = {"primary_horizon": "5c"}

    attachment.attach_a1_conformal_artifact_to_ms_dict(ms_dict, ticker="SPY")

    assert ms_dict["a1_conformal_artifact"] is None


def test_attachment_calls_loader_with_correct_ticker_and_horizon(monkeypatch):
    from v2_decision import a1_conformal_artifact_attachment as attachment

    calls = []

    def fake_loader(**kwargs):
        calls.append(kwargs)
        return {"artifact": True}

    monkeypatch.setattr(attachment, "load_a1_conformal_artifact", fake_loader)
    ms_dict = {"primary_horizon": " 5C "}

    attachment.attach_a1_conformal_artifact_to_ms_dict(ms_dict, ticker="SPY")

    assert calls == [{"ticker": "SPY", "horizon": "5c"}]


def test_attachment_sets_none_when_primary_horizon_missing(monkeypatch):
    from v2_decision import a1_conformal_artifact_attachment as attachment

    calls = []
    monkeypatch.setattr(attachment, "load_a1_conformal_artifact", lambda **kwargs: calls.append(kwargs))
    ms_dict = {}

    attachment.attach_a1_conformal_artifact_to_ms_dict(ms_dict, ticker="SPY")

    assert calls == []
    assert ms_dict["a1_conformal_artifact"] is None


def test_attachment_sets_none_when_ticker_empty(monkeypatch):
    from v2_decision import a1_conformal_artifact_attachment as attachment

    calls = []
    monkeypatch.setattr(attachment, "load_a1_conformal_artifact", lambda **kwargs: calls.append(kwargs))
    ms_dict = {"primary_horizon": "5c"}

    attachment.attach_a1_conformal_artifact_to_ms_dict(ms_dict, ticker="")

    assert calls == []
    assert ms_dict["a1_conformal_artifact"] is None


def test_attachment_does_not_inject_calibrated_probability_or_lineage_id(monkeypatch):
    from v2_decision import a1_conformal_artifact_attachment as attachment

    monkeypatch.setattr(attachment, "load_a1_conformal_artifact", lambda **kwargs: {"artifact": True})
    ms_dict = {"primary_horizon": "5c"}

    attachment.attach_a1_conformal_artifact_to_ms_dict(ms_dict, ticker="SPY")

    assert "a1_calibrated_probability" not in ms_dict
    assert "a1_calibrated_probability_lineage_id" not in ms_dict


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

    stamp_idx = window.index("stamp_decision_bundle(ms_dict)")
    attach_idx = window.index("attach_a1_conformal_artifact_to_ms_dict(ms_dict, ticker=ticker)")
    build_idx = window.index(build_anchor)

    assert stamp_idx < attach_idx < build_idx


def _server_source() -> str:
    return Path("server.py").read_text(encoding="utf-8")
