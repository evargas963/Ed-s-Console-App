> **Classification:** Operator Runbook | **Scope:** Phase 3 worktree cleanup operator guidance.

# Phase 3 worktree cleanup notes

Generated: 2026-05-23T22:00:17.435113+00:00

## Baseline (Phase 0 @ `dbb57c9`)

- Worktrees disk: ~2.26 GB under `.claude/worktrees/`

## Current

- Worktrees disk: ~2.26 GB

## Operator actions (not automated in consolidation)

1. List worktrees: `git worktree list`
2. Remove stale worktrees after confirming no unpushed commits: `git worktree remove <path>`
3. AGENTS.md excludes `**/.claude/worktrees/**` from repo hygiene sweeps — do not treat as product code.

## Duplicate MD review

See `duplicate_md_report.json` — e.g. `MODEL_RESTORE_LOG.md` at repo root vs `models/active/`.
Operator decides per-item delete/merge in Phase 3c; no deletions in this artifact-only slice.
