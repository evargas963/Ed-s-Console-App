> **Classification:** Historical Record | **Scope:** Archived consolidation or memory artifact.

---
name: Audit-for-Schwab-replaceable-derivations on every review
description: Every code review, no matter the scope, must sweep for derived formulas that could use a Schwab leaf instead; never block on prerequisites
type: feedback
originSessionId: b724fbb2-9fd1-49e3-a3a2-f6ee89a57d27
---
Every review, audit, or formula consolidation MUST sweep the touched code (and adjacent code, in passing) for derived formulas that have a Schwab leaf equivalent. If found, name them and drive them to the appropriate commit/MD update. Do not block with "we'd need X first" — name the work and hand to Cursor to draft.

**Why:** Operator (2026-05-16) was explicit and emphatic: "I need to make sure we are using Schwab fields when possible. I don't want to hear you or Cursor block me on this that it can't be done because of X." This builds on prior Schwab-first memories — the new layer is the always-on audit posture and the no-blocking rule.

**How to apply:**
- During any code review, search for derivations alongside the in-scope work. Don't limit the sweep to "the function I was asked about." If I'm reading `math_levels.py` and notice `math_exposure_core.py` derives something Schwab provides, flag it.
- Schwab leaves to prefer over derivation when present: `delta`, `gamma`, `vega`, `theta`, `rho`, `volatility`, `openInterest`, `totalVolume`, `bidSize`, `askSize`, `mark`, `bid`, `ask`, `last`, `strikePrice`, `multiplier`, `putCall`, `daysToExpiration`, `expirationDate`, plus the quote-side leaves (`regularMarketLastPrice` etc.). New leaves should be added here as discovered.
- Derivations that have NO Schwab equivalent (GEX$, DEX$, charm, vanna, gamma pin, HVL, max pain, flip, inflection, expected move, etc.) stay derived — but they must use a single canonical derivation path, dollarize when spot is known, and be registered in `governance/INSTITUTIONAL_STANDARD_V3.md` §8.2 or `governance/DERIVED_ANALYTICS_REGISTRY.md`.
- When I find a Schwab-replaceable derivation: do NOT respond with "this requires re-architecting X." Surface it as a specific actionable for Cursor to draft (the fix), then re-audit the resulting commit/MD against the bytes.
- "Cursor drafts; Claude verifies" still holds — that is a role split, not a blocker. The work happens.
