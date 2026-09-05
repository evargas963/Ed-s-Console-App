# Agent Operating Process v1 (RC-217)

**Mechanical enforcer:** `tools/operating_process_lock.py` + `tools/process_lock_guard.py` (PreToolUse / pre-commit). This file is the checklist; `.py` BLOCKs. (`tools/check_live_path_is_main.py` is a report, not an enforcer — §6, RC-512; the earlier "launch / pre-push / CI" claim on this line was the contradiction RC-520 removed.)

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

1. **Production = main == origin/main, always.** The live desk runs branch `main` at HEAD exactly equal to `origin/main` — never a feature branch, never detached, never ahead (a private divergent lineage) or behind (stale code). Reported by `tools/check_live_path_is_main.py`; not asserted at launch, push or CI (RC-512 above).
2. **Development happens on the separate dev worktree** — one non-live development surface (`EdWebConsole-dev`, a linked git worktree), never in the production checkout.
3. **One authorized AI writer at a time.** The dev surface is handed between agents serially; auditors are read-only. There is no per-vendor worktree assignment — the operator directs who writes each session (AGENTS.md operating model).
4. **Assigned agents cannot change branches or app code in the production checkout.** The PreToolUse guard BLOCKs — at the moment of the command, not only at the next launch — any `git checkout` / `switch` / `branch` / `commit` / `merge` / `reset` / `rebase` / `cherry-pick` that TARGETS the production primary, and any Edit/Write of app code (`server.py`, `*.py`, `static/*.html|*.js`) inside it. Allowed on production: reads, `git fetch`, `git checkout main` (return-to-main), and the fast-forward update in (5). Dev worktrees are unconstrained.
5. **Merge first, then fast-forward.** Feature work lands via PR to `main`; production then updates ONLY by `git merge --ff-only origin/main` (or `git pull --ff-only`). Production never carries a local commit, so the fast-forward is always clean.

- **DONE when:** `check_live_path_is_main.py` reports no violation in the production checkout (branch==main, HEAD==origin/main, no uncommitted app code); dev work is on the dev worktree; production received its change only by fast-forward after the PR merged. This is an operating standard the operator reads and acts on — a violation means the desk is stale or divergent, never that it may not run (RC-512).

## 7. DEBT-CONVERGENCE LAW (fixable repo debt goes down, not sideways)

**No new machinery** — measured with the EXISTING ledgers/checkers: the open + overdue counts from `tools/check_institutional_correctness.py` (`check_root_cause_log`, `check_open_item_cap`), the merge-time delta gate `tools/check_delta_adds_no_debt.py --base origin/main` (which already BLOCKs NEW/WORSENED enforced debt — the hard "no net new debt" floor), and `git log` on `governance/root_cause_log.md`. This is an operating discipline over those numbers; it adds no queue, ratio ledger, or reporting surface.

- **Recording a newly discovered defect is always allowed and never counts as creating debt** — opening an honest RC row is how discovery is tracked (RC-65), the opposite of the failure mode.
- **P0 / emergency correctness work is never delayed by the ratio.** Fix it now; the ratio governs only discretionary forward/expansion work.
- **Discretionary expansion must retire real, pre-existing, FIXABLE engineering debt** in the same body of work. Floor = **2 debt items retired per 1 expansion unit**; normal target **3:1**; a dedicated rehab/cleanup pass targets **≥ 5:1**.
- **What does NOT count as retired:** re-dating, postponing, moving, relabeling, or closing already-fixed stale paperwork. A retirement is a real fixable defect driven to root and proven fixed (or proven obsolete on the current tree). Bookkeeping reconciliation of stale records is legitimate and required, but it is counted SEPARATELY and never as engineering-debt retirement.
- **Excluded from the burn denominator:** externally-blocked / data-accrual / operator-blocked rows (a `BLOCKED_ON_*` marker). They are honestly OPEN, not fixable-now — neither debt you must burn nor debt you retired.
- **Objective: monotonic reduction of actual fixable repo debt** — never status manipulation.

- **DONE when:** across the change, real fixable-debt retired ≥ the ratio for the expansion done, measured against the pre-change open/overdue baseline; stale-record reconciliations are reported separately from engineering-debt retirement.

## 8. SIGN-OFF CHECKLIST (drift audit — run on yourself before any "MET / clean / verified" claim)

Moved here from `.claude/skills/drift-audit/SKILL.md` (2026-09-05, RC-520); the skill file is now a
pointer. A sign-off is INVALID unless every phase ran this turn with cited command output.

1. **Intent & drift.** Restate what the OPERATOR wanted (not what the implementing agent reported); which principle it touches (zero-bias / data-driven / per model×horizon / fail-closed); whether scope slipped or a stage was marked done that is not; whether the acceptance GATE equals the principle or is weaker (presence-only).
2. **Mechanical scans.** AST-scan every changed signature/arity/return with a same-turn `ast.walk` script over every caller (show the script and its output); run the relevant gates and tests yourself — never cite the implementing agent's pass count.
3. **Known failure classes (check each, cite evidence):** arity / unpack; presence vs capability (present-but-inoperative); silent-swallow (`try/except` or a 0/0.5/"neutral"/empty default hiding absence); caller / consumer compatibility (producer→consumer trace); fail-closed on schema/width/version mismatch; the cited test actually exercises the path; stale vs live artifacts; gate strength (proxy vs principle); full-stack / all-N coverage (name every model / layer / ticker / horizon the principle spans — a gate over 3 of 7 that prints "full coverage" is a lie); side-channel consumers of removed traffic (liveness stamps, poll-suppression timers, health badges — trace the receiver before discarding); `EXPLAIN QUERY PLAN` before any ad-hoc JOIN on the production DB (index SEARCH on the join key or rewrite); classification-by-complement (enumerate the tag namespace before classifying `!= known-good`); patch / gate-relax (an env flag that skips a contract, a relax branch, a silent slice/fallback forcing incompatible data through — trace the bundle LOAD lineage, not just the output).
4. **Completeness critic.** "What class did I NOT check? Where is the gate smaller than the goal?" — check it now; propose additions to this list to the operator (the list grows only on the operator's word).
5. **Verdict.** CLEAN, or FINDINGS with file:line + evidence — no impression-verdicts.
6. **Correction loop.** A precise fix directive (file:line, exact change, acceptance; paste-ready for another agent) and, if useful, a proposed rule for the operator — no self-landed law edits, no locks manufactured from a finding.
7. **Sign-off** only after 1–6, stating: "drift-audit run; findings: <…>; corrections: <…>; gate hardened: <y/n>."

Honest limit: this covers KNOWN failure classes and forces the critic; it cannot guarantee a novel class.

---

## Quick commands

| Action | Command |
|--------|---------|
| Measure | `.venv/Scripts/python.exe tools/operating_process_lock.py --measure` |
| Pre-commit gate | `.venv/Scripts/python.exe tools/operating_process_lock.py --pre-commit` |
| Commit check | `.venv/Scripts/python.exe tools/operating_process_lock.py --commit-check` |
| Live-checkout report | `.venv/Scripts/python.exe tools/check_live_path_is_main.py` (production should be branch main == origin/main; reports, does not gate the desk — RC-512) |

No env kill-switch: `ED_PROCESS_LOCK_GUARD` cannot disable the hook (RC-450).
