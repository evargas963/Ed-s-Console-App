# Backup and mirror — what Git holds vs the launch host

Git holds the source, tests, docs and the trading calendar. Everything the app writes at runtime
is on the host only.

## Never in Git (`.gitignore`)

| Category | Paths | Backup |
|----------|-------|--------|
| Secrets | `.env`, `schwab_token.json`, `*.key`, `*.pem` | Secure store only |
| Databases | `data/ed_console.db`, `data/stream_capture.db` | Copies under `backups/db/`; no scheduled backup job exists |
| Runtime output | `data/*` (except `data/trading_calendar/`), `*.log`, `logs/`, `.runtime/`, `reports/` | None |
| Local agent state | `.claude/settings.local.json`, `.claude/scheduled_tasks.lock` | Machine-specific |

## After clone on a new machine

1. `git clone`, then the `.venv` from `requirements.txt`.
2. `copy .env.example .env` and fill values.
3. `python reauth_schwab.py` creates `schwab_token.json`.
4. Restore both databases from `backups/db/` when recovering; they hold different histories.
