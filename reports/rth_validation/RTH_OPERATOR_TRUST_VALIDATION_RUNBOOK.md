# RTH operator trust validation — master runbook

**Scope:** Single checklist for all transport/DB/data proof after PRs #11–#16.

## Record on every run (mandatory)

- git commit
- branch
- date/session (RTH)
- `ED_CALIBRATION_LOG`
- Schwab mode
- DB path
- server PID
- ticker universe

## Sections

1. **Base capture** — `tools/run_rth_base_capture_normalization_validation.py`
2. **Normalization** — same harness; row counts SPY/QQQ/IWM
3. **DB contention** — `tools/run_rth_db_contention_validation.py` + `/api/diagnostics/sqlite-contention`
4. **Guest switching** — `tools/run_rth_guest_switch_validation.py` + switch matrix
5. **STALE / LOADING** — screen recording + switch diag timestamps
6. **Card render timing** — `cards_first_render_ms` in switch diag
7. **Market session** — session boundary chip behavior
8. **Card conflict readiness** — blocked until `fix/card-price-conflict-explainability`

## Calibration rule

`ED_CALIBRATION_LOG` disabled → validation cannot mark PASS (`EVIDENCE_GAP_ED_CALIBRATION_LOG_DISABLED`).

## Ledger

Track outcomes in `docs/OPEN_ITEMS_OPERATOR_TRUST.md` — no passive **known remaining risks**.
