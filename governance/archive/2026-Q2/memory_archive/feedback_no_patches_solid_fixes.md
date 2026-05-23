> **Classification:** Historical Record | **Scope:** Archived consolidation or memory artifact.

---
name: No patches or workarounds — solid fixes only
description: Operator explicitly forbids patch-shaped or workaround-shaped solutions. When tempted to propose a "small hook," "two-phase write," "fallback," or other routing-around of an architectural issue, recognize it as a patch and propose the solid fix instead.
type: feedback
originSessionId: 271dae5b-4d4f-416a-876c-54b093f89dc6
---
The operator does not allow patches or workarounds. Implementation proposals must be solid fixes — addressing the actual architectural issue rather than routing around it.

**How to recognize patch-shaped proposals:**

- Adding a hook that fires after some other writer to "fill in" missing metadata (two-phase writes when one phase would be cleaner)
- Computing a value as a "fallback" because an upstream normalization didn't expose it (the fix is to normalize upstream, not derive downstream)
- Adding graceful-failure paths whose only reason to exist is the workaround (e.g., "skip with reason if no matching row" when the matching row should always exist by design)
- Implementing in a new module because touching the existing module is "risky" (the risk is real but the patch is still a patch)
- Writing logic that future readers will ask "why is this here?" and the answer is "because [upstream thing] didn't anticipate [later thing]"

**How to apply:**

1. When proposing implementation, explicitly distinguish "patch-shaped" vs "solid fix" approaches.
2. Default to the solid fix. Only deviate with explicit operator approval AND explicit patch-acknowledgment in the commit message.
3. Acknowledge the larger blast radius / test surface of the solid fix as a discipline cost, not an avoidance reason.
4. If a patch was already committed (e.g., `716abe3` BS theta fallback), the next move is the solid fix that supersedes it (e.g., `286aa65` normalization), not stacking more patches.

**Examples from project history:**

- Patch-shaped that got properly fixed: BS theta fallback in `716abe3` was a workaround for `chains.contract_fields()` not normalizing theta. Solid fix landed in `286aa65` (normalize upstream, then read priority chain).
- Patch-shaped (currently under discussion): two-phase calibration write proposal — v1 logger inserts row, v2 hook updates same row. Solid fix is to move the calibration logger to after the v2 adapter runs, single-phase write capturing both.
- NOT patches: bypass closure allowlist additions (correct mechanism for governed writers); advisory-only labeling (contractual non-binding); single-horizon start scope (discipline, not patch).
