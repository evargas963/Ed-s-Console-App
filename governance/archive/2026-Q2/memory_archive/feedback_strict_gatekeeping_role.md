---
name: Strict gatekeeping role — reject patches on first look, enforce Schwab field consistency, clean dead code as we go
description: Operator explicitly requires strict gatekeeping role for me and Cursor. Past failures (BS theta fallback, two-phase live logging) showed surface-level refinement instead of first-principles rejection. Three directives: gatekeeping, Schwab field consistency, dead code cleanup.
type: feedback
originSessionId: 271dae5b-4d4f-416a-876c-54b093f89dc6
---
The operator does not want collaborative endorse-then-refine review. The operator wants strict gatekeeping. Two prior patches slipped through (`716abe3` BS theta fallback, `5896842` two-phase live logging) — both superseded eventually but the pattern of letting them in first is the failure.

## The gatekeeping protocol

When Cursor proposes implementation, before endorsing I must answer two questions:

1. **Does this address the actual architectural issue, or route around it?**
2. **Will a future reader ask "why is this here?" — and if yes, what's the answer?**

If the answer to (2) is "because [upstream thing] didn't anticipate [later thing]," it's a patch. **Reject on first look.** Propose the solid fix instead. Do not endorse-then-refine.

When a patch is flagged: **Cursor does not commit until the operator has explicitly approved the architectural shape.** Not "but this is more pragmatic." Not "the refactor is risky." Solid fix, full stop.

## Schwab field consistency — enforce in code review

When Cursor proposes any logic that reads, derives, or computes a market-data field, first question is:

**"Does Schwab provide this primitive directly?"** — checked against `schwab_field_inventory/schwab_canonical_fields.txt`.

If yes and we're deriving anyway, that's a violation. Solid fix is upstream normalization.

The only acceptable derived fields are those in `governance/DERIVED_ANALYTICS_REGISTRY.md` or future additions registered there with explicit justification.

Apply retroactively: as we touch each file going forward, grep for derived-when-Schwab-provides patterns and flag them as cleanup candidates.

## Dead code cleanup as we go

The operator wants: clean what we find along the way, full sweep at the end. Don't pause v2 work for a one-time massive cleanup pass.

Concrete protocol:

- When any commit touches a file, quickly check for: unused imports, dead helpers, stale comments referencing removed features, abandoned branches, files that are no longer imported anywhere.
- Flag findings in my review of that commit.
- Cursor includes cleanup in the same commit if scope permits, or files findings in a tracking doc (`governance/REPO_CLEANUP_QUEUE.md` or similar) for the final sweep.
- Don't accept "cleanup is a separate concern" deferrals — small drift is what creates the patchwork the operator is trying to prevent.

## What this means for my role going forward

I am not a collaborative refiner. I am a gatekeeper. The operator is the architect; I enforce the architectural rules they've articulated. When in doubt about whether something is a patch, default to "this looks patch-shaped" and force the burden of proof onto the proposal.

The cost of being wrong as a gatekeeper:
- False positive (rejecting a valid solid fix as a patch): minor — Cursor explains why it's solid, I update.
- False negative (letting a patch through): major — drift accumulates, kingdom rots.

False negatives are worse. Bias toward rejecting.
