# Pilot 1B A2 0DTE Contract

**Status:** DRAFT implementation contract  
**Date:** 2026-05-05  
**Module:** A - short-horizon event-driven trading  
**Expression profile:** A2 - options / 0DTE  
**Initial tickers:** SPY / QQQ unless amended  
**Runtime plane:** Tier C only  
**Depends on:** `governance/IMPLEMENTATION_BLUEPRINT_V2.md`, `governance/PILOT_1A_BUILD_PLAN.md`, `governance/FRAMEWORK_V2_TARGET_LOCK_RECORD.md`

Pilot 1B promotes 0DTE from downstream option-expression scoring into an explicit v2 expression profile. This document is a contract-first artifact: it defines the required A2 shape before adapting existing option code.

It is not production authority and does not change locked v1.1 behavior.

Pilot 1B operates outside v1.1 prereg authority; it is governed by the v2.0 target lock and this contract until a v2.0 prereg is approved and content-hash-bound. Adding QQQ does not require a v1.1 prereg amendment because Pilot 1B does not consume v1.1 authority.

---

## Objective

A2 answers:

> Given a Module A short-horizon directional signal, is there a valid options / 0DTE expression that should be shown as a draft v2 advisory decision?

A2 is not just "A1 plus a call option." It has separate requirements for:

- option-chain identity and as-of discipline;
- strike / expiry / right selection;
- bid / ask / mid and liquidity quality;
- IV / Greeks and expiration risk;
- contract-level payoff labels;
- spread and fill realism;
- lifecycle actions and forced-exit rules;
- replay/live parity;
- source-indicated v2 output fields.

---

## Non-Goals

Pilot 1B does not:

- train an options-native model yet;
- claim a validated A2 edge;
- promote artifacts;
- alter Module A/A1 authority;
- put option-chain work on Tier A, Tier B, or L1;
- make option output trade-impacting;
- hide missing A2 requirements behind generic confidence fields.
- cover multi-leg structures. Pilot 1B is single-leg directional CALL/PUT only. Verticals, butterflies, calendars, condors, iron condors, and other multi-leg structures require separate expression-profile contracts.

Early A2 output is a deterministic baseline only until labels, replay, provenance, execution, and lifecycle validation exist.

---

## A2 Output Contract

The A2 object should attach under the existing Tier C `v2_decision` object, not as top-level `MarketState` fields.

Required identity fields:

| Field | Required source behavior |
|---|---|
| `module_id` | `value: "A"`, `source: "v1_approximation"` until Module A validation is v2-bound |
| `expression_profile_id` | `value: "A2"`, `source: "v2_compliant"` once this contract is implemented as a shape |
| `instrument_family` | `value: "options_0dte"`, `source: "v2_compliant"` once this contract is implemented as a shape |
| `underlying_ticker` | `v1_approximation` from Tier C ticker |
| `selected_expiry` | `v1_approximation` from selected option-chain expiry |
| `dte` | `v1_approximation` initially; must become v2-compliant when as-of and market-calendar handling are bound |
| `decision_plane` | `value: "Tier C"`, `source: "v2_compliant"` |
| `authority_mode` | `value: "advisory_non_authoritative"`, `source: "v2_compliant"` |

Required option expression fields:

| Field | Required source behavior |
|---|---|
| `option_action` | `TRADE`, `WAIT`, or `AVOID`; deterministic baseline can be `v1_approximation` |
| `option_right` | `CALL`, `PUT`, or `NONE`; deterministic baseline from `recommend_option_expression` |
| `strike` | deterministic baseline from `recommend_option_expression` |
| `contract_symbol` | `not_implemented` unless selected chain row exposes it reliably |
| `bid` / `ask` / `mid` | deterministic baseline from selected chain row |
| `spread` | deterministic baseline from `score_option_expression` |
| `max_loss` | `policy_object_pending` until sizing and debit policy are bound |
| `breakeven` | deterministic baseline when mid is available |
| `selected_contract_snapshot` | deterministic baseline from selected chain row |
| `selection_proof` | deterministic baseline from `recommend_option_expression` proof |

Required probability and expected-value fields:

| Field | Required source behavior |
|---|---|
| `P_underlying_entry_success` | `v1_approximation` from Module A/A1 stack probability |
| `P_contract_profit` | `not_implemented` until contract-level labels exist |
| `P_lifecycle_adjusted_profit` | `not_implemented` until lifecycle policy is validated |
| `p_low` / `p_high` | `not_implemented` until calibrated/conformal A2 bounds exist |
| `EV_contract_mid` | `not_implemented` until contract payoff labels exist |
| `EV_lower` / `EV_upper` | `not_implemented` until calibrated bounds and execution costs exist |
| `execution_adjusted_EV` | `not_implemented` until spread/fill/slippage model exists |

Required execution fields:

| Field | Required source behavior |
|---|---|
| `liquidity_gate_pass` | deterministic baseline from `score_option_expression.liq_gate` |
| `spread_quality` | deterministic baseline from spread and configured threshold |
| `fill_probability` | `not_implemented` |
| `slippage_estimate` | `not_implemented` |
| `adverse_selection_risk` | `not_implemented` |
| `quote_staleness_ms` | `not_implemented` unless quote timestamps are available |
| `capacity_size_cap` | `policy_object_pending` |

Required IV / Greeks fields:

| Field | Required source behavior |
|---|---|
| `delta` | deterministic baseline from selected chain row |
| `gamma` | deterministic baseline from selected chain row |
| `vega` | deterministic baseline from selected chain row when present |
| `theta` | hard input. Use selected chain row when present; otherwise compute Black-Scholes theta from spot, strike, IV, and expiry as `v1_approximation`. A2 must emit `WAIT` if theta is unavailable. |
| `iv` | deterministic baseline from `volatility` / IV field when present |
| `delta_gamma_ratio` | deterministic baseline from `score_option_expression` |
| `gamma_x_oi` | deterministic baseline from `score_option_expression` |
| `vol_oi_ratio` | deterministic baseline from `score_option_expression` |

Required lifecycle fields:

| Field | Required source behavior |
|---|---|
| `entry_policy` | deterministic baseline from replay context or current call plan |
| `stop_policy` | `v1_approximation` from current rules stop geometry |
| `target_policy` | `v1_approximation` from current rules target geometry |
| `timeout_policy` | `policy_object_pending` until A2 lifecycle policy is bound |
| `forced_exit_time` | `policy_object_pending` |
| `allowed_actions` | `policy_object_pending`: hold, exit, tighten, scale_out, convert, force_exit |
| `lifecycle_policy_id` | `policy_object_pending` |

---

## Signal-To-Expression Handoff

The A2 deterministic baseline consumes Module A/A1 signal context but does not override Module A/A1 authority.

Pilot 1B handoff rules:

- A2 may emit non-`WAIT` only when Module A's signal is non-`WAIT`, the direction maps to a single-leg `CALL` for long or `PUT` for short, and the selected option expression passes every hard A2 gate.
- If Module A says `LONG` but no liquid or valid `CALL` is available, A2 emits `WAIT` and records the reason in `health` or `conformance_gaps`.
- If Module A says `SHORT` but no liquid or valid `PUT` is available, A2 emits `WAIT` and records the reason in `health` or `conformance_gaps`.
- If Module A says `TRADE` but A2 has IV, theta, spread, quote, replay, or lifecycle concerns, A2 emits `WAIT` or advisory `AVOID` according to the gate and records the disagreement.
- A2 cannot veto A1 for trade-impacting purposes during Pilot 1B. A2 disagreement is advisory and must be recorded in `health` or `conformance_gaps`, not applied as an authority block.

---

## Readiness Gates

A2 must emit `WAIT` or `AVOID` rather than an option recommendation when any hard gate fails.

Hard gates:

- missing selected expiry;
- selected expiry is not same-day when the profile is in strict 0DTE mode;
- no option-chain archive / current chain rows for selected expiry;
- no side-compatible contracts;
- missing bid or ask for selected contract;
- missing theta from both chain row and Black-Scholes approximation inputs;
- invalid or stale quote timestamp once quote staleness is implemented. Threshold policy object: `a2_quote_staleness_threshold_ms`, TBD pending operator decision; recommended starting value is `2000ms` based on Schwab L1 quote latency profile;
- spread exceeds governed hard threshold once threshold policy is bound. Threshold policy object: `a2_spread_hard_threshold`, TBD pending operator decision; recommended starting value is `$0.10` absolute or `10%` of mid, whichever is tighter, for SPY/QQQ 0DTE;
- missing selected strike or option right;
- Module A signal is `WAIT` or unavailable;
- replay/live parity is failing once validation status is available.

Soft gates:

- wide spread but still scoreable under current deterministic baseline;
- missing optional IV / Greeks fields;
- low volume / OI;
- wall contribution unavailable;
- no validated fill-probability model yet.
- pin risk near strike at expiry;
- late-day gamma acceleration in the final 30 minutes;
- early assignment risk for any future short-option structure.

Soft gates must appear in `conformance_gaps` or `health`, never disappear silently.

---

## Existing Module Audit

| Surface | Current capability | A2 role | Main gaps |
|---|---|---|---|
| `market_state.recommend_option_expression` | Maps `long` to CALL, `short` to PUT, `wait` to NO TRADE; evaluates ATM and one ITM candidate; returns expression, reasons, and proof. | Deterministic expression-selection baseline. | Not options-native edge; no strict 0DTE mode; fallback may choose wide-spread winner; no fill probability; no lifecycle policy ID. |
| `math_probabilities.score_option_expression` | Scores spread, gamma, distance to spot, volume/OI, gamma x OI, max gamma strike, and wall contribution. | Deterministic liquidity/Greeks score baseline. | Score is heuristic, not calibrated EV; no slippage/fill model; no quote staleness; no capacity model; incomplete theta/expiration handling. |
| `realized_contract_eval.py` | Replays selected option contracts with archived chain; entry ask, exit bid; underlying stop/target path; skip reasons and trade logs. | Starting point for A2 label/replay contract. | Current labels are evaluator outputs, not v2 A2 label schema; skip-rate gates need A2 ownership; no conformal bounds; IV/Greeks path attribution incomplete. |
| `live_vs_replay_validation.py` | Compares live option selection proof with replayed selection from archived chain and replay context. | A2 replay/live parity validation support. | Validation quality is a sidecar report, not attached to live `v2_decision`; not yet a readiness gate. |
| `call_engine.py` | Has time-aware, VIX-aware stop geometry described for 0DTE trading. | Lifecycle/risk-geometry baseline. | Underlying-level geometry is not contract-level lifecycle EV; dynamic actions need validation versus static baseline. |
| `server.py` / Tier C payload | Already serializes selected chain, replay context, option proof, and decision bundle. | Attachment point for A2 advisory object. | Must avoid Tier B/L1 option work; A2 construction must fail soft. |

---

## Deterministic Baseline Scope

The first A2 implementation may wrap:

- `market_state.recommend_option_expression`;
- `math_probabilities.score_option_expression`;
- selected contract row snapshot fields;
- replay context entry/exit policy text when available;
- Module A/A1 probability as `P_underlying_entry_success`.

It must label these outputs as `v1_approximation` or `policy_object_pending` unless the field is pure contract shape.

No field may be labeled `v2_compliant` merely because it is present.

---

## Required Gap List For First Adapter

The first A2 adapter must include these gaps at minimum:

- `a2_contract_profit_labels_not_implemented`;
- `a2_execution_model_not_implemented`;
- `a2_fill_probability_not_implemented`;
- `a2_lifecycle_policy_pending`;
- `a2_replay_live_parity_not_gating_runtime`;
- `a2_options_native_provenance_not_bound`;
- `a2_calibrated_probability_interval_not_implemented`;
- `a2_contract_ev_not_implemented`;
- `a2_pin_risk_handling_not_implemented`;
- `a2_late_day_gamma_policy_pending` — **resolved** by **O-34**
  (advisory-warning-only v1 policy bound). Late-day gamma exposure
  may raise lifecycle/sidecar warning state but does not independently
  tighten stops, resize, or force exit. EOD force-exit timing remains
  governed by O-33.
- `a2_early_assignment_risk_not_implemented`.

Lifecycle child gaps under `a2_lifecycle_policy_pending` are governed by `governance/PILOT_1B_A2_LIFECYCLE_CONTRACT.md`. That contract extends the umbrella gap without renaming or superseding existing A2 lifecycle leaves (`P_lifecycle_adjusted_profit`, `timeout_policy`, `lifecycle_policy_id`).

---

## Tests Required Before Runtime Attachment

Add focused tests before attaching A2 to Tier C:

- valid A2 deterministic baseline object validates schema;
- `WAIT` signal emits no option contract and records source indicators;
- missing bid/ask blocks trade output;
- wide spread records a soft or hard gate according to policy;
- selected contract fields include source indicators;
- required A2 probability/EV placeholders are present;
- A2 output remains nested under `v2_decision`;
- `A2.option_action` is coherent with `A1.decision.action`; if A1 says `TRADE LONG` and A2 says `AVOID`, A2 must record the reason in `conformance_gaps` or `health`;
- A2 card/UI text is read-only and labeled advisory if UI is added in this phase.

---

## Binary Closure Criteria

Pilot 1B contract phase is complete when:

- A2 contract fields are enumerated in a durable governance artifact;
- current 0DTE surfaces are audited against the contract;
- deterministic baseline scope is explicitly separated from trained edge;
- required A2 gaps are named before adapter work begins;
- no runtime behavior changes are made by the contract artifact.

Pilot 1B implementation phase is complete when:

- A2 deterministic baseline output is attached to Tier C `v2_decision`;
- A2 output is visibly separate from A1;
- every A2 leaf field has an allowed source indicator;
- hard readiness gates can block unsafe option recommendations;
- replay labels exist before any trained A2 model claim;
- tests enforce advisory-only, Tier C-only behavior.

