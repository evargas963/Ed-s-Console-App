# AGENTS.md — always-on agent rules (EdWebConsole)

**Status:** Phase 1a consolidation (2026-05-23)  
**Sources:** `docs/governance/AGENT_SELF_GOVERNANCE.md`, `CLAUDE.md`, Claude memory files, Cursor user rules (see disposition in `ACTIVE_PROGRAM.md` §Tool-Specific Notes).

Process mechanics (alternation, 7-artifact sign-off, slice tags) remain in [`docs/governance/AGENT_SELF_GOVERNANCE.md`](docs/governance/AGENT_SELF_GOVERNANCE.md).

Schwab market-field methodology remains in [`CLAUDE.md`](CLAUDE.md).

Current program: [`ACTIVE_PROGRAM.md`](ACTIVE_PROGRAM.md).

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

## Banned phrases `[PROMOTED]` (`CLAUDE.md` FORBIDDEN PHRASES)

Rejection-grade if used to narrow scope below full-repo discipline:

- "scope of current section" / "for this section only"
- "scanner capability" / "the scanner doesn't walk that"
- "in scope of the file I'm editing" / "collateral only" / "not in the ticket" / "out of scope of this PR"
- "ms_dict is the source" / "the API provides it" (without leaf trace)
- "based on the files I've reviewed" / "Mega N is done" / "the section is closed"
- "fail-closed in [specific place]" as substitute for canopy→leaf trace
- "closure per D17" while `partial_scan` is true or PR 2 gate not live
- Any phrase whose effect narrows scope to less than the full repo

---

## Banned patterns `[CONSOLIDATED]`

- **Auto-promote without governed executor:** never write `models/active*` except via `arch_competition.promotion_execution.execute_promotion_if_eligible` (or documented manual CLI wrapping it). `[PROMOTED]` training pipeline PR4.
- **End-of-turn menus:** see No permission asks. `[PROMOTED]`
- **New governance MD deliverables:** no standalone `*_PLAN.md` / proposal MDs; amend existing docs or commit message. `[PROMOTED]` memory `feedback_no_new_md_deliverables.md`

---

## Posture rules `[CONSOLIDATED]`

- **Fix-as-we-find:** adjacent FINDs in cone → same commit or OPEN_ITEMS row before next slice. `[PROMOTED]` memory `feedback_fix_as_we_find_scope_policy.md`
- **Scope-explicit completion:** state what was and was NOT verified (by name). `[PROMOTED]` AGENT_SELF_GOVERNANCE #7
- **Full-Read verification:** re-Read at tip; never sign off from another agent's summary alone. `[PROMOTED]` #22
- **Per-item enumeration before positive batch verdict:** enumerate each item before "all pass" / "complete". `[NEW]` Round 3
- **Commit to specifics:** implementing commit is the deliverable, not a proposal doc. `[PROMOTED]` memory `feedback_commit_to_specifics.md`
- **Cleanup-as-we-go:** every turn — dead code touched, stale comments, duplicate rules surfaced. `[NEW]` Phase 4
- **Unprompted surfacing:** if governance MD count grows >10 since last pass or a rule duplicates across ≥3 surfaces, tell operator. `[NEW]` Phase 4

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
