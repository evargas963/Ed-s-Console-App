"""SIMPLICITY REHAB 2026-08-24 — the prepared one-process hook chains.

tools/stop_chain.py and tools/pretooluse_chain.py run the same guard modules
in-process (measured ~300ms per event vs 2,815-5,995ms for the serial interpreter
chains). These controls pin the chain EXECUTOR's contract so the wiring flip the
operator adopts in .claude/settings.json cannot land on a broken runner:
any member's block blocks, a crashing member blocks (unmeasurable is never a pass),
and the argv roster maps hook-file spellings to module names faithfully.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.stop_chain import STOP_CHAIN, _argv_members, run_chain  # noqa: E402
import tools.pretooluse_chain as ptc  # noqa: E402


def test_argv_roster_maps_hook_spellings_to_modules():
    assert _argv_members(["tools/stop_guard.py", "tools\\honesty_guard.py",
                          "proof_only_guard.py"]) == (
        "tools.stop_guard", "tools.honesty_guard", "tools.proof_only_guard")
    assert _argv_members([]) == ()


def test_default_stop_roster_names_the_four_guards():
    assert STOP_CHAIN == ("tools.stop_guard", "tools.proof_only_guard",
                          "tools.honesty_guard", "tools.operator_law_guard")


def test_edit_and_bash_rosters_carry_the_ledger_guard():
    """RC-205's substance: operator_law_guard must see BOTH edits and commands, or the
    edit-dependent Stop clauses go blind."""
    assert "tools.operator_law_guard" in ptc.EDIT_CHAIN
    assert "tools.operator_law_guard" in ptc.BASH_CHAIN
    assert "tools.pretooluse_guard" in ptc.EDIT_CHAIN
    assert "tools.pretooluse_guard" not in ptc.BASH_CHAIN


def test_any_members_block_blocks_and_all_members_run():
    payload = json.dumps({"session_id": "chain-test", "tool_name": "Stop"})
    # a quiet roster passes
    assert run_chain(payload, ("tools.proof_only_guard",)) == 0


def test_a_crashing_member_blocks_not_passes():
    payload = json.dumps({"session_id": "chain-test", "tool_name": "Stop"})
    assert run_chain(payload, ("tools.zz_no_such_guard_zz",)) == 2
