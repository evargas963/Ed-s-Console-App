# Process mechanical locks runbook (RC-217)

See **`governance/AGENT_OPERATING_PROCESS_V1.md`** for the mandatory checklist.

## Set sole writer

Edit `governance/sole_writer.json`:

```json
{
  "writer": "claude",
  "auditor": "cursor",
  "held_commit": "description of held work",
  "updated_at": "2026-08-03T15:30:00-05:00"
}
```

- While `writer` is `claude`, Cursor **BLOCKS** on Edit/Write to `PROTECTED_PATHS` in `tools/operating_process_lock.py`.
- Temporary Cursor edit: add `"cursor_edit_ok": true` (operator only).

## Grant operator GO (held iceberg commit)

Edit `governance/operator_go.json`:

```json
{
  "granted": true,
  "granted_at": "2026-08-03T16:00:00-05:00",
  "granted_by": "operator",
  "scope": ["staged_lock_surface"],
  "note": "explicit GO for coherent lock-surface commit"
}
```

Required when staged `CHECKS` include ENFORCED names not on `HEAD:tools/check_institutional_correctness.py`.

## Commit checklist

1. `python tools/operating_process_lock.py --measure` → `index_worktree_mismatches: []`
2. Run targeted pytest + institutional gate (≥600s timeout; do not kill mid-hook)
3. `python tools/operating_process_lock.py --commit-check`
4. `git commit` (explicit paths only — never `git add -A`)
5. Post-commit: `--measure` again + spot `git show HEAD:tools/check_institutional_correctness.py`
6. If `db.py` seam changed: restart `:8000` before claiming LIVE_ENFORCED

## DISK_ONLY probe

```text
.venv/Scripts/python.exe tools/operating_process_lock.py --measure
```

Read `live_collect_disk_only`. Non-null → runtime is pre-gate; use `DISK_ONLY_UNTIL_RESTART` in status prose until operator restart.

## Demo BLOCK commands

```text
# Sole writer (Cursor editing db.py while writer=claude):
.venv/Scripts/python.exe -c "from tools.operating_process_lock import sole_writer_edit_violation; print(sole_writer_edit_violation('db.py'))"

# Index parity (simulate by editing checker without staging — if WT≠index):
.venv/Scripts/python.exe tools/operating_process_lock.py --pre-commit

# Completion claim at Stop (hook): say "one intentional tree ready to commit" with index≠WT
```

## Hooks wired (Cursor)

`.cursor/hooks.json` → `tools/process_lock_guard.py` on PreToolUse + Stop + Bash.

Claude parity: add the same command to `.claude/settings.json` when landing the iceberg.
