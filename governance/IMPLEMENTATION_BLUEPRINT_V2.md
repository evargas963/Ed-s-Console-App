# Implementation Blueprint v2

**Status:** DRAFT - implementation planning  
**Date:** 2026-05-05  
**Target architecture:** `governance/FRAMEWORK_V2_TARGET_LOCK_RECORD.md`  
**Framework draft:** `governance/Framework-ED-Decision-Engine-v2.0-DRAFT.md`

This blueprint maps the current EdWebConsole app to the v2 target architecture. It is a planning document, not production authority.

---

## Executive Summary

The existing app already has most of the **Module A / A1 equity-ETF spine**:

- canonical 1m snapshot and outcome machinery;
- governed horizon registry for `1c`, `5c`, `15c`, `60c`;
- XGB / LSTM / Transformer / meta stack paths;
- Tier C analytics payload with decision generation stamping;
- UI surface for fusion, stack, and "What the Data Says";
- option-expression recommendation and contract replay utilities.

The main gap is **Module A / A2 0DTE**. Today, 0DTE exists mostly as downstream option-expression scoring and replay layered on top of underlying-direction ML. It does not yet have its own labeled dataset, provenance lane, readiness gate, model namespace, or serving contract.

Implementation should therefore proceed in two tracks:

1. **Pilot 1: Module A / A1**
   Stabilize and wrap the existing short-horizon equity/ETF decision path into explicit v2 contracts.

2. **Pilot 1B: Module A / A2**
   Add an options/0DTE expression profile with its own data contracts, labels, validation, execution model, lifecycle policy, and UI output.

---

## Current App Map

### Runtime And API

| File | Current role | v2 implication |
|---|---|---|
| `server.py` | FastAPI app, startup, background scheduler, HTTP/SSE routes, `_fetch_state`, cache orchestration. | Keep v2 decision-complete payloads on Tier C first. Avoid putting ML into L1. |
| `planes/context_light.py` | L1 / Tier B light context. Explicitly no chain, DB, or ML. | Do not make v2 decision cards authoritative here. L1 may show cached headline only. |
| `market_state.py` | `MarketState`, `build_market_state`, option-expression recommendation. | Natural bridge for v2 Module A output and A2 expression profile. |
| `signals.py` | End-to-end signal pipeline, fusion, ML inference, Bayesian fusion, call computation. | Primary Module A signal integration point. |
| `prediction_engine.py` | Similar-set and empirical prediction enrichment. | Reuse as diagnostic/feature source, not final v2 decision authority by itself. |
| `static/index.html` | Main UI, large inline app rendering fusion and decision context. | Initial v2 decision card can be added here; later refactor into components. |

Current decision-complete route family:

- `GET /api/analytics/state`
- `GET /api/state`
- `GET /api/stream`

Current light/fast route family:

- `GET /api/live/state`
- `GET /api/analytics/light`
- `GET /api/analytics/light/stream`

Design rule:

> v2 trade decisions belong to Tier C unless a future plane contract explicitly allows a lighter cached headline in Tier B.

### Data, Training, And Model Lifecycle

| File | Current role | v2 implication |
|---|---|---|
| `db.py` | SQLite persistence, `snapshots`, `price_bars_1m`, outcomes, predictions, logging universe. | Base store for Module A/A1; A2 needs new option-contract tables or sidecar stores. |
| `ml_horizon.py` | Governed horizon slugs and primary decision horizons. | Maps cleanly to Module A/A1 horizons. |
| `ml_train.py` | XGBoost training on snapshot rows and outcome columns. | Reuse for A1 baseline; do not overload for A2 contract payoffs without a new contract. |
| `lstm_data.py` | Sequence arrays from 1m snapshots. | Reuse for A1 sequence models; A2 needs chain-aware extensions. |
| `ml_predict.py` | Base-model inference and stack output. | Reuse for A1 scoring; v2 adapter should consume outputs rather than rewrite immediately. |
| `ml_scheduler.py` | Training orchestration and candidate evaluation. | Keep paused G2 in mind; v2 planning should define G2.v2 before major lifecycle rewrites. |
| `arch_competition/*` | Governed evaluation, promotion, manual control. | v2 artifacts should eventually register here or in a successor G2.v2 contract. |
| `training_provenance.py` | Training identity/provenance. | A2 must get equivalent provenance, not ad hoc replay files only. |

### Existing Options / 0DTE Surfaces

| File | Current role | v2 implication |
|---|---|---|
| `market_state.py` | `recommend_option_expression` selects option expression from chain. | Starting point for A2 expression selection. |
| `math_probabilities.py` | `score_option_expression` liquidity/spread/Greeks-style scoring. | Reuse as A2 deterministic baseline. |
| `realized_contract_eval.py` | Historical options PnL replay using bid/ask and underlying path. | Starting point for A2 validation/label generation. |
| `call_engine.py` | Stop/target/entry geometry, including 0DTE-aware stop logic. | Reuse for A1/A2 coherent risk geometry. |
| `live_vs_replay_validation.py` | Validates live vs replay option selection. | Useful for A2 parity/replay discipline. |

Current A2 limitation:

> Existing options logic is expression scoring after an underlying signal. It is not yet an options-native model lifecycle.

---

## Target Runtime Shape

### New v2 Decision Object

Design rule:

> The v2 decision schema must be complete in structure and honest in substance.

Fields required by the v2 framework should exist in the schema even when Pilot 1A cannot populate them yet. Each leaf decision field must carry a `source` indicator:

- `v2_compliant`;
- `v1_approximation`;
- `not_implemented`;
- `policy_object_pending`.

Add a nested object to the Tier C `ms_dict`, initially advisory:

```json
{
  "v2_decision": {
    "schema_version": "v2_decision_draft_1",
    "v2_status": "target_architecture_pending_governance_binding",
    "module": "A",
    "expression_profile": "A1",
    "ticker": "SPY",
    "decision": "TRADE|WAIT|AVOID",
    "side": "LONG|SHORT|NONE",
    "horizon_set": ["1m", "5m", "15m", "60m"],
    "signal": {},
    "implementation": {},
    "portfolio": {},
    "lifecycle": {},
    "reason_codes": [],
    "health": {},
    "artifact_trace": {},
    "decision_latency": {}
  }
}
```

Canonical illustration:

```json
{
  "ev_lower": {
    "value": null,
    "source": "not_implemented"
  },
  "execution_adjusted_ev": {
    "value": 0.18,
    "source": "v1_approximation"
  }
}
```

Do not flatten this across top-level `MarketState` fields. Keep v2 isolated until schema and governance mature.

### Tier Placement

| Plane | v2 role |
|---|---|
| Tier A | Quote/session only. No v2 decision authority. |
| Tier B / L1 | Optional cached headline from last Tier C decision only. No fresh ML. |
| Tier C | Authoritative v2 decision-complete payload. |

### UI Placement

Add a v2 decision card near the current fusion / stack / "What the Data Says" section in `static/index.html`.

Initial card sections:

- Decision: `TRADE / WAIT / AVOID`
- Module / expression profile: `A / A1` or `A / A2`
- Signal Edge summary
- Implementation Edge summary
- Portfolio Edge summary
- Lifecycle Edge summary
- Reason codes
- Health gates
- Latency / staleness status

For A2, add:

- option structure;
- strike / expiry;
- IV / Greeks;
- spread / fill probability;
- max loss;
- 0DTE lifecycle plan.

---

## Pilot 1: Module A / A1

### Goal

Turn the existing short-horizon equity/ETF path into an explicit v2 Module A/A1 decision contract.

### Scope

- Ticker: SPY
- Expression profile: A1 equity/ETF
- Horizons: 1m / 5m / 15m / 60m
- Output: `TRADE / WAIT / AVOID`
- Runtime: Tier C only

### Implementation Steps

1. **Create v2 adapter module**
   - Proposed file: `v2_decision/module_a_adapter.py`
   - Reads existing `MarketState` / signal / stack fields.
   - Emits `v2_decision` nested object.

2. **Define v2 decision schema**
   - Proposed file: `v2_decision/schema.py`
   - Keep schema additive and draft-labeled.
   - Validate basic required fields before adding to Tier C payload.

3. **Attach v2 object in Tier C**
   - Integration point: after `build_market_state` and before/near `stamp_decision_bundle` in `_fetch_state`.
   - Do not modify Tier B contract.

4. **Map existing outputs to four edge domains**
   - Signal: multi-horizon stack, fusion, regime, direction.
   - Implementation: current spread/liquidity/risk context where available.
   - Portfolio: initially minimal; position/risk hooks added later.
   - Lifecycle: static stop/target/timeout baseline first.

5. **Add UI card**
   - Initial render from `v2_decision`.
   - Make missing object display "v2 decision unavailable" rather than breaking existing UI.

6. **Add tests**
   - Schema construction test.
   - Tier C payload includes valid `v2_decision` when source data available.
   - Tier B payload does not compute fresh v2 ML.

### Done Criteria

- Tier C payload includes `v2_decision` for SPY A1.
- UI displays v2 card without disturbing existing prediction card.
- No changes to active promotion authority.
- No L1/Tier B contract violation.

---

## Pilot 1B: Module A / A2 0DTE

### Goal

Promote 0DTE from downstream heuristic expression selection into an explicit expression profile with its own contracts.

### Scope

- Module: A
- Expression profile: A2 options/0DTE
- Initial tickers: SPY / QQQ unless amended
- Runtime: Tier C only
- Output: `TRADE / WAIT / AVOID` plus option structure and lifecycle plan

### Build Sequence

1. **A2 expression-profile contract**
   - Define A2 inputs, outputs, validation requirements, lifecycle action set, readiness gates, and source indicators.
   - Do this before reusing existing option-expression modules.

2. **A2 existing-module audit**
   - Audit `recommend_option_expression`, `score_option_expression`, `realized_contract_eval.py`, and `live_vs_replay_validation.py` against the A2 contract.
   - Produce a gap list before adapting code.

3. **A2 deterministic baseline**
   - Wrap `recommend_option_expression` and `score_option_expression`.
   - Emit A2 expression fields inside `v2_decision`.
   - Treat this as deterministic baseline, not trained A2 edge.

4. **A2 data contract**
   - Option-chain as-of timestamp.
   - Expiry/strike/side identity.
   - Bid/ask/mid at decision time.
   - IV and Greeks where available.
   - Spread, liquidity, and fill-quality fields.
   - Assignment/exercise semantics.

5. **A2 label/replay contract**
   - Build from `realized_contract_eval.py` and `live_vs_replay_validation.py`.
   - Define contract-level outcomes:
     - max favorable excursion;
     - max adverse excursion;
     - hit target / hit stop / timeout;
     - realized option PnL;
     - realized spread/fill slippage;
     - IV/Greeks path impact.

6. **A2 execution model**
   - Spread/fill quality model.
   - Slippage estimate.
   - Capacity/size cap.
   - Reject illiquid chains.

7. **A2 lifecycle baseline**
   - Static option exit baseline first.
   - Later dynamic lifecycle actions:
     - hold;
     - exit;
     - tighten;
     - scale out;
     - convert;
     - force exit before defined gamma/theta risk window.

8. **A2 validation**
   - Option-chain as-of enforcement.
   - Replay vs live parity.
   - Contract payoff validation.
   - Spread/fill realism.
   - Lifecycle static baseline comparison.

### Done Criteria

- A2 has a schema and deterministic baseline output.
- A2 output is visibly separate from A1 in UI.
- A2 replay labels exist before any trained A2 model claim.
- A2 readiness gate can block option recommendations when chain/execution quality is insufficient.

---

## G2.v2 Planning Implication

The current G2 plan is paused because it targets the existing parallel/cascade architecture. Before major implementation beyond Pilot 1 adapter work, create a `G2.v2` plan that defines:

- v2 artifact roles;
- v2 decision schema;
- Module A/A1 artifact contract;
- Module A/A2 expression-profile contract;
- promotion and provenance expectations;
- Tier C payload validation;
- UI contract boundaries.

Pilot 1 adapter work can remain advisory/draft if it does not alter promotion authority or active model lifecycle.

---

## Testing Strictness Policy

Testing strictness scales with decision authority.

Amendment note: commit `7671550` established the original strictness policy. This amendment is forward-looking only; prior red-green pairs, including `ee05ce6`/`8e789c6` and `0b73d9b`/`11ad75d`, remain valid evidence that the policy in force at that time was followed.

For advisory / non-authoritative phases, single green implementation commits are acceptable when tests reference the governing contract clauses directly and the payload remains draft-labeled, source-indicated, and Tier C-only. This includes deterministic baselines such as Pilot 1A, Pilot 1B, and future first-cut modules that do not alter trade authority.

Red-green evidence becomes mandatory again when any one of these triggers is present: a v2 decision becomes preregistered, replay-bound, or trade-authoritative. At that point, any change that grants v2 authority, promotes a calibration model, promotes a lifecycle policy, binds a v2 prereg, binds replay/live parity, or otherwise changes live trade behavior must capture failing contract tests before implementation and passing tests after implementation. The failing-test output must be recorded in the commit message, build log, or linked validation artifact.

This policy prevents advisory scaffolding from carrying unnecessary process weight while requiring stronger audit evidence when the system can affect real decisions.

---

## Recommended File Additions

Initial implementation files:

```text
v2_decision/__init__.py
v2_decision/schema.py
v2_decision/module_a_adapter.py
v2_decision/a2_option_expression.py
tests/test_v2_decision_schema.py
tests/test_v2_tier_c_payload.py
```

Later A2 files:

```text
v2_decision/a2_labels.py
v2_decision/a2_execution.py
v2_decision/a2_lifecycle.py
tests/test_v2_a2_option_expression.py
tests/test_v2_a2_replay_labels.py
```

---

## Main Risks

1. **Tier B contract violation**
   - Avoid by keeping v2 decisions Tier C only at first.

2. **A2 false authority**
   - Avoid by labeling early A2 as deterministic baseline until labels/provenance/training exist.

3. **Monolithic UI growth**
   - Initial card can land in `static/index.html`; later refactor into components if the UI expands.

4. **Two truths for options replay**
   - A2 replay labels and live A2 telemetry must share the same contract.

5. **Governance drift**
   - Keep v2 output draft/advisory until G2.v2 defines promotion and artifact contracts.

---

## Next Concrete Step

Create the v2 decision schema and Module A/A1 adapter as a draft, Tier C-only payload addition.

This gives the app a visible v2 spine without changing model training, promotion, or L1 contracts. Once that spine exists, A2 0DTE can be added as a separate expression profile rather than mixed into the current equity/ETF decision payload.

