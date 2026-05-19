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
| 2026-05-19 | **Phase 2** authority UX — `final_confidence` desk headline (Track 2) |
