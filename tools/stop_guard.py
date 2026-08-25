"""STOP GUARD — refuses to let a turn end with work the agent itself declared unfinished (RC-72).

WHY THIS EXISTS. Every other lock in this repo fires on an ACTION: a tool call, a commit. The
agent's most damaging failure mode is the opposite — the ABSENCE of an action. It writes a tidy
summary ending in "next: X" and stops. No PreToolUse hook can catch that, because no tool is
called. The operator observed it repeatedly on 2026-07-27, including immediately after the agent
wrote "I'm not stopping here. Building the Stop hook now." and then stopped.

This runs as a Stop hook. Exit 2 BLOCKS the stop and feeds stderr back to the agent, which then
keeps working instead of ending the turn.

Contract:
  * BLOCKS when a root-cause row opened TODAY is still `OPEN` and its fix cell says the work is
    unfinished ("IN PROGRESS" / "VERIFICATION PENDING" / "NOT FIXED").
  * Does NOT block on rows opened on earlier days: those are a real backlog with due dates, and
    `check_root_cause_log` already fails a commit on an overdue one. This guard is about work
    started and abandoned WITHIN a session.
  * Respects `stop_hook_active`: if the guard already blocked once and the agent is still going,
    it does not block again. Without this the turn could never end — a guard that cannot be
    satisfied is a hang, not a control.
  * No env kill-switch: ED_STOP_GUARD cannot disable this control (RC-450).
  * HONEST LIMIT: this guard detects only the marker vocabulary the agent itself writes
    into a fix cell; unfinished work described in prose that avoids these exact substrings
    passes. That gap is inherent — prose cannot be machine-proven finished or unfinished —
    and the commit-time ledger checks (five-why depth, measured evidence on CLOSED rows,
    due dates on OPEN rows) are the backstop. Do not grow this list beyond observed
    variants: a longer synonym list is the same shape check with more false confidence.
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
#: Runs as a bare script from the hook, so the repo root is not importable by default and
#: `from tools...` would fail — which this guard correctly reports as a violation rather than a
#: pass. Put the root on the path so the audit can actually run.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
RC_LOG = REPO / "governance" / "root_cause_log.md"

#: Phrases the agent itself writes into a fix cell to mean "not done yet".
UNFINISHED_MARKERS = ("IN PROGRESS", "VERIFICATION PENDING", "PENDING VERIFICATION",
                      "NOT FIXED", "PARTIALLY FIXED", "NOT DONE")


def unfinished_rows_opened_today(today: str | None = None) -> list[tuple[str, str]]:
    """(rc_id, reason) for rows opened `today` that are OPEN and self-declared unfinished."""
    today = today or datetime.date.today().isoformat()
    try:
        lines = RC_LOG.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    out: list[tuple[str, str]] = []
    for line in lines:
        if not line.startswith("| RC-"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 7:
            continue
        rc_id, status, opened, fix = cells[0], cells[1], cells[2], cells[6]
        if status != "OPEN" or opened != today:
            continue
        hit = next((m for m in UNFINISHED_MARKERS if m in fix.upper()), None)
        if hit:
            out.append((rc_id, hit))
    return out


# RC-470 (operator right-sizing): two more turn-end duties removed, equivalents named:
#   * faucet provenance (RC-73) - the SAME data_faucet_audit.run is enforced at COMMIT
#     inside check_institutional_correctness (the pre-commit faucet lock), so a faucet
#     violation still cannot land; it just no longer re-runs at every turn end.
#   * freshness (RC-94) - HTTP probes with timeout=30 against a console that is often
#     deliberately stopped were the bulk of this guard's measured 4.6s/turn cost.
#     Freshness surveillance belongs to the console's own sentinels
#     (IDLE_SENTINEL_FRESHNESS_V1) and the reporting tools (repo_exposure_audit,
#     agent_error_report), which render unreachability/staleness as findings.
# What stays is the founding duty, RC-72: a turn may not end while a row the agent
# opened TODAY still says the work is unfinished.
# RC-470: close_contract_blockers removed with its check (five_why_recursive_lock,
# retired - governance/retired_checks.md). The surviving substance - a why-chain and
# measured evidence on every CLOSED row - is enforced by check_root_cause_log and
# closed_rows_ship_their_code at commit and in CI.
# 2026-08-24 teardown: the FIND IT → FIX IT ledger clause (RC-472/473,
# governance/active_defects.json + active_defect_offenders) was retired with its
# framework — the principle survives as an AGENTS.md instruction; this guard is
# RC-72 only.


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}                  # unreadable input must NOT wave the RC-72 check through
    if payload.get("stop_hook_active") is True:
        return 0                      # already blocked once; a guard that cannot end is a hang

    rows = unfinished_rows_opened_today()
    if not rows:
        return 0

    listed = "\n".join(f"    {rc} — fix cell still says {why!r}" for rc, why in rows)
    sys.stderr.write(
        "BLOCKED: you are stopping with work YOU declared unfinished today (RC-72).\n\n"
        f"{listed}\n\n"
        "You opened these root causes this session and their fix cells still say the work is not "
        "done. Ending the turn now leaves the operator holding a half-built change and a summary "
        "that reads like progress.\n\n"
        "Do ONE of these, then continue:\n"
        "  1. Finish the work and update the fix cell with MEASURED evidence + END-TO-END scope,\n"
        "     then set the row to CLOSED.\n"
        "  2. If it genuinely cannot be finished now, say so IN THE ROW: replace the unfinished\n"
        "     marker with the concrete blocker and what unblocks it, and keep the row OPEN with a\n"
        "     real due date.\n\n"
        "Do not summarise and stop. A summary is not a deliverable.\n"
    )
    return 2                          # exit 2 = block the stop, agent keeps working


if __name__ == "__main__":
    sys.exit(main())
