"""v2_decision.a1_conformal_artifact_attachment must attach the loaded conformal
artifact to the decision only when the loader actually returns one -- attaching a
stale/absent artifact would silently misrepresent the decision's calibration
lineage."""
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
    # RC-REHAB-1 (thirty-fifth/-seventh slices): both call sites moved with the v2 build
    # (server_state_decision.py) and the publish (server_state_publish.py).
    for mod in ("server_state_decision.py", "server_state_publish.py"):
        source = Path(mod).read_text(encoding="utf-8")
        assert (
            "from v2_decision.a1_conformal_artifact_attachment "
            "import attach_a1_conformal_artifact_to_ms_dict"
        ) in source


def test_server_logging_path_invokes_attachment_between_stamp_and_build():
    """RC-REHAB-1 (Phase 4, _fetch_state decomposition, nineteenth slice): the
    original end-of-window marker ("from calibration.v2_live_logging") lived
    inside _post_publish_persistence_tail, now promoted to a module-level
    function defined BEFORE _fetch_state -- an unqualified source.index() for
    it now finds an EARLIER position than the window's start, producing an
    invalid (empty) slice. This phase itself (stamp/attach/build) was not
    touched by that promotion; re-bounded using the identity-anchor banner
    that still immediately follows it inside _fetch_state's own body."""
    # RC-REHAB-1 (thirty-fifth slice): the v2 logging build is _v2_decision_for_state in
    # server_state_decision.py; the window is that function's own source.
    import inspect

    import server_state_decision

    assert "_v2_decision_for_state(" in _server_source()
    window = inspect.getsource(server_state_decision._v2_decision_for_state)

    stamp_idx = window.index("stamp_decision_bundle(logging_ms_dict)")
    attach_idx = window.index("attach_a1_conformal_artifact_to_ms_dict(logging_ms_dict, ticker=ticker)")
    build_idx = window.index("build_module_a_a1_decision(logging_ms_dict)")

    assert stamp_idx < attach_idx < build_idx


def test_server_response_path_invokes_attachment_before_v2_decision_build():
    source = _server_source()
    # RC-REHAB-1 (thirty-seventh slice): finalize -> a1 attachments -> v2 decision -> live-plane
    # merge run inside server_state_publish._finalize_and_publish_state, in that order.
    import inspect

    import server_state_publish as _pub

    assert "_finalize_and_publish_state(" in source
    window = inspect.getsource(_pub._finalize_and_publish_state)
    build_anchor = 'ms_dict["v2_decision"] = v2_decision or build_module_a_a1_decision(ms_dict)'
    assert "_srv._finalize_production_decision(ms_dict, decision_route)" in inspect.getsource(_pub._finalize_decision)
    stamp_idx = window.index("_finalize_decision(ms_dict, ms,")
    attach_idx = window.index("attach_a1_conformal_artifact_to_ms_dict(ms_dict, ticker=ticker)")
    build_idx = window.index(build_anchor)

    assert stamp_idx < attach_idx < build_idx


def _server_source() -> str:
    return Path("server.py").read_text(encoding="utf-8")
