# Monday gate — GEX forward capture (must clear before counting days)

**When:** Monday 2026-07-20, **before/at open**, then again **after ~10:00 ET**  
**Why:** `option_chain_morning_full` only fills if a live collector is running **and** has loaded the new server code. A dead or stale process captures nothing.

## Do not assume

- Decisions writing earlier ≠ this code path is live.
- Repo edit ≠ running process restarted.
- Empty `option_chain_morning_full` after 10:00 ET Monday = capture **failed** (investigate; do not invent days).

## Checklist (agent or operator — same turn evidence)

### A. Process up (09:20–09:45 ET)

1. Identify the live decision server (uvicorn / `server.py` for EdWebConsole). Record **PID**, **start time**, **cmdline**.
2. Confirm it is **not** an orphaned spawn worker only.
3. Confirm env includes whatever is required for live logging/chain (`ED_CALIBRATION_LOG` etc. as used in production).

### B. Code identity (same process)

1. Confirm process start time is **after** the commit/mtime that introduced:
   - `calibration/option_chain_morning_full.py`
   - `server.py` call to `maybe_persist_morning_full_chain`
2. If start time is older → **restart** the collector, then re-check A.

### C. Capture proof (after 10:00 ET Monday)

```sql
SELECT ticker, et_date, ts_utc, n_contracts, n_expiries, max_dte
FROM option_chain_morning_full
WHERE et_date = '2026-07-20'
ORDER BY ticker;
```

**PASS:** one row each for SPY, QQQ, IWM; `n_contracts` ≫ ~40; **`n_expiries` ≥ 2**; and per-expiry strike count **≫ 20** (wide fetch `GEX_FULL_CHAIN_STRIKE_COUNT=150`, not the live UI 20-strike chain). `source` should be `schwab_chain_wide_gex`.  
**FAIL:** 0 rows, or ~40 ATM / ≤20 strikes per expiry → do not count Monday toward forward GEX n; fix and retry Tuesday.

### D. Write evidence

Append result to `reports/gex_r1_monday_collector_gate_result.json` (PID, start time, code identity, SQL counts). Until that file says PASS, forward GEX accrual is **not started**.

## Authority

- Directive: `reports/fp_levelset_directive_for_cursor.md` §9(b)
- Queue: `ACTIVE_PROGRAM.md` FP-63
- Ledger: `OPEN_ITEMS.md` OPS-GEX-MORNING-FULL-MONDAY-GATE
