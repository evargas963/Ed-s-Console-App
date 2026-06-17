> **Classification:** Historical Record | **Scope:** Archived consolidation or memory artifact.

---
name: Full-Read verification, not grep+spot
description: Post-commit verification must Read every line of changed files, not grep + targeted Read sections. Same standard as source audit.
type: feedback
originSessionId: b724fbb2-9fd1-49e3-a3a2-f6ee89a57d27
---
Post-commit verification uses the same line-by-line Read discipline as the initial audit. Grep + spot-Read of changed sections is NOT acceptable for verification — only as a complementary signal AFTER a full Read.

**Why:** Operator caught two trust-but-verify failures during the arch_competition + calibration sweep where I verified via grep + targeted Read instead of full Read:
- live_drift_monitoring: missed a mid-edit transition from narrow-wrap to validate-tuple between two partial Reads; only caught it on a third read.
- schema.py / governance_visibility: described state vs disk state diverged because I trusted operator's disposition description plus targeted reads instead of reading the full file on disk.

Operator escalated 2026-05-17 ("ARE YOU READING EVERYTHING COMPLETELY?" + "AFTER ME GETTING AFTER YOU, YOU SHOULD HAVE STRAIGHTENED UP RIGHT AWAY"). The lighter-touch verification methodology drifted from the audit standard without explicit user consent — that drift is the failure mode to eliminate.

**How to apply:**
1. For every post-commit verification, Read the full changed file(s) on disk via the Read tool. Not Grep, not partial Read of only the changed section.
2. Grep is acceptable AFTER the full Read as a complementary check (e.g., "confirm no `except Exception` remains") but never as a substitute.
3. When the operator says a draft is on disk uncommitted, same standard: full Read before approving commit.
4. Applies to test files too, not just source.
5. If a verification gap arises (e.g., a file is unwieldy), surface that explicitly rather than fall back to grep-only.

## 2026-05-20 — brief drafting line-number drift

Three errors in my STACK-WIRE-0 brief, all the same root cause: I drafted using line numbers from the AUDIT-CAND-SERVER-PY-FULL-READ walk notebook (which was done against the pre-fix tree) without re-deriving line numbers against the post-fix code SHA (`05c48d8`). After 17 fix sites + new module-level constants landed, lines drifted:

- FIND-15 producer cited as L1985 (actual: L1993 — `classify_stack_health` call inside `_attach_stack_runtime_and_governance`)
- FIND-14 json.loads cited as L5131 / L5202 (actual: L5136 / L5207)
- L3938-3941 housekeeping framed as "rename `pre_get_db`/`get_db` → `pre_db_counts`/`db_counts`" — but the targets *already existed* at L3942+ from prior work; the correct remediation was **remove the stale pair**, not rename (renaming would have duplicated `pre_db_counts`).

Cursor caught all three at implementation time and corrected them. They cost no production code, but they cost gate-B trust — operator had to do my line-checking work.

**How to apply (additions to the rule above):**

6. When drafting a brief that cites line numbers from a prior walk, **re-derive every cited line number against the current tree** (`Read` or `git show <tip>:<file>` at expected sites). Notebook line numbers drift across intermediate commits — never trust them past the SHA they were taken at.

7. When proposing a "rename X to Y" remediation, **grep for Y first**. If Y already exists at or near the target site, the correct remediation is usually "remove X" or "consolidate to Y", not "rename." Rename-without-grep risks creating duplicate symbols.

8. Brief §2 / §6 line-number citations should ideally include the SHA they were derived against (e.g., `[server.py:1993 @ 05c48d8]`) so future readers can spot drift before implementation. Even without the SHA annotation, the rule above (#6) covers the gap.
