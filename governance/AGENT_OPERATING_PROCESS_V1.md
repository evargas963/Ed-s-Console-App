# Agent Operating Process v1 (RC-217)

**Scope of this file:** the distinct operating-process checklist — measure before claiming, land small, hook discipline, LIVE vs DISK, the live-checkout invariant, and the debt rule. Engineering law (end-to-end correction, no patches, one computation, one owner, proof standard) lives ONLY in `AGENTS.md` and is not restated here.

**Mechanical enforcer:** `tools/operating_process_lock.py` + `tools/process_lock_guard.py` (PreToolUse / pre-commit). This file is the checklist; `.py` BLOCKs. `tools/check_live_path_is_main.py` is an operator/agent-side REPORT and gates nothing (RC-512, section 6).

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

## 6. LIVE-CHECKOUT INVARIANT (production is main-only; development is isolated)

**Mechanical enforcer:** `tools/process_lock_guard.py` PreToolUse — prevention at the moment of the command. The canonical `EdWebConsole` checkout is **production only** — development never runs in it.

**RC-512:** this line used to name `tools/check_live_path_is_main.py` as a fail-closed enforcer at "launch / pre-push / CI". Two of those never existed (`.pre-commit-config.yaml` declares `default_stages: [pre-commit]` and no workflow invokes it) and the launch one was removed: it made desk availability depend on repository position, and on 2026-09-03 it aborted the launcher because the production checkout was 9 commits behind `origin/main`, with no application defect. Governance controls agent actions, commit and merge — it does not decide whether the desk may run. The check remains available as an operator/agent-side report (`violations()`); it gates nothing on the runtime path.

1. **Production = main == origin/main, always.** The live desk runs branch `main` at HEAD exactly equal to `origin/main` — never a feature branch, never detached, never ahead (a private divergent lineage) or behind (stale code). Prevented at the agent seam by `tools/process_lock_guard.py` (item 4) and reported by `tools/check_live_path_is_main.py`; nothing on the runtime path asserts it (RC-512).
2. **Development happens on the separate dev worktree** — one non-live development surface (`EdWebConsole-dev`, a linked git worktree), never in the production checkout.
3. **One authorized AI writer at a time.** The dev surface is handed between agents serially; auditors are read-only. There is no per-vendor worktree assignment — the operator directs who writes each session (AGENTS.md operating model).
4. **Assigned agents cannot change branches or app code in the production checkout.** The PreToolUse guard BLOCKs — at the moment of the command, not only at the next launch — any `git checkout` / `switch` / `branch` / `commit` / `merge` / `reset` / `rebase` / `cherry-pick` that TARGETS the production primary, and any Edit/Write of app code (`server.py`, `*.py`, `static/*.html|*.js`) inside it. Allowed on production: reads, `git fetch`, `git checkout main` (return-to-main), and the fast-forward update in (5). Dev worktrees are unconstrained.
5. **Merge first, then fast-forward.** Feature work lands via PR to `main`; production then updates ONLY by `git merge --ff-only origin/main` (or `git pull --ff-only`). Production never carries a local commit, so the fast-forward is always clean.

- **DONE when:** `tools/check_live_path_is_main.py` reports no violation in the production checkout (branch==main, HEAD==origin/main, no uncommitted app code); dev work is on the dev worktree; production received its change only by fast-forward after the PR merged. This is an operating standard the operator reads and acts on — a violation means the desk is stale or divergent, never that it may not run (RC-512).

## 7. DEBT RULE

**NO NEW OR WORSENED DEBT, AND EVERY MATERIAL DEFECT IN THE CONNECTED MISSION PATH IS FIXED END TO END.** That is the whole rule (AGENTS.md laws 1–5). There is no retirement ratio: a mission is not forced into unrelated cleanup to satisfy a number, and it is not allowed to leave a connected defect behind to protect a number.

- **Measured with the EXISTING mechanisms, no new machinery:** the merge-time delta gate `tools/check_delta_adds_no_debt.py --base origin/main` (BLOCKs any NEW or WORSENED enforced violation and any undeclared removal of an enforced check — the floor), and the open/overdue counts from `check_root_cause_log`.
- **Recording a newly discovered defect is always allowed and never counts as creating debt** — opening an honest RC row is how discovery is tracked (RC-65).
- **What does NOT count as fixing:** re-dating, postponing, moving, relabeling, or closing already-fixed stale paperwork. Stale-record reconciliation is legitimate and required, and it is reported as reconciliation, never as a fix.
- **Externally blocked rows** (status `BLOCKED` with the clearing event named) are honestly OPEN and are the only legal form of an unfixed connected defect (AGENTS.md law 2).

- **DONE when:** the delta gate passes at the final SHA and every material defect discovered on the connected path is CLOSED with evidence or `BLOCKED` on a named external event.

---

## Quick commands

| Action | Command |
|--------|---------|
| Measure | `.venv/Scripts/python.exe tools/operating_process_lock.py --measure` |
| Pre-commit gate | `.venv/Scripts/python.exe tools/operating_process_lock.py --pre-commit` |
| Commit check | `.venv/Scripts/python.exe tools/operating_process_lock.py --commit-check` |
| Live-checkout report | `.venv/Scripts/python.exe tools/check_live_path_is_main.py` (production should be branch main == origin/main; reports, does not gate the desk — RC-512) |

No env kill-switch: `ED_PROCESS_LOCK_GUARD` cannot disable the hook (RC-450).
