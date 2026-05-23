---
name: Scope by data-flow relevance, then line-by-line within scope
description: Directive's "entire repo, no exclusions" is a closure standard, not a uniform-attention rule; operator/gatekeeper bandwidth goes to the trade-decision data flow; long-tail noise is mechanically classified with per-row evidence
type: feedback
originSessionId: d1ef1b06-a269-4fec-93e8-dc9c5b813526
---
**Rule:** The line-by-line directive applies universally as a **closure standard** — no file is exempt by category, every site reaches a disposition, no batches. It does **NOT** mean every one of the ~12.5M scanner-emitted register rows gets equal operator/gatekeeper attention. Implementation:

1. **Operator-attention scope = the trade-decision data flow.** Files that consume Schwab REST / streaming / chain / pricehistory JSON and propagate it forward into the call-card / A2 decision surface. Seed: `server.py`, `signals.py`, `chains.py`, `market_state.py`, `market_data_adapter.py`. Expand by walking imports from `server.py` outward — probably 30–80 files. Within these, **every line gets operator eyes** and **every replacement carries perf_proof**.

2. **Long-tail scope = everything else.** Docstring/comment/test-fixture/HTML/JSON sites where the field-name token appears without participating in a Schwab data flow. These get **mechanical per-row classification** by a committed tool that dumps path:line context and assigns disposition (NOT_MARKET_DATA / NO_SCHWAB_EQUIVALENT / etc.). V4 §5 is satisfied because each row gets path:line inspection — the inspection is mechanical, not operator-personal. Operator audits the classifier's output by sampling, not by reading every row.

3. **Closure unifies both populations.** `unreviewed_count = 0` requires every site dispositioned in either track. Scoreboard reports the two tracks separately so trade-decision-path progress is not drowned by long-tail counts.

**Why:** Operator on 2026-05-11, after two days of governance-MD churn and zero perf-proven product changes: *"PUSH BACK ON ME IF THIS IS THE WRONG APPROACH. I want this done right, but I want something done."* Diagnosed: my interpretation of "ENTIRE repo, ALL extensions, no exclusions" as "every one of 12.5M sites gets equal operator attention" was wrong. The math is impossible (12.5M / any reasonable cadence = years to decades), and it spends scarce operator bandwidth on `volume`-tokens-in-test-fixtures while the actual trade-decision data path stays uninspected. The directive forbids categorical carve-outs (closure bar). It does not require uniform operator-personal review intensity. Treating those two as the same thing is what produced two days of zero visible product progress.

**How to apply:**
- **Define the in-scope file set explicitly before starting any line work.** Cursor maps the trade-decision data flow by walking imports from Schwab API client entry points. Commit the map as `governance/SCHWAB_V4_TRADE_DECISION_DATAFLOW_MAP.md` so the scope is auditable and contestable.
- **Within the in-scope set:** strict line-by-line, operator eyes on each line, perf_proof per replacement, per-line disposition CSV under `governance/SCHWAB_V4_LINE_DISPOSITIONS/<path>.csv`.
- **Outside the in-scope set:** mechanical classifier with per-row context dump and per-row evidence. Operator's role is sample-audit of classifier output, not full read.
- **The classifier is not a batch shortcut.** Each row's evidence is the path:line context dump for that specific row. V4 §5 ("classification per row via path:line inspection of actual source context") is honored mechanically, not waived.
- **Scoreboard reports two tracks:** `trade_decision_path` (rows in-scope) and `long_tail` (rows out-of-scope). `replacements_with_performance_proof` only meaningful for trade-decision-path rows; long-tail rows have no replacements expected.
- **Reject "build more infra first" proposals from me.** The scanner, scoreboard, perf_proof harness, mock-embedding flag, vendor paths YAML, file inventory CSV — these all exist already. Use them; don't build more before starting line work.
- **Reject "uniform attention" framing from me.** If I say "we need to disposition the 12.5M rows" or "every row needs operator review," I'm back in the failure mode. The right framing is two tracks running in parallel: operator-grade attention on the data flow, mechanical-classifier closure on the rest.
- **Reject "skip these files because they're docs / fixtures / tests."** That's a categorical exemption. The right answer for a doc file is "mechanical classifier disposition," not "skip."
- **Operator's measure of progress** is `replacements_with_performance_proof` on trade-decision-path lines, AND `unreviewed_count` shrinking across both tracks. Both numbers in every commit's scoreboard.
