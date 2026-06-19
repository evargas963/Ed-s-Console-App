# RTH base capture / normalization validation runbook

**Harness:** `python tools/run_rth_base_capture_normalization_validation.py`  
**Closure item:** `BASE_CAPTURE_NORMALIZATION_RTH_PROOF_NOT_COMPLETE`

## Prove during RTH

- SPY / QQQ / IWM raw rows rising
- SPY / QQQ / IWM normalized rows rising
- Comparable logger attempts across base tickers

## Commands

```bash
python tools/run_rth_base_capture_normalization_validation.py --dry-run
python tools/run_rth_base_capture_normalization_validation.py --db-path data/ed_console.db
```

**Do not close until:** All three base tickers non-starved or explicit degraded reason documented.
