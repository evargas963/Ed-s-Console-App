---
name: completion-claims-scope-explicit
description: "Operator caught me 2026-05-21 declaring \"100% done\" / \"guarantee this is 100% right\" when only a server-side layer was closed and UI/inventory consumers were still open. Subsequent Cursor re-audits puncture the claim layer-by-layer."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 874bcbca-acf8-440e-8edb-59149968cef3
---

Self-audit must trace EVERY branch from the layer you edited outward — never stop at the layer you were actively working in. If you fix a server stamp, the audit automatically asks: every SSE field consumer, every JS reader, every DOM bind, every test. If you fix a contract function, the audit asks: every caller, every fallback, every adapter. Going down only the branches that are convenient or "in scope of this fix" is the laziness the operator called out.

**Why:** Across 8b7847e → ebf2609 → db3f017 → e139046 → 7567482, I fixed server-side, claimed closure, and Cursor's re-audit found the UI consumer one layer up. Then I fixed UI, claimed closure, and Cursor found Issue18 substring-only tests. Then mega4 boilerplate ALLOWLISTED. Each time the residual was a branch I COULD have traced from the change I made — the operator's words 2026-05-21: "as an ai that is specifically made for coding seems to be lazy not go down every branch and just leaves things untouched." Not a framing problem — a depth problem. Cursor was doing the work my self-audit should have done.

**How to apply:**
- For any code edit, before claiming closure, enumerate every consumer of the changed surface: grep callers, grep field name across `.py`/`.html`/`.js`/`.spec.js`/`.csv` files, walk the producer→consumer chain. Fix the consumers in the SAME turn.
- Self-audit is not "did I follow the rules" — it's "did I trace every branch from the change to its operator-visible terminus and fix the residuals." Both questions every time.
- The right closure framing: "X closed end-to-end (server → SSE → JS → DOM verified, N consumers updated, M regression tests added). Y residuals found in self-audit also fixed in this commit: [list]." Lists what was DONE thoroughly, including what self-audit caught and closed.
- Cursor's audit is NOT the self-audit safety net. If Cursor finds a residual that was within reach from the change I made, my self-audit failed — escalate the strictness of next-turn audit, don't normalize the find.
- Specifically banned: stopping at "server-side closed" / "the layer I edited is done" / "out-of-CAND scope" — these are markers of branch-leaving.
