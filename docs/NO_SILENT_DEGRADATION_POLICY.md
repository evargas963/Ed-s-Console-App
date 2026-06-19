> **Classification:** Policy | **Scope:** Operator-visible degradation — no silent fresh fallbacks

# No silent degradation policy

If **data**, **transport**, **DB**, **ticker completeness**, **calibration logging**, or **market session** state is degraded, the UI or validation report **must surface it**.

## Banned

- Hidden fallback that looks fresh
- STALE/LOADING as the only symptom when DB contention is active
- Guest partial data presented as full stack without copy

## Required operator copy examples (guest partial)

- `GUEST PARTIAL — normalized history unavailable`
- `GUEST PARTIAL — histogram unavailable`
- `GUEST PARTIAL — options layer unavailable`
- `GUEST PARTIAL — ALL/PLAN reduced`

## Transport surfaces (landed)

- `dr-switch-state-chip` — switch timing states
- `dr-db-contention-chip` — DB WAITING / DEGRADED / LOCKED
- `dr-lane-stale-chip` — quote ahead / pending analytics

**Closure criteria:** Card Trust Contract §8 + this policy enforced in `fix/card-price-conflict-explainability`.
