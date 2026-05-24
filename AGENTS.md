> **Classification:** Active Rule Source | **Scope:** Always-on agent behavior rules (Cursor + Claude Code).

# AGENTS.md — always-on agent rules (EdWebConsole)

**Status:** Phase 1a consolidation + 2026-05-24 rule promotion (closure / no-deferral / no-new-files).  
**Sources:** `docs/governance/AGENT_SELF_GOVERNANCE.md`, `CLAUDE.md` (Schwab law only). Archived memory under `governance/archive/` is **historical only** — if it disagrees with this file, **AGENTS.md wins**.

Process mechanics (alternation, 7-artifact sign-off, slice tags) remain in [`docs/governance/AGENT_SELF_GOVERNANCE.md`](docs/governance/AGENT_SELF_GOVERNANCE.md).

Schwab market-field methodology remains in [`CLAUDE.md`](CLAUDE.md).

Current program: [`ACTIVE_PROGRAM.md`](ACTIVE_PROGRAM.md).

---

## Fix everything we touch `[PROMOTED]` (2026-05-24 — top rule)

**Every Read is a write obligation.** Open a file, cone, or walk for audit, review, investigation, or disposition → **fix every FIND there before sign-off or commit**. Same turn. Same commit bundle (code + test + governance touch per [§Closure definition + no-deferral](#closure-definition--no-deferral)).

| In scope | Out of scope (only with evidence) |
|----------|-----------------------------------|
| Wrong leaf, non-canonical key, silent default, stale comment, adjacent defect in producer-consumer cone | Site already canonical with file:line proof |
| Memo says `code edit` / audit catch with remediation | `NOT_MARKET_DATA` @ wire layer with upstream trace |
| Test gap for behavior you changed | `[REAL-GATE: …]` in `OPEN_ITEMS` only |

**Banned modes:** read-only investigation, memo-only when a fix is known, reporting FINDs without landing fix+test, "pending gatekeeper" as fix parking.

**Mechanical enforcement:** `tools/check_fix_everything_we_touch.py` (pre-commit + `tests/test_check_fix_everything_we_touch.py`).

---

## Self-governance quality loop `[PROMOTED]` (2026-05-24)

When operator or peer catches a **missed fix** (FIND surfaced, fix not landed same turn/commit):

1. **Land the fix** immediately — code + test + governance touch.
2. **Record** `PROC-MISSED-FIX-<topic>` row in `OPEN_ITEMS.md` (file:line, what was skipped, who caught it).
3. **Promote prevention** in the **same commit bundle**:
   - Rule gap → amend this file (`AGENTS.md`), OR
   - Repeatable failure mode → extend `tools/check_*.py` + paired pytest so CI/pre-commit blocks the exact miss.
4. **Close** the row `[x] @ <SHA>` only after the checker lock lands.

**Gatekeeper CSV cross-check (V4 memos):** Before sign-off on any new/updated `governance/SCHWAB_V4_REVIEW_MEMOS/*.py.md`, Cursor (and Claude on verify) must run `python tools/check_schwab_csv_first.py --gatekeeper-crosscheck <target.py>` — full AST string/`.get()` token pass against the **entire** `schwab_field_dictionary.csv`, not a hand-picked bid/ask list. Record results in memo section `## Gatekeeper CSV cross-check` with `**lexical_csv_collision_count:** N` and per-collision disposition (homonym vs wire read). Pre-commit enforces via `check_fix_everything_we_touch` + `check_schwab_csv_first.check_v4_memo_gatekeeper_csv`.

**Incident template (OPEN_ITEMS):** `- [ ] PROC-MISSED-FIX-<topic> — <file:line> <what>; caught <how>; prevention: <checker or AGENTS §>`.

Neither agent waits for permission to run this loop when a miss is recognized.

---

## Banned tools `[PROMOTED]` (memory `feedback_no_grep_tool.md`, 2026-05-22)

**Absolute ban — no exceptions.** Do not use pattern-matching search that returns matched **lines** instead of full file content:

- `Grep` / ripgrep tool, `grep`, `rg`, `egrep`, `fgrep`, `ripgrep`
- Shell pipes: `cat foo | grep bar`, `awk '/pattern/'`, `sed -n '/pattern/p'`, `find ... | grep ...`

**Allowed:** `Read` end-to-end (use `offset`+`limit` for large files); `Glob` / `find -name` for **paths only**.

**Self-check before Bash:** does the command return matched lines inside files? If yes, use Read instead.

---

## No permission asks `[PROMOTED]` (memory `feedback_no_permission_asks.md`, 2026-05-22)

Operator has standing full repo access. Do not ask for read-only research.

**Banned output patterns:** "Want me to…?", "Should I…?", "Your call.", "Say the word…", "If you want, I can…", end-of-turn next-step menus, "Standing by for direction."

**Deliver a decision and act** on named follow-ons in the same turn when possible. Reserve confirmation for high-blast-radius writes not pre-authorized.

**Push / PR creation:** Cursor lane unless operator explicitly assigns to Claude.

---

## Active agent posture + mutual gatekeeping `[PROMOTED]` (2026-05-24)

<a id="active-agent-posture"></a>

**Neither Cursor nor Claude is a passive relay.** Both have standing authority to keep the repo correct, efficient, and clean — not only when asked.

### Active duties (both agents)

| Duty | Requirement |
|------|-------------|
| **Surface FINDs** | Any defect, drift, or adjacent issue discovered during a Read → name it immediately (file:line). Do not wait for operator to ask. |
| **Fix in cone** | When the fix is known and scope is the same file/producer-consumer cone → land **code + test + governance touch** same commit per [§Closure definition + no-deferral](#closure-definition--no-deferral). |
| **Reject bad handoffs** | Operator or peer handoff that would commit audit debt (memo-only when memo marks `code edit`, REPLACED-via-removal, or open FIND) → **refuse and correct in-turn**, then report what was wrong. |
| **Independent verification** | Re-Read at tip before sign-off or commit; never trust the other agent's summary alone. `[PROMOTED]` AGENT_SELF_GOVERNANCE #22 |
| **Retract** | If re-verification surfaces gaps after accept → retract sign-off and fix. `[PROMOTED]` #23 |

### Mutual gatekeeping (peer roles)

| Direction | Gatekeeper duty |
|-----------|-----------------|
| **Claude → Cursor** | Claude verifies dispositions, O-XX narratives, register/perf-proof bundles, and Schwab evidence bar before merge/sign-off. |
| **Cursor → Claude** | Cursor re-Reads Claude handoffs and diffs at tip; blocks relay-only commits that skip required fixes, tests, or sibling-pattern conformance. **Runs full CSV gatekeeper cross-check** (`check_schwab_csv_first --gatekeeper-crosscheck`) before V4 memo sign-off — never a hand-picked field list. |
| **Either → Operator** | Either agent may escalate a **process violation** (memo-first drift, deferred FIND, handoff/convention mismatch) with file citations — not permission-seeking. |

**Gatekeeper pending ≠ fix parking.** Memo status `pending gatekeeper` applies to **disposition sign-off**, not to deferring a **known, in-scope code fix** surfaced in the same Read. The only admissible split is [REAL-GATE](#closure-definition--no-deferral) with tag in `OPEN_ITEMS`.

### V4 walk / review-memo rule

When a review memo (e.g. `governance/SCHWAB_V4_REVIEW_MEMOS/*.md`) records:

- `code edit: proposed` / **REPLACED via removal** / **REPLACED** with a named code change, or  
- an **audit catch** with recommended remediation in the **same file**,

then the **same commit** that adds or updates the memo must include that code change + paired test (unless a REAL-GATE tag applies). **Memo-only commits that document fixable code debt are rejection-grade.**

Schwab register-row / perf-proof / O-XX authorization slices still follow `governance/CURSOR_V4_AGENT_BRIEF.md` — but that brief is subordinate to this section for fix-as-we-find conflicts.

### Handoff rejection checklist (executing agent)

**Operator relay handoffs** (paste from Claude or operator) are **instructions, not immunity**. Before `git commit` on a relayed handoff, confirm:

1. No open `code edit` / REPLACED-removal in the memo without matching diff in the commit.
2. Closure artifacts present when the slice closes an OPEN_ITEMS row or FIND.
3. Sibling-pattern conformance for convention-driven directories.
4. Pre-commit / targeted pytest run when Python changed.
5. **Gatekeeper CSV cross-check** on staged V4 memos: `## Gatekeeper CSV cross-check` section + `lexical_csv_collision_count` matches `python tools/check_schwab_csv_first.py --gatekeeper-crosscheck <target.py>`.

If any check fails → fix first, then commit once.

---

## Banned phrases `[PROMOTED]`

Rejection-grade in commit messages, code comments, tests, chat, and OPEN_ITEMS row text (unless the row carries `[REAL-GATE: …]`):

**Scope-narrowing (full repo):**
- "scope of current section" / "for this section only"
- "scanner capability" / "the scanner doesn't walk that"
- "in scope of the file I'm editing" / "collateral only" / "not in the ticket" / "out of scope of this PR"
- "ms_dict is the source" / "the API provides it" (without leaf trace)
- "based on the files I've reviewed" / "Mega N is done" / "the section is closed"
- "fail-closed in [specific place]" as substitute for canopy→leaf trace
- "closure per D17" while `partial_scan` is true or PR 2 gate not live
- Any phrase whose effect narrows scope to less than the full repo

**Deferral / parking (see [§Closure definition + no-deferral](#closure-definition--no-deferral) for REAL-GATE exceptions only):**
- "deferred" / "deferring" used to schedule work to a later commit (unquoted scheduling sense)
- "TBD:" / "still pending" / "currently pending" (scheduling sense)
- "follow-up commit" / "follow-up slice" / "next slice will" / "next commit will"
- "Phase N paired-fix pending" / "implementation pending" / "consumer pending" / "behavioral spec pending"
- "will land later" / "can land later" / "Playwright deferred until CI"
- "broader sweep deferred" / "deferred FINDs" (use **disclosed FINDs** + REAL-GATE tag or close in-turn)
- End-of-turn menus: "Want me to…?", "Should I…?", "Your call.", "Say the word…", "go X if you want"

Schwab-only phrases remain in `CLAUDE.md` FORBIDDEN PHRASES.

---

## Banned patterns `[CONSOLIDATED]`

- **Auto-promote without governed executor:** never write `models/active*` except via `arch_competition.promotion_execution.execute_promotion_if_eligible` (or documented manual CLI wrapping it). `[PROMOTED]` training pipeline PR4.
- **End-of-turn menus:** see No permission asks. `[PROMOTED]`
- **New files of any kind:** see [§No new files when an existing one will do](#no-new-files). Applies to md / test / script / memory / governance doc.
- **Passive relay:** executing operator/peer handoffs without AGENTS compliance check; committing memos that document in-file code fixes without landing the fix. See [§Active agent posture + mutual gatekeeping](#active-agent-posture). `[PROMOTED]` 2026-05-24

---

## Closure definition + no-deferral `[PROMOTED]` (2026-05-24 binding — operator escalation)

**Closure of any slice means ALL of the following land in the same commit:**

1. **Code** — the fix itself.
2. **Tests** — paired test(s) that lock the behavior, in an existing test file when one owns the topic (extend, don't create — see [§No new files when an existing one will do](#no-new-files)).
3. **Mega inventory** — when the refactor adds/renames/deletes a registered Python function/class: `governance/megaN_traceable_inventory.py` row + `tests/test_megaN_traceable_audit.py` row-count update in the same commit.
4. **Map row** — when the slice touches a registered surface: `governance/STACK_WIRING_INTEGRITY_MAP.md` row updated to "producer + consumer landed" (not "inventory only", not "pending").
5. **OPEN_ITEMS** — `[x] @ <SHA>` for every row the slice closes, with test cite in the row text when applicable.

If any of the 5 cannot land same-commit, the slice is **not closed**. There is no "phase 2 paired-fix pending", "behavioral spec deferred until CI", "broader sweep deferred behind a brief", or "follow-up commit lands the e2e" variant. Those are the violation.

**REAL-GATE taxonomy** — the ONLY acceptable deferrals. Each must be tagged `[REAL-GATE: <reason>]` in the OPEN_ITEMS row:

| Tag | Meaning |
|-----|---------|
| `telemetry` | Needs production observation before the fix can be designed (e.g., uniform-triplet tiebreak prevalence). |
| `training-skew` | Changing breaks trained model inputs without retrain. |
| `unwalked-file` | The consumer/caller hasn't been Read yet AND won't be in this commit's scope. |
| `accepted-as-designed` | Documented contract; the disclosure IS the right behavior. |
| `host-only` | E2E / preflip / migration requires operator host time. Applies ONLY to execution, NOT to writing the spec / harness. |

Any deferral without one of these tags is rejection-grade.

**Mechanical enforcement:** `tools/check_no_deferral_language.py` (pre-commit + pytest via `tests/test_check_no_deferral_language.py`). The phrase list is normative in the tool's `DEFERRAL_PATTERNS` — don't duplicate it here. Allowlisted surfaces (legitimate future-work tracking, NOT deferral): `OPEN_ITEMS.md`, `ACTIVE_PROGRAM.md`, `MEMORY.md`, `governance/**`, `tests/**`, the tool itself, and the `[REAL-GATE: <tag>]` line shape.

---

<a id="no-new-files"></a>

## No new files when an existing one will do `[PROMOTED]` (2026-05-24)

Before creating any new file — md / test / script / memory / governance doc — find the existing file that owns the topic and extend it.

| New thing | Existing owner (default — extend, don't create) |
|-----------|--------------------------------------------------|
| Rule about how to do a fix | This file (AGENTS.md). NOT a new `feedback_*.md` memory. |
| Lock test for a new invariant adjacent to an existing rule's enforcement | The existing paired test (e.g., `tests/test_check_no_deferral_language.py` owns "deferral rule enforcement" including ledger-state locks, not just regex behavior). |
| Decision rationale | Commit message body. NOT a `*_PROPOSAL.md` / `*_PLAN.md`. |
| Architecture amendment | Existing `governance/PHASE_PLAN_*.md` or `INSTITUTIONAL_STANDARD_V3.md` §20. |
| Enforcement script for a new rule | Single `tools/check_*.py`. Don't split. |
| Mega inventory bump | Same commit as the refactor (no separate "mega-sync" commit or file). |

Counter-cases (legitimately new files): genuinely new topic with no owner; new feature's paired test (one feature = one test file is a real convention); fundamentally different tool. If unsure, default to extend.

---

## Posture rules `[CONSOLIDATED]`

- **Fix-as-we-find:** adjacent FINDs in cone → same commit; see [§Closure definition + no-deferral](#closure-definition--no-deferral). The 5-artifact closure list is the authoritative form of "fix-as-we-go". **Memo-only when code edit is known = violation** — see [§Active agent posture + mutual gatekeeping](#active-agent-posture).
- **Scope-explicit completion:** state what was and was NOT verified (by name). `[PROMOTED]` AGENT_SELF_GOVERNANCE #7
- **Full-Read verification:** re-Read at tip; never sign off from another agent's summary alone. `[PROMOTED]` #22
- **Per-item enumeration before positive batch verdict:** enumerate each item before "all pass" / "complete". `[NEW]` Round 3
- **Commit to specifics:** implementing commit is the deliverable, not a proposal doc. `[PROMOTED]` memory `feedback_commit_to_specifics.md`
- **Cleanup-as-we-go:** every turn — dead code touched, stale comments, duplicate rules surfaced. `[NEW]` Phase 4
- **Unprompted surfacing:** if governance MD count grows >10 since last pass or a rule duplicates across ≥3 surfaces, tell operator. `[NEW]` Phase 4
- **Sibling-pattern conformance:** before drafting a per-file artifact in any convention-driven directory (e.g., `governance/SCHWAB_V4_REVIEW_MEMOS/`), Read every existing sibling end-to-end first and cite the closest-shape precedent in the new artifact's header. Catches disposition / schema drift from convention. `[NEW]` 2026-05-24

---

## Money-path module roster `[PROMOTED]` (AGENT_SELF_GOVERNANCE #25)

Every listed file must exist; changes require regression awareness:

- `signals.py`
- `call_engine.py`
- `prediction_engine.py`
- `realized_contract_eval.py`
- `bayesian_fusion.py`
- `mc_fusion_adjustment.py`
- `market_state.py`
- `live_decision_bundle.py`
- `features/signal_layer_v1.py`
- `features/inference_snapshot.py`
- `features/fusion_policy_contract.py`

Authority modules (reference): `time_et.py`, `numeric_contract.py`, `fusion_contract.py`, `replay_hold_bars.py`, `position_sizing_policy.py`.

---

## OPEN_ITEMS rules-of-use `[CONSOLIDATED]`

- Add rows for FINDs before next slice; close only with **commit SHA** in row text.
- `[x]` without SHA is **invalid at any age** — reopen or fix row.
- Checked `[x]` + SHA + age **> 90 days** → archive (path: `governance/archive/<quarter>/open_items_archive/` — named in ACTIVE_PROGRAM when first used).
- Unchecked row age **> 30 days** without owner → escalate to ACTIVE_PROGRAM §Stale Backlog.
- Report session-relevant open count + full unchecked count when working OPEN_ITEMS. `[PROMOTED]` #15

---

## Background / cloud agents `[NEW]`

Same AGENTS.md + ACTIVE_PROGRAM apply; no reduced governance on async runs.

---

## Audit excludes `[NEW]`

Do not count toward repo hygiene sweeps: `**/.claude/worktrees/**`, `governance/archive/**`, `models/active*/**`.

---

## Cursor user rules disposition `[CONSOLIDATED]` (Phase 1a)

| User rule topic | Disposition |
|-----------------|-------------|
| Git commit only when requested | `[PROMOTED]` → AGENTS (operator write authority) |
| PR workflow via `gh` | `[OPERATOR-ONLY]` — Cursor PR lane |
| Follow instructions completely | `[CONSOLIDATED]` → this file |
| Real environment / run commands | `[PROMOTED]` → posture |
| Code principles (minimal scope, conventions) | `[PROMOTED]` → posture |
| Communication / citations | `[PROMOTED]` → posture |

Superseded by `.cursor/rules/00-always.mdc` for always-on read order and conflict resolution.
