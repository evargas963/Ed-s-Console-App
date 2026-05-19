# Pilot 1 — Schwab walk + authority UX staging plan

**Status:** SIGNED — operator, Claude, and Cursor aligned (2026-05-18)  
**Supersedes:** Ad-hoc A/B/C discussion only; does not replace locked framework docs  
**Authority docs:** `FRAMEWORK_V2_TARGET_LOCK_RECORD.md`, `IMPLEMENTATION_BLUEPRINT_V2.md`, `INSTITUTIONAL_STANDARD_V3.md`, `architecture_parallel_vs_cascade_competition_spec.md`  
**Tracker home:** `OPEN_ITEMS.md` (Current track header + `[TRACK n]` tags)

---

## Program motto

> **Stack and UI must be honest, consistent, and traceable from real data. Edge is proven separately — never implied by labels alone.**

- **Integrity confidence** — correct field, label, degradation, provenance (I-01, I-16).
- **Edge confidence** — calibration, backfill, promotion, live vs replay (parallel workstream).

---

## What this plan is / is not

| This plan | Not this plan |
|-----------|----------------|
| Staging for **Schwab V4 file-by-file disposition walk** (primary daily work) | Replacing the universal coverage register program |
| One **gated** UI PR for desk authority (`final_confidence`) after producer walks | Four parallel horizon stacks (OPEN_ITEMS L145) — **Phase 4 deferred** |
| Resolving A/B/C without mixing UI into register commits | New trade authority for `v2_decision` (stays advisory) |

**One-line contract:** Keep Schwab file-by-file walk as the only default work; fix `market_state` `or 0.0` on the MHA spine; after `multi_horizon_decision.py` and `bayesian_fusion.py` are walked, ship one Phase 2 UI PR if operator says **go Track 2** — then resume the file queue.

---

## A/B/C resolution (locked)

| Option | Meaning | Decision |
|--------|---------|----------|
| **A** | Current Pilot 1 A1 spine is plan-aligned | **Accepted** — continue Schwab walk |
| **B** | Promote `final_confidence` to desk headline; align v2 + Decision Command | **Phase 2** — one PR after producer walk gate |
| **C** | b23a1e6 — HORIZON CONF vs Fused Confidence labels | **Done** |

---

## Trust problem (why Phase 2 exists)

Per-source numbers can be correct while **cross-surface hierarchy** is broken:

| Surface | Source |
|---------|--------|
| Top card (×4) | `mhap_rows[i].confidence` |
| Hz-panel | `fusion_policy_snapshot_cols["fused_confidence_<hz>"]` + Horizon fallback |
| CONF pill | `call_conviction` (qualitative) |
| V2 Pilot card | `fusion_confidence → confidence → final_quality` (not `final_confidence` today) |
| Tooltip only | `final_confidence` (MHA desk aggregate) |

**Agreed desk headline (Pilot 1 A1):** `final_confidence` from `multi_horizon_decision`.

**After Phase 2:** one numeric desk confidence on Decision Command + V2 card; per-horizon in collapsible breakdown; CONF pill stays qualitative; v2 remains advisory.

---

## Phases

### Phase 0 — This document

Signed alignment record. Optional `OPEN_ITEMS.md` track tags (see tracker).

### Phase 1 — PRIMARY: Schwab file-by-file walk

**This is the original cleanup project. Not a detour.**

**Commit rule:** Register slice + disposition + paired fix-as-we-find only. **No Phase 2 UI in walk commits.**

**Walk order (spine first):**

1. `multi_horizon_decision.py` — gate file for `final_confidence` / `mhap_rows`
2. `bayesian_fusion.py` — `fused_confidence_<hz>`
3. `signals.py` — stack → MHA → call
4. `market_context.py` — index/quote producers
5. `prediction_engine.py`, `call_engine.py`, `liquidity_value_engine.py`, … — continue mega/section queue

**Protocol:** Full read per chunk → register slice CSV + builder → `validate_citation_text` where supported → perf-proof when warranted → commit tallies match CSV.

**Paired fix (I-01, Phase 1):** `market_state.py` ~1420 — do not coerce missing MHA `final_confidence` to `0.0`:

```python
_fc = getattr(_mhd, "final_confidence", None)
ms.final_confidence = float(_fc) if _fc is not None else None
```

Land in **multi_horizon chunk-1** (or earliest MHA-spine commit) with rationale in commit body.

**Phase 1 gate (minimum for Phase 2):** Items 1 and 2 merged with citations; item 3 recommended.

**Trigger:** Operator **`signed, go multi_horizon`** → chunk 1 disposition → Cursor implement → verify → repeat.

### Phase 2 — GATED: Authority UX (single PR)

**Start only after:** operator **`go Track 2`** + Phase 1 gate.

| Change | Location |
|--------|----------|
| `_confidence(ms)` prefers `final_confidence` when present | `v2_decision/module_a_adapter.py` |
| Decision Command primary numeric = `final_confidence` | `static/index.html` |
| Per-horizon → collapsible breakdown | `static/index.html` |
| V2 Pilot card: confidence row (same desk number) | `renderV2PilotDecision` |
| UNAVAILABLE + reason when MHA absent | UI + Tier C (I-01) |
| Tests | adapter + static HTML |

**Non-goals:** No fusion/MHAP math change; no four horizon stacks; no v2 trade authority.

**Operator contract (§9 — locked):**

| Q | Answer |
|---|--------|
| Q1 `final_confidence` vs `call_conviction` | Can disagree; pill qualitative, numeric on Decision Command |
| Q2 MHA skipped | UNAVAILABLE + banner; not silent fusion as headline |
| Q3 probability vs confidence | Separate rows; do not collapse `dominant_probability` with confidence |
| Q4 Tier A/B | No desk confidence on `/api/live/state` or `/api/analytics/light`; Tier C only |
| Q5 V2 card | Add confidence row aligned with Decision Command |

**Phase 2 acceptance:** Headline shows UNAVAILABLE when `final_confidence` is null/missing; never silent `0%` unless MHA truly sent `0.0`.

### Phase 3 — Pilot 1B A2 (later)

Per `IMPLEMENTATION_BLUEPRINT_V2.md` Pilot 1B. After desk hierarchy stable.

### Phase 4 — DEFERRED: Four horizon stacks + four Calls

OPEN_ITEMS L145/L147. Not the same as base-model `parallel_vs_cascade` parallelism.

**Gates:** Phase 2 shipped + horizon honesty (60m, prob grid) + retrain plan + explicit go/no-go.

---

## Roles

| Step | Owner |
|------|--------|
| Disposition brief per chunk | Claude |
| Walk commit (slice, builder, perf-proof, paired fix) | Cursor |
| Post-commit verify | Claude / operator |
| Phase 2 UI PR | Cursor after **go Track 2** |

---

## Sign-off checklist (all YES — 2026-05-18)

1. Guiding star is program motto  
2. Phase sequence 1 → 2 → 3 → 4; Phase 4 gated  
3. `final_confidence` = desk headline for Pilot 1 A1  
4. Per-horizon visible but subordinate (breakdown)  
5. v2 stays advisory  
6. One stack today; four horizon stacks = Phase 4 only  
7. Tracker = `OPEN_ITEMS.md` + this document  
8. Phase 2 after `multi_horizon_decision.py` + `bayesian_fusion.py` walks  

---

## Context — already shipped

- `server.py` Schwab walk chunks 1–5  
- `market_state.py` chunks 6–7  
- **`multi_horizon_decision.py` chunk 1 (L1–854)** — register slice + I-01 `final_confidence` consumer fix (`market_state.py:1420`)  
- **`bayesian_fusion.py` chunk 1 (L1–859)** — register slice; `FusionPayload` producer (fail-closed; no code change)  
- **`signals.py` chunk 1 (L1–1422)** + **`features/fusion_policy_contract.py` (L1–106)** — `fused_confidence_<hz>` producer chain bound  
- **`market_context.py` chunk 1 (L1–961)** — 32 REPLACED quote/pricehistory leaves; `mkt_ctx.*` + `price_levels` producer  
- b23a1e6 — horizon vs fused labels  
- CONFIDENCE-1a — `MarketState.confidence` docstring  
- `v2_decision` adapter, schema, Tier C attach, `#v2-pilot-card` (advisory; authority UX gap remains)

---

## Amendment log

| Date | Change |
|------|--------|
| 2026-05-18 | Initial signed staging plan (operator + Claude + Cursor) |
| 2026-05-18 | `multi_horizon_decision.py` chunk-1 walk (slice + L1420 fix) |
| 2026-05-18 | `bayesian_fusion.py` chunk-1 walk (slice; fusion_policy_contract deferred to signals.py) |
| 2026-05-18 | `signals.py` + `fusion_policy_contract.py` chunk-1 walk (fused_confidence_<hz> chain complete) |
| 2026-05-19 | `market_context.py` chunk-1 walk (32 REPLACED; P_count 12; Phase 1 spine complete) |
| 2026-05-18 | `call_engine.py` chunk-1 walk (0 REPLACED; Decision Command / validation / sizing producer chain) |
| 2026-05-19 | `prediction_engine.py` chunk-1 walk (0 REPLACED; PredictiveCard / WTDS / MHA per-horizon inputs) |
| 2026-05-19 | `rules_engine.py` chunk-1 walk (0 REPLACED; Right Now + stack micro vote; **TRACK 1 priority complete**) |
| 2026-05-19 | `regime_engine.py` chunk-1 walk (0 REPLACED; FIND-RE1 L372 audit-message fix; Mega queue #1) |
| 2026-05-19 | `volatility_regime.py` chunk-1 walk (0 REPLACED; STACK ORDER 2 policy producer; Mega queue #2) |
| 2026-05-19 | `monte_carlo.py` chunk-1 walk (0 REPLACED; mc_eae/efe/containment producer; Mega queue #3) |
| 2026-05-19 | `mc_fusion_adjustment.py` chunk-1 walk (0 REPLACED; post-fusion MC adjust; Mega queue #4) |
| 2026-05-19 | `ml_predict.py` chunk-1 walk (0 REPLACED; parallel stack XGB/LSTM/TR; Mega queue #5) |
| 2026-05-19 | `order_flow_engine.py` chunk-1 walk (0 REPLACED; slice-only; FIND-OF1–7 disclosed; 1161-line HEAD) |
| 2026-05-19 | `order_flow_engine.py` chunk-2 paired fix (FIND-OF1/OF2 — preserve 0.0 measurements through book_for_score / tape_for_score selection) |
| 2026-05-19 | `liquidity_value_engine.py` chunk-1 walk (0 REPLACED; 26 KEEP_DERIVED; 4 PASS_THROUGH; FIND-LVE1/STYLE-LVE2 disclosed; 1520-line HEAD) |
| 2026-05-19 | **Phase 2** authority UX — `final_confidence` desk headline (Track 2) |
| 2026-05-19 | **Phase 1 closure** — 14 producer walks + 2 paired fixes; deferred FINDs → `OPEN_ITEMS.md` |
| 2026-05-19 | `order_flow_engine.py` chunk-3 paired fix (FIND-OF3/OF4/OF5 — renormalize-over-present composite + rvol_is_None readiness branching) |
| 2026-05-19 | `liquidity_value_engine.py` chunk-2 paired fix (FIND-LVE1 — log info on ATR→percent threshold fallback) |
| 2026-05-19 | `order_flow_engine.py` chunk-4 paired fix (FIND-OF6/OF7 — withhold direction/verdict labels at exact-zero composite) |
| 2026-05-19 | `call_engine.py` Layer 5 chunk-2B (FIND-CE3/CE4/CE6/CE7/CE8 — gate/sizing/vol_regime fail-closed) |
| 2026-05-19 | FIND-OF8 + disclosure-accept (STYLE-LVE2, magic thresholds); Phase 1 deferred list closed |
| 2026-05-19 | `features/parallel_stack_schema.py` Layer 5 chunk-1 walk (0 REPLACED; 3 KEEP_DERIVED; FIND-PSS1/PSS2 disclosed; Action 12.11 contracts locked) |
| 2026-05-19 | `mc_fusion_adjustment` + `prediction_engine` Layer 5 chunk-2 paired fix (FIND-MCF1/MCF2 — degenerate `_triplet` / `_norm_triplet_floats` fail-closed instead of silent 1/3) |
| 2026-05-19 | `features/regime_mvp_context.py` Layer 5 chunk-1 walk + MVP2 paired fix (`mvp_net_gamma` float coerce; FIND-MVP1 `mvp_zone` "unknown" sentinel disclosed pending consumer audit) |
| 2026-05-19 | `features/xgb_model_input.py` Layer 5 chunk-1 walk (0 REPLACED; 7 KEEP_DERIVED; FIND-XGB1/XGB2 disclosed pending ml_predict caller audit) |
| 2026-05-19 | `features/lstm_sequence_input.py` Layer 5 chunk-1 walk (0 REPLACED; 9 KEEP_DERIVED; FIND-LSI1/LSI2 disclosed) |
| 2026-05-19 | `features/canonical_contract.py` Layer 5 chunk-1 walk (0 REPLACED; 5 KEEP_DERIVED; clean — OBS-CC1/CC2 informational disclosures) |
| 2026-05-19 | `features/mvp_source_coercion.py` Layer 5 chunk-1 walk + MSC1 paired fix (`_require_mapping` at coercion entry points; closes non-Mapping silent-all-None laundering) |
| 2026-05-19 | `features/db_feature_adapter.py` Layer 5 chunk-1 walk (0 REPLACED; 1 KEEP_DERIVED; 10 PASS_THROUGH; clean; MSC1 propagation locked) |
| 2026-05-19 | `features/fusion_model_input.py` Layer 5 chunk-1 walk + FMI1 paired fix (Mapping guard in similar_setup_filters_from_db_snapshot_row; pairs with MSC1) |
| 2026-05-19 | Combined paired fix MVP1 + XGB1 + XGB2 (mvp_zone None; envelope ticker/as_of_ts strict; ml_predict ticker resolve) |

---

## Phase 1 closure — 2026-05-19

### Walks completed

| # | File | Commit | Tally (REPLACED/KD/PT/NMD) | Notes |
|---|------|--------|----------------------------|-------|
| 1 | multi_horizon_decision.py | 33a7a2f | 0/22/14/818 | TRACK 1 priority |
| 2 | bayesian_fusion.py | d3f0ce8 | 0/32/16/811 | TRACK 1 priority |
| 3 | signals.py + features/fusion_policy_contract.py | a4d46c2 | 0/28/26/1474 (combined) | TRACK 1 priority |
| 4 | market_context.py | 03c6a8f | 32/23/5/901 | TRACK 1 — first net-new REPLACED since V4-A chunk-5 |
| 5 | call_engine.py | 3a55cfe | 0/39/15/1714 | TRACK 1 priority |
| 6 | prediction_engine.py | ec5d8a3 | 0/21/11/1217 | TRACK 1 priority |
| 7 | rules_engine.py | ddfd853 | 0/9/12/233 | TRACK 1 priority complete |
| 8 | regime_engine.py | 5b1c1f4 | 0/16/15/532 | Mega #1 + FIND-RE1 paired fix |
| 9 | volatility_regime.py | e4dc72b | 0/13/8/270 | Mega #2 |
| 10 | monte_carlo.py | 6b66a31 | 0/13/5/407 | Mega #3 |
| 11 | mc_fusion_adjustment.py | 4a2f5ab | 0/10/5/568 | Mega #4 |
| 12 | ml_predict.py | fbc69fa | 0/19/6/1606 | Mega #5 |
| 13 | order_flow_engine.py | dfa1f82 | 0/14/5/1142 | Slice-only; FIND-OF1–7 disclosed |
| 14 | liquidity_value_engine.py | 73bb17f | 0/26/4/1490 | Slice-only; FIND-LVE1/STYLE-LVE2 disclosed |

### Paired fixes landed

| # | Fix | Commit | Files | Tests added |
|---|-----|--------|-------|-------------|
| 1 | FIND-RE1 — VWAP-contra audit message (regime_engine.py L372) | within 5b1c1f4 | regime_engine.py | 1 |
| 2 | FIND-OF1/OF2 — preserve 0.0 measurements through book/tape score selection | e8559ea | order_flow_engine.py L860/L868 | 6 |

### Phase 2 (Track 2, separately tracked)

| Track | Status | Commit |
|---|---|---|
| Authority UX — `final_confidence` desk headline | Done | fadc9be + b23a1e6 |

### Scoreboard at closure

| Metric | Value |
|---|---|
| Producer files walked this pilot | 14 (12 unique + 1 combined signals/fusion_policy + 1 paired-fix-only) |
| REPLACED rows added this pilot | 32 (from market_context.py only) |
| Paired fixes landed | 2 (FIND-RE1 audit message; FIND-OF1/OF2 0.0-preservation) |
| P_count (Schwab register pinned) | 12 → 12 unchanged |
| Walk-cumulative REPLACED (V4 program) | ~95 + 32 = ~127 |
| Disclosure backlog (deferred) | Closed 2026-05-19 — see OPEN_ITEMS.md Pilot 1 subsection |

### Deferred items (historical — all substantive FINDs closed)

Substantive items closed in paired-fix commits (OF1–OF8, LVE1, FIND-RE1, FIND-CE3–CE8). Remaining accepted disclosures only:

- **STYLE-LVE2** — mixed `in tags` vs `in str(tags)` in liquidity_value_engine snapshot builders; accepted (substring match intentional for VWAP band tags).
- **Magic thresholds** — POC shift 0.002, VWAP-vs-POC 0.001, new_value_area 0.005, zone-edge proximities 0.995/0.998/1.002; accepted informational disclosures in liquidity_value_engine.py.
