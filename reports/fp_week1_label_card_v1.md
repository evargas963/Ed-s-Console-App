# Week-1 experiment card — G-LABEL (preregistered)

**Status:** DRAFT — awaiting operator lift of PAUSE + explicit GO  
**Authority:** Claude triage A (`reports/fp_claude_edge_reply.md`) + Cursor acceptance  
**Money-path:** WAIT throughout (admissions stay empty)

## Hypothesis

Prior Find & Prove 0-PASS cells are **uninterpretable** while production direction labels use admitted placeholder constants (`calibration/movement_target_thresholds_by_horizon_v1.json`, `selected_percentile: null`). Replacing those with a **per-ticker cost+vol floor** (and preparing an economic primary target) is required before any model work.

## In scope (Week 1 only — zero model / zero existence screens)

1. **Threshold policy (choose one, commit before recompute):**  
   `threshold_pts(ticker, hz) = max( k · ATR_hz(ticker), round_trip_cost_pts(ticker) )`  
   with `k` and cost model written into the proof JSON before any DB write.  
   *Optional alternate:* run `tools/select_movement_thresholds_percentile_v1.py` **then** enforce cost floor — still must clear G-LABEL.
2. **Recompute** governed snapshot outcomes + decision-log attaches under the new thresholds (research surface; production serving policy unchanged until operator admits).
3. **Report** per-ticker class balance and bp-equivalent of flat band vs cost.
4. **Close or narrow** `FIND-LABEL-INTEGRITY-FORENSICS` with physical cause for extreme cells.
5. **Gates before any Week-2 model:** G-LABEL §1–3 from Claude reply; label-permutation / shuffled-label scheduled as G-LABEL §4 (may span into Week 2 start — no model until green).

## Out of scope

- New FP model families, re-screens, admission packets  
- Widening `BACKFILL_JOIN_TOL_SEC`  
- Live money-path / TRADE influence  
- Triple-barrier primary label **implementation complete** may start as scaffolding but **existence scoring** waits for G-LABEL green

## Acceptance (G-LABEL)

| # | Gate | Pass condition |
|---|---|---|
| 1 | No placeholders | Every active horizon has non-null `selected_percentile` **or** documented cost+vol floor; JSON notes no longer “Placeholder…until percentile search” |
| 2 | Cost floor | Per ticker×horizon, flat-band width in pts ≥ round-trip cost pts |
| 3 | Integrity | Per-ticker balances reported; FIND-LABEL extremes explained or quarantined with reason |
| 4 | Leakage | Best diagnostic model MCC on shuffled labels ≈ 0 (Claude independently re-runs) |

**Claude:** independently recomputes thresholds/balances and permutation check.  
**Cursor:** implements selection + recompute + proof JSON only after operator GO.

## Stop rule

If G-LABEL cannot be met without fabricating ATR/cost inputs → STOP Week 1, escalate to operator (do not proceed to Week 2).

## Operator GO phrase (required)

`GO WEEK1 LABEL` — lifts execution of this card only; hunt PAUSE otherwise remains for model work.
