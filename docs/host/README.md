# Host vs Git

| Doc | Purpose |
|-----|---------|
| [BACKUP_AND_MIRROR.md](BACKUP_AND_MIRROR.md) | What Git holds, what stays on the host, and restoring a new machine |
| [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md) | The `ED_*` settings |

Templates in the repo root: [`.env.example`](../../.env.example) (copy to `.env`) and
[`schwab_token.json.example`](../../schwab_token.json.example) (the real file comes from
`python reauth_schwab.py`).

- Per-worktree venv: `python tools/bootstrap_worktree_venv.py`; `tools/run_with_repo_venv.py`
  re-execs into it and clears a stale `index.lock` (`tools/check_git_index_lock.py`).
- Every linked worktree resolves the primary checkout's `data/ed_console.db` and
  `data/stream_capture.db`.
