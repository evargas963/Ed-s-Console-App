---
name: Schwab consistency is first-principles, not contract-derived
description: When reviewing code that touches market-data fields, ask "where does this come from? Is the Schwab canonical value reaching this code?" BEFORE checking contract compliance — contracts can themselves encode workarounds
type: feedback
originSessionId: 40173c43-8866-4722-b10c-3d0f06836c66
---
The operator's standing rule "enforce Schwab field consistency in code review" is a first-principles check, not a contract-compliance check.

**Why:** I missed this on Slice 1. Code at `_theta()` had a chain → BS fallback. I checked that the labels matched the contract clause and accepted it. The operator caught it because the contract clause itself was a workaround dressed in governance language. Subsequent audit confirmed: market_state truncates Schwab proof rows upstream, so the BS fallback wasn't compensating for missing Schwab data — it was compensating for our own code throwing Schwab data away. Contract compliance was a substitute for actual review.

**How to apply:**
- For every market-data-touching slice, run the Schwab-path check FIRST: where does this field come from in the Schwab payload? Is the canonical value reaching this code?
- If a contract clause says "compute X as v1_approximation when Schwab field is missing," that clause is a yellow flag. Ask: does Schwab actually not provide it, or is something upstream throwing it away?
- Never accept a workaround pattern just because the contract has wrapped it in governance vocabulary. Governance language doesn't make a workaround into a design.
- Empirical check before governance: if the question is "is Schwab field X reliable?", run a read-only archive/sample query first, not after the operator catches it.
- This rule applies to all canonical Schwab fields: greeks, IV, spot, bid/ask/last/mid, volume, OI, contract identity, quote/trade timestamps, derived greeks/composites.
