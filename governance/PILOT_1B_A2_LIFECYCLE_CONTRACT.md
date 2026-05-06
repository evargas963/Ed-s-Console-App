# Pilot 1B A2 Lifecycle Contract

**Status:** DRAFT implementation contract
**Date:** 2026-05-06
**Module:** A - short-horizon event-driven trading
**Expression profile:** A2 - options / 0DTE
**Parent contract:** `governance/PILOT_1B_A2_0DTE_CONTRACT.md`
**Current authority:** advisory only; no runtime, UI, or trade-behavior authority.

This document defines the A2 lifecycle contract before any lifecycle code phase begins. It reconciles existing A2 lifecycle placeholders with a future shared static rule core and names the gaps that must remain visible until implementation, validation, and operator approval close them.

---

## Authority Block

```text
mode = advisory_non_authoritative
tier = C_analytics_only
changes_trade_behavior = False
```

This contract does not authorize live exits, live re-entry blocks, dynamic lifecycle policy, promotion, or runtime authority. All lifecycle output remains advisory until a future operator decision register entry explicitly promotes it.

---

## Field Source Discipline

| Field class | Source classification |
|---|---|
| Inputs | `schwab_native_normalized` |
| Lifecycle decisions | `derived_because_schwab_does_not_provide` |
| Thresholds | `policy_object_pending` |

Lifecycle decisions are derived because Schwab provides quote/chain/market primitives, not A2 lifecycle actions such as hold, exit, force-exit, tighten, scale-out, or re-entry block.

---

## Boundary Statement

Canonical static lifecycle baseline = **shared rule core to be extracted**.

Current sources:

- `realized_contract_eval._simulate_exit` is replay/backtest-side static exit behavior.
- `call_engine.py` is live-side risk geometry and setup behavior.
- A future A2 lifecycle sidecar must consume a shared static rule core instead of independently re-implementing either surface.

Neither `_simulate_exit` nor `call_engine.py` is declared canonical alone. The lifecycle phase must reconcile both sources by extracting shared static rule logic used by replay evaluation and advisory lifecycle output.

---

## Required Sequence

1. **Contract approval** - this document, doc-only.
2. **Shared static rule-core extraction** - refactor existing replay/live rule intent into a shared implementation.
3. **Replay/live parity and divergence audit** - test `_simulate_exit`, `call_engine.py`, and the shared rule core. Divergences must be resolved under `a2_lifecycle_legacy_exit_logic_divergence_audit_pending`.
4. **Advisory lifecycle sidecar** - sidecar consumes the shared rule core and emits advisory C-tier lifecycle leaves.
5. **Dynamic lifecycle candidate** - future phase only, contingent on labels, parity, attribution coherence, uncertainty disclosure, and operator approval.

No implementation phase may skip from contract approval directly to dynamic lifecycle policy.

---

## Cadence Contract

Default lifecycle emission cadence:

- event-triggered under normal intraday conditions;
- every Tier C cycle inside the late-day / EOD window once `a2_lifecycle_eod_window_threshold_minutes_policy_object_pending` is bound.

Event vocabulary:

| Event | Meaning |
|---|---|
| `stop_hit` | Static stop threshold fired. |
| `target_hit` | Static target threshold fired. |
| `time_stop_fired` | Clock-based force-exit threshold fired. |
| `eod_window_entered` | Observation cadence shifts to every Tier C cycle. |
| `iv_change_threshold_crossed` | IV move crossed a governed lifecycle threshold. |
| `spread_widening_threshold_crossed` | Spread widening crossed a governed lifecycle threshold. |

Each event must appear as a named source field on any future `v2_decision` lifecycle leaf that depends on it.

---

## Conflict Vocabulary

The lifecycle conflict vocabulary is parallel to v2 entry-vs-portfolio conflict vocabulary. It is not mapped into portfolio conflict outcomes.

Allowed lifecycle conflict states:

| State | Definition |
|---|---|
| `no_conflict` | Entry and lifecycle views do not disagree. |
| `entry_blocked_by_lifecycle` | Same-day re-entry is advisory-blocked after a lifecycle-driven exit or lifecycle risk event. |
| `lifecycle_exit_overrides_hold` | Lifecycle advisory says exit while entry/position context says hold. |
| `lifecycle_warning_only` | Advisory warning with no block or exit authority. This is the default state during advisory phase. |
| `policy_pending` | A conflict cannot be resolved because a required policy object is unbound. |

During the advisory phase, lifecycle conflicts must default to `lifecycle_warning_only` unless a specific sidecar phase authorizes another non-authoritative state.

---

## Existing A2 Crosswalk

Existing parent contract leaves are retained. This document extends them; it does not rename or supersede them.

| Existing field / gap | Status under this contract |
|---|---|
| `P_lifecycle_adjusted_profit` | Remains `not_implemented` until lifecycle policy and lifecycle-calibrated labels are validated. |
| `timeout_policy` | Remains `policy_object_pending`. |
| `lifecycle_policy_id` | Remains `policy_object_pending`. |
| `a2_lifecycle_policy_pending` | Remains the umbrella blocker for all child lifecycle gaps below. |

---

## Named Gaps

Umbrella gap:

- `a2_lifecycle_policy_pending`

Child gaps:

- `a2_lifecycle_static_rule_core_pending`
- `a2_lifecycle_legacy_exit_logic_divergence_audit_pending`
- `a2_lifecycle_eod_force_exit_logic_not_implemented`
- `a2_lifecycle_time_stop_force_exit_clock_threshold_policy_object_pending`
- `a2_lifecycle_eod_window_threshold_minutes_policy_object_pending`
- `a2_lifecycle_iv_crush_handler_not_implemented`
- `a2_lifecycle_pin_risk_handler_not_implemented`
- `a2_lifecycle_gamma_spike_handler_not_implemented`
- `a2_lifecycle_assignment_risk_handler_not_implemented`
- `a2_lifecycle_spread_widening_exit_not_implemented`
- `a2_lifecycle_partial_fill_handler_not_implemented`
- `a2_lifecycle_dynamic_policy_not_implemented`
- `a2_lifecycle_promotion_to_runtime_authority_not_authorized`

### Time-Related Gap Disambiguation

`a2_lifecycle_time_stop_force_exit_clock_threshold_policy_object_pending` is the force-exit trigger: the clock threshold at which lifecycle must advise closing a position.

`a2_lifecycle_eod_window_threshold_minutes_policy_object_pending` is the cadence shift: the threshold at which lifecycle observation switches from event-triggered to every Tier C cycle.

`a2_lifecycle_eod_force_exit_logic_not_implemented` is the firing mechanism gap upstream of `a2_lifecycle_time_stop_force_exit_clock_threshold_policy_object_pending`: force-exit logic must exist before a clock threshold policy can be meaningful.

### Audit Findings

Static lifecycle concern coverage and legacy divergence findings are tracked in `governance/A2_STATIC_LIFECYCLE_DIVERGENCE_AUDIT.md`.

---

## Output Shape For Future Sidecar

The future sidecar should emit a lifecycle block shaped like:

```text
schema_version
module_id
expression_profile_id
authority
static_rule_core_version
lifecycle_action
lifecycle_conflict_state
event_sources
threshold_policy_objects
named_gaps
source_classification
promotion_state
projected_preview
```

Initial output must remain advisory and must not change `P_lifecycle_adjusted_profit`, `timeout_policy`, or `lifecycle_policy_id` from their current source indicators.

`projected_preview` is additive to the v0 sidecar shape. It is specified below and does not wrap, rename, or move the existing sidecar fields.

---

## Current State vs Projected Preview

The v0 sidecar fields describe current lifecycle state at v2 decision build time. Fields such as `lifecycle_action`, `lifecycle_conflict_state`, `event_sources`, `threshold_policy_objects`, `named_gaps`, `source_classification`, and `promotion_state` report what the lifecycle sidecar can honestly say now. At entry time, the current lifecycle state is `no_active_position`; no lifecycle exit, hold, force-exit, or re-entry block has fired.

`projected_preview` describes what lifecycle geometry would apply if the A2 entry were taken at the current v2 decision build time. It is a pre-entry projection derived from `lifecycle_rule_core`, not a lifecycle decision and not an instruction to exit or manage an active position.

Both surfaces coexist inside `lifecycle.sidecar`:

- v0 sidecar fields remain the current-state surface.
- `projected_preview` is the v1 pre-entry preview surface.
- Neither surface supersedes the other.

---

## Projected Preview Output Shape

`projected_preview` must use this shape:

```text
preview_status
preview_named_gaps
projected_stop
projected_target
projected_target2
projected_max_hold_bars
projected_eod_force_exit_time
derivation_inputs
derivation_source_module
would_apply_if_entered_at_time
preview_authority
```

### `preview_status`

Allowed values:

| `preview_status` | `projected_*` fields shape |
|---|---|
| `available` | All populated with rule-core-derived values. |
| `not_available_no_entry_candidate` | All `None`; no entry candidate exists to project from. |
| `not_available_missing_inputs` | All `None`; `derivation_inputs` enumerates which inputs were missing. |
| `policy_pending` | Threshold-derived fields (`projected_eod_force_exit_time`, `projected_max_hold_bars` when policy-bound) are marked `policy_object_pending`; other `projected_*` fields are populated where derivable. |

No implementation may silently partially fill preview fields. If a field is unavailable, its absence must be visible as `None`, a governed sentinel, or `policy_object_pending`; it must never use stale, default, or unrelated values.

### `preview_named_gaps`

`preview_named_gaps` contains only gaps that block honest population of at least one `projected_*` field. A gap is preview-blocking iff it prevents some `projected_*` field from being honestly populated.

Initial preview-blocking gap subset:

- `a2_lifecycle_eod_force_exit_logic_not_implemented`
- `a2_lifecycle_eod_window_threshold_minutes_policy_object_pending`
- `a2_lifecycle_time_stop_force_exit_clock_threshold_policy_object_pending`

Handler, dynamic-policy, promotion, and runtime-authority gaps remain in the broader sidecar `named_gaps` inventory unless they directly block a `projected_*` field.

### Preview Fields

| Field | Meaning |
|---|---|
| `projected_stop` | Stop level that would apply if the A2 entry were taken now, derived from `lifecycle_rule_core` where inputs are sufficient. |
| `projected_target` | T1 level that would apply if the A2 entry were taken now, derived from `lifecycle_rule_core` where inputs are sufficient. |
| `projected_target2` | T2 level that would apply if the A2 entry were taken now, derived from `lifecycle_rule_core` where inputs are sufficient. |
| `projected_max_hold_bars` | Time-stop projection. It remains `policy_object_pending` unless a governed max-hold policy source is available. |
| `projected_eod_force_exit_time` | EOD force-exit projection. It remains blocked by `a2_lifecycle_eod_force_exit_logic_not_implemented` and related threshold-policy gaps until force-exit logic exists. |
| `derivation_inputs` | Sub-dict enumerating inputs used by the rule core, at minimum `spot`, `vix_level`, `mins_elapsed_since_open`, `risk_multiplier`, `entry`, `direction`, `risk`, `avg5`, `avg15`, `avg60`, and `structural_levels` where available. Missing inputs must be named. |
| `derivation_source_module` | Literal `lifecycle_rule_core`. |
| `would_apply_if_entered_at_time` | Timestamp of the v2 decision build used for the "if entered now" projection. |
| `preview_authority` | Non-authority block stating this is a projection, not a lifecycle decision. |

`preview_authority` must include:

```text
mode = advisory_non_authoritative
tier = C_analytics_only
changes_trade_behavior = False
projection_not_decision = True
text = "Projected lifecycle preview only; not an active lifecycle decision. Future lifecycle action may differ."
```

---

## Source Classification for Preview Fields

- `projected_*` value fields use `derived_because_schwab_does_not_provide` when populated from rule-core derivation.
- Unavailable `projected_*` value fields must use `not_implemented` or `policy_object_pending`, as applicable.
- `preview_status`, `preview_named_gaps`, and `derivation_source_module` are governance metadata and may remain bare values under the schema-walker option III pattern verified by the v0 sidecar implementation.
- `derivation_inputs` is a sub-dict where each input value carries source classification.
- `preview_authority` is a structural metadata block that mirrors the sidecar authority shape and adds explicit projection-not-decision language.

---

## No Silent Partial Fills

Every `projected_*` field must honestly disclose availability. Implementations must not fill missing preview fields with old, default, inferred, or unrelated values. If the preview cannot be computed, the field must be `None`, a governed sentinel, or `policy_object_pending`, and the blocking cause must appear in `preview_status`, `preview_named_gaps`, or `derivation_inputs`.

---

## Backward Compatibility (v1)

The v0 sidecar fields remain unchanged. `projected_preview` is additive. Consumers may rely on the v0 fields being present and unchanged, and consumers should handle both pre-v1 payloads where `projected_preview` is absent and v1+ payloads where it is present.

---

## Follow-Up Intent (non-binding)

The existing 7 lifecycle leaves at the parent level (`entry_policy`, `stop_policy`, `target_policy`, `timeout_policy`, `forced_exit_time`, `allowed_actions`, `lifecycle_policy_id`) are Pilot 1B baseline shape and predate sidecar discipline. A future commit may deprecate them once consumers migrate to `sidecar.projected_preview`. This amendment does not remove or rename them; deprecation requires a separate governed commit.

---

## Promotion Criteria

All criteria are required. None are satisfied by this contract.

- Replay/live parity passing.
- Bound threshold policies.
- Empirical improvement over static baseline.
- Conformal / uncertainty disclosure on lifecycle decisions.
- A2 replay-label validation as a label source.
- Post-trade attribution coherence: lifecycle decisions must reconcile with realized PnL through `v2_decision/post_trade_attribution.py`.
- Operator decision register approval.

Promotion requires a future operator decision. Advisory scaffolds, green tests, or sidecar output alone cannot promote lifecycle behavior to runtime authority.

---

## Test Bar For Future Code

Advisory-phase strictness applies:

- green-only tests are acceptable while lifecycle output is advisory, C-tier only, and non-authoritative;
- tests must cite the contract clause or named gap they cover;
- any future trade-impacting lifecycle authority requires red-green evidence and operator approval before promotion.

---

## Non-Goals

This contract does not:

- implement lifecycle code;
- refactor `_simulate_exit`;
- refactor `call_engine.py`;
- change runtime behavior;
- add UI;
- change v2 decision leaves;
- register derived analytics for lifecycle decisions before real input field lists exist.
