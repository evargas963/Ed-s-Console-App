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

## 8. VERIFICATION EXECUTION (RC-517 — the law is `AGENTS.md`, Verification discipline; this is the procedure)

**What was observed (2026-09-04, this repository, two agents independently):** a serial real-boundary campaign projected at two hours; its first attempt lost 28 minutes to a console-encoding crash with no per-case record; the rerun launched beside an 8-worker pytest-full wave and both slowed; 43 minutes of blind waiting on buffered output; a full wave run on a copied venv missing two pinned dependencies; the same full suite rerun after every fix; fifteen state-bound test failures caused by concurrent worktree mutation, rerun in isolation for 30 minutes.

**Order of work.**
1. Targeted first: the tests that name the changed behaviour, then the affected suites. Green and stable before anything expensive.
2. Preflight the expensive operation: interpreter is the repo `.venv` and imports the modules the run needs; the environment variables are the intended ones (`ED_CI_OFFLINE=1` + placeholder credentials for offline proof; real credentials and NO offline flag for a live claim — never inherited); test and runtime paths are isolated (`ED_TERRAIN_QUARANTINE_LEDGER` and the like point at scratch); the tree is the intended one (`git status --short` empty, HEAD is the SHA under proof, worktree is not the production checkout); `python tools/operating_process_lock.py --heavy-jobs` shows nothing alive. The boundary campaign runs this preflight itself and refuses to start otherwise.
3. Launch ONE expensive wave at a time. Parallelism that is proven isolated (the campaign's base groups: one worktree, one index, one cache entry each) is launched as one command by the owner that proved it (`tests/institutional_e2e_boundary_campaign.py --parallel`), never as several agent-launched waves. The PreToolUse guard blocks a second heavy launch while one is alive.
4. Watch with evidence, not with time. Every long run flushes per-case results as they finish (the campaign writes a JSONL record per case: id, base and candidate SHA, timestamps, both gate lines, exit status, expected violation, correct-reason flag). While waiting, the evidence of health is `--heavy-jobs` (pid, age, CPU seconds, children) plus output growth.
5. Anomaly trigger — investigate, do not wait: when the run exceeds twice its last measured duration for the same operation on this host, or produces no new observable progress for 15 minutes, run `--heavy-jobs`, inspect the newest output, and decide: healthy (CPU advancing, phase advancing) → continue and state that proof; unhealthy (no CPU, no growth, blocked on a lock or an external wait) → stop it and root-fix; slow by design (serial independent work, repeated identical evidence) → fix the design before repeating. Reference durations on this host: one delta-gate side 8–13 min; the campaign's longest base group ≈ 45 min when run as four parallel groups; pytest-full `-n 8` ≈ 44 min.
6. After a failure: classify it (candidate defect / harness defect / environment defect / state-bound test), fix the root cause, rerun ONLY the affected proof. Completed independent proof is reused when its identity is unchanged — the delta gate's base cache is keyed on base commit + gate blob + driver + interpreter, and the campaign reuses a recorded case for the same HEAD unless `--force`. A change to the gate, the roster, the driver's staging or the candidate invalidates the affected proof and only that proof.
7. The required final verification runs ONCE at the final SHA: the commit hook battery, then required Hardening and pytest-full on the pushed commit. No further local full wave is launched to "be safe".

**Classification of each requirement.**

| Requirement | Class | Owner |
|---|---|---|
| No competing heavy waves | MECHANICALLY_ENFORCEABLE_EXISTING_OWNER | `tools/process_lock_guard.py` → `operating_process_lock.competing_heavy_verification_violations` (blocks a heavy launch while `heavy_verification_jobs()` is non-empty). Known blind spot, measured: a second launch issued within the first wave's process start-up window (about 2 s, before the interpreter exists in the process table) is not seen — the inventory reads processes, not intentions; two launches in one breath remain the agent's discipline |
| Unchanged base-side proof is not recomputed | MECHANICALLY_ENFORCEABLE_EXISTING_OWNER | `tools/check_delta_adds_no_debt.py` base cache keyed on base commit + gate blob + driver + interpreter, shared across worktrees |
| Completed campaign proof is not rerun after one group fails | MECHANICALLY_ENFORCEABLE_EXISTING_OWNER | `tests/institutional_e2e_boundary_campaign.py` per-case JSONL + reuse for the same HEAD (`--force` to override) |
| Expensive-operation preflight | DECLARATIVE_ONLY, with a mechanical instance | the campaign's own preflight refuses to start; the general case is declarative because a guard cannot know what an arbitrary command intends to prove |
| Targeted before expensive; known failure fixed first | NOT_RELIABLY_DETECTABLE | a guard cannot know which failure is "known" or whether the expensive run is the diagnosis; declarative in `AGENTS.md` |
| Long-run observability and the anomaly trigger | DECLARATIVE_ONLY | the evidence tool exists (`--heavy-jobs`); the decision is the agent's and is judged by the operator on the stated proof |
| Safe parallelism; selective rerun; self-healing | DECLARATIVE_ONLY | judgement over isolation and evidence identity; no reliable mechanical proxy |
| Live claim with inherited `ED_CI_OFFLINE` / placeholder credentials | NOT_RELIABLY_DETECTABLE at the command seam | "claimed live" is prose; the launcher's `live_schwab_env.py --sanitize` owns the runtime case; declarative for agent probes |

---

## Quick commands

| Action | Command |
|--------|---------|
| Measure | `.venv/Scripts/python.exe tools/operating_process_lock.py --measure` |
| Pre-commit gate | `.venv/Scripts/python.exe tools/operating_process_lock.py --pre-commit` |
| Commit check | `.venv/Scripts/python.exe tools/operating_process_lock.py --commit-check` |
| Heavy verification inventory (RC-517) | `.venv/Scripts/python.exe tools/operating_process_lock.py --heavy-jobs` |
| Live-checkout report | `.venv/Scripts/python.exe tools/check_live_path_is_main.py` (production should be branch main == origin/main; reports, does not gate the desk — RC-512) |

No env kill-switch: `ED_PROCESS_LOCK_GUARD` cannot disable the hook (RC-450).
