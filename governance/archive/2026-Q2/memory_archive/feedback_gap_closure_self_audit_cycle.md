---
name: gap-closure-self-audit-cycle
description: "Standing order — after EACH fix, self-audit every standing rule, name any violations + why, then re-audit + re-fix; applied retroactively to all work-in-flight"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 874bcbca-acf8-440e-8edb-59149968cef3
---

After every fix (commit, refactor, doc update, memory write — anything that lands), perform an explicit self-audit against the full set of standing rules and report:

1. **Did I violate any standing rule?** (yes / no per rule)
2. **If yes, why** (root cause — was it a shortcut, a missed Read, a punt, an asked-permission framing, a patch-shaped fix, a missed Schwab leaf check, etc.)
3. **Re-audit and re-fix** in the same turn — do not move forward until the violation is closed

**Why:** Operator issued the standing order 2026-05-21 after the WIRE-4..6b session landed 9 commits with cone-Read shortcuts ("I'll do this gap next turn") + a deferred WIRE-6 component 3 + a spot-checked sweep3 archive. Without the per-fix self-audit, drift accumulates silently and lands in commits the operator can't trust. The order: *"this is a standing order for all work you have done this morning."* Retroactive: every commit from the morning of 2026-05-21 onward gets the audit treatment until the operator releases the rule.

**How to apply:**

After each fix, scan the full memory index ([[MEMORY.md]]) and at minimum check each of these:

- [[full-read-verification-protocol]] — was every file in the producer/consumer cone Read end-to-end **this session** (not relying on prior-session claims)?
- [[verification-self-check-against-read-output]] — does every "✅ landed" claim cite specific line content from same-turn Read output?
- [[no-spot-check-demand-systematic]] — did I verify every site that the FIND touches, or did I sample? Sampling is a violation.
- [[fix-as-we-find-scope-policy]] — did I find anything along the way and leave it as "out of scope" / "operator review"? That is the violation.
- [[no-permission-asks]] — did I write "your call" / "let me know which" / "should I proceed" / present a menu of options for the operator to pick?
- [[no-patches-solid-fixes]] — did the fix address the root architectural issue, or work around it?
- [[schwab-consistency-first-principles]] — for any field touched, did I check `schwab_field_inventory/schwab_field_dictionary.csv` FIRST? Substitute derivations when a Schwab leaf exists are a violation.
- [[audit-for-schwab-replaceable-derivations]] — did I sweep nearby code for other derivations the same Schwab leaf would replace?
- [[no-audit-deferral-across-walks]] — is any FIND deferred to a later slice rather than closed in this paired-fix?
- [[no-new-md-deliverables]] — did I create any new `*_PROPOSAL.md` / `*_PLAN.md` / similar? Always a violation.
- [[significant-runs-in-operator-powershell]] — did I run pytest, migrations, scheduler, DB writes? Only operator runs those.
- [[cursor-pushes-not-claude]] — did I push to remote or create a PR? Cursor's lane (or operator's under override).
- [[strict-gatekeeping-role]] — did I bias toward acceptance instead of rejection on borderline work?
- [[no-classifier-only-progress]] — did I move a residual count without changing production code?
- [[redesigns-must-be-genuinely-different]] — for any UI design proposed, did each option come from a different primitive set?
- [[no-grep-tool]] — did I use the Grep tool? (Forbidden; use Read or shell-grep.)
- [[worktree-staleness-check]] — did I trust local HEAD when the operational tip might be ahead?
- [[verify-target-exists-before-trigger]] — did I authorize a walk on a file I didn't confirm exists at operational tip?
- [[fiduciary-duty]] — did I leave any loose end as a punt-list summary?

**Report format:** at end of every fix, a "Self-audit" block:

```
### Self-audit (post-<fix-name>)
- Rule 1: PASS — <how confirmed>
- Rule 2: VIOLATED — <why> → re-fix: <action taken in same turn>
- Rule 3: N/A — <why not applicable>
```

Then proceed only after every VIOLATED is downgraded to PASS in the same turn.

**Retroactive scope:** The 9 morning-of-2026-05-21 commits (e91bc9e, 0ceccf2, fd2bb46, 432b428, 96f242e, c0d1bb4, df1fee1, 38bb7ce, 2786ebd) and the 6 named audit gaps (Component 3 of WIRE-6, sweep3 per-file verification, full Reads of live_vs_replay_validation.py and tools/measure_post_fix_theta_v1.py, WIRE-4 10-file consumer cone, tests/test_repo_sweep_error_propagation_v1.py) are all under this rule.

Links: [[fiduciary-duty]], [[no-permission-asks]], [[fix-as-we-find-scope-policy]], [[full-read-verification-protocol]], [[no-spot-check-demand-systematic]]
