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

Related runbooks: [`TRAINING_AND_MAINTENANCE.md`](../../TRAINING_AND_MAINTENANCE.md), [`OPEN_ITEMS.md`](../../OPEN_ITEMS.md) § GitHub backup state.
