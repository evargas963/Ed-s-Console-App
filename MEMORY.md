> **Classification:** Active Rule Source | **Scope:** Thin pointer to AGENTS/ACTIVE_PROGRAM and [OPERATOR-ONLY] archive prefs.

# MEMORY.md — thin pointer (Phase 1c)

**Portable rules live in [`AGENTS.md`](AGENTS.md) and [`ACTIVE_PROGRAM.md`](ACTIVE_PROGRAM.md).**  
**Schwab program:** [`CLAUDE.md`](CLAUDE.md).  
**Multi-agent sync:** HEAD is the shared brain — `python tools/check_worktree_handoff.py` (wired into `tools/session_closeout.py`).  
**Physical isolation:** Cursor = primary checkout; Claude = sibling git worktree `*-Claude` (`tools/agent_worktree_policy.json`). `ED_AGENT_ROLE=cursor|claude` is **mandatory** (fail-fast if unset — no silent default). Never share one working directory.  
**Per-worktree venv:** `python tools/bootstrap_worktree_venv.py` (isolated `.venv`; `run_with_repo_venv` re-execs into it).  
**ONE DB:** every role and every worktree resolves `data/ed_console.db` (override: `ED_CONSOLE_DB` / `ED_DB_PATH`; a non-canonical target needs `ED_CONSOLE_ALLOW_NONCANONICAL_DB=1`). RC-401 deleted the per-agent fork.  
**Git lock defense:** `tools/check_git_index_lock.py` clears `index.lock` older than 60s (wired into `run_with_repo_venv`).

Incident-context memory files are **archived, not deleted:**  
[`governance/archive/2026-Q2/memory_archive/`](governance/archive/2026-Q2/memory_archive/) (34 files; triggers rewritten to topic names 2026-05-23).

---

## [OPERATOR-ONLY] — session / lane preferences (not auto-injected like AGENTS)

| Topic | Archive file |
|-------|----------------|
| Fiduciary duty + in-turn action (no end-of-turn menus) | `governance/archive/2026-Q2/memory_archive/feedback_fiduciary_duty.md` |
| Cursor pushes / PR lane; Claude verifies | `governance/archive/2026-Q2/memory_archive/feedback_cursor_pushes_not_claude.md` |
| Cursor drafts; Claude verifies (Cursor-down override in file) | `governance/archive/2026-Q2/memory_archive/feedback_cursor_drafts_claude_verifies.md` |
| Significant runs in operator PowerShell (pytest, schedulers, DB) | `governance/archive/2026-Q2/memory_archive/feedback_significant_runs_in_operator_powershell.md` |
| Worktree staleness — use `git show origin/branch:path` | `governance/archive/2026-Q2/memory_archive/feedback_worktree_staleness_check.md` |
| Gate B session bookmarks (historical) | `governance/archive/2026-Q2/memory_archive/project_gate_b_state_2026_05_20.md`, `project_gate_b_state_2026_05_21.md` |

**Active program state** is always **`ACTIVE_PROGRAM.md`**, not this file.
