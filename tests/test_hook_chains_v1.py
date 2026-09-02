"""SIMPLICITY REHAB 2026-08-24 — the prepared one-process hook chains.

tools/stop_chain.py and tools/pretooluse_chain.py run the same guard modules
in-process (measured ~300ms per event vs 2,815-5,995ms for the serial interpreter
chains). These controls pin the chain EXECUTOR's contract so the wiring flip the
operator adopts in .claude/settings.json cannot land on a broken runner:
any member's block blocks, a crashing member blocks (unmeasurable is never a pass),
and the argv roster maps hook-file spellings to module names faithfully.

PER-MEMBER BLOCKING EQUIVALENCE (operator-named hole, 2026-08-24): the controls above
proved argv mapping, rosters, a quiet pass, and crash-blocks — NOT that when an
individual member would block, the chain blocks with that member's stderr. The
``*_member_block_equivalence`` tests below drive EVERY member of the Stop roster and of
the PreToolUse rosters to a real standalone exit-2 block, then run the chain executor
as a subprocess on the IDENTICAL stdin payload and assert equal exit codes AND the
member's distinctive stderr marker in the chain output. One further control proves the
chain keeps running every member after an early block (two members' markers co-appear).
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.stop_chain import STOP_CHAIN, _argv_members, run_chain  # noqa: E402
import tools.operator_law_guard as olg  # noqa: E402
import tools.pretooluse_chain as ptc  # noqa: E402


def test_argv_roster_maps_hook_spellings_to_modules():
    assert _argv_members(["tools/stop_guard.py", "tools\\honesty_guard.py",
                          "operator_law_guard.py"]) == (
        "tools.stop_guard", "tools.honesty_guard", "tools.operator_law_guard")
    assert _argv_members([]) == ()


def test_default_stop_roster_names_the_three_guards():
    """RC-504: proof_only_guard was removed as Stop authority and deleted."""
    assert STOP_CHAIN == ("tools.stop_guard", "tools.honesty_guard",
                          "tools.operator_law_guard")


def test_edit_and_bash_rosters_carry_the_ledger_guard():
    """RC-205's substance: operator_law_guard must see BOTH edits and commands, or the
    edit-dependent Stop clauses go blind."""
    assert "tools.operator_law_guard" in ptc.EDIT_CHAIN
    assert "tools.operator_law_guard" in ptc.BASH_CHAIN
    assert "tools.pretooluse_guard" in ptc.EDIT_CHAIN
    assert "tools.pretooluse_guard" not in ptc.BASH_CHAIN


def test_any_members_block_blocks_and_all_members_run(tmp_path):
    # a quiet roster passes — with a readable, benign transcript (audit round 2:
    # a MISSING transcript_path now fails closed rather than passing silently)
    tp = tmp_path / "quiet.jsonl"
    tp.write_text(
        json.dumps({"type": "user", "message": {"role": "user",
                                                "content": [{"type": "text", "text": "hi"}]}})
        + "\n"
        + json.dumps({"type": "assistant",
                      "message": {"role": "assistant",
                                  "content": [{"type": "text", "text": "reading the file now."}]}})
        + "\n", encoding="utf-8")
    payload = json.dumps({"session_id": "chain-test", "tool_name": "Stop",
                          "transcript_path": str(tp)})
    assert run_chain(payload, ("tools.honesty_guard",)) == 0


def test_a_crashing_member_blocks_not_passes():
    payload = json.dumps({"session_id": "chain-test", "tool_name": "Stop"})
    assert run_chain(payload, ("tools.zz_no_such_guard_zz",)) == 2


# ---------------------------------------- per-member blocking equivalence --

_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def _pipe(argv: list[str], raw_payload: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=str(cwd), input=raw_payload, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", env=_ENV,
                          timeout=120)


def _pair(payload: dict, guard_rel: str, root: Path = ROOT
          ) -> tuple[subprocess.CompletedProcess[str], subprocess.CompletedProcess[str]]:
    """The member standalone AND the chain, both subprocesses, IDENTICAL stdin bytes."""
    raw = json.dumps(payload)
    standalone = _pipe([sys.executable, str(root / guard_rel)], raw, root)
    chain = _pipe([sys.executable, str(root / "tools" / "stop_chain.py"), guard_rel],
                  raw, root)
    return standalone, chain


def _assert_blocking_pair(standalone, chain, markers: tuple[str, ...]) -> None:
    assert standalone.returncode == 2, (standalone.stderr, standalone.stdout)
    assert chain.returncode == standalone.returncode, (chain.stderr, chain.stdout)
    for marker in markers:
        assert marker in standalone.stderr, standalone.stderr
        assert marker in chain.stderr, chain.stderr


def _mini_stop_repo(tmp_path: Path) -> Path:
    """A hermetic checkout carrying the REAL executor and the REAL stop guard.

    stop_guard resolves its ledger from its own file location (REPO/governance/
    root_cause_log.md), so planting a same-day unfinished row without touching the
    tracked governance log requires giving the guard a repo of its own. Executor and
    guard are byte-identical copies of this repo's files (asserted below), so the
    equivalence proven is about THIS repo's code; the block under test is EXACTLY the
    planted RC-72 row and nothing else (the guard's only input is the ledger since the
    2026-08-24 find-it-fix-it teardown).
    """
    root = tmp_path / "mini"
    (root / "tools").mkdir(parents=True)
    (root / "governance").mkdir()
    # mission_latch.py joins the copy list because RC-498 moved the ledger parser there:
    # stop_guard imports it at module level, and the chain treats a missing member as a
    # crash-block — which would make this equivalence pass for the wrong reason.
    for name in ("__init__.py", "stop_chain.py", "stop_guard.py", "mission_latch.py"):
        shutil.copy(ROOT / "tools" / name, root / "tools" / name)
        assert (root / "tools" / name).read_bytes() == (ROOT / "tools" / name).read_bytes()
    today = datetime.date.today().isoformat()
    (root / "governance" / "root_cause_log.md").write_text(
        "| id | status | opened | due | defect | why | fix |\n"
        f"| RC-9901 | OPEN | {today} | 2099-01-01 | d | w | IN PROGRESS: planted for the "
        "chain-equivalence control |\n",
        encoding="utf-8",
    )
    return root


def test_stop_guard_member_block_equivalence(tmp_path):
    """RC-72 block: a row opened TODAY still IN PROGRESS blocks standalone and in-chain."""
    root = _mini_stop_repo(tmp_path)
    payload = {"session_id": "eqv-stop-guard", "stop_hook_active": False}
    standalone, chain = _pair(payload, "tools/stop_guard.py", root=root)
    # RC-498 widened the banner to "(RC-72 / RC-498)" — the same RC-72 block, now naming the
    # clause that generalised it. The marker drops the parentheses and asserts the same thing.
    _assert_blocking_pair(standalone, chain, ("RC-72", "RC-9901"))


# RC-504: test_proof_only_guard_member_block_equivalence was REMOVED with the guard. It proved
# standalone/in-chain equivalence for a member that no longer exists; the same property is
# still proven for every SURVIVING member by the stop_guard and honesty_guard equivalence
# tests above and below.


def test_the_retired_prose_oracle_is_gone_from_every_live_surface(tmp_path):
    """RC-504 NEGATIVE CONTROL. proof_only_guard decided truth and completion by matching
    words in prose, and that was experimentally confirmed to false-block: the sentence
    "rather than tell you again from memory" — a DISCLAIMER of memory written immediately
    before running commands — was flagged as citing memory as evidence. A substring cannot
    tell an assertion from a denial.

    This asserts the removal is COMPLETE and, critically, that no successor took its place:
    no vocabulary list, no regex escape, no replacement guard."""
    assert not (ROOT / "tools" / "proof_only_guard.py").exists()
    assert "proof_only_guard" not in STOP_CHAIN and "tools.proof_only_guard" not in STOP_CHAIN

    for cfg, key in ((ROOT / ".claude" / "settings.json", "Stop"),
                     (ROOT / ".cursor" / "hooks.json", "stop")):
        raw = cfg.read_text(encoding="utf-8")
        assert "proof_only_guard" not in raw, cfg.name

    # No successor: nothing new appeared on Stop to do the same job under another name.
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    stop_cmd = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
    members = {t for t in stop_cmd.split() if t.startswith("tools/") and "chain" not in t}
    assert members == {"tools/stop_guard.py", "tools/honesty_guard.py",
                       "tools/operator_law_guard.py"}, members


def test_honesty_guard_member_block_equivalence(tmp_path):
    """RC-209 block: honesty_guard on an unreadable transcript — unmeasurable never passes."""
    payload = {"transcript_path": str(tmp_path / "absent_transcript.jsonl"),
               "stop_hook_active": False}
    standalone, chain = _pair(payload, "tools/honesty_guard.py")
    _assert_blocking_pair(standalone, chain, ("BLOCKED (RC-209)",))


def test_operator_law_guard_stop_member_block_equivalence(tmp_path):
    """RC-93 Stop block: a recorded production edit with NOTHING run this turn.

    The ledger is seeded through the guard's own recorder (module seam) into its real
    per-session temp file; the entry is a legacy-shape `edit` row, which the guard
    treats as a landed change (RC-57: unmeasurable is never 'nothing happened'). The
    ledger is re-seeded to the identical single row before each subprocess, because a
    block appends a `stop_blocked` observability row.
    """
    subject = tmp_path / "subject"
    (subject / ".git").mkdir(parents=True)
    (subject / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    sid = f"eqv-oplaw-{time.time_ns()}"
    ledger = olg._ledger_path(sid)

    def seed() -> None:
        ledger.unlink(missing_ok=True)
        olg._record(sid, "edit", str(subject / "mod.py"), olg.normalize_repo(subject))

    payload = {"session_id": sid, "tool_name": "Stop", "cwd": str(subject)}
    raw = json.dumps(payload)
    try:
        seed()
        standalone = _pipe([sys.executable, str(ROOT / "tools" / "operator_law_guard.py")],
                           raw, ROOT)
        seed()
        chain = _pipe([sys.executable, str(ROOT / "tools" / "stop_chain.py"),
                       "tools/operator_law_guard.py"], raw, ROOT)
    finally:
        ledger.unlink(missing_ok=True)
    _assert_blocking_pair(standalone, chain,
                          ("BLOCKED (RC-93)", "RAN WITHOUT ERROR"))


def test_pretooluse_guard_member_block_equivalence():
    """RC-160 block: SPY-only framing written into an agent-instruction path (EDIT roster)."""
    payload = {"tool_name": "Write",
               "tool_input": {"file_path": str(ROOT / "AGENTS.md"),
                              "content": "SPY-only coverage is complete."}}
    standalone, chain = _pair(payload, "tools/pretooluse_guard.py")
    _assert_blocking_pair(standalone, chain, ("RC-160",))


def test_process_lock_guard_member_block_equivalence():
    """LOCK-2 block: bare tree-destructive git (Bash roster member), through BOTH entrypoints.

    The same payload is also driven through tools/pretooluse_chain.py with an explicit
    roster, because that is the file .claude/settings.json actually wires for
    PreToolUse — both entrypoints share run_chain, and this pins it.
    """
    payload = {"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}}
    standalone, chain = _pair(payload, "tools/process_lock_guard.py")
    _assert_blocking_pair(standalone, chain, ("RESET_GUARD", "operating process lock"))
    ptu_chain = _pipe([sys.executable, str(ROOT / "tools" / "pretooluse_chain.py"),
                       "tools/process_lock_guard.py"], json.dumps(payload), ROOT)
    assert ptu_chain.returncode == 2, ptu_chain.stderr
    assert "RESET_GUARD" in ptu_chain.stderr, ptu_chain.stderr


def test_chain_runs_all_members_even_after_an_early_block(tmp_path):
    """Two blocking members' distinctive markers CO-APPEAR: an early block skips nobody."""
    payload = json.dumps({"transcript_path": str(tmp_path / "absent_transcript.jsonl"),
                          "stop_hook_active": False})
    chain = _pipe([sys.executable, str(ROOT / "tools" / "stop_chain.py"),
                   "tools/honesty_guard.py", "tools/operator_law_guard.py"], payload, ROOT)
    assert chain.returncode == 2, chain.stderr
    assert "BLOCKED (RC-209)" in chain.stderr, chain.stderr
    assert "BLOCKED" in chain.stderr.replace("BLOCKED (RC-209)", "", 1), chain.stderr
