---
name: Complete redesign committed
description: Operator has decided — this is a complete redesign of the trading system, not incremental fixes; existing artifacts only kept where they pass review and updated to current standard
type: project
originSessionId: 40173c43-8866-4722-b10c-3d0f06836c66
---
The operator confirmed (2026-05-07): **THIS IS A REDESIGN**. Stated three times explicitly. Said they had told me before and I had failed to internalize it.

Scope: complete architectural redesign. Existing code is reusable only when it passes review against current standard; otherwise it gets rebuilt, not patched. The phrase "we are only using what we can" — anything kept must be reviewed and updated, not just inherited.

**Why:** the operator's goal is a world-class app. Incremental slicing on top of a foundation that bypasses Schwab canonical fields (BS theta fallback, market_state proof-row truncation, uneven source labeling) is "putting lipstick on a pig" in their words. The governance veneer was hiding that the underlying data flows didn't match the standard.

**How to apply:**
- Stop proposing incremental fix-slice work as "forward progress" without first asking whether the underlying foundation passes redesign review
- When reviewing any code, ask first: does this match the redesign target framework? If no, the answer is rebuild, not patch
- Contracts that encode workarounds (e.g., "compute X as v1_approximation when Schwab field missing") are NOT load-bearing — flag them as redesign candidates, don't gatekeep against them as-if-canonical
- Memory of this decision is permanent until the operator explicitly says the redesign is complete; don't assume it's "done" because individual slices land
- Redesign target framework lives in governance/ (FRAMEWORK_V2_TARGET_LOCK_RECORD.md, IMPLEMENTATION_BLUEPRINT_V2.md, INSTITUTIONAL_STANDARD_V3.md, PHASE_PLAN_TARGET_STATE.md, REBUILD_CONTEXT.md) — read those, not just the contract for the slice in front of me
