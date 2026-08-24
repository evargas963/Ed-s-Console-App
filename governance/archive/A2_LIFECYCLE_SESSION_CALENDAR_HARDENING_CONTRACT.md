# A2 Lifecycle Session Calendar Hardening Contract

**Status:** IMPLEMENTED — calendar loader and consumer landed (`cac88a6`); session-aware force-exit and cadence shifts active. Advisory v1 authority. Promotion to runtime authority requires a future operator decision.  
**Date:** 2026-05-06  
**Module:** A - short-horizon directional trading  
**Expression profile:** A2 - 0DTE options  
**Scope:** Advisory session-calendar hardening for A2 EOD force-exit and cadence logic.

This contract binds the future session-aware calendar surface that replaces the RTH-normal-session-only v1 assumption in `governance/A2_LIFECYCLE_EOD_FORCE_EXIT_AND_CADENCE_CONTRACT.md`. It covers shortened sessions, full closures, and out-of-session stale-state behavior. Broker-realized position state remains a separate track.

---

## Authority Block

```text
mode = advisory_non_authoritative
tier = C_analytics_only
changes_trade_behavior = False
```

This contract does not authorize order placement, liquidation, sizing changes, runtime authority, or promotion of lifecycle behavior to `v2_compliant`. It defines advisory sidecar semantics and future implementation contracts only.

---

## Scope

In scope:

- canonical A2 session calendar source as a repo-local operator-curated JSON file;
- schema specification for the calendar fixture;
- loader contract surface, signature only;
- session classification rules for normal RTH, early close, full closure, and out-of-session states;
- force-exit and cadence threshold derivation per session type;
- `v2_decision/a2_eod_force_exit.py` consumption rules for a future code commit.

Out of scope:

- code implementation, deferred to a future commit;
- edits to other session-aware code paths, including `ml_scheduler.py` holiday lists, `db.py` / `market_context.py` ET-clock-only classifications, and `calibration/signal_engineering.py` rough cash-hours filters;
- external library dependencies such as `pandas_market_calendars` or `exchange_calendars`;
- multi-exchange support;
- extended-hours, pre-market, or overnight trading semantics;
- broker-realized position state, tracked separately by `a2_lifecycle_position_realization_state_pending`;
- direct rebinding of O-32 and O-33 absolute-clock values.

---

## Calendar Source

V1 venue:

```text
data/trading_calendar/us_equities.json
```

The file is repo-local, operator-curated, and scoped to US equities. It is updated annually and ad hoc for unscheduled closures. No new external calendar dependency is authorized in v1.

The fixture is advisory infrastructure for A2 lifecycle evaluation only. Other session-aware code paths remain non-canonical until separate contracts or cleanup commits explicitly consume this source.

---

## Schema Specification

The calendar JSON MUST use this shape:

```json
{
  "schema_version": "1",
  "scope": "us_equities",
  "exchange": "NYSE/NASDAQ unified",
  "valid_through_date": "2026-12-31",
  "last_updated_epoch_seconds": 1735689600,
  "regular_session": {
    "open_et": "09:30",
    "close_et": "16:00"
  },
  "full_closures": [
    "2026-01-01",
    "2026-07-04",
    "2026-12-25"
  ],
  "early_closes": [
    {"date": "2026-07-03", "close_et": "13:00"},
    {"date": "2026-11-27", "close_et": "13:00"},
    {"date": "2026-12-24", "close_et": "13:00"}
  ]
}
```

Required top-level fields:

- `schema_version` - string; initial value `"1"`.
- `scope` - string; MUST be `"us_equities"` for this contract.
- `exchange` - string; human-readable venue descriptor.
- `valid_through_date` - `YYYY-MM-DD`; latest date for which the fixture is considered fresh.
- `last_updated_epoch_seconds` - integer epoch seconds.
- `regular_session.open_et` - `HH:MM` ET regular open.
- `regular_session.close_et` - `HH:MM` ET regular close.
- `full_closures` - list of `YYYY-MM-DD` full market closure dates.
- `early_closes` - list of objects with `date` and `close_et`.

Malformed, missing, or stale calendar data MUST be treated as unavailable by the loader.

---

## Loader Contract Surface

Future code commit surface:

```python
def load_a2_session_calendar(*, data_root: Path | None = None) -> dict | None:
    """Returns the calendar dict or None on missing/malformed/stale.
    Never raises in production. Logs at debug.
    """


def get_session_info(*, decision_time_ms: int, calendar: dict) -> SessionInfo:
    """Returns session classification and boundaries for the decision moment.
    SessionInfo includes session_type, session_open_et, and session_close_et.
    """
```

`SessionInfo` is a future `NamedTuple` or equivalent immutable structured return value. Minimum fields:

- `session_type`: one of `"normal_rth"`, `"early_close"`, `"full_closure"`, `"out_of_session"`.
- `session_open_et`: `HH:MM` string or `None`.
- `session_close_et`: `HH:MM` string or `None`.
- `decision_date_et`: `YYYY-MM-DD`.
- `decision_minute_et`: integer minutes since midnight ET.

Both helpers MUST be production-safe and never raise to callers.

---

## Session Classification

Classification uses `decision_time_ms` converted to ET with the existing `ZoneInfo("America/New_York")` clock discipline.

Allowed categories:

- `normal_rth` - weekday, not in `full_closures`, not in `early_closes`, and decision time is inside regular open-close boundaries.
- `early_close` - weekday date listed in `early_closes`, not in `full_closures`, and decision time is inside open-close boundaries using the listed early close.
- `full_closure` - date listed in `full_closures` or weekend.
- `out_of_session` - same-day pre-open or post-close when the date is otherwise a trading session.

Full closure takes precedence over early close. Early close takes precedence over normal RTH.

---

## Force-Exit Threshold Derivation

Future calendar-aware force-exit fires only when:

1. session type is `"normal_rth"` or `"early_close"`;
2. current ET clock is at or after `session_close_et - a2_force_exit_offset_from_session_close_minutes`;
3. active position and 0DTE predicates from `governance/A2_LIFECYCLE_EOD_FORCE_EXIT_AND_CADENCE_CONTRACT.md` still hold.

Operator decision O-35 binds:

```text
a2_force_exit_offset_from_session_close_minutes = 10
```

On normal RTH days, this preserves O-33's literal 15:50 ET behavior because 16:00 minus 10 minutes is 15:50. On a 13:00 ET early close day, the threshold is 12:50 ET.

On `full_closure` or `out_of_session`, force-exit MUST NOT fire.

---

## Cadence Shift Threshold Derivation

Future calendar-aware cadence shifts only when:

1. session type is `"normal_rth"` or `"early_close"`;
2. current ET clock is at or after `session_close_et - a2_cadence_shift_offset_from_session_close_minutes`.

Operator decision O-36 binds:

```text
a2_cadence_shift_offset_from_session_close_minutes = 30
```

On normal RTH days, this preserves O-32's literal 15:30 ET behavior because 16:00 minus 30 minutes is 15:30. On a 13:00 ET early close day, the threshold is 12:30 ET.

On `full_closure` or `out_of_session`, cadence MUST remain `"event_triggered"`.

---

## Operator Decision Implications

This contract selects explicit operator-decision binding for session-close-relative offsets:

- O-35 - `a2_force_exit_offset_from_session_close_minutes` = 10.
- O-36 - `a2_cadence_shift_offset_from_session_close_minutes` = 30.

O-32 and O-33 remain the existing absolute-clock bindings for normal RTH days. O-35 and O-36, added with this governance commit, make the derived early-close behavior governance-visible without changing backward-compatible normal-session semantics.

---

## Out-Of-Session Stale State Behavior

Pre-open behavior:

- force-exit does not fire;
- cadence is `"event_triggered"`.

Post-close behavior:

- force-exit does not fire;
- cadence is `"event_triggered"`.

Weekend behavior:

- classified as `full_closure`;
- force-exit does not fire;
- cadence is `"event_triggered"`.

Calendar unavailable behavior:

- missing, malformed, or stale calendar yields `None` from `load_a2_session_calendar`;
- the consumer falls back to the current RTH-only v1 normal-session assumption from `governance/A2_LIFECYCLE_EOD_FORCE_EXIT_AND_CADENCE_CONTRACT.md`;
- fallback MUST be explicit in code and tests.

---

## Stale Calendar Discipline

If the current ET date is after `calendar["valid_through_date"]`, the loader MUST log at debug and return `None`.

The consumer treats `None` calendar as fallback to RTH-only v1 normal-session behavior. This preserves current advisory semantics while avoiding false precision from stale calendar data.

Named gap:

- `a2_session_calendar_freshness_pending` - automated alerting, refresh workflow, and operator acknowledgement for stale or soon-to-expire calendar fixtures.

---

## Named Gaps

Closed by this implementation commit (`cac88a6`):

- `a2_lifecycle_eod_force_exit_shortened_session_handling_pending` — early-close days fire force-exit at `session_close_et - 10 min` per O-35;
- `a2_lifecycle_eod_force_exit_holiday_session_handling_pending` — full-closure dates yield `session_type = "full_closure"`; force-exit MUST NOT fire and cadence stays `"event_triggered"`;
- `a2_lifecycle_eod_force_exit_out_of_session_stale_state_pending` — pre-open and post-close ranges yield `session_type = "out_of_session"`; force-exit MUST NOT fire and cadence stays `"event_triggered"`. Stale calendar (`current_date > valid_through_date`) falls back to RTH-only v1 normal-session behavior per §Stale Calendar Discipline.

Opens in this contract:

- `a2_session_calendar_freshness_pending` - alerting and refresh policy for stale calendar fixtures.
- `a2_session_calendar_multi_exchange_pending` - non-US-equities and per-exchange support.
- `a2_session_calendar_extended_hours_pending` - pre-market, after-hours, and overnight session handling.

Stays open elsewhere:

- `a2_lifecycle_position_realization_state_pending` - broker-realized position and fill-state propagation.

---

## Crosswalk

`governance/A2_LIFECYCLE_EOD_FORCE_EXIT_AND_CADENCE_CONTRACT.md`:

- Its RTH-normal-session-only v1 assumption is replaced by calendar-aware classification per `cac88a6` (`v2_decision/a2_session_calendar.py` loader + `v2_decision/a2_eod_force_exit.py` consumer).
- Active-position and 0DTE predicates remain unchanged.

`governance/OPERATOR_DECISION_REGISTER.md`:

- O-32 and O-33 remain consumed for normal RTH absolute-clock behavior.
- O-35 and O-36 bind the session-close-relative offsets used by this contract.

`v2_decision/a2_eod_force_exit.py`:

- The implementation commit (`cac88a6`) consumes the calendar loader and derives thresholds from session close.
- The no-calendar path remains the explicit fallback per §Stale Calendar Discipline.

Other session-aware code paths:

- `db.py`, `market_context.py`, `ml_scheduler.py`, and `calibration/signal_engineering.py` are not touched by this contract.
- Their existing local session heuristics are not promoted to canonical status.

---

## Test Bar

Future code commit minimums:

- Normal RTH day behavior is identical to current EOD logic.
- Early close day with calendar present: force-exit fires at close minus 10 minutes.
- Early close day with calendar present: cadence shifts at close minus 30 minutes.
- Full closure day: force-exit does not fire and cadence remains `"event_triggered"`.
- Weekend: same as full closure.
- Pre-open: force-exit does not fire and cadence remains `"event_triggered"`.
- Post-close: force-exit does not fire and cadence remains `"event_triggered"`.
- Calendar missing: consumer falls back to RTH-only v1 behavior.
- Calendar malformed: consumer falls back to RTH-only v1 behavior.
- Calendar stale: consumer falls back to RTH-only v1 behavior.
- DST transitions: ET clock derivation remains correct.
- `ms_dict` is not mutated.

This contract:

```text
pytest n/a - doc-only governance
```

---

## Non-Goals

This contract does not:

- implement code;
- add the calendar JSON fixture;
- add external dependencies;
- add multi-exchange support;
- add extended-hours support;
- resolve broker-realized position state;
- retrofit `ml_scheduler.py`, `db.py`, `market_context.py`, or `calibration/signal_engineering.py`;
- edit `MarketState` or `_ms_to_dict`.
