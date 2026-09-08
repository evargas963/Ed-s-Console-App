> **Classification:** Operator Runbook | **Scope:** Host-local secrets, backup, and environment guidance.

# Host vs Git — operator mirror guide

This folder documents what belongs in **Git** (reproducible code + tracked production models) versus what stays on the **launch machine** (database, secrets, training caches, OS env).

| Doc | Purpose |
|-----|---------|
| [BACKUP_AND_MIRROR.md](BACKUP_AND_MIRROR.md) | What is tracked, ignored, and how to back up the rest |
| [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md) | All `ED_*` knobs (names, defaults, when to set) |

**Templates in repo root:**

- [`.env.example`](../../.env.example) — copy to `.env` locally (never commit `.env`)
- [`schwab_token.json.example`](../../schwab_token.json.example) — OAuth token placeholder (real file from `python reauth_schwab.py`)

**Regenerate local inventory (gitignored output):**

```powershell
.\scripts\export_host_manifest.ps1
```

**Worktree and host facts** (moved here from the deleted root memory pointer file, 2026-09-05, RC-520):

- **Per-worktree venv:** `python tools/bootstrap_worktree_venv.py` (isolated `.venv`; `run_with_repo_venv` re-execs into it).
- **ONE DB:** every worktree resolves `data/ed_console.db` (override: `ED_CONSOLE_DB` / `ED_DB_PATH`; a non-canonical target needs `ED_CONSOLE_ALLOW_NONCANONICAL_DB=1`).
- **Git lock defense:** `tools/check_git_index_lock.py` clears `index.lock` older than 60s (wired into `run_with_repo_venv`).
- **Multi-agent sync:** HEAD is the shared brain; the operator assigns work per session in chat (no standing agent roles, no worktree hand-off checker).

Related runbook: [`TRAINING_AND_MAINTENANCE.md`](../../TRAINING_AND_MAINTENANCE.md). Historical incident memories: `governance/archive/2026-Q2/memory_archive/`.
