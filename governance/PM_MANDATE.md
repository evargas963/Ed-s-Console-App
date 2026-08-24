# Cursor Project Manager Mandate (RC-218 / RC-220)

> **NO DESIGNATED ROLES (operator ruling 2026-08-24, RC-462).** There is no standing
> writer, auditor or reader. The operator decides what each AI does *that session* by
> asking it - the same AI may read one day, write the next and audit the day after. The
> repo stores no role for anyone, and no field in any tracked file grants permission to
> anything. Read every "PM agent: Cursor" phrase below as a description of BEHAVIOURS
> the operator may ask any agent to perform, never as an assignment.

**Governing authority:** the operator. **Default program:** whole-repo rehab
(`governance/REHAB_PROGRAM.md`), spine = **multi-faucet audit/find/fix end-to-end, no
patches**.

**The one standing rule.** While an AI is acting (`ED_AGENT_ROLE` is set) it may not edit
the files that decide who is in charge - CODEOWNERS, the required workflows, the agent
settings/hooks that carry the assignment, the operator grant files, and the rail itself
(`tools/writer_drift_lock.control_authority_violation`). Changing any of them needs
operator approval at merge (CODEOWNERS + branch protection). Everything else - ordinary
product code, tests, reports - the assigned AI does autonomously. There is no OS sandbox,
privileged helper or host provisioning; that design was removed as overbuilt (RC-461).

The operator must **not** have to tell the PM to rehab the repo or to stay on multi-faucet. If the session starts without a clear faucet/rehab slice in flight, **PM opens the next RH-F1 P0**.

## Hard duties

1. **Own the whole repo.** Every turn: rehab posture first (queue + facets), then the active slice. Levels / FORCES / DB are slices — not the job boundary.
2. **Sequence work.** One active *build* mission at a time. Recommend-only census/scans may run alongside. Avoid two agents editing the same product paths at once - a coordination habit, not a permission rule.
3. **End-to-end, no patches.** Kill the second path in the same mission window or leave status PARTIAL with OPEN RC. Refuse “fallback forever.”
4. **Stop thrash.** Disputed facts → MEASURE before more edits.
5. **Mission windows.** Collect/lock vs UI polish sequenced; never unordered free-for-all.
6. **GO / NO-GO.** `operator_go.json` for held surfaces; LIVE vs DISK honesty.
7. **Rehab backlog.** Triage `reports/rehab_latest.md` every session; turn P0s into `pm_mission.json` without waiting to be asked.
8. **Change-request protocol (RC-219).** Operator → plan → GO → `pm_mission.json` active (coordination only) → build → audit → idle.
9. **Keep the operator straight.** Remind Automation, GO file, restart, one active mission — proactively.
10. **Honest status.** Lead with: rehab program status · active slice · blockers · single next operator action.
11. **RC resolve (RC-228).** Reject mission COMPLETE / DONE / idle transition while any OPEN RC names that `mission_id`. Prefer CLOSE with FIXED reach or honest PARTIAL + `OUT-OF-SCOPE:` tracker — never mass-fake CLOSE. Triage `reports/rc_open_drain_latest.md` into the next work queue after (or parallel to, when non-conflicting) the active build mission.

## What is actually enforced

Two things, and nothing else:

1. **In-process (defense-in-depth).** `tools/process_lock_guard.py` calls
   `control_authority_violation` on every Edit/Write and on commit. If an AI is acting and
   the path is an authority file, it is denied with prefix `SOD_DRIFT:`. Ordinary product
   paths are never denied, whatever any mission or metadata says.
2. **At merge (the durable boundary).** CODEOWNERS + branch protection require the
   operator to approve any change to the authority files.

There is no writer/non-writer distinction, no `scope_paths` gate, and no mission-status
gate on product edits. Those were removed (RC-461/RC-462) because the operator does not
delegate roles - they simply say what they want done.

## Daily rehab automation

- Tool: `tools/rehab_daily_scan.py` → `reports/rehab_latest.md` + `reports/rehab_queue.jsonl`
- Schedule: Cursor Automation (weekdays after RTH) and/or `tools/run_rehab_daily.ps1`
- **Never** auto-commit, auto-restart, or auto-edit Collect/Decide

## Halt

`STOP` / `PAUSE` / `HANG IT UP` / `DO NOT CONTINUE`
