> **Classification:** Policy Specification | **Scope:** Governance documentation `bayesian_fusion.py.md`.

# Review memo — bayesian_fusion.py

**Status:** pending gatekeeper review
**Date:** 2026-05-24
**Reviewer:** Claude (proposed) → Gatekeeper (verified) → Operator (O-XX if needed)
**File language family:** python
**Evidence bar:** `governance/SCHWAB_REPLACEMENT_LOOP_PROTOCOL_V4.md` § **Evidence bar (V4-A enforcement)**

**Closest-shape precedent** (per `AGENTS.md` Posture rules — sibling-pattern conformance, 2026-05-24): `signals.py.md` (original precedent for "all sites NOT_MARKET_DATA when no in-file Schwab JSON subscripts"); `call_engine.py.md` + `prediction_engine.py.md` (just-landed money-path roster shape — same posture as a fusion-layer consumer of typed model outputs).

**Active-posture Class A check** (per `AGENTS.md` §Active agent posture + §Fix everything we touch, 2026-05-24): no Schwab-replaceable derivation, no non-canonical fallback, no in-file FIND requiring a code change. **Class A memo-only — no fix to bundle.**

---

## Audit methodology (clause 4 — attribute / call / subscript)

Audited **this file** (850 lines) for:

| Channel | Method |
|---------|--------|
| String-literal dict access on Schwab payloads | None — file does not subscript any Schwab JSON payload. |
| Bracket dict access on Schwab payloads | None. |
| Attribute access on market-bearing objects | `getattr(regime, "primary"\|"confidence")` on RegimePayload; `getattr(out, "available"\|"prob_up"\|"prob_down"\|"prob_flat"\|"continuation_support"\|"reversal_support"\|"confidence_label")` on XGB / LSTM / Transformer model output dataclasses; `getattr(mc_out, "available"\|"containment_prob"\|"expansion_prob"\|"expected_favorable_excursion"\|"expected_adverse_excursion"\|"upper_50"\|"lower_50"\|"n_paths"\|"horizon_bars"\|"assumptions")` on MonteCarloOutput; `getattr(rules, "signal"\|"conviction")` on RulesCard. All Python dataclass / object attributes, not Schwab JSON keys. |
| Method calls passing Schwab market objects | None — calls pass already-typed payload objects (RegimePayload, model outputs, MonteCarloOutput, RulesCard, FusionTickCache, FusionPayload). |
| Internal projection-key reads (NOT Schwab wire) | `_assum.get("garch_active"\|"scaled_sigma"\|"blended_sigma")` on MonteCarloOutput's `assumptions` dict (L763–764); `signal_layer_v1` payload keys via `features.signal_layer_v1.meta_n_bars_int` + `signal_layer_v1_to_direction_probs` helpers (L665, L669). None match any row in `schwab_field_inventory/schwab_field_dictionary.csv`. |
| Environment variables | `os.environ.get("ED_SIGNAL_LAYER_FUSION_BLEND", "0.38")` (L671) — operator-tunable blend weight; clamped to `[0, 1]` at L679. Not Schwab. |

**Review complete:** Every site **in this file** falls under **S1–S8** below; no Schwab `example_raw_field` tokens, chain JSON subscripts, or streaming content keys occur anywhere in `bayesian_fusion.py`.

---

## Market-data sites identified

### S1 — Module imports + `FusionPayload` dataclass

- **lines:** L1–114 — imports (L26–34); module logger (L36); `FusionPayload` dataclass (L43–113) with ~35 fields covering posterior probabilities for six outcome families, per-source trust weights (xgboost / lstm / transformer / monte_carlo / rules / regime), dominant posterior + fusion confidence, evidence quality counts, evidence/contradiction summaries, MC pass-through, model-agreement triplet, directional fusion (prob_up/down/flat), audit fields (`fusion_mc_contribution`, `mc_post_fusion_audit`, `signal_layer_v1_fusion`), and participation audit (`contributing_models`, `missing_models`).
- **surface:** Imports `direction_from_normalized_triplet` + `float_finite_or_none` from `numeric_contract`; standard library types only. `FusionPayload` field names are internal output projection keys (not Schwab wire tokens).
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab wire-token layer — module scaffolding + internal output shape.
- **code edit:** none.

### S2 — Module constants: `BASE_WEIGHTS`, `REGIME_WEIGHT_ADJUSTMENTS`, `DEFAULT_PRIORS`, `REGIME_PRIORS`

- **lines:** L117–183.
- **surface:** Four dict-of-floats constants — base trust weights per source (L121–128), regime-specific multipliers (L131–156), default outcome priors near-uniform (L164–171), regime-conditioned prior triplets (L174–183). All values are operator-tunable Bayesian fusion parameters.
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab wire-token layer — fusion math tunables; no Schwab field names, no leaf mappings.
- **code edit:** none.

### S3 — Helpers: `_resolved_regime_label` + `_model_dominant_class` + `_optional_support` + `_model_direction_triplet`

- **lines:** L190–235.
- **surface:** `_resolved_regime_label(regime)` (L190–200): `getattr(regime, "primary")` → str/lower; treats absent / `"unknown"` as `None` (fail-closed for fusion trust). `_model_dominant_class(out)` (L203–211): reads `out.available` + the normalized triplet; returns winning direction via `direction_from_normalized_triplet`. `_optional_support(out, attr)` (L214–215): `float_finite_or_none(getattr(out, attr, None))`. `_model_direction_triplet(out)` (L218–235): reads `out.prob_up / prob_down / prob_flat`; normalizes via `tot = up + down + flat` (rejects `tot <= 0` or non-finite — fail-closed); returns L1-normalized triplet.
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab wire-token layer — model-output attribute extraction + triplet normalization. No Schwab JSON reads.
- **observation:** `_resolved_regime_label` fail-closes when regime is None / absent / "unknown" — does not silently default to a fallback regime label. `_model_direction_triplet` fail-closes when any of the three probs is None, non-finite, or sums to ≤ 0 — does not surface a fabricated uniform triplet.
- **code edit:** none.

### S4 — Evidence translators: `_translate_xgb_evidence` + `_translate_lstm_evidence` + `_translate_transformer_evidence` + `_translate_rules_evidence`

- **lines:** L238–337.
- **surface:** Three model-evidence translators (L238–310) follow identical shape — read `out.available`, extract normalized triplet via `_model_direction_triplet`, read `continuation_support` + `reversal_support` via `_optional_support`; return six-key likelihood dict mapping `{breakout, continuation, reversal, pinning, vol_expansion, mean_reversion}` to float scores. Per-model scoring weights differ slightly (e.g., XGB: directional×0.8 for breakout vs LSTM/Transformer: ×0.7) — operator-tuned per model class. `_translate_rules_evidence` (L313–337): reads `rules.signal` + `rules.conviction`; returns conviction-multiplied likelihood dict for `(long/short)` lean vs `wait`.
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab wire-token layer — likelihood-translation math over typed model outputs. No Schwab JSON keys.
- **observation:** All translators fail-closed when `out.available` is False, when the triplet is None, or when `continuation_support` / `reversal_support` is None — returns empty dict `{}` which `_bayesian_update` then ignores (L394).
- **code edit:** none.

### S5 — `FusionTickCache` + `build_fusion_tick_cache`

- **lines:** L340–374.
- **surface:** Frozen dataclass capturing per-tick fusion prep (`regime_label`, `direction_hint`, `priors`, `weight_adjustments`, `rules_evidence`) that's invariant across horizons. `build_fusion_tick_cache(regime, rules)` resolves the regime label (S3), selects regime-conditioned priors (S2), builds the regime weight adjustment dict (S2), and pre-computes the rules-evidence likelihood (S4). Cached prep is then passed into `fuse(..., fusion_tick_cache=...)` per-horizon.
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab wire-token layer — perf optimization cache for the per-tick invariant prep.
- **code edit:** none.

### S6 — `_bayesian_update` (multiplicative posterior update)

- **lines:** L381–413.
- **surface:** Pure math — for each outcome family, multiplies prior by `Π_i [evidence_i(o) ^ weight_i]`, then L1-normalizes. Uses `max(0.01, lh)` floor on each likelihood (L403) to avoid log(0) singularities. Fallback to priors when normalization sum is non-positive (L410–411).
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab wire-token layer — Bayesian update math; no Schwab JSON.
- **observation:** `max(0.01, lh)` floor is a numerical-stability guard (avoid posterior collapse on a single near-zero likelihood); disclosed in the function docstring. `float_finite_or_none(likelihood)` check (L400–402) skips non-finite likelihoods — fail-disclosed by continuing the loop rather than fabricating values.
- **code edit:** none.

### S7 — `fuse` public API + `_fuse_impl` orchestrator

- **lines:** L420–811.
- **surface:** `fuse(regime, xgb_out, lstm_out, transformer_out, mc_out, rules, signal_layer_v1=None, fusion_tick_cache=None)` (L420–467): public API wrapping `_fuse_impl` in a broad try/except (L462–467) that returns `FusionPayload(available=False, fusion_summary=f"Fusion error: {e}")` on failure — **fail-disclosed**, not silent.
- **surface (`_fuse_impl` L470–811):**
  - **Tick-cache prep (L482–500):** uses cached prep when provided; else resolves regime label, selects priors, builds weight adjustments.
  - **Weight computation (L501–525):** applies regime multipliers to base weights; zeros out unavailable sources (including MC — intentionally excluded per L511–513); normalizes active weights to sum 1.
  - **Source-availability bookkeeping (L527–533):** counts `n_sources_available` + `n_sources_active`; assembles `contributing_models` + `missing_models` for explicit participation audit (L530–533).
  - **Evidence translation + Bayesian update (L536–563):** translates each available model's evidence (S4), runs `_bayesian_update` (S6) to produce posteriors.
  - **Confidence classification (L566–605):** dominant outcome + gap analysis → confidence tier; four dampening rules (low-predictive-count caps, calibration penalty `CALIBRATION_PENALTY = 0.85` at L603 with TODO for removal after 60+ days of calibration data, contradiction penalty applied after contradiction list is built at L731–734).
  - **Model agreement (L608–622):** Counter over model dominant directions; agreement label `high/medium/low` thresholds 0.75/0.5.
  - **Directional fusion (L624–660):** weighted blend of per-model prob triplets; L1-normalized; dominant direction via `direction_from_normalized_triplet`.
  - **signal_layer_v1 blend (L662–698):** when `signal_layer_v1` payload present AND `meta_n_bars_int ≥ 25`, blend the upstream directional triplet via env-tunable weight `ED_SIGNAL_LAYER_FUSION_BLEND` (default 0.38, clamped `[0, 1]`); audit dict captured in `signal_layer_v1_fusion` output field.
  - **Evidence + contradiction summaries (L700–728):** plain-English summary list (MC containment/expansion narrative, XGB dominant + confidence, regime label + confidence, rules lean); contradictions: model disagreement (agreement < 0.5) and pinning-vs-directional-rules clash.
  - **Damp 4 contradiction penalty (L731–742):** `conf_score *= 0.90` per contradiction (compounded for ≥ 2); re-classify confidence tier from final dampened score.
  - **Summary text assembly (L744–756):** `OUTCOME_LABELS` mapping; dominant outcome label + active-model count + agreement label.
  - **MC pass-through (L758–764):** reads MonteCarloOutput attributes — `n_paths`, `horizon_bars`, `assumptions.get("garch_active"|"scaled_sigma"|"blended_sigma")` — for downstream `FusionPayload` fields.
  - **FusionPayload assembly (L766–811):** ~35 fields rounded to 3 decimals; explicit `weight_monte_carlo=0.0` (L777) confirms MC's exclusion from fusion weights; `fusion_mc_contribution=None` + `mc_post_fusion_audit=None` (L806–807) note that MC enters only as post-fusion context (see `mc_fusion_adjustment.py`).
- **proposed disposition:** **NOT_MARKET_DATA** at Schwab wire-token layer — fusion-pipeline orchestration over typed model + regime + rules + MC objects.
- **observation:** Every source-availability check fail-closed (sets weight to 0 and skips evidence). Broad `except` in `fuse()` returns a structured unavailable FusionPayload with the error message — visible to caller, not silent. `_assum.get("garch_active")` etc. (L763–764) reads MonteCarloOutput's own `assumptions` dict — internal payload key, not Schwab JSON. The MC intentional exclusion (L511–513) is operator-cited per the docstring at L443.
- **code edit:** none.

### S8 — Self-test (`__main__` block)

- **lines:** L818–849.
- **surface:** `SimpleNamespace` mock construction of regime / rules / xgb / lstm / transformer / mc; call `fuse(...)`; print dominant outcome, confidence, source counts, summary. No Schwab JSON.
- **proposed disposition:** **NOT_MARKET_DATA** — diagnostic self-test scaffold.
- **code edit:** none.

---

## Appendix A — NOT_MARKET_DATA clusters (wire-token layer)

**Entirety of this file is NOT_MARKET_DATA at the Schwab wire-token layer.** No `q_json[...]` / `c_json[...]` / `pricehistory[...]` / `streaming.content.*` subscripts occur anywhere in 850 lines. Bulk classification:

- **Module scaffolding + `FusionPayload` shape (S1):** Imports, dataclass field declarations — internal output projection schema.
- **Fusion math tunables (S2):** Base trust weights, regime-multiplier adjustments, default + regime-conditioned priors — operator-tuned Bayesian parameters.
- **Helper extractors (S3):** Regime label resolution, model dominant class, optional support, triplet normalization — all on typed payload objects with explicit fail-closed semantics.
- **Evidence translators (S4):** Model output → likelihood dict, with fail-closed empty-dict return when inputs are absent/invalid.
- **Per-tick cache (S5):** Perf optimization for horizon-invariant prep.
- **Posterior update math (S6):** Multiplicative Bayesian update with `max(0.01, lh)` numerical-stability floor and prior-fallback on non-positive sum.
- **`fuse` orchestrator (S7):** Source-availability checks → evidence translation → posterior update → confidence dampening → model agreement → directional fusion → signal_layer_v1 blend → contradiction analysis → FusionPayload assembly. Fail-disclosed at every boundary.
- **Self-test (S8):** Diagnostic scaffold.

This file's contribution to V4 closure is **establishing the Bayesian-fusion layer** as Schwab-wire-clean: all Schwab-sourced numerics arrive as already-typed attributes on the typed model output dataclasses (XGBOutput / LSTMOutput / TransformerOutput / MonteCarloOutput / RegimePayload / RulesCard), populated upstream by `xgboost_model.py` / `lstm_model.py` / `transformer_model.py` / `monte_carlo.py` / `regime_engine.py` / `rules_engine.py`. The MC intentional exclusion from fusion weights (L511–513) and the post-fusion MC context layer (`mc_fusion_adjustment.py`) are operator-cited per the module docstring at L443.

---

## Gatekeeper CSV cross-check

Independent Cursor gatekeeper pass @ 2026-05-24 (operator challenge after `a7d4622` relay). Full AST string / `.get()` token extract cross-checked against **entire** `schwab_field_inventory/schwab_field_dictionary.csv` via `python tools/check_schwab_csv_first.py --gatekeeper-crosscheck bayesian_fusion.py`.

- **lexical_csv_collision_count:** 11
- **wire_read_collisions:** 0

| Line | Kind | Token | CSV example | Disposition |
|------|------|-------|-------------|-------------|
| L316 | literal | `low` | `pricehistory.candles.*.low` | homonym — rules conviction tier default, not OHLC |
| L318 | literal | `high`, `low` | candles high/low | homonym — `conv_mult` map for conviction tiers |
| L573, L592, L619, L738 | literal | `high` | candles high | homonym — fusion confidence tier assignment |
| L579, L742 | literal | `low` | candles low | homonym — fusion confidence tier assignment |
| L838 | literal | `volatility` | `chains.*.volatility` | homonym — `__main__` mock `mc_feature_dict` key, not chain Greek |

**Verdict:** memo-only Class A stands; prior spot-check gatekeeping was inadequate — this section is the corrective record.

---

## Aggregate disposition for inventory

- **status:** pending (awaiting gatekeeper)
- **memo_ref:** governance/SCHWAB_V4_REVIEW_MEMOS/bayesian_fusion.py.md
- **Class A determination:** memo-only — no in-file Schwab field reads, no Schwab-replaceable derivation, no non-canonical fallback, no actionable FIND.
