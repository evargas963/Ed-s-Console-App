# Agent Operating Process v1 (RC-217 / RC-218)

**Authority:** mandatory for Claude and Cursor. **Mechanical enforcer:** `tools/operating_process_lock.py` + `tools/process_lock_guard.py` (PreToolUse / Stop / pre-commit). This file is the checklist; `.py` BLOCKs.

> **SUPERSEDED — operator ruling 2026-08-22 (RC-452/RC-457):** Operator is the governing authority / PM. Claude and Cursor may both implement. The operator selects ACTIVE_WRITER per mission. No agent has permanent writer or auditor status. ONE canonical worktree total. ONE active writer at a time. The 2026-08-18 "Cursor is an adversarial auditor only" sentence is void. The one-writer-per-worktree multi-checkout architecture is void.

**Project Manager:** Operator. **ACTIVE_WRITER:** per `governance/sole_writer.json` / `governance/pm_mission.json`. See `.cursor/rules/07-cursor-pm.mdc`.

---

## 0. PM (Operator) + ACTIVE_WRITER + change requests (RC-219 / RC-452)

- Every multi-agent or “what next” turn: state **mission · active_writer · blockers · single next operator action**.
- **Change requests:** operator → plan → operator GO → `governance/pm_mission.json` names ACTIVE_WRITER → that agent executes → the other agent must not concurrently mutate the canonical worktree.
- Product edits without an in-progress mission are **BLOCKED** (`pm_mission_edit_violation`).
- **Writer no-drift (RC-226):** non-writer staged `scope_paths` → BLOCK (`writer_drift_lock.py` / `check_writer_no_drift`). Cursor=auditor only while Claude writes.
- One active mission; Collect/lock vs UI polish are sequenced windows, not a free-for-all.
- Daily rehab: `tools/rehab_daily_scan.py` → `reports/rehab_latest.md` (recommend only).
- **DONE when:** `sole_writer.json` has `"pm": "operator"` (operator 2026-08-18; auditor `"cursor"`); `pm_mission.json` reflects the only approved active work.

## 1. SOLE_WRITER

- **Before** editing collect seam, checker, or lock modules: read `governance/sole_writer.json`.
- **DONE when:** `writer` names exactly one agent; `pm` is `operator` (operator 2026-08-18); Cursor is auditor-only for protected paths.
- **Cursor:** do not Edit/Write protected paths (see enforcer `PROTECTED_PATHS`) while `writer` ≠ `cursor`.
- **Operator clears** by setting `writer` to the active agent or deleting the file.

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
| Set sole writer | Edit `governance/sole_writer.json` (`writer`, `auditor`, `updated_at`) |
| Grant held commit | Edit `governance/operator_go.json` (`granted`, `scope`) |

**Operator-only:** `ED_PROCESS_LOCK_GUARD=off` disables the hook (visible, not silent).
