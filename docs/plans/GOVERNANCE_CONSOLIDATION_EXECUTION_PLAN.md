# EdWebConsole Governance Consolidation & Repo Cleanup — Final Execution-Ready Plan

**Date:** 2026-05-23 (Round 3 final)  
**Status:** Ratified by Cursor and Claude Code through Round 3; **codified** in-repo for execution  
**Tip at codification:** `230724a`  
**Origin sync:** Pushed via TRAINING-PIPELINE-PUSH-REVIEW on 2026-05-21/23  
**Pytest:** 2619 passed at tip, 0 failed  
**Triangulation:** Complete — no further rounds required before Phase 0

**Authority:** This document is the execution source of truth for consolidation. Until `ACTIVE_PROGRAM.md` lands in Phase 1a, agents treat this plan as the active program definition for governance work.

---

## Operator decisions (confirm to unlock Phase 0 execution)

| # | Decision | Agent default | Operator |
|---|----------|---------------|----------|
| 1 | Branch strategy | **Resolved** — push-first executed 2026-05-23 | — |
| 2 | V4 register authority | Tracked `governance/artifacts/schwab_v4_register_build_meta.json`; CSV operator-local | Confirm or override |
| 3 | OPEN_ITEMS aging | `[x]` + SHA + age > 90d → archive; unchecked > 30d no owner → ACTIVE_PROGRAM §Stale Backlog; `[x]` without SHA = invalid at any age | Confirm or override |
| 4 | V4 Schwab Universal Coverage = active program | Yes | Confirm |
| 5 | Training Pipeline PR5–PR7 = concurrent epic | Yes (PR1–PR4.1 landed and pushed) | Confirm |
| 6 | Deferred list | G-series, V3 INF-1-4, Coverage Proof Phase 2, Pilot v1.1 — operator confirms/amends | Confirm |

---

## Target architecture (ratified)

```text
EdWebConsole/
├── AGENTS.md                              ← always-on (Cursor via .mdc; Claude Code TBD Phase 0 test)
├── ACTIVE_PROGRAM.md                      ← always-on
├── CLAUDE.md                              ← Schwab program-specific
├── .cursor/rules/00-always.mdc            ← Cursor mirror (25-40 lines)
└── docs/governance/AGENT_SELF_GOVERNANCE.md  ← procedural, on-demand
```

### Boundary block

- **AGENTS.md** — Detectable violations: banned tools (grep/rg/awk-pattern/sed-pattern), banned phrases (CLAUDE.md FORBIDDEN PHRASES, permission-ask idioms), banned patterns (auto-promote without governed executor, end-of-turn menus), posture rules (fix-as-we-find, scope-explicit completion, full-Read verification, per-item enumeration before positive batch verdict), money-path roster, OPEN_ITEMS rules (add/close/SHA/aging).
- **AGENT_SELF_GOVERNANCE.md** — Process mechanics: alternation cycle, 7-artifact sign-off, ledger conventions, slice tags.
- **CLAUDE.md** — Schwab methodology: Read-not-scan, canopy→trunk→branch→leaf, V4 anchor.
- **ACTIVE_PROGRAM.md** — Current work: active program, concurrent epic, deferred list, conflict resolutions, known risks, host-vs-git pointer to [`docs/host/`](../host/README.md).

### Memory disposition

Archive `~/.claude/projects/.../memory/` → `governance/archive/2026-Q2/memory_archive/` via `git mv`. **No deletion.** Phase 1c: thin `MEMORY.md` + rewrite archived triggers from rule-numbers to topic-names.

### `.cursor/rules/00-always.mdc` spec (25-40 lines)

- `alwaysApply: true` + description
- Read order: ACTIVE_PROGRAM → AGENTS → CLAUDE (when Schwab)
- Conflict resolution: epic in ACTIVE_PROGRAM; AGENTS wins behavior; CLAUDE wins Schwab; project > user rules; MCP tool-scoped (`move_agent_to_root` operational only); Skills task-scoped, do not override AGENTS
- Multi-file precedence: single always-apply until further notice; later: project > user; alwaysApply > glob; specific glob wins
- Workspace-root: `move_agent_to_root` if not in EdWebConsole
- No-grep ban verbatim (~7 lines)
- No-permission-asks ban verbatim (~7 lines)
- Do not treat `governance/*.md` or `docs/plans/*.md` as binding unless ACTIVE_PROGRAM or AGENTS points there **for the current epic**

### Promotion categories

`[PROMOTED]` | `[CONSOLIDATED]` | `[NEW]` | `[STALE]` | `[OPERATOR-ONLY]` — orthogonal tags allowed.

---

## Closed before consolidation

| Item | Status |
|------|--------|
| PR4.1 follow-up | Committed `8feab6b` / `cd7d615`, pushed |
| Push-first | Done 2026-05-23 |
| TRAINING-PIPELINE-PUSH-REVIEW | Closed |
| Phase 3a.1 `scheduler_log_loss_winner` | **Closed @ `4cf18c0+`** — `promotion_decision_record` and eval dashboard use `scheduler_log_loss_winner`; not ambiguous `"winner"` |

---

## Phase 0 — Prerequisites

1. ✅ Pytest green — 2619 passed.
2. Read `.github/workflows/schwab-csv-first.yml` end-to-end; hardcoded paths.
3. Read 30th memory file.
4. Baseline snapshot at **actual HEAD** (line counts, `.py` per dir, memory count, worktree disk).
5. Claude Code AGENTS.md auto-load test (marker file; pass/fail per plan tightening).
6. Cursor `.mdc` always-apply test.
7. AST-walk governance path anchors → "do not rename" list.
8. Cursor user rules export.
9. Branch decision — satisfied if pushed; push again if new work before 1a.
10. OPEN_ITEMS rows **host-enable only:** (a) preflip e2e, (b) live_reload on console URL. No PR4.1 rows.

**Phase 0.5:** Lightweight classification spreadsheet (AGENT_SELF_GOVERNANCE + CLAUDE + 30 memories + exported user rules).

**Phase 0 gate:** 1–10 + 0.5 complete; auto-load results documented; baseline at HEAD.

---

## Phase 1 — Rule consolidation

### 1a (one commit)

- `AGENTS.md`, `ACTIVE_PROGRAM.md`, `.cursor/rules/00-always.mdc`
- `tests/test_governance_consolidation.py` (exists, alwaysApply, pointers, excerpt-hash no-grep + no-permission-asks, stubs 1b/1c)
- `.gitignore`: `!.cursor/rules/**`; ignore rest of `.cursor/`
- Cursor user rules disposition (every rule: promote / OPERATOR-ONLY / superseded)

**Gate:** ≤10-line agent confirmation; tests pass.

### 1b (one commit)

- Slim AGENT_SELF_GOVERNANCE (~60 lines, numbered stubs)
- Rules #17, #20, #22 grep-free
- CLAUDE scope header; 3 rules from ENGINEERING_GATEKEEPING_POLICY
- V4 register authority per operator #2
- `PROMOTION_POLICY.md` → Historical
- `tests/test_forbidden_phrases.py`, money-path roster test

**Gate:** One OPEN_ITEMS row end-to-end via new structure; zero drift incidents; tests pass.

### 1c (one commit)

- Thin `MEMORY.md`; archive memories; rewrite triggers

**Gate:** Coverage table — zero missing rules.

---

## Phase 2 — Classification and headering

Measure against Phase 0 baseline. Categories: Active Rule Source, Policy Specification, Operator Runbook, Operational Ledger, Historical Record, Superseded.

Include: `schwab_field_inventory/` (refresh on Schwab CHANGELOG or quarterly); 17 root audit `.md` → Historical.

**Gate:** Every `.md` has scope header; spreadsheet complete.

---

## Phase 3 — Repo cleanup

- **3a** — Conflicts; promotion authority in ACTIVE_PROGRAM
- **3a.1** — ✅ Closed (promotion_decision_record + eval dashboard; test `test_scheduler_log_loss_winner_field.py`)
- **3b** — Archive to `governance/archive/2026-Q2/`
- **3c** — Delete true duplicates (operator per item)
- **3d** — `.py` audit (import-graph proof for protected modules)
- **3e** — Worktree cleanup; AGENTS audit exclude `**/.claude/worktrees/**`
- **3f** — Runtime artifacts; token rotation in TRAINING_AND_MAINTENANCE; LFS hooks audit

**Gate:** ≥5% root `.py` reduction OR operator sign-off with rationale; archive + deletions done; worktrees pruned; both agents re-audit.

---

## Phase 4 — Ongoing enforcement

- Cleanup-as-we-go + unprompted surfacing if >10 new MDs or rule duplicated ≥3 surfaces
- `.pre-commit-config.yaml` (anti_pattern_sweep + grep subprocess AST)
- Pytest-to-CI — separate OPEN_ITEMS row
- Optional Claude hooks post-Phase 3
- Operator-triggered quarterly review + tooling-version checks
- Drift-incident-rate OPEN_ITEMS row (non-blocking)

---

## Known risks (→ ACTIVE_PROGRAM §Known Risks in 1a)

- CI = schwab-csv-first only; full pytest local until pytest-to-CI
- Memory portability vs [OPERATOR-ONLY] prefs
- Long-branch renames — small commits, no force-push
- `config.py` hardcoded Schwab credentials — credential-hygiene slice queued
- `verify_active_models.py` exit 1 on non-core tickers — expected; SPY/QQQ/IWM compliant
- Host backup — [`docs/host/`](../host/README.md)

## Not solvable at this layer

Consolidation reduces forgetfulness drift, not silent non-compliance after Read. Forbidden-phrases test catches output-side violations only.

---

## Execution order

1. Operator confirms content decisions (table above).
2. Phase 0 + 0.5.
3. Phase 1a → 1b → 1c.
4. Phase 2 → 3 → 4 (ongoing).

Track progress in OPEN_ITEMS: **GOVERNANCE-CONSOLIDATION**.
