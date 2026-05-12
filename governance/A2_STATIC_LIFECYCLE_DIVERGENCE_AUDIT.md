# A2 Static Lifecycle Divergence Audit

**Status:** DRAFT audit artifact
**Date:** 2026-05-06
**Source pin:** `origin/main` / `HEAD` at `132561f`
**Lifecycle contract:** `governance/PILOT_1B_A2_LIFECYCLE_CONTRACT.md`

This audit supports the next A2 lifecycle implementation phase. It is doc-only: no rule-core extraction, no code refactor, no threshold binding, no registry entry, and no lifecycle runtime authority.

---

## Framing

The existing implementations are not peer exit-decision engines.

```text
call_engine.py = threshold / setup geometry producer
realized_contract_eval._simulate_exit = exit trigger / replay firing engine
shared lifecycle rule core = future pipeline contract that names both halves
```

Therefore this audit is organized as a **by-concern coverage matrix**, not a by-file side-by-side comparison.

---

## Scope Boundary

### In Scope For `call_engine.py`

- `_stop_distance()`
- `_compute_levels()`
- nested `_snap_to_structural()`
- VIX-aware and time-of-day stop-distance adjustment logic
- direct helpers required by those functions

### Adjacent, Not Extracted

- `_build_invalidation()` and invalidation messaging. These may mention stop levels but are presentation / explanation, not the lifecycle rule core.

### Out Of Scope

- conviction
- sizing
- signal generation
- regime classification
- presentation text
- UI copy

### In Scope For `realized_contract_eval.py`

- `_simulate_exit()`
- replay use of `replay_max_hold_bars`
- exit reason vocabulary emitted from replay
- missing-data behavior that determines whether replay emits labels or skips

---

## Matrix Schema

Each row uses this schema:

| Field | Meaning |
|---|---|
| Concern | Named lifecycle concern. |
| Current owner | `realized_contract_eval` / `call_engine` / `both` / `neither`. |
| Input contract | Fields/types consumed by the current logic. |
| Output contract | Values produced by the current logic. |
| Divergence flag | `true` only if owner = `both` and behaviors differ. |
| Coverage gap | `true` if owner = `neither` and required for static baseline. |
| Linked named gap | Lifecycle contract child gap or `n/a`. |
| Audit finding | Behavior, edge cases, missing-data path, or divergence detail. |

---

## Coverage Matrix

| Concern | Current owner | Input contract | Output contract | Divergence flag | Coverage gap | Linked named gap | Audit finding |
|---|---|---|---|---|---|---|---|
| Stop distance derivation | `call_engine` | `SignalInput`, `risk_multiplier`, `vix_level`, current time via ET clock | Percentage-scaled stop distance | false | false | `a2_lifecycle_static_rule_core_pending` | `_stop_distance()` derives a stop distance before any exit firing exists. Replay consumes final `rules_stop`; it does not derive it. |
| Target distance derivation | `call_engine` | spot, zone, structural levels, prediction move fields, risk from stop distance | `target`, `target2` levels | false | false | `a2_lifecycle_static_rule_core_pending` | `_compute_levels()` derives targets from prediction move distances with structural snapping and R:R caps. Replay consumes final `rules_target`; it does not derive it. |
| Time-of-day decay on stop distance | `call_engine` | ET clock through `now_et()`, minutes elapsed since 9:30 | Decayed stop-distance percentage | false | false | `a2_lifecycle_static_rule_core_pending` | `_stop_distance()` tightens stop distance as the session progresses. Replay has no equivalent derivation; it only consumes thresholds already stored on the row. |
| VIX-aware stop adjustment | `call_engine` | `SignalInput.vix_level` | Wider stop-distance percentage when VIX is elevated | false | false | `a2_lifecycle_static_rule_core_pending` | `_stop_distance()` widens stops for VIX > 20 / > 30. Position sizing has separate VIX logic, but sizing is out of scope for rule-core extraction. |
| Structural-level snapping | `call_engine` | VWAP, gamma walls, OI walls, direction, predicted target | Snapped target / target2 levels | false | false | `a2_lifecycle_static_rule_core_pending` | Nested `_snap_to_structural()` snaps targets toward nearby structural levels. Replay does not snap; it consumes stored threshold values. |
| Risk multiplier semantics | `call_engine` | `risk_multiplier` / volatility-regime risk multiplier | Scaled stop distance with clamp | false | false | `a2_lifecycle_static_rule_core_pending` | `_stop_distance()` clamps and applies multiplier to stop distance. Future shared core must preserve or explicitly revise this semantics before replay/live parity can be asserted. |
| Exit firing trigger | `realized_contract_eval` | call signal, stop, target, forward 1m OHLC bars | `stop_hit`, `target_hit`, or skip reason | false | false | `a2_lifecycle_static_rule_core_pending` | `_simulate_exit()` fires exits from precomputed thresholds. `call_engine.py` does not decide which future bar fired. |
| Same-bar stop+target conflict resolution | `realized_contract_eval` | forward bar OHLC; stop and target thresholds | exit reason plus path model / resolution rule | false | false | `a2_lifecycle_static_rule_core_pending` | `_simulate_exit()` resolves same-bar conflicts using candle body direction when open/close exist; otherwise conservative stop-first. `call_engine.py` has no equivalent firing rule. |
| Time stop / max-hold bars | `realized_contract_eval` consumes; `call_engine` provides support function | `replay_max_hold_bars` from replay context; forward bars | `time_expiry` when no stop/target fires within max hold | false | false | `a2_lifecycle_static_rule_core_pending` | `call_engine.replay_max_hold_bars_for_setup()` supplies max-hold intent; `_simulate_exit()` executes time expiry by exhausting forward bars. Shared core must name this handoff. |
| EOD-driven force-exit | `neither` | Future clock threshold policy and current time-to-close | Future force-exit advisory / event source | false | true | `a2_lifecycle_eod_force_exit_logic_not_implemented` | No confirmed clock-aligned force-exit firing logic exists. `call_engine.py` has time-to-close sizing warnings; `_simulate_exit()` has max-hold time expiry, not EOD force-exit. Logic gap is upstream of `a2_lifecycle_time_stop_force_exit_clock_threshold_policy_object_pending`; implementation must exist before any threshold value is meaningful. |
| Long vs short handling | `both` | Direction / call signal | Direction-specific threshold geometry and exit firing | false | false | `a2_lifecycle_static_rule_core_pending` | `call_engine` derives long and short entry/stop/target geometry; `_simulate_exit()` fires long and short exits with inverted stop/target tests. Behaviors are complementary, not divergent peers. |
| Missing-data behavior | `both` | Missing spot/threshold/OHLC/prediction/level inputs | Fallback, skip, or placeholder behavior depending on layer | false | false | `a2_lifecycle_legacy_exit_logic_divergence_audit_pending` | `_simulate_exit()` emits explicit skip reasons for missing OHLC or missing stop/target. `call_engine` falls back for target construction when prediction/levels are unavailable. Extraction must preserve explicit replay skips and document live-side fallbacks. |
| Output reason vocabulary | `realized_contract_eval` plus adjacent `call_engine` notes | Replay path outcomes; call card explanatory text | Replay emits enumerated reasons; call engine emits free-text notes | false | false | `a2_lifecycle_legacy_exit_logic_divergence_audit_pending` | Replay reason vocabulary is structured: `stop_hit`, `target_hit`, `time_expiry`, plus skip reasons. `call_engine` output is explanatory text, not lifecycle event vocabulary. Shared core must not treat free text as a rule output. |
| Pin/gamma/assignment risk | `neither` | Future option-chain / Greeks / assignment-risk fields | Future advisory risk events or lifecycle actions | false | true | `a2_lifecycle_pin_risk_handler_not_implemented`; `a2_lifecycle_gamma_spike_handler_not_implemented`; `a2_lifecycle_assignment_risk_handler_not_implemented` | Existing A2 expression health surfaces pin/gamma concerns, but static lifecycle firing does not yet handle pin risk, gamma spike, or assignment risk as lifecycle exit logic. |
| Spread-widening exit | `neither` | Future bid/ask/spread threshold and current selected contract quote | Future exit advisory when spread widens beyond policy | false | true | `a2_lifecycle_spread_widening_exit_not_implemented` | A2 entry gates and execution EV scaffolds use spread inputs, but lifecycle has no exit rule that fires because spread widened after entry. |
| **`volatility`-crush** handler | `neither` | Future **`volatility`** path / selected contract **`volatility`** / threshold policy | Future advisory exit or warning event | false | true | `a2_lifecycle_iv_crush_handler_not_implemented` | No static lifecycle rule currently fires on **`volatility`** crush. This remains a named lifecycle gap. |
| Partial-fill handler | `neither` | Future fill-status and order-state inputs | Future lifecycle action over partial position state | false | true | `a2_lifecycle_partial_fill_handler_not_implemented` | Existing replay assumes full contract count; lifecycle has no partial-fill state machine. |

---

## New Gap Cross-Reference

`a2_lifecycle_eod_force_exit_logic_not_implemented` is distinct from `a2_lifecycle_time_stop_force_exit_clock_threshold_policy_object_pending`.

- `a2_lifecycle_eod_force_exit_logic_not_implemented` = firing mechanism gap.
- `a2_lifecycle_time_stop_force_exit_clock_threshold_policy_object_pending` = threshold value / policy-object gap.

The logic gap is upstream of the policy gap: implementation must exist before any force-exit clock threshold can be meaningful.

---

## Extraction Implications

The future `lifecycle_rule_core.py` should not import either existing source as canonical. It should extract a shared static lifecycle pipeline with two named halves:

1. **Threshold / setup geometry** currently represented by in-scope `call_engine.py` functions.
2. **Exit firing / replay outcome** currently represented by `_simulate_exit()`.

The extraction commit must use this matrix row-by-row. It must not silently choose a winner for missing-data behavior, reason vocabulary, same-bar conflict handling, or time handling.

---

## Non-Goals

This audit does not:

- refactor code;
- extract a rule core;
- bind threshold policies;
- add registry entries;
- change runtime behavior;
- change UI;
- change v2 decision leaves;
- conclude which file is "right" on contested behaviors.

Divergences and gaps are named, not resolved. Resolution belongs to the future rule-core extraction commit, guided by this audit and operator approval.
