"""Negative controls for RC-205 Ultimate plus-player mechanical lock."""
from __future__ import annotations

import json
import time
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent

# RC-368: declared direct owner — this suite drives research_violation in the audit tool.
TURN_AUDIT_OWNS = [
    "tools/turn_self_audit.py",
]


def test_plus_player_law_blocks_incomplete_catalog():
    from tools.check_institutional_correctness import plus_player_law_violations

    bad = {"version": 1, "attributes": [{"id": "RES-01", "pillar": "research",
                                         "enforcement": "enforced", "enforcer": "research_before_act",
                                         "soft_reason": None}]}
    v = plus_player_law_violations(bad)
    assert v, "incomplete catalog must BLOCK"
    assert any("missing CORE" in x or "soft_partial forbidden" in x for x in v)


def test_plus_player_law_live_catalog_clean():
    from tools.check_institutional_correctness import plus_player_law_violations

    assert plus_player_law_violations() == []


def test_plus_player_cursor_hooks_blocks_missing():
    from tools.check_institutional_correctness import plus_player_cursor_hooks_violations

    assert plus_player_cursor_hooks_violations("")
    assert plus_player_cursor_hooks_violations('{"hooks":{}}')
    assert plus_player_cursor_hooks_violations() == []


def test_research_violation_blocks_unresolved_path():
    from tools.turn_self_audit import research_violation

    assert research_violation(
        "I thought about static/does_not_exist_zz99.html carefully enough",
        ["server.py"],
    )
    assert research_violation(
        "static/chart.html clampView is the reference for overscroll semantics",
        ["static/exposure.html"],
    ) is None


def test_research_before_act_rejects_nonresolving_research(tmp_path):
    from tools.check_institutional_correctness import research_before_act_violations

    log = tmp_path / "a.jsonl"
    log.write_text(json.dumps({
        "ts_utc": time.time(),
        "changed": ["server.py"],
        "research": "definitely a vibe with .py mentioned but no real file",
    }) + "\n", encoding="utf-8")
    assert research_before_act_violations(["server.py"], log)

    log.write_text(json.dumps({
        "ts_utc": time.time(),
        "changed": ["server.py"],
        "research": "static/chart.html clampView — institutional reference for view clamp",
    }) + "\n", encoding="utf-8")
    assert research_before_act_violations(["server.py"], log) == []
