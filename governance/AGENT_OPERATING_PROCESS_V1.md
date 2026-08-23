# Agent Operating Process v1 (RC-217 / RC-218)

**Authority:** mandatory for Claude and Cursor. **Mechanical enforcer:** `tools/operating_process_lock.py` + `tools/process_lock_guard.py` (PreToolUse / Stop / pre-commit). This file is the checklist; `.py` BLOCKs.

> **SUPERSEDED — operator ruling 2026-08-18:** **Operator is the governing authority / PM. Cursor is an adversarial auditor only** (it audits/falsifies; it never writes feature/kill/implementation code). Everywhere this file and the PM docs say "Cursor is PM / Project Manager", read **"Operator is PM; Cursor audits."** The sequencing/no-patches/MEASURE-before-edit behaviors below are retained; only the PM-role attribution moves to the operator. See RC-403.

**Project Manager:** Operator (adversarial auditor: Cursor) — see `governance/PM_MANDATE.md` and `.cursor/rules/07-cursor-pm.mdc` for the audit behaviors (now the operator-PM + Cursor-auditor process). Sequences missions, stops thrash, triages rehab; does not replace sole-writer for edits.

---

## 0. PM (Operator; Cursor = adversarial auditor) + change requests (RC-219)

- Every multi-agent or “what next” turn: Cursor states **mission · blockers · single next operator action**.
- **Change requests:** operator → Cursor PM → plan → operator GO → Cursor sets `governance/pm_mission.json` `status=active` → writer executes → Cursor audits → mission `idle`.
- Product edits without an in-progress mission are **BLOCKED** (`pm_mission_edit_violation`).
- **Operator writer selection (RC-454):** persisted `writer` fields are not authorization. Control-authority rails stay denied to every assigned AI (`writer_drift_lock.py` / `check_writer_no_drift`).
- One active mission; Collect/lock vs UI polish are sequenced windows, not a free-for-all.
- Daily rehab: `tools/rehab_daily_scan.py` → `reports/rehab_latest.md` (recommend only).
- **DONE when:** `sole_writer.json` has `"pm": "operator"` (operator 2026-08-18; RC-454 tombstone — not write authorization); `pm_mission.json` reflects the only approved active work.

## 1. OPERATOR SELECTS THE WORKING AI (RC-454)

- The operator chooses the active AI by running that AI. The repository must not privilege Claude, Cursor, Codex, GPT, or any other vendor.
- `governance/sole_writer.json` is a tombstone (`pm=operator` only). It is not write authorization.
- `pm_mission.json` `writer` / `auditor` fields are history. They must not veto ordinary product work.
- Control-authority surfaces stay denied to every assigned principal. Becoming the selected writer does not grant rails privilege.
- Switching AI does not require a policy-code edit.

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
| Select working AI | Run that AI. Do not restore a standing writer privilege in `sole_writer.json`. |
| Grant held commit | Edit `governance/operator_go.json` (`granted`, `scope`) |

**Operator-only:** `ED_PROCESS_LOCK_GUARD=off` disables the hook (visible, not silent).
