# Claude encode — PM full-prompt coverage lock (RC-233)

**Author:** Cursor (PM) · **Writer of `.py`:** Claude · **Date:** 2026-08-04  
**Trigger law:** Operator 2026-08-04 — a true PM addresses ALL issues in a pasted multi-issue prompt; headline-only replies are forbidden.  
**Cursor rule (already landed):** `.cursor/rules/09-pm-full-prompt-coverage.mdc`  
**OUT-OF-SCOPE for Cursor:** product code, `operator_go` flip, kill tests. Prefer no commit until Claude lands the guard with hooks-on under existing GO/mission rules.

---

## Goal

Mechanically BLOCK Cursor wrap-up / Stop completion when:

1. The **operator user message** contains multiple ISSUE-class markers, AND
2. The **assistant reply** (final text) lacks a coverage table / enumerated dispositions.

This is detection for the failure class in RC-233. The `.mdc` is the standing obligation; this file is the encode checklist for Claude.

---

## ISSUE-class markers (detect ≥2 distinct items)

Treat as multi-issue paste when **any** of the following yield **≥2** distinct issue units:

- Numbered or bulleted lists (`1.` / `-` / `*` lines with actionable content)
- Explicit labels: `ISSUE`, `BLOCKER`, `RESIDUAL`, `P0`, `NEXT`, `GO`, `QUIET`, `FAIL`, `PASS`
- Named process tokens: `sole_writer`, `operator_go`, `pm_mission`, `PDL`, `PDH`, `DISK_ONLY`, `LIVE_ENFORCED`, `quiet`, `restart`, `lock remainder`, `LOCK-`
- Section headers in Claude status dumps (`##`, `###`, `CLAIM:`, `DONE:`, `NEXT:`)

Escape: operator line `# pm-coverage-ok:` naming waived items.

---

## Required coverage table shape (assistant must emit)

Assistant final reply must include a markdown table or numbered list where **each** distinct issue unit has:

- `disposition` ∈ {`VERIFIED`, `ACCEPTED`, `REJECTED`, `QUEUED`, `BLOCKED`}
- one-line disposition note

Heuristic check (Claude implements): for each extracted issue keyword/bullet slug, at least one disposition token appears in the same reply within ~200 chars of a matching slug OR the reply contains a `## Coverage` / `Coverage table` section whose row count ≥ extracted issue count.

False-positive control: single-question operator chats (no multi-marker) → do not BLOCK.

---

## Wire points (extend — do not invent a novel stack)

| Layer | Module | Behavior |
|---|---|---|
| Stop | `tools/stop_guard.py` and/or `tools/honesty_guard.py` / `tools/operating_process_lock.py` completion path | BLOCK Stop when multi-issue operator text + missing coverage table; deny prefix `PM_COVERAGE:` |
| PreToolUse (optional secondary) | `tools/process_lock_guard.py` | If a Cursor "final answer" tool path exists, same predicate; else Stop-only is enough |
| Cursor hooks | `.cursor/hooks.json` | Ensure Stop invokes the same guard as Claude (parity via existing `check_claude_cursor_guard_parity`) |
| Tests | `tests/test_pm_full_coverage_lock_v1.py` (new) | (1) multi-bullet operator + headline-only assistant → BLOCK; (2) same + full coverage table → ALLOW; (3) single-issue chat → ALLOW; (4) `# pm-coverage-ok:` → ALLOW |

---

## FIXED reach for RC-233 CLOSE (Claude)

Do not CLOSE RC-233 until:

1. Guard `.py` + negative-control tests green.
2. Cursor + Claude Stop parity measured.
3. One fixture proves BLOCK on a synthetic "headline-only" PM reply against a multi-issue paste that includes at least: `sole_writer`, `PDL`/`quiet`/`GO`, and one lock residual.

---

## Non-goals

- Do not flip `operator_go.json`.
- Do not edit `static/chart.html` / `server.py` / kill tests for this lock.
- Do not treat the `.mdc` alone as the mechanical lock (honesty / LOCK-7).
