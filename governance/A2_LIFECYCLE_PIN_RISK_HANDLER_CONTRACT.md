# A2 Lifecycle Pin Risk Handler Contract

**Status:** Draft lifecycle handler contract  
**Date:** 2026-05-07  
**Module:** A - short-horizon directional trading  
**Expression profile:** A2 - 0DTE options  
**Scope:** Advisory pin-risk lifecycle event emission for the A2 lifecycle sidecar.

This contract defines the advisory pin-risk handler surface for A2. It lifts the existing A2 option-expression pin-risk health logic into a shared lifecycle health helper and emits pin-risk observations through the existing sidecar `event_sources` list. It does not authorize trade behavior, runtime execution, position liquidation, or promotion of lifecycle behavior to runtime authority.

---

## Authority Block

```text
mode = advisory_non_authoritative
tier = C_analytics_only
changes_trade_behavior = False
```

Pin-risk handler output is advisory lifecycle context only. It may inform call-card display and operator review, but it MUST NOT place orders, force exits, resize positions, tighten stops, or override EOD force-exit behavior.

---

## Scope

In scope:

- pin-risk lifecycle event contract for A2;
- reuse of the existing A2 pin-risk health shape and thresholds;
- shared helper surface at `v2_decision/a2_lifecycle_health.py`;
- `event_sources` event-entry schema for pin-risk observations;
- O-37 threshold binding for the current pin-risk health thresholds;
- session-aware suppression rules when a session calendar is available;
- composition rules with EOD force-exit.

Out of scope:

- lifting or implementing gamma-spike, IV-crush, assignment-risk, spread-widening, partial-fill, or dynamic-policy handlers;
- broker-realized position state;
- promotion to runtime authority;
- new top-level sidecar fields;
- order placement, lifecycle action mutation, or execution behavior.

---

## Detection Source

Canonical detection source:

```text
v2_decision/a2_lifecycle_health.py::derive_a2_pin_risk_health(...)
```

The former `_pin_risk_health` logic from `v2_decision/a2_option_expression.py` is lifted into this shared helper. The helper is the single source of truth consumed by both:

- `v2_decision/a2_option_expression.py` for `health.pin_risk`;
- `v2_decision/a2_lifecycle_sidecar.py` for lifecycle `event_sources`.

The sidecar MUST NOT duplicate pin-risk logic and MUST NOT rebuild the full A2 expression payload internally. `v2_decision/a2_option_expression.py` must continue to emit the same `health.pin_risk` shape after the helper lift.

Current `health.pin_risk` shape:

```text
{
  "status": "not_detected" | "watch" | "elevated",
  "selected_strike": float | None,
  "nearest_wall": {"level": str, "strike": float, "distance": float, "contrib": float} | None,
  "wall_score_component": float | None,
  "wall_proximity_component": float | None,
  "wall_bias_component": float | None,
  "bias_notes": list,
  "reasons": list[str],
}
```

Missing `selected_strike`, missing `nearest_wall`, or `status == "not_detected"` MUST emit no pin-risk lifecycle event.

---

## Helper Contract Surface

Implementation surface:

```python
def derive_a2_pin_risk_health(
    *,
    selected_audit: dict,
    strike: float | None,
) -> dict:
    """Return the A2 pin-risk health payload.
    Never raises in production.
    """


def build_a2_pin_risk_event_source(
    *,
    pin_risk_health: dict,
    session_type: str | None,
) -> dict | None:
    """Return a sidecar event_sources entry, or None when no event should emit.
    Never raises in production.
    """
```

The helper module name is locked as:

```text
v2_decision/a2_lifecycle_health.py
```

This module may later host gamma-spike lifecycle health helpers, but this contract only authorizes the pin-risk helper surface.

---

## Event Schema

Pin-risk lifecycle observations are emitted through the existing sidecar top-level field:

```text
sidecar["event_sources"]
```

No new top-level sidecar field is authorized by this contract.

Pin-risk event-entry shape:

```json
{
  "event_type": "pin_risk",
  "status": "watch",
  "reasons": ["material_wall_contribution"],
  "nearest_wall": null,
  "wall_score_component": 1.25,
  "wall_proximity_component": 0.8,
  "selected_strike": 500.0,
  "session_type": "normal_rth",
  "source_classification": "v1_approximation"
}
```

Allowed `status` values in emitted events:

- `"watch"`;
- `"elevated"`.

`status == "not_detected"` MUST emit no event. Missing `selected_strike` or missing `nearest_wall` MUST emit no event even if malformed upstream fields are present.

Allowed `session_type` values in emitted events:

- `"normal_rth"`;
- `"early_close"`;
- `"calendar_unavailable"`.

If the session calendar is available and classifies the decision moment as `"full_closure"` or `"out_of_session"`, pin-risk event emission is suppressed.

---

## Threshold Bindings

O-37 binds the current A2 pin-risk health thresholds as `a2_pin_risk_health_thresholds_v1`:

```text
nearest_wall.distance <= 1.0 strike points -> status = "elevated"
wall_score_component >= 1.0 -> status = "watch"
wall_proximity_component >= 0.75 -> status = "watch"
```

These values ratify the existing `_pin_risk_health` thresholds in `v2_decision/a2_option_expression.py`. They are not deferred policy gaps.

Threshold precedence:

1. nearest-wall distance threshold emits `"elevated"`;
2. wall-score threshold emits `"watch"` if elevated did not fire;
3. wall-proximity threshold emits `"watch"` if elevated and wall-score did not fire;
4. otherwise status remains `"not_detected"`.

---

## Session-Aware Suppression

When `load_a2_session_calendar()` and `get_session_info()` are available:

- `session_type == "normal_rth"` permits pin-risk event emission;
- `session_type == "early_close"` permits pin-risk event emission;
- `session_type == "full_closure"` suppresses pin-risk event emission;
- `session_type == "out_of_session"` suppresses pin-risk event emission.

When the calendar is missing, malformed, stale, or unavailable, the sidecar MUST NOT suppress pin-risk solely because session state is unknown. In that case, emitted events use:

```text
session_type = "calendar_unavailable"
```

This avoids false suppression from missing infrastructure while still preventing stale wall signals from being treated as live when the calendar explicitly says the market is closed or out of session.

---

## Composition With EOD Force-Exit

`lifecycle_action` remains owned by the EOD force-exit evaluator.

Pin-risk handler output MUST NOT:

- set `lifecycle_action`;
- override `lifecycle_action`;
- emit `"force_exit_recommended"`;
- tighten stops, resize positions, or mutate lifecycle policy.

If EOD force-exit emits:

```text
sidecar["lifecycle_action"] = "force_exit_recommended"
```

and pin risk is elevated or watch, both facts may coexist:

- `lifecycle_action` remains `"force_exit_recommended"`;
- the pin-risk observation appears in `event_sources`.

---

## Out-Of-Session And Calendar-Unavailable Behavior

Pre-entry behavior:

- pin-risk events may emit when health status is `"watch"` or `"elevated"`;
- broker-realized fill state is not required because output is advisory-only.

Filled-position behavior:

- pin-risk events may emit when health status is `"watch"` or `"elevated"`;
- output remains advisory and non-authoritative.

Full closure / out-of-session behavior:

- suppress when a valid calendar classifies the decision moment as `"full_closure"` or `"out_of_session"`;
- do not suppress solely on calendar unavailability.

Missing strike / no nearest wall behavior:

- emits no event.

---

## Operator Decision Implications

This contract adds one binding operator decision:

- O-37 - `a2_pin_risk_health_thresholds_v1`.

No new operator decisions are required for output mechanism or runtime authority. `event_sources` is an existing sidecar field, and pin-risk output remains advisory.

---

## Named Gaps

Retired by this implementation commit:

- `a2_lifecycle_pin_risk_handler_not_implemented` — resolved by adding `v2_decision/a2_lifecycle_health.py`, wiring advisory pin-risk events into `v2_decision/a2_lifecycle_sidecar.py::event_sources`, and preserving `health.pin_risk` parity through the shared helper.

No new named gaps are opened by this contract. O-37 ratifies the pin-risk thresholds, so no threshold-promotion or policy-object-pending gap is introduced.

Retirement discipline:

- `a2_lifecycle_pin_risk_handler_not_implemented` is removed from `v2_decision/a2_lifecycle_sidecar.py::LIFECYCLE_GAP_NAMES` by this implementation commit.

---

## Crosswalk

`governance/PILOT_1B_A2_LIFECYCLE_CONTRACT.md`:

- Names `a2_lifecycle_pin_risk_handler_not_implemented` as an A2 lifecycle gap.
- This contract defines the advisory handler surface and this implementation commit retires the gap.

`governance/A2_STATIC_LIFECYCLE_DIVERGENCE_AUDIT.md`:

- Existing audit material motivates the gap and remains a historical reference.

`governance/OPERATOR_DECISION_REGISTER.md`:

- O-37 binds the pin-risk health thresholds.

`v2_decision/a2_option_expression.py`:

- The former local `_pin_risk_health` detection logic is lifted into `v2_decision/a2_lifecycle_health.py`.
- Existing `health.pin_risk` payload shape must be preserved.

`v2_decision/a2_lifecycle_sidecar.py`:

- Code consumes the shared helper and appends pin-risk events to `event_sources`.
- `lifecycle_action` remains delegated to EOD force-exit.
- `a2_lifecycle_pin_risk_handler_not_implemented` is retired from `LIFECYCLE_GAP_NAMES` by this implementation commit.

`v2_decision/a2_session_calendar.py`:

- The session classifier suppresses pin-risk events on full closures or out-of-session decisions.
- Calendar unavailable means no session-based suppression.

---

## Test Bar

Implementation commit minimums:

- `health.pin_risk.status == "elevated"` emits one `event_sources` entry with `event_type = "pin_risk"` and `status = "elevated"`.
- `health.pin_risk.status == "watch"` emits one lower-tier pin-risk event.
- `health.pin_risk.status == "not_detected"` emits no pin-risk event.
- Missing `selected_strike` emits no pin-risk event.
- Missing `nearest_wall` emits no pin-risk event.
- A valid calendar with `session_type == "full_closure"` suppresses pin-risk event emission.
- A valid calendar with `session_type == "out_of_session"` suppresses pin-risk event emission.
- Calendar missing, malformed, stale, or unavailable does not suppress pin-risk solely on session uncertainty and emits `session_type = "calendar_unavailable"` when an event otherwise fires.
- EOD force-exit composition: `lifecycle_action == "force_exit_recommended"` remains unchanged when a pin-risk event also fires.
- `ms_dict` is not mutated.
- Existing sidecar shape remains backward compatible except for populated `event_sources`.

This implementation:

```text
pytest tests/test_v2_a2_pin_risk.py -q
```

---

## Non-Goals

This implementation does not:

- lift gamma-spike or IV-crush logic;
- add new top-level sidecar fields;
- change `lifecycle_action` value range;
- promote lifecycle behavior to runtime authority;
- resolve broker-realized position state;
- add new named gaps.
