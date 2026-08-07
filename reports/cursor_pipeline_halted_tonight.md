# Cursor pipeline HALTED — 2026-08-03

- **Timestamp:** 2026-08-03T22:03:00-05:00 (America/Chicago)
- **HALTED:** yes
- **Claude cleared to rebuild:** yes
- **Mission:** `one-faucet-closeout-v1` (B3 / STRIP / PDH_PRECISION / B6)
- **sole_writer.writer:** `claude`
- **pm_mission.writer:** `claude`
- **pm / auditor:** `cursor`
- **Rebuild spec:** `scratchpad/_one_faucet_closeout_rebuild_spec.md`
- **Collision RC:** RC-229 (OPEN) — Cursor pipeline index+worktree reset destroyed authorized Claude landing; third RC-210-class recurrence
- **Standing law baked:** Cursor PMs; Claude codes. Cursor never writes feature/kill/implementation code.
- **Cursor must not touch:** `static/chart.html`, `server.py`, kill tests, git reset/checkout on mission scope
- **Reset-guard mechanical lock:** NEXT (RC-229) — deferred tonight to avoid thrash; SoD restore only
- **chart.html measure (report-only):** HEAD blob `4ecc2d501ec98ba35251f747d05d00a62a5c0d6b` ≠ WT `36a26a49fa2943c9cc18d2885561ed0f08914802` — worktree dirty vs HEAD (not rewritten by this halt turn)
