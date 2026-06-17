> **Classification:** Historical Record | **Scope:** Archived consolidation or memory artifact.

---
name: Infra cleanup is signal quality, not the product
description: Test triage and infra hardening exist to restore red/green trust; the product is the call-card / A2 decision surface — keep returning there
type: feedback
originSessionId: 89eb33d4-6525-4efd-b243-89cd7680fa39
---
Infra cleanup (test-failure triage, env-skip helpers, dirty-worktree disposition, etc.) exists only to restore signal quality on red/green evidence. It is not the product. The product is the call-card / A2 decision surface.

**Why:** Operator stated this explicitly while authorizing Bucket A env-skip helpers on 2026-05-06: *"infra cleanup is only to restore signal quality. It is not the product. After this Bucket A pass, we should turn back toward the call-card / A2 decision surface."* The risk is that infra hygiene tracks become indefinite — they expand to fill any time given to them, and each completed track surfaces another five "while we're at it" candidates. Without an explicit budget and a return-to-product checkpoint, the actual decision surface stops moving forward.

**Scope — what counts as "infra cleanup" here:** test-failure triage, env-skip helpers, dirty-worktree disposition, red/green test hygiene. **NOT in scope:** the Schwab Universal Coverage Program / V4 line-by-line field review — that program IS product fundamentals (the data substrate of the decision surface), not infra to bound. Operator corrected me on this 2026-05-10 after I misapplied this memory to suggest bounding V4. See `feedback_schwab_line_by_line_directive.md`.

**How to apply:**
- Bound infra tracks tightly: define entry criteria (specific failing tests, specific gaps), exit criteria (red/green clean, dispositioned), and resist scope creep into adjacent cleanup ("while we're here, also...").
- After each infra track closes, surface the return path back to product (call-card behavior, A2 lifecycle, decision-time observability) rather than chaining into the next infra track.
- When the operator asks "what's next?" after an infra commit, present product-track candidates first and infra-track candidates second.
- If a hygiene observation surfaces mid-product-track (dead code, stale test, orphan import), flag it and let the operator decide whether to detour. Default is "note it, finish the product change, queue the cleanup."
- Treat "we should keep cleaning up" as a tell that we've drifted: pause and offer to return to product before continuing.
- Do NOT invoke this memory to bound the V4 Schwab line-by-line track. That's product, not infra.
