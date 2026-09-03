> **Classification:** Historical Record | **Scope:** Archived consolidation or memory artifact.

---
name: Per-iteration scoreboard required on every commit
description: Operator demands a five-number scoreboard plus performance-proof artifacts on every V4 iteration; no commit closes without them; this is how we tell motion from progress
type: feedback
originSessionId: d1ef1b06-a269-4fec-93e8-dc9c5b813526
---
**Rule:** Every commit that touches the V4 register, makes a code replacement (derived → Schwab field), or runs the scanner MUST emit a committed metrics JSON at `reports/artifacts/schwab_v4_metrics_<date>_<seq>.json` AND reproduce the same numbers verbatim in the commit message body. Replacements MUST also carry a per-replacement performance-proof JSON at `reports/artifacts/perf_proof_<register_id>_<date>.json` with before/after measurements and verdict=PASS. Any commit missing these is rejected on the spot.

**The five numbers (plus deltas):**
1. `fields_identified_total` — every site the scanner emitted as a register row.
2. `schwab_canonical_referenced` — register rows whose surface_form maps to a `canonical_field` row in `schwab_field_inventory/schwab_field_dictionary.csv` (disposition `REPLACED` or already-canonical).
3. `derived_fields_total` — register rows whose surface_form is non-canonical (alias / derived / project-internal token), regardless of disposition.
4. `derived_with_no_schwab_equivalent` — derived rows with disposition `NO_SCHWAB_EQUIVALENT` AND a four-channel exhaustion record per V4 evidence bar §3.
5. `replacements_landed_this_pass` (R) AND `replacements_with_performance_proof` (P) — every commit must show both; `R - P` must always be zero. If `P < R`, the commit is rejected; either Cursor produces the missing proofs or rolls back the replacements.

**Deltas vs prior iteration:** `Δ unreviewed_count` (must be ≤ 0; never grows), `Δ schwab_canonical_referenced` (target: positive), `Δ replacements_with_performance_proof` (target: positive). These appear in every iteration's commit body.

**Performance-proof artifact contents (per replacement):** register_id; file:line; derived_surface_form (before) and schwab_surface_form (after); canonical_field; behavior_driven (what production path consumes the value); metric (concrete measurable); harness path under `tests/perf_proof/`; input_corpus (including adversarial cases); before / after measurements (value_distribution, latency_ms_p50, error_count, n); comparison (EQUAL | BETTER | WORSE); pass_condition stated; verdict (PASS | FAIL); tree commit shas before/after; ISO timestamp. Verdict != PASS → roll back, do not commit.

**Why:** Operator on 2026-05-10, after a full day of work: *"I've been working on this all day and all I have are a bunch of MD files."* Diagnosed: that day's record was 20+ governance MD edits, 3 contract additions, 4 code edits without performance proofs, 5 inventory files, 5 per-file memos, 2 embedding artifacts — and **zero** populated V4 register rows, **zero** performance-proof JSONs. The scoreboard makes that gap impossible to hide. Without `P` moving and `unreviewed_count` shrinking, an iteration scored zero regardless of how many MD files moved. The scoreboard is the line between motion and progress.

**How to apply:**
- **Gatekeeping first question on every commit:** show me the iteration scoreboard. If it isn't in the commit body or the metrics JSON, reject without further review.
- **Replacement claim accepted only with performance proof.** A replacement that compiles, passes unit tests, and matches the Schwab canonical leaf is still not "landed" until its perf_proof JSON has verdict=PASS. The prior conversation's four code edits (`expiration` fallback removal × 3, `_underlying_node` arm) currently have `P = 0`; they need retroactive proofs to count.
- **No "we'll add the proof later"** — Cursor's offer to defer the proof is rejected. Either commit the proof in the same commit as the replacement, or the replacement isn't admissible.
- **Reject "this MD edit moved the program forward."** It moves only if it advances `P` or shrinks `unreviewed_count`. Governance scaffolding does neither.
- **Reject any iteration where `R > 0` and `P < R`.** The replacement count without proof count is the diagnostic for "claiming progress without proving it."
- **The scoreboard is the audit ledger.** Every iteration's metrics JSON is committed; the sequence of JSONs over time IS the program's progress record. The closure audit (Deliverable 16) compiles them.
- **NOT_MARKET_DATA, NO_SCHWAB_EQUIVALENT, GOVERNED_EXCEPTION (O-NN)** dispositions do not require performance proof — there is no replacement to measure. They still need their own evidence per V4 evidence bar.
- **Do not let "we don't have a measurement harness yet" pass.** Building the harness is `tests/perf_proof/` infra work that must precede the first replacement claim. Without the harness, no replacement is admissible — full stop.
