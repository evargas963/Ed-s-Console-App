# Agent Operating Process v1 (RC-217 / RC-218)

**Authority:** mandatory for Claude and Cursor. **Mechanical enforcer:** `tools/operating_process_lock.py` + `tools/process_lock_guard.py` (PreToolUse / Stop / pre-commit). This file is the checklist; `.py` BLOCKs.

> **NO DESIGNATED ROLES (operator ruling 2026-08-24, RC-462).** The operator is the
> governing authority. There is no standing writer, auditor or reader: the operator
> decides what each AI does that session, and the same AI may read one day, write the
> next and audit the day after. Wherever this file says "Cursor is PM" or names a
> writer/auditor, read it as a BEHAVIOUR the operator may ask any agent to perform.

**Governing authority:** the operator - see `governance/PM_MANDATE.md` for the sequencing / no-patches / MEASURE-before-edit behaviours. Roles are not assigned in the repo.

---

## 0. Coordination + change requests (RC-219)

- Every multi-agent or “what next” turn: Cursor states **mission · blockers · single next operator action**.
- **Change requests:** operator → plan → operator GO → `governance/pm_mission.json` `status=active` (coordination only) → build → audit → mission `idle`.
- Ordinary product edits need **no** active mission and are never blocked by mission status (RC-461/RC-462).
- **Authority (RC-226, simplified RC-462):** while an AI is acting it may not edit the files that decide who is in charge (CODEOWNERS, required workflows, agent settings/hooks, operator grant files, the rail modules) → BLOCK (`writer_drift_lock.control_authority_violation` / `check_writer_no_drift`).
- One active mission; Collect/lock vs UI polish are sequenced windows, not a free-for-all.
- Daily rehab: `tools/rehab_daily_scan.py` → `reports/rehab_latest.md` (recommend only).
- **DONE when:** `pm_mission.json` reflects the only approved active work (coordination metadata; it grants nothing).

## 1. WHO MAY DO WHAT

- There is **no sole writer** and no assigned auditor. The operator says what they want done; the acting AI does it.
- The one standing limit: an acting AI (`ED_AGENT_ROLE` set) may not edit the files that decide who is in charge. The operator (empty `ED_AGENT_ROLE`) is unconstrained.
- Durability comes from operator review at merge (CODEOWNERS + branch protection), not from any file in the tree.

## 2. MEASURE before claim

- **Before** any “green”, “ready”, “one intentional tree”, or parity claim, run:
  ```text
  .venv/Scripts/python.exe tools/operating_process_lock.py --measure
  ```
- **DONE when:** `index_worktree_mismatches` is empty for enforcement paths; hashes recorded in chat if claiming PROVEN.

## 3. SMALL LANDINGS

- No multi-hour staged iceberg without explicit operator GO.
- **DONE when:** each commit is one coherent intention; held surfaces documented in `governance/operator_go.json`.

## 4. PRE-COMMIT discipline

- Hook battery may exceed 5 minutes under RTH DB contention — **never kill mid-hook** (RC-215 stash-strip).
- Use ≥600s timeout; prefer background commit with monitoring.
- **After commit:** verify `git show HEAD:<path>` for enforcement files + re-run `--measure` (index=WT).
- **DONE when:** commit completes without SIGTERM; post-commit measure is clean.

## 5. LIVE vs DISK (runtime seams)

- Disk changes to `db.py` collect-window gate are **DISK_ONLY_UNTIL_RESTART** until `:8000` process `StartTime` > `db.py` mtime.
- **Never** write `LIVE_ENFORCED` / “live write path gated” / RC `CLOSED` for runtime seam without either:
  - `DISK_ONLY_UNTIL_RESTART` in the same sentence, or
  - PROVEN restart (measure shows process newer than gate file).
- **DONE when:** `live_collect_disk_only` is null OR prose declares DISK_ONLY.

## 6. AUDITOR WINDOW

- Do not claim green during an in-flight hook cycle.
- Re-prove immediately before commit and before ending the turn.
- **DONE when:** last `--measure` in the authority window precedes the claim.

## 7. GREEN-LIGHT (held staged surface)

- Staged ENFORCED checks not on HEAD require operator GO file:
  ```json
  { "granted": true, "scope": ["staged_lock_surface"], "granted_by": "operator", "granted_at": "..." }
  ```
  in `governance/operator_go.json`.
- **DONE when:** GO present before commit of iceberg; removed after land.

## 8. EVIDENCE

- Quantitative / parity / live claims: **PROVEN** (same-turn command output) or **`[UNVERIFIED]`** — no third form (RC-53).

---

## Quick commands

| Action | Command |
|--------|---------|
| Measure | `.venv/Scripts/python.exe tools/operating_process_lock.py --measure` |
| Pre-commit gate | `.venv/Scripts/python.exe tools/operating_process_lock.py --pre-commit` |
| Commit check | `.venv/Scripts/python.exe tools/operating_process_lock.py --commit-check` |
| Grant held commit | Edit `governance/operator_go.json` (`granted`, `scope`) |

**Operator-only:** `ED_PROCESS_LOCK_GUARD=off` disables the hook (visible, not silent).
