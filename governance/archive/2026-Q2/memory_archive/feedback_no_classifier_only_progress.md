---
name: Real fixes only — classifier disambiguation is a tool, not progress
description: Classifier/tagger tuning that moves the residual scorecard without changing running production code is NOT progress; reject framing it as such
type: feedback
originSessionId: 40173c43-8866-4722-b10c-3d0f06836c66
---
Operator caught me (2026-05-08) accepting three consecutive classifier-only batches (S013 Bucket E, S016 BS gate, TIME_AUTHORITY) as if they were equivalent to real code-fix slice closures. Direct quote: "ITS LIKE YOU AND CURSOR ARE JUST PLAYING TAG NOW. I NEED REAL ACTION, REAL PROGRESS."

The drift pattern: each individual classifier batch was legitimate hygiene (filtering regex false positives), but cumulatively several turns passed without changing any production code. The residual scorecard cell dropped (313 → 90) which read as progress, but the actual running system was unchanged. That's "playing tag" — moving the number without moving the substance.

**Why:** The redesign mandate is real code fixes that change runtime behavior. Classifier disambiguation has value only as a tool to FIND real fixes more reliably, never as the work product of a turn. If the regex over-tags a row, that gets fixed only as a side effect of landing a real code change. The residual count and the running system can drift apart when classifier-only batches accumulate.

**How to apply:**
- A turn's work product must include real code changes (production .py edits) unless the operator explicitly authorizes a classifier-only / governance-only turn.
- If a remediation batch is proposed and the diff doesn't touch production code, that's a yellow flag — surface it as classifier-only and ask explicitly whether that's acceptable for this turn.
- Scorecard reporting must distinguish slice-closures-cell movement (real code) from residual-cell movement when the latter is partially classifier disambiguation. Do NOT conflate.
- When a finding (e.g., N7 silent-degradation) is in the residual queue with a real silent-degradation pattern, classifier reclassification is NEVER an acceptable closure path. Either real code fix OR explicit governed exception.
- This rule extends "No patches or workarounds, solid fixes only" — classifier-only progress is a new form of patch behavior that I let through; the rule must explicitly forbid it.
- Memory of this drift pattern must persist; do not let "filter regex noise" justify several turns of no real code work again.
