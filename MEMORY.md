> **Classification:** Pointer — NOT a rule source | **Scope:** Where the rules live, the runtime facts a session needs on arrival, and an index into the [OPERATOR-ONLY] archive.
>
> RC-505: this said "Active Rule Source" while its own body says portable rules live in
> `AGENTS.md`. A file that both claims authority and disclaims it is a second rule surface
> waiting to be cited. The rules are in `AGENTS.md`; this file points at them.

# MEMORY.md — thin pointer (Phase 1c)

**Portable rules live in [`AGENTS.md`](AGENTS.md) and [`ACTIVE_PROGRAM.md`](ACTIVE_PROGRAM.md).** (`CLAUDE.md` is a one-line pointer to AGENTS.md.)  
**Multi-agent sync:** HEAD is the shared brain (2026-08-24 teardown removed the worktree-handoff checker, vendor worktree policy and `ED_AGENT_ROLE` — the operator assigns work per session in chat).  
**Per-worktree venv:** `python tools/bootstrap_worktree_venv.py` (isolated `.venv`; `run_with_repo_venv` re-execs into it).  
**ONE DB:** every worktree resolves `data/ed_console.db` (override: `ED_CONSOLE_DB` / `ED_DB_PATH`; a non-canonical target needs `ED_CONSOLE_ALLOW_NONCANONICAL_DB=1`). RC-401 deleted the per-agent fork.  
**Git lock defense:** `tools/check_git_index_lock.py` clears `index.lock` older than 60s (wired into `run_with_repo_venv`).

Incident-context memory files are **archived, not deleted:**  
[`governance/archive/2026-Q2/memory_archive/`](governance/archive/2026-Q2/memory_archive/) (34 files; triggers rewritten to topic names 2026-05-23).

---

## [OPERATOR-ONLY] — session / lane preferences (not auto-injected like AGENTS)

| Topic | Archive file |
|-------|----------------|
| Fiduciary duty + in-turn action (no end-of-turn menus) | `governance/archive/2026-Q2/memory_archive/feedback_fiduciary_duty.md` |
| Cursor pushes / PR lane; Claude verifies — HISTORICAL, superseded by the 2026-08-24 teardown (operator assigns per session in chat) | `governance/archive/2026-Q2/memory_archive/feedback_cursor_pushes_not_claude.md` |
| Cursor drafts; Claude verifies — HISTORICAL, superseded by the 2026-08-24 teardown | `governance/archive/2026-Q2/memory_archive/feedback_cursor_drafts_claude_verifies.md` |
| Significant runs in operator PowerShell (pytest, schedulers, DB) | `governance/archive/2026-Q2/memory_archive/feedback_significant_runs_in_operator_powershell.md` |
| Worktree staleness — use `git show origin/branch:path` | `governance/archive/2026-Q2/memory_archive/feedback_worktree_staleness_check.md` |
| Gate B session bookmarks (historical) | `governance/archive/2026-Q2/memory_archive/project_gate_b_state_2026_05_20.md`, `project_gate_b_state_2026_05_21.md` |

**Active program state** is always **`ACTIVE_PROGRAM.md`**, not this file.
