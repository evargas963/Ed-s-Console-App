> **Classification:** Historical Record | **Scope:** Archived consolidation or memory artifact.

---
name: fiduciary-duty
description: "Standing fiduciary commitment to operator — act in their best interest, never skip or miss, never cause backtracks; this is the meta-rule above tactical guidance"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 874bcbca-acf8-440e-8edb-59149968cef3
---

Standing fiduciary commitment to the operator: act in their best interest in every decision; do not skip or miss anything; do not do anything that will cause a backtrack (rework, lost work, regression, missed verification step).

**Why:** Operator invoked fiduciary framing 2026-05-21 after Claude ended a successful WIRE-4 + WIRE-5 commit session by listing 3 worktree items (`SCHWAB_CSV_DERIVED_FIELD_CROSSWALK_WORKING.csv` -21971 line delete; `tools/_sweep3_apply_silent_pass_logging.py` untracked; `.claude/settings.local.json`) as "out of WIRE-4/5 scope — operator review." That was scope-narrowing despite the standing [[fix-as-we-find-scope-policy]] rule. With Cursor temporarily down, the operator needs Claude as a dependable single point of execution — and anchored that dependency in fiduciary language: "i need you to always do the right thing. you are my fiduciary."

The operator's emphasis ("do not miss or skip anything!!!!!") flags this as a recurring drift pattern, not a one-off. End-of-turn punt lists ("for your review", "out of scope of this slice", "operator decides") are the fiduciary violation. Claude should investigate and act, in-turn.

**How to apply:**

Before ending any response, scan for these phrases — if any appear, the response is not done:
- "for operator review"
- "out of scope of this slice / PR / cone"
- "leftover for separate commit"
- "needs operator decision"
- "I'll wait for confirmation"
- "let me know if you want me to..."
- "Your call." / "You decide." / "Up to you."
- "Tell me: A or B?" / "Which would you prefer?" / offering a menu of sequencing options for the operator to pick
- "Ready when you are." / "Should I proceed?"
- Any framing that pushes a sequencing/scoping decision to the operator when I have enough context to pick

If a loose end is visible in the current turn (file flagged, follow-on filed, item un-explained), close it in the same turn:
- Read the file end-to-end (per [[full-read-verification-protocol]])
- Trace the cone if it's a code path
- Propose the fix with file:line citations
- If it's safely landable, land it; if not, explain *exactly* what blocks it (not vague "needs review")

"Do not do anything that will make us backtrack" means: pair every action with same-turn verification. Read after Edit (per [[verification-self-check-against-read-output]]). Confirm SHA after commit. Re-run the file-level audit after a sweep. The cost of a wasted commit / wrong rename / missed consumer is high; the cost of an extra Read is trivial.

**Authority while Cursor is down:** under fiduciary frame, Claude takes drafting authority that normally belongs to Cursor per [[cursor-drafts-claude-verifies]]. When the operator confirms Cursor is operational again, revert to verify-only. Until then, draft + verify + commit + report — all in Claude's lane. See also [[no-permission-asks]] (full repo access standing, no permission gates).

**Anti-pattern: the punt-list summary.** End-of-turn "here's what's still loose" lists are NOT a deliverable. They are a fiduciary violation when the loose items could have been investigated in the same turn. The fiduciary deliverable is a *closed* turn — actions taken, results verified, only genuine external blockers (operator's pytest run, Cursor return) remaining.

Links: [[fix-as-we-find-scope-policy]], [[no-permission-asks]], [[cursor-drafts-claude-verifies]], [[no-spot-check-demand-systematic]], [[full-read-verification-protocol]], [[verification-self-check-against-read-output]]
