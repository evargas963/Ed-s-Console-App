> **Classification:** Active Rule Source | **Scope:** Always-on agent behavior rules (Cursor + Claude Code).

# AGENTS.md — always-on agent rules (EdWebConsole)

**Status:** Phase 1a consolidation + 2026-05-24 rule promotion (closure / no-deferral / no-new-files).  
**Sources:** `docs/governance/AGENT_SELF_GOVERNANCE.md`, `CLAUDE.md` (Schwab law only). Archived memory under `governance/archive/` is **historical only** — if it disagrees with this file, **AGENTS.md wins**.

Process mechanics (alternation, 7-artifact sign-off, slice tags) remain in [`docs/governance/AGENT_SELF_GOVERNANCE.md`](docs/governance/AGENT_SELF_GOVERNANCE.md).

Schwab market-field methodology remains in [`CLAUDE.md`](CLAUDE.md).

Current program: [`ACTIVE_PROGRAM.md`](ACTIVE_PROGRAM.md).

---

## Institutional-grade code gate `[PROMOTED]` (2026-05-27 — operator binding, top rule)

**Before writing or landing code:** ask whether the change is institutional-grade — the standard an MIT professor would accept for a production trading system (correctness, uniformity, fail-closed where appropriate, tests, no silent partial behavior). **Research when uncertain** (Read end-to-end, trace producer→consumer, check enrollment and data contracts). If the answer is not **yes**, **stop** and fix the design before coding.

| Must hold | Failure mode |
|-----------|----------------|
| Operator intent wired in code, not comments only | "Policy by design" that contradicts stated product rules |
| Train-success-live for ML scheduler targets | Train completes but `models/active/` empty without explicit operator opt-out |
| Parallel and cascade obey the same row/scoring contract where compared | Asymmetric degrade/skip without documented operator approval |
| Confluence-only symbols excluded from training | `panel_auto` tickers trained like tradeables |

**Partial enforcement:** paired tests for promotion policy, enrollment filter, and scheduler outcomes; operator catch-net for intent drift.

---

## Do not lie to the operator `[PROMOTED]` (2026-05-24 — binding, hard rule, no exceptions)

**Never present unverified claims as verified. Never soften known bad news into reassurance. Never frame a clean-looking artifact (memo, green checker, handoff, status note) as proof that the underlying work was done.**

| Banned behavior | What it actually is |
|-----------------|----------------------|
| "Verified" / "confirmed" without evidence cite | Asserting certainty without doing the verification |
| "This will prevent X" about a tool/lock | Selling a partial guard as a full guarantee |
| "All sites NOT_MARKET_DATA" without full CSV cross-check | Hand-picked spot-check framed as audit |
| Omitting a known limit when describing a fix | Lie by selective framing |
| "Standing by" / clean handoff while a known FIND is unfixed | Performing readiness; the work is incomplete |
| Restating operator's view back as if independently arrived at | Agreement theater |
| "Section present" / "heading at L<n>" without reading the body | Treating structure as content — the `§File delete gatekeeper` slip (title said gatekeeper, body said catch-net; heading existed, body contradicted intent) |
| "Per [subagent / Cursor / peer] summary" without source-Read | Echoing upstream as fact — the zero-refs slip (accepted "zero references outside itself" without enumerating; 10 referrers existed) |
| "Looks clean" / "appears orphaned" / "should be safe" as verdict | Inference framed as verification; verdicts require enumerated tables or recomputed values, not impressions |
| Tool exit 0 cited as proof of correctness | Tool ran; doesn't prove the right thing was checked. Cite both the tool AND the intent it verified |
| Count match (rows / files / tests pass) cited as content match | Cardinality alignment ≠ semantic alignment; 174459 rows can sum correctly while individual dispositions are wrong |
| "Same gap applies" / "parallel pattern" / "extends to" without same-turn verification | Scope-extension lie — the bid/ask parallel slip (2026-05-25: claimed server.py L2328-2333 had "same vocab+AST gap" as the verified L2334-2341 set, then admitted "haven't done it this turn"). An unverified parallel observation is just an unverified claim wearing a humility costume. |
| "Haven't verified" / "haven't checked" / "separate verification" / "out of scope of this turn" as live caveats in the body of a response | The admission is the violation. If the claim couldn't be verified in-turn, the claim shouldn't be in the response — verify or omit. Caveats narrate the gap; they don't close it. |

**When uncertain, say uncertain.** When a tool or rule has a known limit, name the limit in the same sentence that describes the tool. When operator catches a slip, correct in the same turn, not the next.

**Verdict discipline (universal):** Before any verdict word — `verified`, `confirmed`, `correct`, `matches`, `ready`, `complete`, `safe` — the response must carry either (a) an enumerated table with file:line / SHA / tool-exit-code citations, (b) a recomputed value with the recompute command shown, or (c) explicit attribution to the upstream source the claim came from (and naming that source as unverified-by-me if so). Heading existence, tool exit 0, count match, and summary receipt are necessary inputs to a verdict, never the verdict itself.

**Verify-in-turn-or-omit (universal):** Every factual claim, parallel observation, scope-extension note, "while we're here" remark, and "same pattern applies" comment carries the same evidence bar as the primary finding. If the claim can be verified in-turn (Read, count, recompute) → do it before posting. If it can't → omit. "Haven't verified" / "haven't checked" / "separate verification needed" / "out of scope of this turn" caveats are themselves the violation — they narrate the gap instead of closing it, and they put the burden of catch on the operator. Future-tense verification ("would need to check") = current-turn omission obligation.

**Honest limit of mechanical enforcement:** Pre-commit / commit-msg checkers can catch surface patterns (e.g., "verified" without evidence cite, "guarantees" without a cited mechanism). They **cannot** catch omission, framing, soft-selling, or false reassurance on natural language. The primary enforcement is **operator-as-catch-net + agent discipline**. The rule binds regardless of how partial mechanical coverage is. Adding a regex check does not discharge the obligation.

**Partial mechanical enforcement:** `tools/check_fix_everything_we_touch.py` — commit-msg patterns for `verified` / `confirmed` / `guarantee(s)` / `all clear` without an evidence cite on the same line (`tests/…`, `@` SHA, or `:line`). Paired test: `tests/test_check_fix_everything_we_touch.py`.

This rule sits above §Fix everything we touch because lying makes every other rule unreliable: a fix claimed but not made, a test claimed but not added, a deletion claimed but not executed — all of those are application failures of this one rule.

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

## Code-first / no governance-only turn `[PROMOTED]` (2026-05-25 — operator escalation)

**Every turn must land application code + paired tests** unless the operator explicitly assigns a governance-only lane (e.g. `go SCHWAB FULL REPO — governance PR only`, register regen in operator PowerShell lane with no agent code scope).

| Required in the turn | Banned as the sole deliverable |
|----------------------|--------------------------------|
| Producer / consumer / money-path fix (`server.py`, `signals.py`, `call_engine.py`, `market_state.py`, `static/index.html`, fusion stack, order flow, etc.) | Register regen, scanner cardinality tuning, CI workflow pin, meta/scoreboard repin, OPEN_ITEMS or ACTIVE_PROGRAM text-only |
| Paired test in an **existing** test file for the behavior changed | Scanner-only `pattern_kind`, memo-only disposition, inventory/report without wire or UI fix |

**Schwab scanner / register work** is admissible only **paired** with a code fix in the **same commit** or the immediately adjacent commit in the **same session** (same FIND family — producer or consumer cone). A scanner gap on code that already reads the correct Schwab leaf is **bookkeeping**, not a product bug; it must not block or replace app-quality fixes.

**Program anchor:** [`ACTIVE_PROGRAM.md`](ACTIVE_PROGRAM.md) §Active program (code-first posture).

**Partial mechanical enforcement:** `tests/test_governance_consolidation.py::test_agents_code_first_no_governance_only_section` — AGENTS body must carry this section.

---

## Action-not-documentation `[PROMOTED]` (2026-05-25 — operator escalation)

**No documentation without code-fix scope.** Every plan, phase, memo, audit, OPEN_ITEMS row, or process artifact must carry CODE-FIX scope — paired commit SHA, paired test ID, OR named code target (`file:line`) for the next action. Artifacts exist to drive code change; they are not the deliverable, the code they cite is. Pure description without action is the violation.

| Required content (per artifact section) | Banned as sole content |
|-----------------------------------------|------------------------|
| Per FIND / issue: paired-fix SHA, paired test, OR `[REAL-GATE: <tag>]` per [§Closure definition + no-deferral](#closure-definition--no-deferral) | Audits / memos / phase docs that list FINDs without per-FIND remediation cite |
| Per phase in a phase plan: code commit SHA when closed; named `file:line` code target when open | Phase plans with goal/scope but zero code-target lines |
| OPEN_ITEMS new rows: `**Fix direction:**` AND named target file:line | Rows that describe risk without naming the consumer-side or producer-side code that needs editing |
| Memos: code-fix scope same commit ([§Fix everything we touch](#fix-everything-we-touch)) | Doc-only memo handoffs — re-affirmed |

**This rule is the artifact-content corollary of §Code-first.** §Code-first bans governance-only turns at the commit level. This rule bans governance-only *content* inside artifacts: a phase doc that lists six phases without code-fix scope per phase, an audit that flags ten FINDs without per-FIND remediation cite, a memo that documents state without naming the code change — all violations even if shipped alongside other code.

**Operator intent (2026-05-25):** "ALL PLANS, ALL PHASES, MEMOS, AUDITS, ETC. MUST CONTAIN ACTION TO FIX ISSUES. THEY CAN NEVER BE JUST DOCUMENTATION. WE MUST PRODUCE CODE THAT CONTINUES TO MOVE THE APP FORWARD."

**Honest limit:** Rule files (`AGENTS.md`, `CLAUDE.md`, `MEMORY.md`), sign-off pins (`governance/artifacts/*.json`), and operator-assigned governance-only lanes are not in scope. The §Code-first existing carve-outs apply identically here.

**Mechanical enforcement (partial):** `tools/check_fix_everything_we_touch.py` — staged commits where only governance artifacts (`governance/audits/**`, `governance/SCHWAB_V4_REVIEW_MEMOS/**`, `governance/PHASE_PLAN_*.md`) change and those artifacts contain action language (`FIND-`, `fix direction`, `Risk:`, `Remaining:`, `Open:`, `TODO`) WITHOUT paired code change (`.py` / `.html` / `.js` / `.css`) fail at pre-commit. Paired test: `tests/test_check_fix_everything_we_touch.py`.

---

## Storage-needs-consumer `[PROMOTED]` (2026-05-25 — operator escalation)

**No writer without a consumer.** Every new persistence path (new DB table + writer, new file writer, new emit-to-API path) must land in the same commit with BOTH:

1. **At least one production caller** that invokes the writer from a live code path (not just tests, not just a helper definition).
2. **At least one consumer** — reader API used somewhere visible, scheduled-audit script that reads the rows, operator-visible surface (UI element, log summary, alert), or pytest assertion that exercises consumed-row content.

**Why this rule exists (empirical 2026-05-25/26):** the production DB had 4 tables (`level_crosses`, `confluence_log`, `model_accuracy`, `session_log`) plus `news_events` with full schemas and writer methods but ZERO production callers (one had a guarded call site with no downstream reader). They were scaffolded — closure-rule artifacts (code + tests) could have been ticked — but never wired to a live path. Result: real engineering time spent on storage that delivered zero operator value. The `calibration_decision_log` env-gate gap also went 24 days undetected because no consumer surfaced the rate — Pass 3 added `/api/ops/calibration_rowcount` + Calibration health card on `static/ops.html` (rate-vs-expected-WARN). Pass 4 wired `level_crosses`; Pass 5a/5b wired `model_accuracy`; Passes 6 / 7 / 8 dropped `session_log` / `confluence_log` / `news_events` (no defensible consumer). One remaining dormant writer (`logging_universe_import_legacy_json_tickers`) is a legacy importer — REAL-GATE-tracked.

| Required in the same commit as a new writer | Banned as the sole deliverable |
|---------------------------------------------|--------------------------------|
| Live producer call from `server.py` / `market_state` / `signals` / scheduler / equivalent | New `INSERT INTO` helper with only test callers |
| Consumer: reader function used by UI/API/log/alert, OR scheduled audit script, OR test that asserts on row content meaningful to operator | Writer-only ship; "consumer in next slice" |
| Throttle / debounce / state-management design for tick-rate writers | Per-tick INSERT without rate limit |

**This is the artifact-content corollary of §Action-not-documentation extended to PERSISTENCE.** A new writer that nobody calls is doc-only code: it documents intent (a table can exist) without producing operator value (no rows, no reads, no surface).

**Operator intent (2026-05-25):** "WE BETTER NOT HAVE GOVERNANCE, OR RULES, ETC WITH NO PATH TO CODE CHANGES UPDATE… WHATEVER NEEDS TO BE DONE PERIOD."

**Honest limit:** Refactors that move an existing writer (no new persistence path), schema-only migrations preparing for a future slice tagged `[REAL-GATE: <tag>]`, and writer additions inside an already-consumed table family (where the consumer already exists upstream) are not in scope. The rule narrows to NEW persistence paths.

**Mechanical enforcement:** `tools/check_fix_everything_we_touch.py` — staged `db.py` (or other persistence-layer module) adding new `INSERT INTO <table>` statements without a paired non-`db.py` non-`tests/` `.py` file in the same commit fails at pre-commit. Paired test: `tests/test_check_fix_everything_we_touch.py`.

**Source-of-truth artifact:** `governance/artifacts/persistence_consumer_map.json`, generated by `tools/audit_persistence_consumers.py` (AST-walks `db.py` + `calibration/writer.py`; one row per writer with `tables_written`, `production_callers`, `read_consumers`, `status`). The map is the authoritative ledger of which writers have callers and which tables have readers. Any commit that edits `db.py`, `calibration/writer.py`, or the audit tool itself must re-stage the map in the same commit; pre-commit blocks via `check_persistence_map_fresh`. Paired test: `tests/test_audit_persistence_consumers.py`.

**Honest limit on the mechanical lock:** the pre-commit gate is `caller + (reader symbol OR tracked REAL-GATE row)`, not full semantic consumer proof. A logger that writes a row and an endpoint that returns the row both satisfy the lock; whether the row is *meaningfully consumed by an operator-visible decision* is product judgment that the lock cannot enforce.

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

## File delete gatekeeper `[PROMOTED]` (2026-05-25)

<a id="file-delete-gatekeeper"></a>

**The agent is gatekeeper and own catch-net** — block bad deletes before they reach the operator; do not rely on the operator to catch a missed enumeration. Enumeration first, verdict second.

Before any delete, archive verdict, or **"safe to delete"** / **"zero references"** claim:

1. **Glob** the basename across the repo (paths only).
2. **Read** every hit — full file when small; at minimum the registry/allowlist block that names the path.
3. **Publish an in-chat referrer table:** `path | role | classification` where classification is `runtime import/exec`, `tooling allowlist/registry`, or `historical dead pointer`.
4. **Verdict only after the table is complete** — per-item enumeration before any positive batch delete claim.
5. **Delete = multi-file cone closure** in one commit: removed file + every tooling allowlist/registry that names it. Historical audit JSON and archived memory are exempt (dead pointers only).

**Banned without referrer table:** "zero references outside itself", "orphan/self-referential only", "safe single-slice delete", "safe-delete count: N" (N > 0).

**Subagent/explore summaries are leads, not verdicts** — re-Read or independently enumerate before sign-off.

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

**ML scheduler train-success-live (operator 2026-05-27):** For tickers that complete train + governed eval without `failed_closed`, closure requires `models/active/{TICKER}/` refreshed in the **same scheduler run** via `execute_promotion_if_eligible` (default ON). Outcome `promote_ok` or `trained` without `promoted: true` in the training report is **not closed** for that ticker. Panic-only opt-out: `ED_DISABLE_AUTO_PROMOTE=1` or `ED_SCHEDULER_AUTO_PROMOTE=0`.

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
