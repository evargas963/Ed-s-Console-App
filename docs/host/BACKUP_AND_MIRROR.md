# Backup and mirror — what Git holds vs the launch host

Git holds the source, tests and docs (the market's sessions are Schwab's /markets answers, read by
`time_et.py`). Everything the app writes at runtime is on the host only.

## Never in Git (`.gitignore`)

| Category          | Paths                                                         | Backup                                                   |
| ----------------- | ------------------------------------------------------------- | -------------------------------------------------------- |
| Secrets           | `.env`, `schwab_token.json`, `*.key`, `*.pem`                 | Secure store only                                        |
| Database          | `data/ed.db`                                                  | None: no database backups are kept (operator 2026-10-10) |
| Runtime output    | `data/*`, `*.log`, `logs/`, `.runtime/`, `reports/`           | None                                                     |
| Local agent state | `.claude/settings.local.json`, `.claude/scheduled_tasks.lock` | Machine-specific                                         |

## After clone on a new machine

1. `git clone`, then the `.venv` from `requirements.txt` (a worktree's own:
   `python tools/bootstrap_worktree_venv.py`).
2. `copy .env.example .env` (every setting the code reads) and fill values.
3. `python reauth_schwab.py` creates `schwab_token.json` (its shape: `schwab_token.json.example`).
4. The database starts empty: the program creates it, and the history builds from the first session
   on (the stream's tables keep five sessions).
