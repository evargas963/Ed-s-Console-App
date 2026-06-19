> **Classification:** Contract | **Scope:** Runtime evidence for RTH validation and audits

# Runtime evidence environment contract

## ED_CALIBRATION_LOG

| Value | Effect |
|-------|--------|
| `1` / `true` / `yes` / `on` | `calibration_decision_log` rows written |
| unset / other | Writer **silently skips** — evidence gap |

**RTH proof rule:** If `ED_CALIBRATION_LOG` is disabled, live validation reports must **not** classify `PASS`. Classify `EVIDENCE_GAP_ED_CALIBRATION_LOG_DISABLED`.

**Objective-audit:** Records warning when disabled; does not fail startup.

## Console DB / `snapshots_1m_normalized` (pytest + CI objective-audit)

| Situation | Contract |
|-----------|----------|
| Empty or schema-less `ED_CONSOLE_DB` / canonical `data/ed_console.db` | **In-scope** for `--objective-audit` and governance pytest — `db.ensure_console_db_training_schema()` bootstraps required tables before audit reads |
| `db_training_fingerprint` / `db_training_floor_stats` on schema-less file | **Fail-closed:** return `row_count: 0` / `labeled_rows: 0` with `schema_absent: true` — never raw `OperationalError` |
| Production RTH proof | Operator DB must contain labeled rows — bootstrap alone is not RTH PASS evidence |

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
