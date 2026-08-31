"""v2_decision.a1_isotonic_calibration_attachment must only attach a calibrated
probability + lineage when both the isotonic artifact and the raw probability are
actually present -- attaching a calibrated value built on a missing input would
silently misstate the decision's true calibration provenance."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path


def test_attachment_sets_calibrated_probability_and_lineage_when_artifact_and_raw_present(monkeypatch):
    from v2_decision import a1_isotonic_calibration_attachment as attachment

    artifact = {"calibration_run_id": "cal-test-run"}
    monkeypatch.setattr(attachment, "load_a1_isotonic_artifact", lambda **kwargs: artifact)
    monkeypatch.setattr(attachment, "dominant_probability", lambda ms_dict: 0.42)
    monkeypatch.setattr(
        attachment,
        "apply_a1_v2_calibration_to_raw_probability",
        lambda **kwargs: (0.51, "cal-test-run:hash"),
    )
    ms_dict = {"primary_horizon": "5c", "dominant_prob": 0.42}

    attachment.attach_a1_isotonic_calibration_to_ms_dict(ms_dict, ticker="SPY")

    assert ms_dict["a1_calibrated_probability"] == 0.51
    assert ms_dict["a1_calibrated_probability_lineage_id"] == "cal-test-run:hash"


def test_attachment_sets_none_when_isotonic_artifact_loader_returns_none(monkeypatch):
    from v2_decision import a1_isotonic_calibration_attachment as attachment

    monkeypatch.setattr(attachment, "load_a1_isotonic_artifact", lambda **kwargs: None)
    monkeypatch.setattr(attachment, "dominant_probability", lambda ms_dict: 0.42)
    monkeypatch.setattr(attachment, "apply_a1_v2_calibration_to_raw_probability", lambda **kwargs: (None, None))
    ms_dict = {"primary_horizon": "5c", "dominant_prob": 0.42}

    attachment.attach_a1_isotonic_calibration_to_ms_dict(ms_dict, ticker="SPY")

    assert ms_dict["a1_calibrated_probability"] is None
    assert ms_dict["a1_calibrated_probability_lineage_id"] is None


def test_attachment_sets_none_when_dominant_probability_returns_none(monkeypatch):
    from v2_decision import a1_isotonic_calibration_attachment as attachment

    monkeypatch.setattr(attachment, "load_a1_isotonic_artifact", lambda **kwargs: {"artifact": True})
    monkeypatch.setattr(attachment, "dominant_probability", lambda ms_dict: None)
    monkeypatch.setattr(attachment, "apply_a1_v2_calibration_to_raw_probability", lambda **kwargs: (None, None))
    ms_dict = {"primary_horizon": "5c"}

    attachment.attach_a1_isotonic_calibration_to_ms_dict(ms_dict, ticker="SPY")

    assert ms_dict["a1_calibrated_probability"] is None
    assert ms_dict["a1_calibrated_probability_lineage_id"] is None


def test_attachment_sets_none_when_runtime_apply_returns_none_none(monkeypatch):
    from v2_decision import a1_isotonic_calibration_attachment as attachment

    monkeypatch.setattr(attachment, "load_a1_isotonic_artifact", lambda **kwargs: {"artifact": True})
    monkeypatch.setattr(attachment, "dominant_probability", lambda ms_dict: 0.42)
    monkeypatch.setattr(attachment, "apply_a1_v2_calibration_to_raw_probability", lambda **kwargs: (None, None))
    ms_dict = {"primary_horizon": "5c", "dominant_prob": 0.42}

    attachment.attach_a1_isotonic_calibration_to_ms_dict(ms_dict, ticker="SPY")

    assert ms_dict["a1_calibrated_probability"] is None
    assert ms_dict["a1_calibrated_probability_lineage_id"] is None


def test_attachment_sets_none_when_ticker_empty(monkeypatch):
    from v2_decision import a1_isotonic_calibration_attachment as attachment

    calls = []
    monkeypatch.setattr(attachment, "load_a1_isotonic_artifact", lambda **kwargs: calls.append(kwargs))
    ms_dict = {"primary_horizon": "5c"}

    attachment.attach_a1_isotonic_calibration_to_ms_dict(ms_dict, ticker="")

    assert calls == []
    assert ms_dict["a1_calibrated_probability"] is None
    assert ms_dict["a1_calibrated_probability_lineage_id"] is None


def test_attachment_sets_none_when_primary_horizon_missing(monkeypatch):
    from v2_decision import a1_isotonic_calibration_attachment as attachment

    calls = []
    monkeypatch.setattr(attachment, "load_a1_isotonic_artifact", lambda **kwargs: calls.append(kwargs))
    ms_dict = {}

    attachment.attach_a1_isotonic_calibration_to_ms_dict(ms_dict, ticker="SPY")

    assert calls == []
    assert ms_dict["a1_calibrated_probability"] is None
    assert ms_dict["a1_calibrated_probability_lineage_id"] is None


def test_attachment_calls_isotonic_loader_with_correct_ticker_and_horizon(monkeypatch):
    from v2_decision import a1_isotonic_calibration_attachment as attachment

    calls = []

    def fake_loader(**kwargs):
        calls.append(kwargs)
        return {"artifact": True}

    monkeypatch.setattr(attachment, "load_a1_isotonic_artifact", fake_loader)
    monkeypatch.setattr(attachment, "dominant_probability", lambda ms_dict: 0.42)
    monkeypatch.setattr(
        attachment,
        "apply_a1_v2_calibration_to_raw_probability",
        lambda **kwargs: (0.51, "cal-test-run:hash"),
    )
    ms_dict = {"primary_horizon": " 5C "}

    attachment.attach_a1_isotonic_calibration_to_ms_dict(ms_dict, ticker="SPY")

    assert calls == [{"ticker": "SPY", "horizon": "5c"}]


def test_attachment_calls_runtime_apply_with_artifact_and_raw_probability(monkeypatch):
    from v2_decision import a1_isotonic_calibration_attachment as attachment

    artifact = {"artifact": True}
    calls = []
    monkeypatch.setattr(attachment, "load_a1_isotonic_artifact", lambda **kwargs: artifact)
    monkeypatch.setattr(attachment, "dominant_probability", lambda ms_dict: 0.42)

    def fake_apply(**kwargs):
        calls.append(kwargs)
        return 0.51, "cal-test-run:hash"

    monkeypatch.setattr(attachment, "apply_a1_v2_calibration_to_raw_probability", fake_apply)
    ms_dict = {"primary_horizon": "5c", "dominant_prob": 0.42}

    attachment.attach_a1_isotonic_calibration_to_ms_dict(ms_dict, ticker="SPY")

    assert calls == [{"isotonic_artifact": artifact, "raw_probability": 0.42}]


def test_attachment_does_not_mutate_artifact_or_raw_probability_inputs(monkeypatch):
    from v2_decision import a1_isotonic_calibration_attachment as attachment

    artifact = {"calibration_run_id": "cal-test-run", "model": {"x_thresholds": [0.0, 1.0]}}
    artifact_before = deepcopy(artifact)
    raw_probability = 0.42
    monkeypatch.setattr(attachment, "load_a1_isotonic_artifact", lambda **kwargs: artifact)
    monkeypatch.setattr(attachment, "dominant_probability", lambda ms_dict: raw_probability)
    monkeypatch.setattr(
        attachment,
        "apply_a1_v2_calibration_to_raw_probability",
        lambda **kwargs: (0.51, "cal-test-run:hash"),
    )
    ms_dict = {"primary_horizon": "5c", "dominant_prob": raw_probability}

    attachment.attach_a1_isotonic_calibration_to_ms_dict(ms_dict, ticker="SPY")

    assert artifact == artifact_before
    assert raw_probability == 0.42


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
