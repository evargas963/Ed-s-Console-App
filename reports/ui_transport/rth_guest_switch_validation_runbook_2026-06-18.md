# RTH guest switch validation runbook

> **Classification:** Operator Runbook | **Scope:** LIVE_GUEST_SLA_NOT_PROVEN — RTH closure harness

**Harness:** `python tools/run_rth_guest_switch_validation.py`  
**Closure item:** `LIVE_GUEST_SLA_NOT_PROVEN` — **NEEDS_RTH_VALIDATION_WITH_HARNESS**

## Prerequisites

- Market open / RTH
- Server at repo tip
- Browser: `window.ED_SWITCH_TIMING = true`
- `ED_CALIBRATION_LOG=1` (RTH proof — disabled = cannot PASS)
- Endpoints: `/api/diagnostics/ticker-switch`, `/api/diagnostics/sqlite-contention`

## Switch matrix

| From | To |
|------|-----|
| SPY | QQQ |
| QQQ | IWM |
| SPY | NVDA |
| NVDA | IWM |
| PLTR | AAPL |
| SPY | SPX |
| SPY | $VIX |

## Pass/fail

**FAIL** if: wrong ticker accepted; stale generation accepted; cache as fresh; guest incomplete without reason; cards timing missing after timeout; DB degraded not surfaced; final state stuck without READY/degraded.

## Commands

```bash
# Dry run (never PASS)
python tools/run_rth_guest_switch_validation.py --dry-run

# Live RTH
python tools/run_rth_guest_switch_validation.py --base-url http://127.0.0.1:8000
```

**Owner branch:** Operator host. **Do not close until:** PASS report with calibration enabled.
