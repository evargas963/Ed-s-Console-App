# A2 Lifecycle EOD Force-Exit And Cadence Contract

**Status:** Draft lifecycle contract
**Date:** 2026-05-06
**Module:** A - short-horizon directional trading
**Expression profile:** A2 - 0DTE options
**Scope:** Advisory EOD force-exit firing and late-day cadence semantics for A2 lifecycle sidecar.

This contract locks the advisory v1 behavior for the A2 EOD force-exit and EOD cadence-shift path. It consumes B2 operator decisions O-32, O-33, and O-34, and defines the future code surface that closes `a2_lifecycle_eod_force_exit_logic_not_implemented`.

---

## Authority Block

```text
mode = advisory_non_authoritative
tier = C_analytics_only
changes_trade_behavior = False
```

This contract does not authorize trade behavior, order placement, position liquidation, sizing changes, runtime authority, or promotion of lifecycle behavior to `v2_compliant`. It defines advisory sidecar semantics only.

---

## Scope

In scope:

- force-exit firing predicates and triggers per O-33 plus position state;
- cadence shift semantics per O-32;
- sidecar emission shape changes: `lifecycle_action` value expansion and new `cadence_observation_mode` field;
- position-state proxy declaration;
- clock-source declaration;
- RTH-normal-session-only v1 assumption.

Out of scope:

- code implementation, deferred to a future commit;
- edits to existing contracts, including lifecycle, A2 0DTE, and sidecar contracts;
- edits to `MarketState` dataclass or `_ms_to_dict`;
- trading-calendar dependency;
- shortened-session, holiday, and out-of-session handling, named as future gaps below;
- bridge contract drafting;
- EV, execution-EV, or A1 work;
- new operator decision register entries;
- `a2_option_expression.py:383` cleanup for unpropagated `mins_to_close`, deferred to a separate follow-up commit.

---

## Operator Decisions Consumed

- **O-33** - force-exit clock threshold = 15:50 ET.
- **O-32** - EOD cadence window = 30 minutes before close, which is 15:30 ET in a normal RTH session.
- **O-34** - late-day gamma policy = advisory warning only, consistent with this contract's advisory-only authority.

No new operator decision register entries are required by this contract.

---

## Position State Proxy

The v1 force-exit logic uses `ms_dict["entry_state"] == "filled"` as a proxy for active position state. This is **INTENT-based**: it indicates the multi-horizon decision pipeline has classified the entry state machine as "filled" based on signal/setup conditions, NOT broker-realized fill confirmation. The advisory architecture has no broker connection that confirms actual order fills.

Named gap `a2_lifecycle_position_realization_state_pending` remains open until broker-realized position/fill state is propagated into ms_dict. Until then, the proxy is acceptable because:

- Authority is advisory non-authoritative; force-exit emits a recommendation, not a trade action
- Future broker-realized state propagation can refine the predicate without contract amendment, since the contract specifies the predicate in terms of "active position state" semantics rather than the specific key name

If `entry_state` is missing, empty, or any value other than `"filled"`, force-exit MUST NOT fire.

---

## Clock Source

The canonical decision timestamp is `ms_dict["decision_time_ms"]` (epoch milliseconds; set at `server.py:4173` = `int(_refresh_ts_utc * 1000)`). ET clock derivation uses `zoneinfo.ZoneInfo("America/New_York")`:

```python
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

def derive_et_clock_from_decision_time_ms(decision_time_ms: int) -> tuple[int, int]:
    dt_utc = datetime.fromtimestamp(decision_time_ms / 1000, tz=timezone.utc)
    dt_et = dt_utc.astimezone(ET)
    return dt_et.hour, dt_et.minute
```

No new dataclass fields are added to `MarketState`. No `et_hour`, `et_minute`, or `mins_to_close` injection into ms_dict via this contract. Future contracts may revise.

---

## Force-Exit Firing Semantics

Force-exit fires if and only if ALL predicates hold:

1. `ms_dict["entry_state"] == "filled"` (position proxy per `Position State Proxy`);
2. ET clock is at or after **15:50** per O-33;
3. RTH normal session holds: ET clock between 09:30 and 16:00, weekday only;
4. 0DTE holds: `ms_dict["selected_exp"]` matches today's date in ET.

If all predicates hold:

```text
sidecar["lifecycle_action"] = "force_exit_recommended"
```

If any predicate fails:

```text
sidecar["lifecycle_action"] = "no_active_position"
```

No silent partial fills are permitted. `lifecycle_action` is always one of the allowed values.

---

## Cadence Shift Semantics

Per O-32, when minutes-to-close is less than or equal to 30 in a normal RTH session, lifecycle observation cadence shifts into EOD mode.

The sidecar emits a new field:

```text
sidecar["cadence_observation_mode"]
```

Allowed values:

- `"event_triggered"` - default; ET clock before 15:30, or out-of-session;
- `"every_tier_c_cycle"` - ET clock at or after 15:30 and in RTH normal session.

Practical implication: the sidecar is already built on every server response cycle. The `cadence_observation_mode` field documents the discipline at the payload level for downstream observers. No actual scheduler change is authorized in v1.

---

## Sidecar Emission Shape

The sidecar gains one new field and modifies the value range of one existing field:

- `lifecycle_action` (existing) - value range expands from `{"no_active_position"}` to `{"no_active_position", "force_exit_recommended"}`.
- `cadence_observation_mode` (new) - value range is `{"event_triggered", "every_tier_c_cycle"}`.

No changes are made to `projected_preview`, `named_gaps`, or other sidecar fields by this contract.

---

## Session Handling

V1 is RTH-normal-session-only. Force-exit logic and cadence shift assume a normal RTH close at 16:00 ET and a normal RTH open at 09:30 ET on weekdays.

The original RTH-normal-session-only deviations are retired by the session-calendar hardening implementation:

- `a2_lifecycle_eod_force_exit_shortened_session_handling_pending` - **resolved** by this implementation commit. Calendar-aware force-exit consumes `session_close_et` from `data/trading_calendar/us_equities.json` (`cac88a6`) and derives threshold = `session_close_et - 10 min` per O-35. Early close days fire force-exit at the early-close-relative threshold rather than 15:50.
- `a2_lifecycle_eod_force_exit_holiday_session_handling_pending` - **resolved** by this implementation commit. Full closure dates in the calendar yield `session_type = "full_closure"`; force-exit MUST NOT fire and cadence stays `"event_triggered"`.
- `a2_lifecycle_eod_force_exit_out_of_session_stale_state_pending` - **resolved** by this implementation commit. Pre-open and post-close ranges yield `session_type = "out_of_session"`; force-exit MUST NOT fire and cadence stays `"event_triggered"`. Stale calendar (`current_date > valid_through_date`) falls back to RTH-only v1 normal-session behavior, explicit per `governance/A2_LIFECYCLE_SESSION_CALENDAR_HARDENING_CONTRACT.md` stale-fallback discipline.

---

## Named Gaps

- `a2_lifecycle_position_realization_state_pending` - broker-realized position state propagation.
- `a2_lifecycle_eod_force_exit_shortened_session_handling_pending` - **resolved** by this implementation commit. Calendar-aware force-exit consumes `session_close_et` from `data/trading_calendar/us_equities.json` (`cac88a6`) and derives threshold = `session_close_et - 10 min` per O-35. Early close days fire force-exit at the early-close-relative threshold rather than 15:50.
- `a2_lifecycle_eod_force_exit_holiday_session_handling_pending` - **resolved** by this implementation commit. Full closure dates in the calendar yield `session_type = "full_closure"`; force-exit MUST NOT fire and cadence stays `"event_triggered"`.
- `a2_lifecycle_eod_force_exit_out_of_session_stale_state_pending` - **resolved** by this implementation commit. Pre-open and post-close ranges yield `session_type = "out_of_session"`; force-exit MUST NOT fire and cadence stays `"event_triggered"`. Stale calendar (`current_date > valid_through_date`) falls back to RTH-only v1 normal-session behavior, explicit per `governance/A2_LIFECYCLE_SESSION_CALENDAR_HARDENING_CONTRACT.md` stale-fallback discipline.
- `a2_lifecycle_eod_force_exit_logic_not_implemented` - referenced from `governance/PILOT_1B_A2_LIFECYCLE_CONTRACT.md`; closes when this contract's code commit lands.

---

## Promotion Criteria

Promotion criteria:

- Bound threshold policies: satisfied by O-32 and O-33.
- Code implementation: not satisfied.
- Replay/live parity passing for force-exit decisions: not satisfied.
- Empirical improvement over baseline: not satisfied; no static baseline measurement exists.
- Conformal or uncertainty disclosure on force-exit decisions: not satisfied.
- Broker-realized position state propagation: not satisfied.
- Session-aware handling: satisfied for shortened sessions, full closures, and out-of-session stale-state behavior by the session-calendar hardening implementation; automated calendar freshness alerting remains tracked separately by `a2_session_calendar_freshness_pending`.
- Operator decision register entry promoting lifecycle behavior to runtime authority: not satisfied.

V1 is advisory only. Promotion to runtime authority requires a future operator decision.

---

## Crosswalk

`governance/PILOT_1B_A2_LIFECYCLE_CONTRACT.md`:

- Names `a2_lifecycle_eod_force_exit_logic_not_implemented`; this contract closes it via a future code commit.
- Cadence semantics align with the default lifecycle emission cadence section.

`governance/PILOT_1B_A2_0DTE_CONTRACT.md`:

- Defines the A2 0DTE scope. Force-exit applies only to 0DTE positions.
- O-34 late-day gamma policy remains advisory-warning-only and does not independently tighten stops, resize, or force exit.

`governance/OPERATOR_DECISION_REGISTER.md`:

- O-32, O-33, and O-34 are consumed by this contract.

`v2_decision/a2_lifecycle_sidecar.py`:

- `lifecycle_action` value range and new `cadence_observation_mode` field are locked here; a future code commit implements them.

---

## Test Bar

Future code commit minimums:

- Force-exit fires when all four predicates hold.
- Force-exit does not fire when each predicate individually fails.
- Cadence mode flips at 15:30 ET.
- `decision_time_ms` timezone conversion is accurate, including DST transitions and exact 15:30, 15:50, and 16:00 boundaries.
- No silent partial fills: `lifecycle_action` is always in the allowed set.
- `ms_dict` is not mutated beyond the lifecycle sidecar fields `lifecycle_action` and `cadence_observation_mode`.
- Existing 24 sidecar tests stay green.
- Existing 71 attachment-and-promotion tests stay green.

This contract:

```text
pytest n/a - doc-only contract
```

---

## Non-Goals

This contract does not:

- implement code;
- edit existing contracts;
- add new operator decisions;
- edit `MarketState` dataclass;
- edit `_ms_to_dict`;
- add a trading-calendar dependency;
- add new `ms_dict` keys;
- draft a bridge contract;
- perform EV, execution-EV, or A1 work;
- add registry entries;
- update the cleanup queue for `a2_option_expression.py:383`.
