"""Negative controls for the research-before-act continuum (RC-205).

RC-470: the plus_player catalog checks (plus_player_law, plus_player_cursor_hooks) are
retired - governance/retired_checks.md - and their three negative controls left with
them. The two research controls below cover research_before_act, which stays ENFORCED.
"""
from __future__ import annotations

import json
import time
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent

# RC-368: declared direct owner — this suite drives research_violation in the audit tool.
TURN_AUDIT_OWNS = [
    "tools/turn_self_audit.py",
]


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
