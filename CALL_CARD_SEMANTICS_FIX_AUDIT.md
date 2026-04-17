# Call Card Semantics Fix — Closure Audit

## Root Cause

**Logic mismatch between “What the Data Says” and “The Call”:**

1. **Different stacks**: “5 of 5 agree” is **fusion model agreement** (XGB, LSTM, Transformer, MC, Fusion — 5 ML sources). The Call uses a **7-layer stack**: micro (rules), Greeks, cross-instrument, prediction, regime, fusion, order_flow. Fusion contributes **one vote**.

2. **Prediction abstention**: The “prediction” stack vote requires `pred_conf != "low"`. When `pred_conf == "low"`, prediction abstains (0). So with fusion=short (1 vote) and prediction abstaining, we get **1 short** — below the threshold of 2.

3. **Misleading message**: The headline “WAIT — stack consensus below threshold” did not show stack counts, failed gate, or the fact that the Call stack differs from fusion model agreement.

4. **Blockers not surfaced**: When WAIT came from vol regime or risk gates (not insufficient stack votes), the same generic message was shown.

## Affected Scenario

- Fusion: 5/5 bearish, 98% downside  
- Call: WAIT with “stack consensus below threshold”  
- Cause: stack has 1 short (fusion only) because prediction abstained (low confidence). Message did not explain this.

## Files Changed

| File | Changes |
|------|---------|
| `call_engine.py` | `wait_blocker` with reason/values; refactor `_build_call_headlines`; diagnostic log |
| `signal_types.py` | Add `wait_blocker` to TheCall |
| `market_state.py` | Add `call_wait_blocker`; copy from TheCall |
| `server.py` | Add `wait_blocker` to `call_readiness` payload |
| `static/index.html` | DIAG log for call decision bundle |

---

## Exact Diffs

### call_engine.py

**1. Replace stack_wait_reason with wait_blocker (stack case):**
```python
# Before: stack_wait_reason = "Stack: X long, Y short. Consensus below 2..."
# After:
wait_blocker = None
if final_signal == "wait":
    wait_blocker = {
        "reason": "stack",
        "long_count": long_count, "short_count": short_count,
        "long_names": long_names, "short_names": short_names,
        "threshold": STACK_THRESHOLD,
    }
```

**2. Vol and gates overrides set wait_blocker:**
```python
# Vol override:
wait_blocker = {"reason": "vol_regime", "detail": "...", "full_detail": "..."}
# Gates override:
wait_blocker = {"reason": "gates", "gate_reasons": _gate_reasons}
```

**3. _build_call_headlines — reason-specific headlines:**
- **stack**: `"WAIT — stack: X long, Y short (need 2+ in one direction)."`; reasoning explains 7 layers vs fusion.
- **vol_regime**: `"WAIT — vol regime: unstable — require 4+ confluence."`
- **gates**: `"WAIT — gated: structure/probability/risk."`

**4. Diagnostic log (when signal=wait):**
```python
log.debug("[call] WAIT decision: blocker=%s stack_votes=%s long=%d short=%d pred_dir=%s pred_conf=%s fus=%s", ...)
```

### signal_types.py

```python
wait_blocker: Optional[dict] = None  # when signal=wait
```

### market_state.py

```python
call_wait_blocker: Optional[dict] = None
# ...
ms.call_wait_blocker = getattr(_call, 'wait_blocker', None)
```

### server.py

```python
"wait_blocker": getattr(ms, "call_wait_blocker", None),  # in call_readiness
```

### static/index.html

```javascript
if (DIAG) console.log('[render] The Call', { call_signal, call_state, readiness_score, wait_blocker, confluence });
```

---

## Before / After

### Decision Logic (unchanged)

- Stack votes: micro, Greeks, cross, prediction, regime, fusion, order_flow  
- STACK_THRESHOLD = 2  
- Vol regime and risk gates can override to wait  

### Card Semantics

| Aspect | Before | After |
|--------|--------|-------|
| Headline (stack wait) | "WAIT — stack consensus below threshold." | "WAIT — stack: 0 long, 1 short (need 2+ in one direction)." |
| Reasoning (stack) | "Stack: X long, Y short. Consensus below 2 sources — no directional edge." | Explains 7-layer stack vs fusion; notes that "5 of 5" is one stack vote |
| Headline (vol) | Same generic | "WAIT — vol regime: unstable — require 4+ confluence." |
| Headline (gates) | Same generic | "WAIT — gated: structure / probability / risk." |
| Diagnostics | None | log.debug + frontend DIAG with wait_blocker |

### Clarification

The message now states that the Call stack uses 7 layers and that fusion model agreement (“5 of 5”) counts as one stack vote, so strong fusion agreement can still yield only 1 short vote when prediction abstains.

---

## Closure Audit Result

- [x] Root cause identified (7-layer stack vs 5-model fusion; prediction abstention)
- [x] Headlines/reasoning show actual blocker and counts
- [x] Stack, vol_regime, and gates surfaced separately
- [x] `wait_blocker` added for diagnostics
- [x] DIAG logging in frontend and backend
- [x] No dead legacy logic (stack_wait_reason removed)

---

## Validation

For 5/5 bearish + WAIT:

1. **Why WAIT**: Only 1 short vote (e.g. fusion) because prediction abstained (low confidence).
2. **Message**: Shows stack counts and “need 2+”, plus note on fusion vs stack.
3. **Backend**: `log.debug` prints decision bundle when log level is DEBUG.
4. **Frontend**: `window._edDiag = true` logs `wait_blocker` and related fields.

---

## Follow-up: Time-Warning Consistency (≤30 min to close)

### Root Cause

The time-warning override ran **after** headlines were built. When `mins_to_close <= 30`, it set `final_signal = "wait"` and `size_cue = "SKIP"`, but headline and reasoning had already been built for long/short. The UI showed headline suggesting LONG/SHORT while badge showed WAIT.

### Fix

1. **Reorder**: Time-warning block moved **before** headlines. Display fields built only after all overrides.
2. **wait_blocker for time**: When time forces wait, set `wait_blocker = {"reason": "time", "detail": "≤N min to close", "full_detail": "…"}`.
3. **_build_call_headlines**: Add `reason == "time"` branch.

### Assembly Order (after fix)

| Step | Content |
|------|---------|
| 1–6 | Stack signal, conviction, trade type, levels, invalidation, time qualifier |
| 7 | Position sizing |
| **8** | **Time warning** (override when ≤30 min) |
| — | Diagnostics (when wait) |
| **9** | **Headlines** (after all overrides) |
| 10–11 | size_note, call readiness, put readiness, TheCall |

### Validation

- `tests/test_call_time_warning.py`: Near-close (25 min) forces WAIT with consistent headline/reasoning/blocker.
