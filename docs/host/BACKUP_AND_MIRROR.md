# Backup and mirror — what Git holds vs the launch host

Git holds the source, tests and docs (the trading calendar is code: `time_et.py`). Everything the
app writes at runtime is on the host only.

## Never in Git (`.gitignore`)

| Category | Paths | Backup |
|----------|-------|--------|
| Secrets | `.env`, `schwab_token.json`, `*.key`, `*.pem` | Secure store only |
| Databases | `data/ed_console.db`, `data/stream_capture.db` | Manual copies under `backups/db/`, same disk, never restored; no scheduled backup, no retention (`ACTIVE_PROGRAM.md` OPS-HOST) |
| Runtime output | `data/*`, `*.log`, `logs/`, `.runtime/`, `reports/` | None |
| Local agent state | `.claude/settings.local.json`, `.claude/scheduled_tasks.lock` | Machine-specific |

## After clone on a new machine

1. `git clone`, then the `.venv` from `requirements.txt`.
2. `copy .env.example .env` and fill values.
3. `python reauth_schwab.py` creates `schwab_token.json`.
4. Restore both databases from `backups/db/` when recovering; they hold different histories.
