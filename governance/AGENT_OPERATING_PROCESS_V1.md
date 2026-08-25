# Agent Operating Process v1 (RC-217)

**Mechanical enforcer:** `tools/operating_process_lock.py` + `tools/process_lock_guard.py` (PreToolUse / pre-commit). This file is the checklist; `.py` BLOCKs.

> **2026-08-24 Architecture A teardown.** The role, mission, GO-file and authority-rail
> machinery this process once carried is REMOVED. The operator directs each session in
> chat; there are no standing roles and no grant files. What survives here is process
> integrity: measure before claiming, land small, never kill a hook mid-flight, and keep
> LIVE vs DISK honest.

---

## 1. MEASURE before claim

- **Before** any "green", "ready", "one intentional tree", or parity claim, run:
  ```text
  .venv/Scripts/python.exe tools/operating_process_lock.py --measure
  ```
- **DONE when:** `index_worktree_mismatches` is empty for enforcement paths; hashes recorded in chat if claiming PROVEN.

## 2. SMALL LANDINGS

- Each commit is one coherent intention; no multi-hour staged iceberg.

## 3. PRE-COMMIT discipline

- Hook battery may exceed 5 minutes under RTH DB contention — **never kill mid-hook** (RC-215 stash-strip).
- Use ≥600s timeout; prefer background commit with monitoring.
- **After commit:** verify `git show HEAD:<path>` for enforcement files + re-run `--measure` (index=WT).
- **DONE when:** commit completes without SIGTERM; post-commit measure is clean.

## 4. LIVE vs DISK (runtime seams)

- Disk changes to `db.py` collect-window gate are **DISK_ONLY_UNTIL_RESTART** until `:8000` process `StartTime` > `db.py` mtime.
- **Never** write `LIVE_ENFORCED` / "live write path gated" / RC `CLOSED` for runtime seam without either:
  - `DISK_ONLY_UNTIL_RESTART` in the same sentence, or
  - PROVEN restart (measure shows process newer than gate file).
- **DONE when:** `live_collect_disk_only` is null OR prose declares DISK_ONLY.

## 5. EVIDENCE

- Quantitative / parity / live claims: **PROVEN** (same-turn command output) or **`[UNVERIFIED]`** — no third form (RC-53).

---

## Quick commands

| Action | Command |
|--------|---------|
| Measure | `.venv/Scripts/python.exe tools/operating_process_lock.py --measure` |
| Pre-commit gate | `.venv/Scripts/python.exe tools/operating_process_lock.py --pre-commit` |
| Commit check | `.venv/Scripts/python.exe tools/operating_process_lock.py --commit-check` |

No env kill-switch: `ED_PROCESS_LOCK_GUARD` cannot disable the hook (RC-450).
