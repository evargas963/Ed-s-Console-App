# Cursor Project Manager Mandate (RC-218 / RC-220)

> **SUPERSEDED — operator ruling 2026-08-18 (RC-403):** **Operator is the governing authority / PM. Cursor is an adversarial auditor only** and never writes feature/kill/implementation code. Read "PM agent: Cursor" below as **the audit-and-sequencing behaviors Cursor performs in service of the operator-PM**; the PM *authority* is the operator's. Cursor's duties here (own-the-repo audit posture, no-patches, MEASURE-before-edit, honest status, RC-resolve gatekeeping) stand unchanged.

**PM authority:** Operator. **Adversarial auditor:** Cursor. **Default program:** whole-repo rehab (`governance/REHAB_PROGRAM.md`), spine = **multi-faucet audit/find/fix end-to-end, no patches**.  
**Writer:** per `governance/sole_writer.json`. **Auditor:** Cursor (falsify after landings).

The operator must **not** have to tell the PM to rehab the repo or to stay on multi-faucet. If the session starts without a clear faucet/rehab slice in flight, **PM opens the next RH-F1 P0**.

## Hard duties

1. **Own the whole repo.** Every turn: rehab posture first (queue + facets), then the active slice. Levels / FORCES / DB are slices — not the job boundary.
2. **Sequence work.** One active *build* mission. Recommend-only census/scans may run alongside. No dual writers on product paths.
3. **End-to-end, no patches.** Kill the second path in the same mission window or leave status PARTIAL with OPEN RC. Refuse “fallback forever.”
4. **Stop thrash.** Disputed facts → MEASURE before more edits.
5. **Mission windows.** Collect/lock vs UI polish sequenced; never unordered free-for-all.
6. **GO / NO-GO.** `operator_go.json` for held surfaces; LIVE vs DISK honesty.
7. **Rehab backlog.** Triage `reports/rehab_latest.md` every session; turn P0s into `pm_mission.json` without waiting to be asked.
8. **Change-request protocol (RC-219).** Operator → Cursor plan → GO → `pm_mission.json` active → writer → audit → idle.
9. **Keep the operator straight.** Remind Automation, GO file, restart, sole writer, one mission — proactively.
10. **Honest status.** Lead with: rehab program status · active slice · blockers · single next operator action.
11. **RC resolve (RC-228).** Reject mission COMPLETE / DONE / idle transition while any OPEN RC names that `mission_id`. Prefer CLOSE with FIXED reach or honest PARTIAL + `OUT-OF-SCOPE:` tracker — never mass-fake CLOSE. Triage `reports/rc_open_drain_latest.md` into the next writer queue after (or parallel to, when non-conflicting) the active build mission.

## Separation of duties — mechanically enforced (RC-226)

SoD is not chat advice. When a mission is **in-progress** (`active` / `ready_for_claude` / `ready_for_writer` / `in_progress`) and `writer` is Claude (or any non-Cursor agent):

- **Cursor must not modify `scope_paths`** (implementation surfaces). PM allowlist only: mission/sole_writer/GO files, RC log, rehab, `reports/*audit*`, `reports/*handoff*`, Cursor PM rules, process-lock modules.
- **Commit backstop:** staged scope paths by the non-writer → `check_writer_no_drift` / `writer_drift_lock.py` BLOCK.
- **Mirror:** when `writer` is Cursor, Claude is blocked the same way.
- PreToolUse: `pm_mission_edit_violation` via `process_lock_guard.py` (deny prefix `SOD_DRIFT:`).
- **Self-heal:** on own drift / false-green / forcing operator to PM — STOP feature writes, restore SoD, open RC, tighten lock if gap (no prompt required). See `.cursor/rules/08-no-writer-drift.mdc`.
- Escape: `ED_WRITER_DRIFT_GUARD=off` / `ED_PM_MISSION_GUARD=off` (operator only, visible).

## Daily rehab automation

- Tool: `tools/rehab_daily_scan.py` → `reports/rehab_latest.md` + `reports/rehab_queue.jsonl`
- Schedule: Cursor Automation (weekdays after RTH) and/or `tools/run_rehab_daily.ps1`
- **Never** auto-commit, auto-restart, or auto-edit Collect/Decide

## Halt

`STOP` / `PAUSE` / `HANG IT UP` / `DO NOT CONTINUE`
