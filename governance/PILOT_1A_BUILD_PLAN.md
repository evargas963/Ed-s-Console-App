# Pilot 1A Build Plan

**Status:** DRAFT implementation plan  
**Date:** 2026-05-05  
**Module:** A - short-horizon event-driven trading  
**Expression profile:** A1 - equity / ETF  
**Initial ticker:** SPY  
**Target architecture:** `governance/FRAMEWORK_V2_TARGET_LOCK_RECORD.md`  
**Implementation blueprint:** `governance/IMPLEMENTATION_BLUEPRINT_V2.md`

Pilot 1A creates the visible v2 spine inside the existing app without changing model training, active promotion, or L1/Tier B contracts.

---

## Objective

Add an advisory, draft-labeled `v2_decision` object to the existing Tier C market-state payload for Module A/A1.

This gives the app a concrete v2 output shape:

- four edge-domain sections;
- module and expression-profile identity;
- decision / side / confidence fields;
- health and latency metadata;
- reason codes;
- UI card.

---

## Non-Goals

Pilot 1A does not:

- train new models;
- promote new artifacts;
- alter `models/active/`;
- change G2/G3/G4 lifecycle behavior;
- add A2 / 0DTE trading logic;
- put fresh ML or option-chain work on L1/Tier B;
- claim production authority for v2.

---

## Existing Reuse Points

| Existing file | Reuse |
|---|---|
| `server.py` | Attach `v2_decision` inside Tier C `_fetch_state` flow. |
| `market_state.py` | Source `MarketState` / `ms_dict` fields for adapter input. |
| `signals.py` | Existing signal, fusion, and stack context. |
| `ml_predict.py` | Existing base model / stack outputs. |
| `ml_horizon.py` | Existing primary horizon contract: `1c`, `5c`, `15c`, `60c`. |
| `static/index.html` | Initial v2 decision card surface. |

---

## Proposed File Additions

```text
v2_decision/__init__.py
v2_decision/schema.py
v2_decision/module_a_adapter.py
tests/test_v2_decision_schema.py
tests/test_v2_tier_c_payload.py
```

No A2 files are required for Pilot 1A. A2 starts in Pilot 1B.

---

## v2 Decision Schema

The draft schema should be a plain Python object or dataclass converted to JSON-compatible dicts.

Schema design rule:

> Complete in structure, honest in substance.

All v2.0 §18 output fields should be represented structurally even when Pilot 1A cannot populate them. Every leaf field must include a `source` indicator:

- `v2_compliant`;
- `v1_approximation`;
- `not_implemented`;
- `policy_object_pending`.

Required top-level fields:

```text
schema_version
status
v2_status
module
expression_profile
ticker
decision
side
horizon_set
signal
implementation
portfolio
lifecycle
reason_codes
health
artifact_trace
decision_latency
```

Initial values:

```text
schema_version: v2_decision_draft_1
status: advisory_draft
v2_status: target_architecture_pending_governance_binding
module: A
expression_profile: A1
horizon_set: [1m, 5m, 15m, 60m]
```

Canonical field shape:

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

The schema validator should fail closed for malformed internal construction but the Tier C attachment should fail soft by omitting `v2_decision` and logging/marking health if construction fails. Pilot 1A must not break the existing app payload.

---

## Module A/A1 Adapter

`v2_decision/module_a_adapter.py` should expose one narrow function:

```python
def build_module_a_a1_decision(ms_dict: dict) -> dict:
    ...
```

The adapter should read from the already-built Tier C `ms_dict`.

Initial mapping:

| v2 section | Initial source |
|---|---|
| `signal` | existing fusion, stack, direction, confidence, regime, multi-horizon fields where available |
| `implementation` | existing spread/liquidity/risk fields where available; otherwise `status: insufficient_data` |
| `portfolio` | initially minimal with `status: not_integrated` |
| `lifecycle` | static stop/target/timeout baseline from existing call/risk geometry where available |
| `reason_codes` | derived from existing fusion/stack/regime/health fields |
| `health` | source availability, stale/missing markers, schema validity |
| `artifact_trace` | existing model/runtime identifiers where available |
| `decision_latency` | existing Tier C timing fields where available |

Known Pilot 1A conformance gaps must be explicit:

| Field / concept | Pilot 1A source indicator |
|---|---|
| `P_entry_success` | `v1_approximation` if mapped from existing confidence/probability fields |
| `P_lifecycle_adjusted_success` | `not_implemented` |
| `p_low` / `p_high` | `not_implemented` unless an existing calibrated interval is proven available |
| `EV_lower` / `EV_upper` | `not_implemented` |
| execution-adjusted EV | `v1_approximation` unless a v2 execution model is available |
| policy object IDs | `policy_object_pending` |
| portfolio allocation fields | `not_implemented` or `policy_object_pending` |

Initial decision policy should be conservative:

- emit `WAIT` when required signal fields are missing;
- emit `AVOID` when existing hard gates indicate invalid/stale/blocked conditions;
- emit `TRADE` only when existing direction/confidence/risk fields are coherent enough to support a draft advisory decision.

Pilot 1A may choose to keep all decisions advisory even when `TRADE` appears.

---

## Tier C Integration

Integration point:

```text
server.py
  _fetch_state(...)
    build_market_state(...)
    attach stack/runtime/governance
    apply trader horizon contract
    stamp decision bundle
    attach v2_decision
```

Exact placement can be before or after `stamp_decision_bundle`, but `v2_decision` must include or inherit the final decision generation metadata before it reaches the client.

Rules:

- Do not modify L1/Tier B builder.
- Do not fetch option chains for Pilot 1A.
- Do not query DB from the adapter unless absolutely necessary.
- Do not change existing top-level payload fields.
- Keep `v2_decision` nested and additive.

---

## UI Integration

Add a v2 decision card to `static/index.html`.

Initial card:

- hidden or "unavailable" when `v2_decision` is missing;
- displays `module`, `expression_profile`, `decision`, `side`, and `status`;
- displays persistent banner: "Target architecture pending governance binding - non-authoritative";
- shows the four edge-domain sections;
- lists reason codes;
- shows health and latency status;
- clearly labels the output as `v2 advisory draft`.

The UI must not remove or replace the existing prediction/fusion display in Pilot 1A. The v2 card is read-only and must not expose actionable controls.

---

## Tests

### `tests/test_v2_decision_schema.py`

Required cases:

- valid minimal A/A1 decision passes schema validation;
- invalid decision enum is rejected;
- missing required top-level field is rejected;
- every leaf decision field has an allowed `source` indicator;
- `v2_status == "target_architecture_pending_governance_binding"`;
- unknown extra fields are either rejected or explicitly allowed according to schema policy;
- JSON serialization round-trip works.

### `tests/test_v2_tier_c_payload.py`

Required cases:

- Tier C payload can include `v2_decision`;
- `v2_decision.schema_version == "v2_decision_draft_1"`;
- `module == "A"`;
- `expression_profile == "A1"`;
- L1/Tier B payload does not compute or require fresh `v2_decision`.

Use fixtures/mocks where full server state is too expensive.

---

## Acceptance Criteria

Pilot 1A is complete when:

- `v2_decision` appears in Tier C payload for valid Module A/A1 state;
- the UI renders a v2 advisory card without breaking existing UI;
- tests cover schema and Tier C payload behavior;
- L1/Tier B remains light and does not perform fresh v2 ML;
- no promotion or active artifact behavior changes;
- docs clearly state that output is advisory/draft.

Binary closure criteria:

- **Schema done:** all v2.0 §18 fields are enumerated structurally; every leaf field has a source indicator; schema validator passes.
- **Adapter done:** every mapped field has a documented source; every unimplemented field is listed; unit tests cover each adapter mapping.
- **Tier C attachment done:** `v2_decision` reaches Tier C payload; non-authority labeling is present; no v1 contract changes.
- **UI card done:** all schema sections render; non-authority banner is visible; card is read-only; existing v1 card remains primary.

---

## Follow-On: Pilot 1B

After Pilot 1A is stable, Pilot 1B adds A2 / 0DTE as a separate expression profile:

```text
v2_decision/a2_option_expression.py
v2_decision/a2_labels.py
v2_decision/a2_execution.py
v2_decision/a2_lifecycle.py
```

Pilot 1B must define the A2 expression-profile contract before reusing existing options code. The required sequence is:

1. Design A2 expression-profile contract.
2. Audit `market_state.recommend_option_expression`, `math_probabilities.score_option_expression`, `realized_contract_eval.py`, and `live_vs_replay_validation.py` against that contract.
3. Produce a gap list.
4. Refactor/adapt existing modules as deterministic baselines.
5. Attach A2 output to `v2_decision`.

No trained A2 claim is allowed until A2 labels, provenance, replay, and readiness gates exist.

