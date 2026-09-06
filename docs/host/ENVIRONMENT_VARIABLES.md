> **Classification:** Operator Runbook | **Scope:** Host-local secrets, backup, and environment guidance.

# Environment variables (`ED_*` and related)

Copy [`.env.example`](../../.env.example) to `.env` in the repo root. **Never commit `.env`.**

Truthy for most flags: `1`, `true`, `yes`, `on` (case-insensitive). Falsy: `0`, `false`, `no`, `off`.

## Database and authority

| Variable | Default | Purpose |
|----------|---------|---------|
| `ED_RUNTIME_ROOT` | the source checkout | RC-523 (ARCHITECTURE §8): root of runtime STATE — `data/` (the live DB, barchart), `logs/`, `schwab_token.json`, `diagnostics/`. Read by `runtime_layout.py` at import (from the process environment or the repo-root `.env`). Set it to `C:\Users\<you>\Documents\Trading\runtime\EdWebConsole` after moving those directories there; unset, nothing moves. |
| `ED_ARTIFACTS_ROOT` | `ED_RUNTIME_ROOT` | RC-523: root of runtime-written ARTIFACTS — `reports/` (terrain scorecard + history + quarantine ledger, operable-surface reports, the fp scoreboard the Desk reads). Defaults to the runtime root. |
| `ED_CONSOLE_DB` | `<ED_RUNTIME_ROOT>/data/ed_console.db` | SQLite path override (wins over the runtime root; non-canonical targets still need the acknowledgement below) |
| `ED_CONSOLE_ALLOW_NONCANONICAL_DB` | off | Allow non-canonical DB path (dangerous) |
| `ED_SQLITE_BUSY_RETRIES` | `8` | Busy-handler retries |
| `ED_SQLITE_BUSY_BASE_SLEEP_SEC` | `0.02` | Backoff base |
| `ED_SQLITE_BUSY_MAX_SLEEP_SEC` | `0.4` | Backoff cap |
| `ED_SQLITE_LOCK_WAIT_WARN_MS` | `100` | Log slow lock waits |
| `ED_SQLITE_WRITE_SLOW_MS` | `500` | Log slow writes |
| `ED_CONSOLE_DANGEROUS_SQL_UNRESTRICTED` | off | Tests / emergency only |
| `ED_DB_SNAPSHOT_THROTTLE` | `1` | One snapshot row per ticker per UTC minute |

## Console server / live UI

| Variable | Default | Purpose |
|----------|---------|---------|
| `ED_CONSOLE_PORT` | `8000` | HTTP port (reload URL derivation) |
| `ED_CONSOLE_RELOAD_URL` | derived | `POST` target for model registry reload after promote |
| `ED_CONSOLE_RELOAD_TOKEN` | empty | Optional Bearer token for reload route |
| `ED_ALLOW_ACTIVE_SYNC` | `0` | Request-path active mutation (G4-1; keep off) |
| `ED_CONSOLE_ALLOW_PRED_OVERRIDE` | off | Allow prediction override paths |
| `ED_VIEWER_SSE_REFRESH_SEC` | `1.0` | Viewer SSE interval |
| `ED_VIEWER_STATE_CACHE_TTL_SEC` | `1.0` | State cache TTL |
| `ED_LIVE_QUOTE_SSE_INTERVAL_SEC` | `0.12` | Live quote SSE |
| `ED_TICK_COHERENT_GATE_SEC` | `0.5` | Tick-coherent refresh gate |
| `ED_TICK_COHERENT_MIN_SEC` | `0.45` | Minimum coherent interval |
| `ED_TICK_REFRESH_SPOT_PCT` | (code default) | Spot % threshold for refresh |
| `ED_TICK_REFRESH_SPOT_ABS` | (code default) | Spot abs threshold for refresh |
| `ED_ANALYTICS_BG_MAX_CONSECUTIVE_FAILURES` | `3` | BG analytics failure cap |
| `ED_LIVE_SNAPSHOT_MATERIALIZE` | `0` | Live snapshot materialization |
| `ED_LOGGING_UNIVERSE_FIFO_EVICTION` | off | FIFO eviction for logging universe |
| `ED_MAX_USER_PERSISTED_LOGGING_TICKERS` | (unset) | Cap persisted logging tickers |

## Training scheduler and auto-promote (PR4)

| Variable | Default | Purpose |
|----------|---------|---------|
| `ED_SCHEDULER_AUTO_PROMOTE` | off | Enable governed auto-promote after arch_competition |
| `ED_DISABLE_AUTO_PROMOTE` | off | Panic — forces auto-promote off |
| `ED_SCHEDULER_AUTO_PROMOTE_CORE_ONLY` | `1` | Limit auto-promote to SPY/QQQ/IWM |
| `ED_SCHEDULER_AUTO_PROMOTE_REQUIRE_VERIFY` | `1` | Post-promote `verify_single_bundle` on scheduler path |
| `ED_SCHEDULER_AUTO_PROMOTE_STRICT_CORE_FRESHNESS` | off | Strict freshness gate (enable after baseline week) |
| `ED_SCHEDULER_CACHE_SKIP_CAP` | (code) | Max consecutive manifest cache skips |
| `ED_ML_SCHEDULER_TICKERS` | empty | Subset of resolved training roster (intersected with anchors unless expansion on) |
| `ED_ML_SCHEDULER_TRAINING_EXPAND` | off | `1` = train full enrolled roster minus `panel_auto` (legacy expansion; default is SPY/QQQ/IWM only) |
| `ED_ML_SCHEDULER_HORIZON` | default slug | Single-horizon scheduler mode |

## Training cache and archives

| Variable | Default | Purpose |
|----------|---------|---------|
| `ED_DISABLE_TORCH_RESUME` | off | Disable torch checkpoint resume |
| `ED_TRAIN_ROLLING_RTH_SESSIONS_TABULAR` | `0` | Rolling RTH sessions (tabular) |
| `ED_TRAIN_ROLLING_RTH_SESSIONS_SEQUENCE` | `0` | Rolling RTH sessions (sequence) |
| `ED_TRAIN_ROLLING_DAYS_TABULAR` | `0` | Legacy alias for rolling window |
| `ED_TRAIN_ROLLING_DAYS_SEQUENCE` | `0` | Legacy alias |
| `ED_MANIFEST_MAX_AGE_DAYS` | `7` | Manifest skip max age |
| `ED_MAX_CONSECUTIVE_SKIPS` | `14` | Scheduler skip streak cap |
| `ED_XGB_INCREMENTAL` | off | Allow XGB incremental continuation |
| `ED_TORCH_CHECKPOINT_EVERY_N_EPOCHS` | `5` | Torch checkpoint frequency |
| `ED_FEATURE_CACHE_MAX_DIRS` | `96` | Feature cache retention count |
| `ED_FEATURE_CACHE_MIN_AGE_SEC` | `3600` | Min age before cache delete |
| `ED_MODEL_ARCHIVE` | `1` | Enable model archive snapshots |
| `ED_MODEL_ARCHIVE_MAX_SNAPSHOTS` | `8` | Per-ticker arch cap |
| `ED_MODEL_ARCHIVE_MAX_AGE_DAYS` | `120` | Archive max age |
| `ED_META_TRAIN_MAX_ROWS` | `0` | Meta train row cap (`train_all`) |
| `ED_NORMALIZED_REFRESH_DEBOUNCE_SEC` | `120` | Normalized table refresh debounce |

## Inference / models

| Variable | Default | Purpose |
|----------|---------|---------|
| `ED_XGB_STRICT_ACTIVE_ONLY` | `1` | Fail closed if active bundle incomplete |
| `ED_PREDICT_ENRICHMENT` | `1` | Cold-path UI enrichment |
| `ED_MH_EMPIRICAL_SUPPORT` | `0.15` | Multi-horizon empirical weight |
| `ED_MH_FALLBACK_CANONICAL_BLEND` | `0.0` | MH fallback blend |
| `ED_SIGNAL_LAYER_FUSION_BLEND` | `0.38` | Signal-layer fusion blend |

## Calibration and ops

| Variable | Default | Purpose |
|----------|---------|---------|
| `ED_CALIBRATION_LOG` | off | Write calibration decision log |
| `ED_BUILD_GENERATION` | empty | Stamp build generation in calibration |
| `ED_OPS_RUNNER` | off | Enable `/api/ops/run*` |
| `ED_OPS_ALLOW_REMOTE` | off | Allow ops runner from non-loopback |
| `ED_GOVERNANCE_UI_ACTIONS` | off | Governance UI actions |
| `ED_GOVERNANCE_ALLOW_REMOTE` | off | Remote governance API |

## Notifications

| Variable | Default | Purpose |
|----------|---------|---------|
| `ED_NOTIFICATION_SINK_FILE` | `1` | File notification sink |
| `ED_NOTIFICATION_WEBHOOK_ENABLED` | `0` | Webhook sink |
| `ED_NOTIFICATION_WEBHOOK_URL` | empty | Webhook URL (secret — do not commit) |
| `ED_NOTIFICATION_SINK_EMAIL_ENABLED` | `0` | Email sink |
| `ED_NOTIFICATION_SINK_SLACK_ENABLED` | `0` | Slack sink |

## Diagnostics and news

| Variable | Default | Purpose |
|----------|---------|---------|
| `ED_LIVE_DIAG` | off | Verbose live pipeline diag logs |
| `ED_DIAG_BASE` | `http://127.0.0.1:8000` | Diag tool base URL |
| `ED_DIAG_EXPIRY` | empty | Optional expiry for diag |
| `ED_DIAG_TOKEN` | empty | Optional Bearer for diag |
| `ED_NEWS_THROTTLE_SEC` | `90` | News REST throttle |
| `ED_NEWS_HTTP_TIMEOUT_SEC` | `5` | News HTTP timeout |
| `ED_NEWS_CONTEXT_DEADLINE_SEC` | `5` | News wall-time deadline |

## Schwab (non-`ED_` but host-critical)

| Variable | Default | Purpose |
|----------|---------|---------|
| `SCHWAB_TOKEN_PATH` | `schwab_token.json` | OAuth token file path |
| `SCHWAB_API_KEY` | `config.py` | API key override |
| `SCHWAB_APP_SECRET` | `config.py` | App secret override |
| `SCHWAB_CALLBACK_URL` | `config.py` | OAuth callback |

## Host-enable sequence (auto-promote)

1. Keep `ED_SCHEDULER_AUTO_PROMOTE=0` until preflip harness verify passes on real candidates.
2. Confirm promote + reload: `live_reload.succeeded: true` on your console URL.
3. Set `ED_SCHEDULER_AUTO_PROMOTE=1`, keep `ED_SCHEDULER_AUTO_PROMOTE_STRICT_CORE_FRESHNESS=0` for 1–2 weeks.
4. Optionally enable strict freshness for steady state.

See [`TRAINING_AND_MAINTENANCE.md`](../../TRAINING_AND_MAINTENANCE.md) § Auto-promote.

## Runtime evidence contract (moved from the retired runtime-evidence env contract doc, 2026-09-05, RC-520)

### `ED_CALIBRATION_LOG`

| Value | Effect |
|-------|--------|
| `1` / `true` / `yes` / `on` | `calibration_decision_log` rows written |
| unset / other | Writer **silently skips** — evidence gap |

**RTH proof rule:** if `ED_CALIBRATION_LOG` is disabled, a live validation report must **not** classify `PASS`; it classifies `EVIDENCE_GAP_ED_CALIBRATION_LOG_DISABLED`. The objective audit records a warning when it is disabled and does not fail startup. Local dev without calibration analysis may leave it off — the validation report then says what evidence is missing.

### Console DB / `snapshots_1m_normalized` (pytest + CI objective-audit)

| Situation | Contract |
|-----------|----------|
| Empty or schema-less `ED_CONSOLE_DB` / canonical `data/ed_console.db` | **In-scope** for `--objective-audit` and governance pytest — `db.ensure_console_db_training_schema()` bootstraps required tables before audit reads |
| `db_training_fingerprint` / `db_training_floor_stats` on a schema-less file | **Fail-closed:** return `row_count: 0` / `labeled_rows: 0` with `schema_absent: true` — never a raw `OperationalError` |
| Production RTH proof | The operator DB must contain labeled rows — bootstrap alone is not RTH PASS evidence |

### Required env capture (every RTH validation report)

`git_commit`, `branch`, `date/session` (UTC), `market_session_mode`, `ED_CALIBRATION_LOG` raw value + enabled bool, Schwab/Barchart mode env, `db_path`, WAL / busy timeout (from DB config when available), `server_pid`, `ticker_universe` note.

**Minimum env for an RTH proof run:** market open / RTH; server at repo tip; `ED_CALIBRATION_LOG=1`; `window.ED_SWITCH_TIMING = true` in the browser for the switch matrix.
