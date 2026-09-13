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
  - PROVEN restart (the `:8000` process start time, read by hand, is newer than the change).
- **DONE when:** the restart is proven by measurement quoted in the row, or the row says DISK_ONLY. (BEDROCK 2026-09-06: the `live_collect_disk_only` probe and the completion-claim lock LOCK-5/RC-232 that read prose for COMPLETE/LIVE_ENFORCED words are removed from the hooks — this is a record standard the operator reads, held by the CLOSE contract, not a mechanism.)

## 5. EVIDENCE

- Quantitative / parity / live claims: **PROVEN** (same-turn command output) or **`[UNVERIFIED]`** — no third form (RC-53).

## 6. LIVE-CHECKOUT INVARIANT (production is main-only; development is isolated)

**Mechanical enforcer:** `tools/process_lock_guard.py` PreToolUse — prevention at the moment of the command. The canonical `EdWebConsole` checkout is **production only** — development never runs in it.

**RC-512:** this line used to name `tools/check_live_path_is_main.py` as a fail-closed enforcer at "launch / pre-push / CI". Two of those never existed (`.pre-commit-config.yaml` declares `default_stages: [pre-commit]` and no workflow invokes it) and the launch one was removed: it made desk availability depend on repository position, and on 2026-09-03 it aborted the launcher because the production checkout was 9 commits behind `origin/main`, with no application defect. Governance controls agent actions, commit and merge — it does not decide whether the desk may run. The check remains available as an operator/agent-side report (`violations()`); it gates nothing on the runtime path.

1. **Production = main == origin/main, always.** The live desk runs branch `main` at HEAD exactly equal to `origin/main` — never a feature branch, never detached, never ahead (a private divergent lineage) or behind (stale code). Reported by `tools/check_live_path_is_main.py`; not asserted at launch, push or CI (RC-512 above).
2. **Development happens on the separate dev worktree** — one non-live development surface (`EdWebConsole-dev`, a linked git worktree), never in the production checkout. **Launch the agent session IN that worktree:** the hooks run from the session's checkout and judge every event from its own payload (RC-544); there is no cross-worktree delegation, so a session launched in the production checkout is judged by the production checkout's guards and ledger. Do not move a session between checkouts: the host resolves the relative hook command (`.venv/Scripts/python.exe tools/hook_chain.py …`) in the session's working directory but loads the wiring from the checkout the session opened in, so for the turn after a directory change the opening checkout's wiring executes against the new tree — measured 2026-09-10: `main`'s wiring named `tools/pretooluse_chain.py`, which PR #239 deleted, and every shell and edit tool was refused (fail-closed, nothing executed) until the next turn reloaded the new checkout's wiring. One session, one checkout.
3. **One authorized AI writer at a time.** The dev surface is handed between agents serially; auditors are read-only. There is no per-vendor worktree assignment — the operator directs who writes each session (AGENTS.md operating model).
4. **Assigned agents cannot change branches or app code in the production checkout.** The PreToolUse guard BLOCKs — at the moment of the command, not only at the next launch — any `git checkout` / `switch` / `branch` / `commit` / `merge` / `reset` / `rebase` / `cherry-pick` that TARGETS the production primary, and any Edit/Write of app code (`server.py`, `*.py`, `static/*.html|*.js`) inside it. Allowed on production: reads, `git fetch`, `git checkout main` (return-to-main), and the fast-forward update in (5). Dev worktrees are unconstrained.
5. **Merge first, then fast-forward.** Feature work lands via PR to `main`; production then updates ONLY by `git merge --ff-only origin/main` (or `git pull --ff-only`). Production never carries a local commit, so the fast-forward is always clean.

- **DONE when:** `check_live_path_is_main.py` reports no violation in the production checkout (branch==main, HEAD==origin/main, no uncommitted app code); dev work is on the dev worktree; production received its change only by fast-forward after the PR merged. This is an operating standard the operator reads and acts on — a violation means the desk is stale or divergent, never that it may not run (RC-512).

## 7. DEBT (no ratios)

The ratios that stood here (2:1 / 3:1 / 5:1 retirements per expansion) were a ratchet, and the operator ruled ratchets out (RC-280: "we do not need ratchets, we need great code"). The surviving law is `AGENTS.md` **Backlog**: a dated row may not rot — it is finished, or BLOCKED with a live date and a stated reason — and the merge-time delta gate (`tools/check_delta_adds_no_debt.py --base origin/main`) refuses any change that adds or worsens enforced debt. Recording a newly discovered defect is always allowed and never counts as debt; closing already-fixed paperwork is reconciliation, not repair.

- **DONE when:** no overdue row of this worktree's own, and the delta gate reports no new or worsened enforced violation.

## 8. CANONICAL REVIEW STANDARD (fourteen requirements — run before any "MET / clean / verified / PASS" claim)

This is the ONE detailed review standard for this repository (AGENTS.md states the governing
principles; this section carries the detail — see AGENTS.md's "Agent operating process" law and
its "Evidence before assertion" law). It supersedes and replaces the former drift-audit checklist
(moved here 2026-09-05, RC-520; superseded 2026-09-12) — `.claude/skills/drift-audit/SKILL.md`
remains a pointer to "§8 of this file," unchanged, and now resolves here. It applies to any
candidate change, audit, or completion claim in this repository — not only the mission active
when this section was last revised. A review is INVALID unless every requirement below actually
ran this turn, against the real current repository state (`git` state, not a pasted summary —
see AGENTS.md's "Research, then act" and "Agent truth" laws), with cited command output where a
requirement calls for evidence.

Google's [Code Review Developer Guide](https://google.github.io/eng-practices/review/) is a
useful **supporting** reference for design, complexity, test validity, and general code health —
consult it for that judgment. It is not an operative requirement of this repository: the fourteen
items below are self-contained here so their meaning never depends on an external page staying
put or on an agent's memory of it.

1. **Inspect reality first.** Establish the required behavior independently of the current
   implementation — from the product requirement, verified external semantics (a vendor's own
   documented contract, not an assumption about it), and engineering evidence. Treat code, tests,
   governance documents, comments, and architecture documents as CLAIMS to examine against that
   independently-established requirement, never as the requirement itself.
2. **Professional standards.** Specify observable acceptance criteria before judging or
   implementing. They must describe the COMPLETE required behavior — universality (no
   arbitrary narrowing to a convenient example), data semantics (identity, freshness,
   provenance, missingness vs. a genuine zero), lifecycle (start, steady state, change,
   shutdown/failure, restart), and failure behavior.
3. **Proactive findings.** Challenge the requirements encoded in EXISTING tests, not only the
   code. Identify a test that preserves a defective assumption, or that asserts internal
   activity occurred (a function was called, a flag was set) without proving the required
   externally-observable RESULT.
4. **Architecture challenge.** Inspect existing ownership before adding a new mechanism —
   `docs/ARCHITECTURE.md` states the target and, per its own §9, what a touched responsibility
   must expose for review. Consolidate duplicate responsibilities and resolve contradictory
   instructions rather than accommodating them (AGENTS.md's "Conflict rule"). A genuine
   architecture-amendment disagreement is judged by AGENTS.md's Placement rule: an engineering
   determination is fixed on the evidence, not queued for permission; only a genuine product or
   business tradeoff with no engineering answer needs the operator.
5. **Root-cause repair.** Correct every materially connected producer, consumer, persistence
   layer, configuration surface, runtime path, and test required for closure — not only the one
   file where the symptom was observed. Calling one canonical computation repeatedly across
   different inputs does not itself create a duplicate computation authority (AGENTS.md's "ONE
   computation" law) — do not fork a second implementation to "fix" ordinary repeated use.
6. **Product outcome.** Demonstrate the actual operator workflow the change is for, driven
   end to end in the running product — not a proxy for it, and not merely its parts proven in
   isolation. Name the concrete chain the workflow must complete for the mission at hand (for
   example: a subscription request must reach the vendor, capture, replay, coherent
   application state, the calculation, and a visible, truthful update — stated in whatever
   terms the actual workflow under review requires).
7. **Reality reconstruction.** Trace inputs, state transitions, scope, provenance, timestamps,
   ownership, and failure propagation through the COMPLETE workflow, not just its entry and
   exit points.
8. **Architecture judgment.** Give every materially touched responsibility cohesive canonical
   placement with an explicit input/output contract and explicit failure behavior. Rewire
   consumers and remove superseded implementations — do not leave both the old and new path
   live. Direct market-data display must remain available independently of optional
   research/model capabilities (`docs/ARCHITECTURE.md` §4/§7: a capability failure degrades
   that capability, never the application shell). Proof that one module works in isolation
   must be accompanied by proof that the connections between the touched modules actually work
   — passing each module's own tests cannot by itself close a multi-module workflow.
9. **Adversarial behavior.** Derive the expected result independently before checking the
   actual one. For a material correctness defect, prove the CURRENTLY-broken production
   behavior actually fails the test meant to catch it (a negative control) — a test that would
   pass against the known-broken code proves nothing. Validate every test double's simulated
   behavior against the actual external contract (the real vendor/library's documented or
   installed behavior) before trusting it, and state plainly which claims rest on simulated
   behavior versus behavior actually verified against the real dependency.
10. **Survivor challenge.** Every mechanism added or retained must satisfy ALL of: the required
    behavior genuinely needs it; no sufficient native or already-canonical capability exists
    that would do the same job; it owns one distinct required responsibility, not a duplicate
    of another mechanism's; and removing it would break required behavior or a required failure
    boundary. A mechanism failing any one of these is removed or consolidated, not kept "to be
    safe."
11. **Quality delta.** Require before-and-after evidence covering correctness, ownership,
    minimum-complete design, removed superseded paths, completed consumer migration, failure
    handling, and performance where the change could affect it. Test totals, line-count
    changes, completed paperwork, and a green required check are NOT by themselves that
    evidence — they show the candidate satisfies whatever the tests/checks encode, not that the
    encoding itself was sufficient or that anything actually improved.
12. **Proof standard.** Separate unit, integration, real-browser, real-runtime, real-production,
    and live-market evidence explicitly — state what EACH tier actually proves and what remains
    unproven, rather than letting a strong result at one tier stand in for another. Review every
    CHANGED test and validator in the candidate for weakened expectations (a loosened assertion,
    a widened tolerance, a dropped negative control) as carefully as the production code itself.
    **Layered-testing clarification (2026-09-12, independent-review request):** the tiers above
    map onto four questions, each answered by a DIFFERENT kind of test, never substituted for one
    another: **component** (does this one responsibility produce an independently-justified
    result, checked against an expected value NOT produced by calling the same production
    calculation on both sides — AGENTS.md's "ONE computation" clarifications); **integration**
    (do connected components preserve identity, ordering, data, and failure behavior across the
    seam — real inputs through real plumbing, external dependencies doubled only where a live one
    is genuinely unavailable, and that doubling's own behavior validated against the real
    dependency's documented/installed contract per requirement 9); **system acceptance** (does the
    operator's complete workflow deliver the required visible outcome, end to end); **runtime
    verification** (does the deployed application, with its ACTUAL dependencies — live vendor,
    live browser, the authorized process entry point — accomplish that outcome). A pass at a
    higher tier never overrides a valid failure demonstrated at a lower one. Adversarial cases
    (requirement 9) apply at every tier, not only the one a change happens to touch. Changing a
    test's expectation to match a new implementation is legitimate ONLY when the required
    behavior itself changed or was previously mis-stated — "the new code behaves differently" is
    not, by itself, a reason; cite the required-behavior basis for the change in the same place
    the test changes.
13. **Proactive repair.** Complete the necessary connected engineering work within the existing
    authorization before stopping — do not pause mid-mission for a separate go-ahead on work
    already authorized, and do not let an unrelated correction (a documentation fix, a drive-by
    cleanup) become an excuse to leave connected active-mission work undone, or the reverse.
    Preserve existing product surfaces (routes, launcher behavior, authorized entry points)
    unless the mission explicitly authorizes removing them.
14. **Final answer.** Report against every requirement above with the exact revision reviewed
    and the supporting evidence for each. Verdict vocabulary is PASS / FAIL / NOT_PROVEN:
    **PASS** requires every required condition actually proven; **FAIL** is any demonstrated
    violation of a required condition, regardless of what else passed; otherwise **NOT_PROVEN**
    for any required condition that is missing proof. Do not report PASS, or claim a mission or
    audit complete, while a required condition is FAIL or NOT_PROVEN.

**Honest limit.** This structures what a review must check and forces the reviewer to look; it
does not mechanically guarantee that a review actually ran, that it ran correctly, or that
following it prevents every failure mode — no document can. Durability comes from keeping the
requirements themselves in the version-controlled repository, not from any promise that reading
them substitutes for applying them to the actual change in front of the reviewer.

---

## Quick commands

| Action | Command |
|--------|---------|
| Measure | `.venv/Scripts/python.exe tools/operating_process_lock.py --measure` |
| Pre-commit gate | `.venv/Scripts/python.exe tools/operating_process_lock.py --pre-commit` |
| Live-checkout report | `.venv/Scripts/python.exe tools/check_live_path_is_main.py` (production should be branch main == origin/main; reports, does not gate the desk — RC-512) |

No env kill-switch: `ED_PROCESS_LOCK_GUARD` cannot disable the hook (RC-450).
