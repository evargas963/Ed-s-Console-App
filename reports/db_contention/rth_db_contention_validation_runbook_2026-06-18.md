# RTH DB contention validation runbook

> **Classification:** Operator Runbook | **Scope:** DB_CONTENTION_RTH_CORRELATION_NOT_PROVEN — RTH closure harness

**Harness:** `python tools/run_rth_db_contention_validation.py`  
**Closure item:** `DB_CONTENTION_RTH_CORRELATION_NOT_PROVEN`

## Correlate

- sqlite lock wait / database locked counter deltas
- STALE pill timing
- LOADING duration
- ticker switch timing
- Tier C delay
- snapshot / normalized cadence

## Commands

```bash
python tools/run_rth_db_contention_validation.py --dry-run
python tools/run_rth_db_contention_validation.py --base-url http://127.0.0.1:8000
```

**Do not close until:** DB contention events joined to operator DB chip + lane STALE timestamps.
