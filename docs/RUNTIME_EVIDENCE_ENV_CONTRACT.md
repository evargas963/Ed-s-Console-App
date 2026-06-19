> **Classification:** Contract | **Scope:** Runtime evidence for RTH validation and audits

# Runtime evidence environment contract

## ED_CALIBRATION_LOG

| Value | Effect |
|-------|--------|
| `1` / `true` / `yes` / `on` | `calibration_decision_log` rows written |
| unset / other | Writer **silently skips** — evidence gap |

**RTH proof rule:** If `ED_CALIBRATION_LOG` is disabled, live validation reports must **not** classify `PASS`. Classify `EVIDENCE_GAP_ED_CALIBRATION_LOG_DISABLED`.

**Objective-audit:** Records warning when disabled; does not fail startup.

## Required env capture (every RTH validation report)

- `git_commit`
- `branch`
- `date/session` (UTC)
- `market_session_mode`
- `ED_CALIBRATION_LOG` raw value + enabled bool
- Schwab/Barchart mode env
- `db_path`
- WAL / busy timeout (from DB config when available)
- `server_pid`
- `ticker_universe` note

## Minimum env for RTH proof runs

- Market open / RTH
- Server at repo tip
- `ED_CALIBRATION_LOG=1` recommended
- `window.ED_SWITCH_TIMING = true` in browser for switch matrix

## When calibration logging may be disabled

Local dev without calibration analysis — **document in validation report** what evidence is missing.
