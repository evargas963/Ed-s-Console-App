"""STOP GUARD — refuses to let a turn end with work the agent itself declared unfinished (RC-72).

WHY THIS EXISTS. Every other lock in this repo fires on an ACTION: a tool call, a commit. The
agent's most damaging failure mode is the opposite — the ABSENCE of an action. It writes a tidy
summary ending in "next: X" and stops. No PreToolUse hook can catch that, because no tool is
called. The operator observed it repeatedly on 2026-07-27, including immediately after the agent
wrote "I'm not stopping here. Building the Stop hook now." and then stopped.

This runs as a Stop hook. Exit 2 BLOCKS the stop and feeds stderr back to the agent, which then
keeps working instead of ending the turn.

Contract:
  * BLOCKS unfinished-turn obligations from `tools/find_it_fix_it_lock.py` reading the sole
    master (`ED_CONSOLE_INSTITUTIONAL_TRUTH_AND_REMEDIATION_V1_MASTER_CHECKLIST.md`), never
    from `governance/root_cause_log.md` OPEN / ACTIVE rows (zero execution authority).
  * Respects `stop_hook_active`: if the guard already blocked once and the agent is still going,
    it does not block again. Without this the turn could never end — a guard that cannot be
    satisfied is a hang, not a control.
  * ED_STOP_GUARD=off disables it. Deliberate and visible: an operator may switch it off; an
    agent may not silently route around it.
"""
from __future__ import annotations

import json
import os
import re
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
UNFINISHED_MARKERS = ("IN PROGRESS", "VERIFICATION PENDING", "NOT FIXED", "PARTIALLY FIXED")


def unfinished_rows_opened_today(today: str | None = None) -> list[tuple[str, str]]:
    """RC log does not determine Stop eligibility (RC-480). Returns empty.

    Unfinished-turn obligations come from find_it_fix_it_lock.fix_law_blockers
    reading the sole master, not from today's OPEN RC rows.
    """
    return []


#: RC-235: the ONLY freshness reason exempt from the turn-block — the producer is running
#: but Schwab auth is latched, and clearing it is an operator-only OAuth flow (RC-227).
_AUTH_LATCH_RE = re.compile(r"SchwabAuthError|auth\s+latched", re.I)


def freshness_blockers() -> list[dict]:
    """RC-94: staleness on a REACHABLE console blocks the turn; an unreachable console does not.

    freshness_violations() was built as RC-91's tightening and shipped as an optional function no
    enforced path called — RC-74's class recurring within hours. Wiring it here makes staleness a
    turn-blocker the moment it is visible on a running console.

    The unreachable case is deliberately NOT a blocker HERE: a Stop guard that fails whenever the
    console is off would block every after-hours turn forever — a guard that cannot be satisfied
    is a hang, not a control. Unreachability is still a FINDING (RC-57), but its reporters are
    repo_exposure_audit and agent_error_report, which render it; this hook only gates."""
    try:
        from tools.data_faucet_audit import freshness_violations
        # RC-120: staleness while the producer is legitimately CLOSED (after the 16:30 ET
        # window) is the designed, labeled state — RC-78's rule is that budget-justified
        # staleness gets LABELLED, and RC-102/117 test-lock the labels. Blocking every
        # after-hours turn on it is a guard that cannot be satisfied — a hang, not a control
        # (the same reasoning as the unreachable exemption above). Staleness while the
        # producer SHOULD be running (refresh_active True or unknown) still blocks.
        # RC-235: staleness whose stated reason is the Schwab AUTH LATCH is the same shape —
        # a LABELED state only the operator can clear (re-auth is a credential flow agents are
        # prohibited from running; the blocker is recorded in RC-227). Blocking every turn on
        # it is unsatisfiable by the agent: option 2's "say so in the row" cannot clear a
        # live-payload check, so without this exemption the guard hangs instead of controlling.
        # The exemption is NARROW — the reason must name the latch; unlabeled staleness while
        # the producer should run still blocks exactly as before.
        return [v for v in freshness_violations()
                if not v.get("unreachable") and v.get("refresh_active") is not False
                and not _AUTH_LATCH_RE.search(str(v.get("detail") or ""))]
    except Exception as e:
        return [{"concept": "(freshness audit unavailable)",
                 "detail": f"{type(e).__name__}: {e}"}]


def faucet_violations() -> list[dict]:
    """RC-73: a rendered field fed by an UNDECLARED source. Measured by the provenance audit, not
    asserted. A fallback is a second faucet — that regression was introduced and caught inside a
    single fix on 2026-07-27, which is exactly why the turn must not end while one exists.
    An audit that cannot run is reported as a violation, never silently treated as clean."""
    try:
        from tools.data_faucet_audit import run as _run
        rep = _run(str(REPO / "data" / "ed_console.db"))
    except Exception as e:
        return [{"concept": "(audit unavailable)", "undeclared": [f"{type(e).__name__}: {e}"]}]
    return list(rep.get("faucet_violations", []))


def close_contract_blockers() -> list[str]:
    """RC-106 front end: the gate blocks the COMMIT; this blocks the TURN.

    A CLOSED row written this turn that fails the close contract (missing FIXED:, pending
    vocabulary, unbound VISIBLE_SURFACE) must be repaired before the turn may end — otherwise
    the operator reads a green summary over a close the gate will reject at commit time.
    Fail-closed: if the gate module itself cannot run, that is a loud block, not a pass.
    """
    try:
        import sys as _sys
        from pathlib import Path as _Path
        root = str(_Path(__file__).resolve().parent.parent)
        if root not in _sys.path:
            _sys.path.insert(0, root)
        from tools.check_institutional_correctness import check_five_why_recursive_lock
        return [f"{v}"[:180] for v in check_five_why_recursive_lock()]
    except Exception as e:  # noqa: BLE001 — a broken gate must scream, not wave through
        return [f"close-contract check could not run ({type(e).__name__}: {e}) — "
                f"fix the gate before ending the turn"]


def fix_law_blockers(payload: dict | None = None) -> list[tuple[str, str]]:
    """RC-453/RC-458: FIND IT → FIX IT — same authority as check_find_it_fix_it."""
    try:
        from tools.find_it_fix_it_lock import fix_law_blockers as _flb
        return list(_flb(payload=payload))
    except Exception as e:  # noqa: BLE001 — a broken lock must scream, not wave through
        return [("(find_it_fix_it)", f"{type(e).__name__}: {e}")]


def main() -> int:
    if os.environ.get("ED_STOP_GUARD", "").strip().lower() in ("off", "0", "false"):
        return 0
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    # Attach last-assistant text so MATERIAL_DEFECT: declarations in the wrap-up
    # are reconciled even when transcript_path is absent from the payload.
    transcript = payload.get("transcript_path") or ""
    if transcript and not payload.get("last_assistant_text"):
        try:
            from tools.proof_only_guard import last_assistant_text
            payload = dict(payload)
            payload["last_assistant_text"] = last_assistant_text(transcript) or ""
        except Exception:  # institutional-swallow-ok: discovery scan still has transcript_path
            pass
    # FIND IT → FIX IT re-blocks on repeat Stop (an already-blocked turn cannot
    # launder an active obligation by setting stop_hook_active). Other session
    # hang-guards still honour the one-retry latch below.
    fix_offenders = fix_law_blockers(payload)
    if payload.get("stop_hook_active") is True and not fix_offenders:
        return 0

    rows = unfinished_rows_opened_today()
    faucets = faucet_violations()
    stale = freshness_blockers()          # RC-94: stale-on-a-live-console ends no turn quietly
    contract = close_contract_blockers()  # RC-106: a CLOSED row must satisfy the close contract
    if not rows and not faucets and not stale and not contract and not fix_offenders:
        return 0
    rows = rows + [(c, "violates the RC-106 close contract") for c in contract]
    rows = rows + list(fix_offenders)
    faucets = faucets + [
        {"concept": v["concept"], "undeclared": [v.get("detail", "stale")]} for v in stale
    ]

    listed = "\n".join(f"    {rc} — fix cell still says {why!r}" for rc, why in rows)
    if faucets:
        listed += ("\n" if listed else "") + "\n".join(
            f"    FAUCET: concept {v['concept']!r} fed by undeclared source(s) {v['undeclared']}"
            for v in faucets
        )
    sys.stderr.write(
        "BLOCKED: you are stopping with work YOU declared unfinished today, or with a rendered "
        "field fed by more than one faucet (RC-72 / RC-73).\n\n"
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
