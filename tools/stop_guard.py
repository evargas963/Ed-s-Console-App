"""STOP GUARD — refuses to let a turn end with work the agent itself declared unfinished (RC-72),
or with a material defect disposed of as prose (RC-498).

WHY THIS EXISTS. Every other lock in this repo fires on an ACTION: a tool call, a commit. The
agent's most damaging failure mode is the opposite — the ABSENCE of an action. It writes a tidy
summary ending in "next: X" and stops. No PreToolUse hook can catch that, because no tool is
called. The operator observed it repeatedly on 2026-07-27, including immediately after the agent
wrote "I'm not stopping here. Building the Stop hook now." and then stopped.

This runs as a Stop hook. Exit 2 BLOCKS the stop and feeds stderr back to the agent, which then
keeps working instead of ending the turn.

RC-72 (2026-07-27) — the founding duty, unchanged: a row opened TODAY that still says the work
is unfinished blocks the turn.

RC-498 (operator, FIND_FIX_EXECUTION_LATCH_V1) — what RC-72 could not reach. MEASURED on
334c5daf against this exact guard, driving the real Stop roster:

  * a defect described only in PROSE, with no row ever created ............ PASSED
  * a row whose fix cell was relabelled "follow-up / out of scope" ........ PASSED
  * a row whose fix cell was relabelled "pre-existing" .................... PASSED

RC-72 keyed entirely on a marker vocabulary the agent writes about ITSELF, so the cheapest way
past it was to write different words. AGENTS.md already forbids exactly those words — "a material
defect is never disposed as queued / logged / TODO / follow-up / pre-existing / out-of-scope" —
so the fix is not a longer synonym list (the old docstring warned against precisely that, and it
was right) but a change of QUESTION: an OPEN row opened today must be FINISHED or OBJECTIVELY
BLOCKED, or it blocks. Silence is no longer a pass, and silence is what made the rename work.

ON THE RETRY FLAG. RC-72 returned 0 whenever `stop_hook_active` was set, reasoning that a guard
which cannot be satisfied is a hang. That is true, and it also meant the entire control was
clearable by stopping twice. This guard follows the precedent `operator_law_guard` already sets
at this same seam: the flag proves only that the host is retrying a blocked Stop and grants no
authorization — the policy is evaluated again. That is safe HERE because every blocking state
has a named escape the agent can always reach, and `tests/test_stop_guard_v1.py` PROVES each one
clears the block rather than asserting satisfiability in a comment:

    finish it        -> set the row CLOSED with measured evidence
    genuinely stuck  -> record BLOCKED_ON_* plus the event that clears it
    operator says so -> the operator's own halt word ends the turn immediately

The retired find-it-fix-it framework (RC-472/473) re-blocked on this flag too and DID hang,
because a missing or malformed ledger was itself an offender. This module inverts that: an
unreadable ledger yields no rows, so the clause abstains. A control that cannot be satisfied is
not a control.

Contract:
  * BLOCKS when a row opened TODAY is OPEN and neither finished nor objectively blocked.
  * BLOCKS when production files are modified in the working tree and NO row was opened today —
    the outcome-side companion to the RC-498 PreToolUse latch, which no choice of shell command
    form can evade (Phase 3: a defect surfaced mid-mission cannot vanish when the turn ends).
  * PASSES on the operator's explicit halt word, read from the operator's OWN message.
  * Does NOT block on rows opened on earlier days: those are a dated backlog, and
    `check_root_cause_log` already fails a commit on an overdue one. This guard is about work
    started and abandoned WITHIN a session.
  * No env kill-switch: ED_STOP_GUARD cannot disable this control (RC-450).
  * HONEST LIMIT: this reads the LEDGER and the WORKING TREE, not the agent's prose. A defect
    that is never written down and never touches a tracked production file is still invisible
    here. That gap is why the PreToolUse latch demands the row BEFORE the mutation — between
    them, work that reaches production code cannot end undocumented.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
#: Runs as a bare script from the hook, so the repo root is not importable by default and
#: `from tools...` would fail — which this guard correctly reports as a violation rather than a
#: pass. Put the root on the path so the audit can actually run.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import tools.mission_latch as mission_latch  # noqa: E402

#: RC-72's marker vocabulary now lives beside the ledger parser, so the repository holds ONE
#: list and ONE `| RC-` scan. Re-exported because this name is the RC-72 seam.
UNFINISHED_MARKERS = mission_latch.UNFINISHED_MARKERS


def unfinished_rows_opened_today(today: str | None = None) -> list[tuple[str, str]]:
    """(rc_id, marker) for rows opened `today` that are OPEN and self-declared unfinished.

    RC-72's original predicate, preserved exactly. It is a STRICT SUBSET of what `main()` now
    blocks on, and is kept as a named function because it is the founding duty and its negative
    controls attack it directly.
    """
    out: list[tuple[str, str]] = []
    for row in mission_latch.same_day_rows(today):
        if row.status != "OPEN":
            continue
        hit = next((m for m in UNFINISHED_MARKERS if m in row.fix.upper()), None)
        if hit:
            out.append((row.rc_id, hit))
    return out


# RC-470 (operator right-sizing): two more turn-end duties removed, equivalents named:
#   * faucet provenance (RC-73) - the SAME data_faucet_audit.run is enforced at COMMIT
#     inside check_institutional_correctness (the pre-commit faucet lock), so a faucet
#     violation still cannot land; it just no longer re-runs at every turn end.
#   * freshness (RC-94) - HTTP probes with timeout=30 against a console that is often
#     deliberately stopped were the bulk of this guard's measured 4.6s/turn cost.
# RC-470: close_contract_blockers removed with its check (five_why_recursive_lock,
# retired - governance/retired_checks.md). The surviving substance - a why-chain and
# measured evidence on every CLOSED row - is enforced by check_root_cause_log and
# closed_rows_ship_their_code at commit and in CI.
# 2026-08-24 teardown: the FIND IT -> FIX IT ledger clause (RC-472/473,
# governance/active_defects.json + active_defect_offenders) was retired with its
# framework. RC-498 does NOT resurrect it: no new state file, no offender registry and
# no fail-closed-on-missing-ledger clause - only the ledger the repo already keeps,
# read through tools/mission_latch.py.


def _explain(blockers: list[tuple[str, str]], dirty: list[str], retry: bool) -> str:
    lines = ["BLOCKED: the turn is ending with a material defect undischarged "
             "(RC-72 / RC-498).\n\n"]
    if blockers:
        lines.append("Root-cause rows opened TODAY that are not finished:\n")
        lines += [f"    {rc} — {why}\n" for rc, why in blockers]
        lines.append("\n")
    if dirty:
        lines.append(
            "Production files are modified in the working tree and NO row was opened today:\n")
        lines += [f"    {p}\n" for p in dirty[:12]]
        if len(dirty) > 12:
            lines.append(f"    ... and {len(dirty) - 12} more\n")
        lines.append("\n")
    lines.append(
        'AGENTS.md: "Find something broken -> fix it. Discovery creates the obligation to\n'
        "remediate through the full blast radius in the active session. A material defect is\n"
        'never disposed as queued / logged / TODO / follow-up / pre-existing / out-of-scope."\n\n'
        "Do ONE of these, then continue:\n"
        "  1. FINISH IT — drive the fix, then set the row CLOSED with measured evidence and\n"
        "     END-TO-END scope. This is the expected outcome.\n"
        f"  2. OBJECTIVELY BLOCKED — set the row's STATUS cell to {mission_latch.BLOCKED_STATUS}\n"
        "     and give it a due date that has not passed. Say in the fix cell what is awaited\n"
        "     and what clears it, so a human can judge the claim. A blocked row still goes\n"
        "     overdue, and it no longer authorizes production work — being blocked and being\n"
        "     licensed to proceed are contradictory. Preference, scope convenience and running\n"
        "     out of runway are not blockers.\n"
        "  3. If production is dirty with no mission, open ONE row describing the work.\n\n"
        'Renaming the work "follow-up", "out of scope", "pre-existing" or "next mission" does\n'
        "not clear this — those are the exact disposals the law names.\n")
    if retry:
        lines.append(
            "\nNOTE: stop_hook_active was set. That flag says the host is retrying a blocked\n"
            "Stop; it is not an authorization, so the policy was evaluated again. Every escape\n"
            "above remains available, and editing governance/ is never gated.\n")
    return "".join(lines)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}                  # unreadable input must NOT wave the checks through

    # Operator halt authority (AGENTS.md: STOP / PAUSE / HANG IT UP / DO NOT CONTINUE), read
    # from the operator's OWN message. The agent authors assistant records, so reading the
    # assistant side would let the subject grant itself the escape.
    if mission_latch.operator_halt_instruction(payload.get("transcript_path") or ""):
        return 0

    # The ledger that governs this turn belongs to the checkout the SESSION ran in. When work
    # happens in a linked worktree, that is not the tree this guard file sits in — MEASURED:
    # `| RC-498 ` resolved 0 times in the production checkout the hook read and 1 time in the
    # worktree that held the work, so an honest same-day row read as a broken promise.
    repo = str(payload.get("cwd") or "") or None
    blockers = mission_latch.mission_blockers(repo=repo)
    # Outcome-side companion to the PreToolUse latch, asked ONLY when there is no mission at
    # all: once a row exists, the row's own state is the question and a dirty tree is simply
    # the work in progress.
    dirty = ([] if mission_latch.has_active_mission(repo=repo)
             else mission_latch.dirty_production_files(Path(repo) if repo else None))
    if not blockers and not dirty:
        return 0

    sys.stderr.write(_explain(blockers, dirty, payload.get("stop_hook_active") is True))
    return 2                          # exit 2 = block the stop, agent keeps working


if __name__ == "__main__":
    sys.exit(main())
