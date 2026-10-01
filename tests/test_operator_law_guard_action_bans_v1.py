from __future__ import annotations

import json
from pathlib import Path


def test_operator_law_guard_wired_for_edit_tools():
    """RC-205: the Edit/Write branch of operator_law_guard was DEAD CODE because
    .claude/settings.json only routed Bash|PowerShell to it — the ledger never received
    'edit' entries and the RC-190/RC-203 Stop clauses were blind on edit-only turns
    (Cursor's lock research). This pins the wiring so it cannot silently unwire."""
    settings = json.loads((Path(__file__).resolve().parent.parent / ".claude" / "settings.json")
                          .read_text(encoding="utf-8"))
    edit_matchers = [m for m in settings["hooks"]["PreToolUse"]
                     if "Edit" in (m.get("matcher") or "")]
    assert edit_matchers, "no PreToolUse matcher covers Edit tools at all"
    cmds = "\n".join(h["command"] for m in edit_matchers for h in m["hooks"])
    assert "operator_law_guard" in cmds, (
        "operator_law_guard is not wired for Edit/Write — its ledger cannot see production "
        "edits and every edit-dependent Stop clause is blind (RC-205)")
    # BEDROCK 2026-09-06: pretooluse_guard is off the roster by design (its content gates and
    # the mutation-side latch are removed); an inert rostered guard is the E-05/E-07 class.
    assert "pretooluse_guard" not in cmds
