> **Classification:** Policy Specification | **Scope:** Governance documentation `mc_fusion_adjustment.py.md`.

# Review memo — mc_fusion_adjustment.py

**Status:** pending gatekeeper review
**Date:** 2026-05-24
**Reviewer:** Claude (proposed) → Gatekeeper (verified) → Operator (O-XX if needed)
**File language family:** python
**Evidence bar:** `governance/SCHWAB_REPLACEMENT_LOOP_PROTOCOL_V4.md` § **Evidence bar (V4-A enforcement)** + `AGENTS.md` §V4 walk / review-memo rule (gatekeeper CSV-first cross-check, 2026-05-24 @ `977e706`)

**Closest-shape precedent** (per `AGENTS.md` Posture rules — sibling-pattern conformance): `bayesian_fusion.py.md` @ `977e706` (immediate sibling — adjacent post-fusion MC layer, same fusion-math-only shape, just-landed gatekeeper CSV cross-check appendix is the model for the section below); `signals.py.md` (original all-NOT_MARKET_DATA precedent); `call_engine.py.md` / `prediction_engine.py.md` (money-path roster shape).

**Active-posture Class A check** (per `AGENTS.md` §Active agent posture + §Fix everything we touch): no Schwab-replaceable derivation, no non-canonical fallback, no Schwab wire-token leak. **One in-cone hardening landed this slice:** `fuse_payload_apply_mc_adjustment` stored-triplet simplex fix (round → renormalize → fail-closed argmax-flip guard) so persisted `FusionPayload.prob_*` legs always sum to exactly 1.0 — closes a foot-gun where ~18% of cases stored sums of `0.999998` / `1.000001` etc. that consumers (`fusion_policy_contract`, `canonical_forecast_from_fusion`, MH bundle, display, calibration JSON, audit trails) had to renormalize defensively. Code + paired test land same commit per Class A bundling.

---

## Gatekeeper CSV cross-check (mandatory per AGENTS §V4 walk rule, 977e706)

**Tool:** `python tools/check_schwab_csv_first.py --gatekeeper-crosscheck mc_fusion_adjustment.py`
**CSV lookup tokens loaded:** 394 (from `schwab_field_inventory/schwab_field_dictionary.csv`)
**lexical_csv_collision_count:** 2

| # | line | kind | token | CSV would suggest | Actual use | Classification |
|---|------|------|-------|---------------------|------------|----------------|
| 1 | L50 | `dict.get` | `'volatility'` | `chains.callExpDateMap.*.volatility` (dict L62), `chains.putExpDateMap.*.volatility` (L129), `chains.volatility` (L158), `chains.callExpDateMap.*.theoreticalVolatility` (L56) | `mc_output.get("volatility")` reading from MonteCarloOutput's `mc_feature_dict()` return shape (path-simulation-derived MC feature, not Schwab chain greek). | **HOMONYM** — MC feature namespace; producer is `monte_carlo.py` path simulation. |
| 2 | L50 | literal | `'volatility'` | (same set as #1) | Same line as #1 — single source-token site flagged twice by AST extractor (one as dict-key arg, one as constant). | **HOMONYM** — same site, single use. |

**Zero wire reads.** No `q_json[...]` / `c_json[...]` / `pricehistory[...]` / `streaming.content.*` subscripts anywhere in 637 lines. The MC feature dict (`expected_move` / `volatility` / `skew` / `tail_risk` / `directional_bias`) is `monte_carlo.MonteCarloOutput.mc_feature_dict()` return shape — internal-engine projection, not Schwab payload.

---

## Audit methodology (clause 4 — attribute / call / subscript)

Audited **this file** (637 lines) for:

| Channel | Method |
|---------|--------|
| String-literal dict access on Schwab payloads | None — file does not subscript any Schwab JSON payload. |
| Bracket dict access on Schwab payloads | None. |
| String-literal dict access on internal MC feature dict | `mc_output.get("expected_move"\|"volatility"\|"skew"\|"tail_risk"\|"directional_bias")` (L48, L50, L52, L54, L56) — MonteCarloOutput's `mc_feature_dict()` projection (internal engine namespace, see Gatekeeper CSV cross-check above for the one CSV-collision token `volatility` classified as homonym). |
| String-literal dict access on internal normalized MC dict | `mc_features["mc_volatility"\|"mc_tail_risk"\|"mc_bias"]` + `mc_features.get(...)` (L441, L447, L449, L451) — `normalize_mc` output namespace (prefix `mc_` deliberately disambiguates from any unprefixed schema). |
| Attribute access on market-bearing objects | `getattr(mc_out, "available"\|"mc_feature_dict")` (L531, L571); `getattr(fusion, "prob_up"\|"prob_down"\|"prob_flat")` (L543–547) on `FusionPayload`-like object; `fusion_is_authoritative(fusion)` (L527) from `fusion_contract`. All Python dataclass / object attributes, not Schwab JSON keys. |
| Method calls passing Schwab market objects | None — calls pass `fusion` (FusionPayload), `mc_out` (MonteCarloOutput), and `spot_price` (float). |
| Internal projection-key reads (NOT Schwab wire) | `raw.pop("source", None)` (L577) on the MC feature dict — operator-tagged MC bundle source label, not Schwab. `mc_feature_source` audit key (L605). `pre_triplet` / `post_triplet` / `normalized_mc` / `base_argmax` / `final_argmax` (L595–605) — internal audit payload keys. |
| Schwab field dictionary citations consumed | None at the wire-token layer (all-NOT_MARKET_DATA file). Indirect: callers pass `FusionPayload` whose `prob_up/prob_down/prob_flat` originate from `bayesian_fusion.fuse()` (typed at the boundary; LEAF citations belong to upstream producer + populator memos). |

**Review complete:** Every site **in this file** falls under **S1–S10** below; no Schwab `example_raw_field` tokens, chain JSON subscripts, or streaming content keys occur anywhere in `mc_fusion_adjustment.py`. The single CSV-token collision (`volatility` at L50) is a confirmed homonym (MC feature namespace, not chain greek) per the Gatekeeper CSV cross-check section above.

---

## Market-data sites identified

### S1 — Module imports + module logger

- **lines:** L15–30.
- **surface:** Imports `math`, `logging`, `dataclasses.replace`, typing helpers; `fusion_is_authoritative` from `fusion_contract`. Module logger.
- **proposed disposition:** **NOT_MARKET_DATA** — module scaffolding.
- **code edit:** none.

### S2 — `normalize_mc` (MC feature dict → bounded normalized inputs)

- **lines:** L36–106.
- **surface:** Reads five MC feature keys from `mc_output: Mapping[str, Any]` — `expected_move` (L48), `volatility` (L50), `skew` (L52), `tail_risk` (L54), `directional_bias` (L56). Each key originates from `monte_carlo.MonteCarloOutput.mc_feature_dict()` return shape (operator-defined MC feature namespace). Fail-closed when any key is None (L58–60), non-numeric (L64–78), non-finite (L80–82), or when `spot_price` is None/zero/non-finite (L86–90). Returns normalized dict with `mc_expected_move = em / sp`, `mc_volatility = vol / sp`, plus clamped `mc_skew` (`[-3, 3]`), `mc_tail_risk` (`[0, 1]`), `mc_bias` (`[-1, 1]`).
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab wire-token layer — normalizes internal MC engine output to bounded scaled inputs; no Schwab JSON. The L50 `'volatility'` key is a confirmed CSV-token homonym (see Gatekeeper CSV cross-check).
- **observation:** Fail-closed at every boundary — no fabricated zeros (per docstring L44).
- **code edit:** none.

### S3 — `_triplet` (probability triplet L1-normalizer)

- **lines:** L112–126.
- **surface:** Float coerce, finiteness check, L1-normalize. Returns None when input non-finite or sum ≤ 0.
- **proposed disposition:** **NOT_MARKET_DATA** — pure math.
- **code edit:** none.

### S4 — `_argmax_dir` (winning direction)

- **lines:** L132–135.
- **surface:** Delegates to `numeric_contract.direction_from_normalized_triplet(u, d, f)`.
- **proposed disposition:** **NOT_MARKET_DATA** — pure math delegation.
- **code edit:** none.

### S5 — `_blend_uniform` (uniform-blend triplet)

- **lines:** L141–161.
- **surface:** `((1-lam)*p + lam/3.0)` per class; renormalize via `_triplet`. Falls back to input on degenerate `_triplet` return.
- **proposed disposition:** **NOT_MARKET_DATA** — pure math.
- **code edit:** none.

### S6 — `_max_uniform_blend_preserving_argmax` (binary search)

- **lines:** L167–203.
- **surface:** Binary search in `[0, max_lam]` for largest `lam` such that `_blend_uniform` preserves the input `winner`. 22 iterations, 1e-7 tolerance.
- **proposed disposition:** **NOT_MARKET_DATA** — pure math search.
- **code edit:** none.

### S7 — `_add_to_flat_from_others` + `_max_tail_flat_delta`

- **lines:** L209–283 (`_add_to_flat_from_others`); L289–321 (`_max_tail_flat_delta`).
- **surface:** Add mass to flat from non-winner buckets (pool ordering depends on winner); binary search the max delta that preserves argmax. Uses `min(rem, max(0.0, p) * 0.95)` floor to avoid full drain.
- **proposed disposition:** **NOT_MARKET_DATA** — probability transport math; fail-closed when `_triplet` returns None (L279–281).
- **code edit:** none.

### S8 — `_apply_directional_bias`

- **lines:** L327–395.
- **surface:** Move at most `max_shift` total mass toward up (bias>0) or down (bias<0) without flipping argmax. Take from non-winner first via 0.9 cap to avoid total drain. Returns input unchanged on degenerate triplet or argmax flip (with debug log L383, L391).
- **proposed disposition:** **NOT_MARKET_DATA** — probability transport math with explicit invariant checks.
- **code edit:** none.

### S9 — `apply_mc_adjustment` (public API)

- **lines:** L401–511.
- **surface:** Three-step adjustment on input `(prob_up, prob_down, prob_flat)`:
  1. **Volatility blend (L455–459):** `max_lam = min(0.22, 0.14 * vol)` cap; binary-search max blend; `_blend_uniform`.
  2. **Tail flat (L463–467):** `tail_cap = min(0.18, 0.10*tail + 0.06*tail*vol)`; binary-search max delta; `_add_to_flat_from_others`.
  3. **Directional bias (L471):** `max_shift = 0.05` cap; `_apply_directional_bias`.
  Clamp each to `[0, 1]` (L475–479); renormalize (L481–489); fail-closed argmax invariant check (L493–497 — reverts to base on argmax flip with warning).
- **proposed disposition:** **NOT_MARKET_DATA** — adjustment pipeline orchestration over MC features and probability triplet.
- **observation:** Per the module docstring (L1–13): "Monte Carlo is not a probability model here; it only modulates confidence / flat mass / small directional nudge without changing the base fusion argmax." Three explicit invariant guards (degenerate input L429–433, missing MC feature L441–445, post-adjustment argmax mismatch L493–497) — all fail-closed reverting to base fusion triplet.
- **code edit:** none.

### S10 — `fuse_payload_apply_mc_adjustment` (FusionPayload integration)

- **lines:** L517–636.
- **surface:** Checks `fusion_is_authoritative(fusion)` (L527); checks `getattr(mc_out, "available", False)` (L531); reads `fusion.prob_up/prob_down/prob_flat` (L543–547); calls `mc_out.mc_feature_dict()` (L571, defensive `callable(fd)` guard); pops the bundle source label (L577); calls `normalize_mc(raw, sp)` (S2); applies `apply_mc_adjustment` (S9); assembles audit dict (L593–607) with `pre_triplet` / `post_triplet` / `normalized_mc` / `base_argmax` / `final_argmax` / `mc_feature_source`; returns `dataclasses.replace(fusion, ...)` with updated triplet + `mc_post_fusion_audit` field. Falls back to `setattr` on `TypeError` (L625–635 — supports non-dataclass FusionPayload-like objects).
- **proposed disposition:** **NOT_MARKET_DATA** — FusionPayload integration glue. The `mc_post_fusion_audit` field on FusionPayload is the operator-side audit channel (per `bayesian_fusion.py.md` S1 FusionPayload field declaration).
- **observation:** Every boundary check fail-closed (returns the input `fusion` unchanged on missing MC, non-finite triplet, degenerate triplet sum, missing MC features, etc.). The `dataclasses.replace` path preserves immutability when supported; `setattr` fallback handles non-dataclass callers.
- **in-cone hardening this slice (L590–648):** Round each leg to 6 decimals for storage, then renormalize via `_triplet` so persisted `FusionPayload.prob_up/prob_down/prob_flat` always sum to exactly 1.0. Fail-closed guard: if rounded triplet flips argmax, keep the pre-round adjusted triplet. The audit `post_triplet` now reads from the stored values (`u_out/d_out/fl_out`) so audit matches payload exactly — no double-round drift.
- **code edit:** landed — stored-triplet simplex fix + paired test `tests/test_mc_fusion_adjustment.py::test_fuse_payload_stored_triplet_sums_to_one_after_round` (200-case sweep asserting `sum == 1.0` exactly + argmax preserved + audit-vs-payload parity; 16/16 pass on mc_fusion slice).

---

## Appendix A — NOT_MARKET_DATA clusters (wire-token layer)

**Entirety of this file is NOT_MARKET_DATA at the Schwab wire-token layer.** No `q_json[...]` / `c_json[...]` / `pricehistory[...]` / `streaming.content.*` subscripts occur anywhere in 637 lines. Bulk classification:

- **Module scaffolding (S1):** Imports + logger.
- **MC normalization (S2):** Reads MC feature dict from `MonteCarloOutput.mc_feature_dict()` (internal engine projection); single CSV-token collision (`volatility` at L50) confirmed homonym (MC feature, not chain greek) per Gatekeeper CSV cross-check.
- **Probability math primitives (S3–S8):** `_triplet` L1-normalizer, `_argmax_dir`, `_blend_uniform`, binary-search adjustment magnitudes, mass-transport-with-pool-ordering. All operate on float triplets; no Schwab JSON.
- **Public API (S9):** `apply_mc_adjustment` orchestrates the three-step adjustment with explicit argmax-invariant fail-closed reverts.
- **FusionPayload glue (S10):** `fuse_payload_apply_mc_adjustment` reads typed FusionPayload attributes, normalizes MC features via S2, applies adjustment via S9, replaces the triplet + writes audit dict. Fail-closed at every boundary.

This file's contribution to V4 closure is **establishing the post-fusion MC context layer** as Schwab-wire-clean: all Schwab-sourced numerics arrive as already-typed `FusionPayload.prob_*` attributes (LEAF citations live in `bayesian_fusion.py.md` chain + upstream producer/populator memos); the MC feature dict is operator-defined engine projection (not Schwab payload). The single CSV-token homonym (`volatility`) was caught by the mechanical AST + dictionary cross-check landed @ `977e706` and confirmed as a non-wire-read.

---

## Aggregate disposition for inventory

- **status:** pending (awaiting gatekeeper)
- **memo_ref:** governance/SCHWAB_V4_REVIEW_MEMOS/mc_fusion_adjustment.py.md
- **Class A determination:** code + test + memo bundled same commit per AGENTS §Fix everything we touch. No Schwab wire-token leak, no Schwab-replaceable derivation, no non-canonical fallback. One in-cone hardening landed (S10 stored-triplet simplex fix + paired test). Single CSV-token collision (`volatility` L50) confirmed homonym via mechanical cross-check (tool: `tools/check_schwab_csv_first.py --gatekeeper-crosscheck`, landed @ `977e706`).
