# Agent Operating Process v1 (RC-217)

**Mechanical enforcer:** `tools/operating_process_lock.py` + `tools/process_lock_guard.py` (PreToolUse / pre-commit) + `tools/check_live_path_is_main.py` (RC-350, launch / pre-push / CI). This file is the checklist; `.py` BLOCKs.

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

**Mechanical enforcer:** `tools/check_live_path_is_main.py` (RC-350; launch / pre-push / CI, fail-closed) + `tools/process_lock_guard.py` PreToolUse (prevention at the moment of the command). The canonical `EdWebConsole` checkout is **production only** — development never runs in it.

1. **Production = main == origin/main, always.** The live desk runs branch `main` at HEAD exactly equal to `origin/main` — never a feature branch, never detached, never ahead (a private divergent lineage) or behind (stale code). Asserted at every launch / push / CI (emergency bypass `ED_LIVE_PATH_UNLOCKED=1` for a downed desk only — every use is a logged admission the invariant broke).
2. **Development happens on the separate dev worktree** — one non-live development surface (`EdWebConsole-dev`, a linked git worktree), never in the production checkout.
3. **One authorized AI writer at a time.** The dev surface is handed between agents serially; auditors are read-only. There is no per-vendor worktree assignment — the operator directs who writes each session (AGENTS.md operating model).
4. **Assigned agents cannot change branches or app code in the production checkout.** The PreToolUse guard BLOCKs — at the moment of the command, not only at the next launch — any `git checkout` / `switch` / `branch` / `commit` / `merge` / `reset` / `rebase` / `cherry-pick` that TARGETS the production primary, and any Edit/Write of app code (`server.py`, `*.py`, `static/*.html|*.js`) inside it. Allowed on production: reads, `git fetch`, `git checkout main` (return-to-main), and the fast-forward update in (5). Dev worktrees are unconstrained.
5. **Merge first, then fast-forward.** Feature work lands via PR to `main`; production then updates ONLY by `git merge --ff-only origin/main` (or `git pull --ff-only`). Production never carries a local commit, so the fast-forward is always clean.

- **DONE when:** `check_live_path_is_main.py` PASSes in the production checkout (branch==main, HEAD==origin/main, no uncommitted app code); dev work is on the dev worktree; production received its change only by fast-forward after the PR merged.

## 7. DEBT-CONVERGENCE LAW (fixable repo debt goes down, not sideways)

**No new machinery** — measured with the EXISTING ledgers/checkers: the open + overdue counts from `tools/check_institutional_correctness.py` (`check_root_cause_log` for RC rows, `check_measured_claims_cite_evidence` for register claims — RC-505 retired `check_open_item_cap`, which reported the same items twice), the merge-time delta gate `tools/check_delta_adds_no_debt.py --base origin/main` (which already BLOCKs NEW/WORSENED enforced debt — the hard "no net new debt" floor), and `git log` on `governance/root_cause_log.md`. This is an operating discipline over those numbers; it adds no queue, ratio ledger, or reporting surface.

- **Recording a newly discovered defect is always allowed and never counts as creating debt** — opening an honest RC row is how discovery is tracked (RC-65), the opposite of the failure mode.
- **P0 / emergency correctness work is never delayed by the ratio.** Fix it now; the ratio governs only discretionary forward/expansion work.
- **Discretionary expansion must retire real, pre-existing, FIXABLE engineering debt** in the same body of work. Floor = **2 debt items retired per 1 expansion unit**; normal target **3:1**; a dedicated rehab/cleanup pass targets **≥ 5:1**.
- **What does NOT count as retired:** re-dating, postponing, moving, relabeling, or closing already-fixed stale paperwork. A retirement is a real fixable defect driven to root and proven fixed (or proven obsolete on the current tree). Bookkeeping reconciliation of stale records is legitimate and required, but it is counted SEPARATELY and never as engineering-debt retirement.
- **Excluded from the burn denominator:** externally-blocked / data-accrual / operator-blocked rows (a `BLOCKED_ON_*` marker). They are honestly OPEN, not fixable-now — neither debt you must burn nor debt you retired.
- **Objective: monotonic reduction of actual fixable repo debt** — never status manipulation.

- **DONE when:** across the change, real fixable-debt retired ≥ the ratio for the expansion done, measured against the pre-change open/overdue baseline; stale-record reconciliations are reported separately from engineering-debt retirement.

---

## Quick commands

| Action | Command |
|--------|---------|
| Measure | `.venv/Scripts/python.exe tools/operating_process_lock.py --measure` |
| Pre-commit gate | `.venv/Scripts/python.exe tools/operating_process_lock.py --pre-commit` |
| Commit check | `.venv/Scripts/python.exe tools/operating_process_lock.py --commit-check` |
| Live-checkout lock | `.venv/Scripts/python.exe tools/check_live_path_is_main.py` (production must be branch main == origin/main) |

No env kill-switch: `ED_PROCESS_LOCK_GUARD` cannot disable the hook (RC-450).
