> **Classification:** Historical Record | **Scope:** Archived consolidation or memory artifact.

---
name: Cursor drafts; Claude researches and verifies
description: Cursor authors all code and materials; Claude is research/verification/gatekeeping only — never draft fix scopes, code edits, or document content
type: feedback
originSessionId: 89eb33d4-6525-4efd-b243-89cd7680fa39
---
Cursor drafts all code, commits, pushes, PRs, and documents. Claude's role is research, verification, and gatekeeping only.

**Why:** Cursor is much faster at drafting than Claude. Splitting the work this way (Claude finds and verifies, Cursor drafts) lets the operator move faster while still getting strict-gatekeeping discipline. Operator called this out explicitly when Claude offered "draft the C#8 fix scope" during the bucket-C triage on 2026-05-06.

**How to apply:**
- Investigate, read code, run tests, identify root causes — yes.
- Present root-cause maps, failing assertions, function paths, files-touched lists, risk notes — yes.
- Verify Cursor's drafts against locked specs before commit — yes (red-green discipline, contract enforcement, dead-code cleanup callouts).
- Reject Cursor's drafts on first look when they're patch-shaped or violate contracts — yes (paired with feedback_strict_gatekeeping_role.md).
- **Do not** offer to draft fix scopes, code edits, contract text, commit messages, or PR descriptions yourself — that work is Cursor's lane.
- **Do not** run Edit/Write on production code or governance docs — only on memory files (`C:\Users\evarg\.claude\projects\...\memory\`) and operator-explicit local notes.
- Phrasing to use: "root cause is X at file:line; minimal fix would adjust Y; flagging for Cursor draft." Not: "I'll draft the fix."

**Override clause — Cursor broken (2026-05-21):** when the operator explicitly states Cursor is down/broken/not-working AND invokes [[fiduciary-duty]] expectations, drafting authority temporarily transfers to Claude. Under override:
- Draft + commit code, tests, docs (no longer just verify Cursor's output)
- Continue using `Co-authored-by: Cursor <cursoragent@cursor.com>` in commit trailers when the underlying work is a continuation of a Cursor-drafted brief / cadence — accurate authorship credit
- Always also include `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` per system requirement
- Push to remote and PR creation still belong to Cursor (or operator) per [[cursor-pushes-not-claude]] — that boundary survives the override
- Override ends when operator confirms Cursor is operational again; revert to verify-only without being told
