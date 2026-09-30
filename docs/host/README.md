# Host vs Git, and operations

| Doc | Purpose |
|-----|---------|
| [BACKUP_AND_MIRROR.md](BACKUP_AND_MIRROR.md) | What Git holds, what stays on the host, and restoring a new machine |

Templates in the repo root: [`.env.example`](../../.env.example) (every setting the code reads;
copy to `.env`) and
[`schwab_token.json.example`](../../schwab_token.json.example) (the real file comes from
`python reauth_schwab.py`).

- Per-worktree venv: `python tools/bootstrap_worktree_venv.py`; `tools/run_with_repo_venv.py`
  re-execs into it and clears a stale `index.lock` (`tools/check_git_index_lock.py`).
- Every linked worktree resolves the primary checkout's `data/ed_console.db` and
  `data/stream_capture.db`.

## Operations: owner and failure behavior (AGENTS.md rule 13)

Checked 2026-09-30 on the production host. A row whose owner or failure behavior is missing is a
work item (`ACTIVE_PROGRAM.md` OPS-HOST).

| Responsibility | Owner today | When it fails, the screen | Missing |
|---|---|---|---|
| Capture daemon | `start_capture_daemon.bat`: restarts it 5 s after any exit, except exit 2 (may not run live here) and 3 (another daemon owns the stream) | reads every streamed value not live within 3 s (DATA_FLOW §3.4 Live) | an alert off the screen |
| Console | `start_ed_console.bat` runs `uvicorn` once; nothing restarts it | prices keep arriving from the daemon; levels, chain and flow stop updating, and the page's session label reads `—` | supervision and restart; an alert |
| Schwab sign-in | `reauth_schwab.py` by hand, every 7 days; `server.schwab_sign_in_status` warns from day 5 | the header shows when it ends; after it ends nothing from Schwab is live | the reauth writes the new token only on success (today it deletes the old one first) |
| Network exposure | the console binds `0.0.0.0:8000`, the daemon's price socket `0.0.0.0:8800`; the network is classed Public | — | the intended exposure, decided; routes that change state (streaming demand, a chain fetch) have no authentication |
| Disk | nothing: no retention; 146 GB free, `ed_console.db` 77.9 GB, `stream_capture.db` 27.8 GB | a write that fails when the disk is full | retention per table, a free-space check |
| Backups and restore | manual copies only (`backups/db/`, 2026-09-07/08, same disk), never restored | — | a scheduled backup off this disk, a tested restore that keeps provenance |
| Deploy and rollback | `git pull --ff-only` in the production checkout, both processes restarted, the screen checked | — | rollback: a PR reverting the merge, then the same steps; the previous good commit recorded at each deploy |

`start_ed_console.bat` also runs a scheduled task that does not exist (`EdConsole Stream Capture`)
and sets `ED_OPS_RUNNER`, which no code reads; both are dead lines (OPS-HOST).
