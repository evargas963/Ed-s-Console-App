from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_tier_c_attaches_v2_decision_after_decision_bundle_stamp():
    server_source = (ROOT / "server.py").read_text(encoding="utf-8")

    stamp_idx = server_source.index("stamp_decision_bundle(ms_dict)")
    attach_idx = server_source.index('ms_dict["v2_decision"] = build_module_a_a1_decision(ms_dict)')
    merge_idx = server_source.index("_lmp.merge_into_state(ms_dict, ticker)", attach_idx)

    assert stamp_idx < attach_idx < merge_idx


def test_tier_c_imports_module_a_a1_adapter():
    server_source = (ROOT / "server.py").read_text(encoding="utf-8")

    assert "from v2_decision import build_module_a_a1_decision" in server_source


def test_v2_ui_card_is_read_only_and_draft_labeled():
    ui_source = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

    assert 'id="v2-pilot-card"' in ui_source
    assert "renderV2PilotDecision(d)" in ui_source
    assert "Draft v2 view only. Does not replace the locked v1.1 decision policy." in ui_source
    assert "advisory_non_authoritative" in ui_source
    assert '<button' not in _v2_card_markup(ui_source)


def _v2_card_markup(ui_source: str) -> str:
    start = ui_source.index('id="v2-pilot-card"')
    end = ui_source.index('<div class="exec-grid">', start)
    return ui_source[start:end]

